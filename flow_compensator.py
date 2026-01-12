#!/usr/bin/env python3
"""
Flow Compensator for Prusa Slicer
Post-processing script to compensate for underextrusion at high volumetric flow rates.

This script parses G-code files, calculates volumetric flow rates for each extrusion move,
and applies dynamic flow compensation based on a configurable cubic spline curve.

Author: Generated for high-flow hotend compensation
License: MIT
"""

import argparse
import math
import re
import sys
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

import yaml
import numpy as np
from scipy.interpolate import PchipInterpolator


class GCodeParser:
    """Parser for G-code files that extracts metadata and processes moves."""

    # Regex patterns for G-code parsing
    G1_PATTERN = re.compile(r'^G[01]')
    EXTRUSION_PATTERN = re.compile(r'E([\-+]?\d*\.?\d+)')
    FEEDRATE_PATTERN = re.compile(r'F([\-+]?\d*\.?\d+)')
    XYZ_PATTERN = re.compile(r'([XYZ])([\-+]?\d*\.?\d+)')
    TOOL_CHANGE_PATTERN = re.compile(r'^T(\d+)')  # T0, T1, T2, etc.

    # Metadata patterns
    FILAMENT_TYPE_PATTERN = re.compile(r'filament_type\s*=\s*(\w+)', re.IGNORECASE)
    FILAMENT_DIAMETER_PATTERN = re.compile(r'M200\s*D([\-+]?\d*\.?\d+)', re.IGNORECASE)
    LAYER_HEIGHT_PATTERN = re.compile(r'layer_height\s*=\s*([\-+]?\d*\.?\d+)', re.IGNORECASE)
    LINE_WIDTH_PATTERN = re.compile(r'line_width\s*=\s*([\-+]?\d*\.?\d+)', re.IGNORECASE)

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.lines: List[str] = []
        self.metadata: Dict[str, Any] = {
            'filament_type': None,
            'filament_diameter': None,
            'layer_height': None,
            'line_width': None,
        }

    def parse_metadata(self) -> Dict[str, Any]:
        """Extract metadata from G-code header comments and commands."""
        with open(self.filepath, 'r', encoding='utf-8', errors='ignore') as f:
            # Read first 500 lines for metadata (typically in header)
            for i, line in enumerate(f):
                if i > 500:
                    break
                self._extract_metadata_from_line(line)

        return self.metadata

    def _extract_metadata_from_line(self, line: str):
        """Extract metadata from a single G-code line."""
        # Check for filament type in comments
        ft_match = self.FILAMENT_TYPE_PATTERN.search(line)
        if ft_match and self.metadata['filament_type'] is None:
            self.metadata['filament_type'] = ft_match.group(1).upper()

        # Check for filament diameter from M200 command
        fd_match = self.FILAMENT_DIAMETER_PATTERN.search(line)
        if fd_match and self.metadata['filament_diameter'] is None:
            self.metadata['filament_diameter'] = float(fd_match.group(1))

        # Check for layer height
        lh_match = self.LAYER_HEIGHT_PATTERN.search(line)
        if lh_match and self.metadata['layer_height'] is None:
            self.metadata['layer_height'] = float(lh_match.group(1))

        # Check for line width
        lw_match = self.LINE_WIDTH_PATTERN.search(line)
        if lw_match and self.metadata['line_width'] is None:
            self.metadata['line_width'] = float(lw_match.group(1))

    def read_all_lines(self):
        """Read all lines from the G-code file."""
        with open(self.filepath, 'r', encoding='utf-8', errors='ignore') as f:
            self.lines = f.readlines()

    def parse_move(self, line: str, current_pos: Dict[str, float],
                   current_feedrate: float) -> Tuple[Optional[Dict], Dict[str, float], float]:
        """
        Parse a G1/G0 move line.

        Returns:
            (move_info, updated_position, updated_feedrate)
            - move_info: dict with 'extrusion', 'distance', 'feedrate', or None if not a move
            - updated_position: dict with x, y, z, e values
            - updated_feedrate: current feedrate in mm/min
        """
        if not self.G1_PATTERN.match(line):
            return None, current_pos, current_feedrate

        # Get feedrate
        feedrate_match = self.FEEDRATE_PATTERN.search(line)
        if feedrate_match:
            current_feedrate = float(feedrate_match.group(1))

        # Parse XYZ coordinates - ALWAYS update for G1/G0 moves
        new_pos = current_pos.copy()
        xyz_matches = self.XYZ_PATTERN.findall(line)
        for axis, value in xyz_matches:
            new_pos[axis.lower()] = float(value)

        # Check if there's extrusion
        extrusion_match = self.EXTRUSION_PATTERN.search(line)
        if not extrusion_match:
            # Travel move without extrusion - update position but return None
            return None, new_pos, current_feedrate

        extrusion_amount = float(extrusion_match.group(1))
        if extrusion_amount == 0:
            return None, new_pos, current_feedrate

        # Calculate move distance
        dx = new_pos.get('x', current_pos.get('x', 0)) - current_pos.get('x', 0)
        dy = new_pos.get('y', current_pos.get('y', 0)) - current_pos.get('y', 0)
        dz = new_pos.get('z', current_pos.get('z', 0)) - current_pos.get('z', 0)
        distance = math.sqrt(dx**2 + dy**2 + dz**2)

        move_info = {
            'extrusion': abs(extrusion_amount),
            'distance': distance,
            'feedrate': current_feedrate,  # mm/min
        }

        # Update E position
        new_pos['e'] = current_pos.get('e', 0) + extrusion_amount

        return move_info, new_pos, current_feedrate


class FlowCompensator:
    """Main flow compensation engine with multi-material support."""

    EXTRUSION_PATTERN = re.compile(r'E([\-+]?\d*\.?\d+)')

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.filament_diameter = None
        self.filament_area = None

        # Multi-material support: profiles per tool
        self.tool_profiles: Dict[int, Dict] = {}  # {tool_num: {material, spline, profile}}
        self.active_tool: int = 0  # Default to T0

        # Statistics per tool
        self.stats: Dict[int, Dict] = {}  # {tool_num: stats_dict}
        self._init_stats_for_tool(0)

    def _init_stats_for_tool(self, tool_num: int):
        """Initialize statistics for a tool."""
        if tool_num not in self.stats:
            self.stats[tool_num] = {
                'total_moves': 0,
                'compensated_moves': 0,
                'min_flow': float('inf'),
                'max_flow': 0,
                'avg_flow': 0,
                'total_flow': 0,
                'min_multiplier': float('inf'),
                'max_multiplier': 0,
            }

    def _get_material_profile(self, material_type: str) -> Optional[Dict]:
        """Get material profile from config (case-insensitive)."""
        materials = self.config.get('materials', {})

        # Try exact match first
        if material_type in materials:
            return materials[material_type]

        # Try case-insensitive match
        for key, value in materials.items():
            if key.upper() == material_type.upper():
                return value

        return None

    def _build_spline_for_profile(self, profile: Dict) -> PchipInterpolator:
        """Build PCHIP spline from material profile curve points."""
        curve_points = profile.get('curve_points', [])
        if len(curve_points) < 2:
            raise ValueError("At least 2 curve points required for interpolation")

        points = sorted(curve_points, key=lambda p: p[0])
        x_vals = [p[0] for p in points]
        y_vals = [p[1] for p in points]

        return PchipInterpolator(x_vals, y_vals)

    def load_material_profile(self, material_type: Optional[str] = None, tool_num: int = 0):
        """Load material profile for a specific tool."""
        materials = self.config.get('materials', {})
        profile = None

        if material_type:
            profile = self._get_material_profile(material_type)

        if not profile:
            fallback = self.config.get('auto_detect', {}).get('fallback_material', 'default')
            profile = materials.get(fallback, materials.get('default'))
            material_name = fallback
            if material_type:
                print(f"Material '{material_type}' not found, using fallback: {fallback}")
        else:
            material_name = material_type

        if not profile:
            raise ValueError("No material profile found in configuration")

        # Build spline for this tool
        spline = self._build_spline_for_profile(profile)

        # Store profile for this tool
        self.tool_profiles[tool_num] = {
            'material': material_name,
            'profile': profile,
            'spline': spline
        }

        # Initialize stats for this tool
        self._init_stats_for_tool(tool_num)

        print(f"Tool T{tool_num}: Using material profile: {material_name}")

    def load_extruder_mapping(self):
        """Load all tools from extruder_mapping config."""
        mapping = self.config.get('extruder_mapping', {})

        if not mapping:
            # No mapping configured, use single material mode
            return False

        print(f"Loading {len(mapping)} tools from extruder_mapping:")
        for tool_str, material in mapping.items():
            # Parse "T0", "T1", etc.
            if tool_str.upper().startswith('T'):
                try:
                    tool_num = int(tool_str[1:])
                    self.load_material_profile(material, tool_num)
                except ValueError:
                    print(f"Warning: Invalid tool format '{tool_str}', skipping")

        return len(self.tool_profiles) > 0

    def set_active_tool(self, tool_num: int):
        """Set the active tool for compensation."""
        self.active_tool = tool_num

    def get_active_tool_material(self) -> str:
        """Get the material name for the active tool."""
        if self.active_tool in self.tool_profiles:
            return self.tool_profiles[self.active_tool]['material']
        return 'unknown'

    def build_spline(self):
        """Legacy method - kept for backward compatibility."""
        if self.tool_profiles:
            # Already built during load_material_profile
            tool_0 = self.tool_profiles.get(0)
            if tool_0:
                spline = tool_0['spline']
                print(f"Built spline with control points")
                print(f"Flow rate range: {spline.x[0]:.1f} - {spline.x[-1]:.1f} mm3/s")
                return

        # Fallback for single material mode
        if not self.tool_profiles:
            self.load_material_profile(None, 0)

    def set_filament_diameter(self, diameter: float):
        """Set filament diameter and calculate cross-sectional area."""
        self.filament_diameter = diameter
        self.filament_area = math.pi * (diameter / 2) ** 2
        print(f"Filament diameter: {diameter} mm, area: {self.filament_area:.4f} mm2")

    def calculate_flow_rate(self, extrusion: float, distance: float, feedrate: float) -> float:
        """
        Calculate volumetric flow rate in mm³/s.

        Args:
            extrusion: Extrusion amount in mm
            distance: Move distance in mm
            feedrate: Feedrate in mm/min

        Returns:
            Volumetric flow rate in mm³/s
        """
        if distance == 0:
            return 0.0

        # Flow rate = (extrusion_length * filament_area / distance) * feedrate
        # Result is in mm³/min, convert to mm³/s
        flow_rate_mm3_min = (extrusion * self.filament_area / distance) * feedrate
        return flow_rate_mm3_min / 60.0

    def get_compensation_multiplier(self, flow_rate: float) -> float:
        """
        Get compensation multiplier for a given flow rate (uses active tool).

        Args:
            flow_rate: Volumetric flow rate in mm³/s

        Returns:
            Compensation multiplier (1.0 = no compensation)
        """
        # Get spline for active tool
        if self.active_tool not in self.tool_profiles:
            return 1.0  # No compensation if tool not configured

        spline = self.tool_profiles[self.active_tool]['spline']

        # Clamp flow rate to spline range
        x_min = spline.x[0]
        x_max = spline.x[-1]

        if flow_rate < x_min:
            flow_rate_clamped = x_min
        elif flow_rate > x_max:
            flow_rate_clamped = x_max
        else:
            flow_rate_clamped = flow_rate

        # Get multiplier from spline
        multiplier = float(spline(flow_rate_clamped))

        # Apply safety limits
        min_comp = self.config.get('output', {}).get('min_compensation', 0.8)
        max_comp = self.config.get('output', {}).get('max_compensation', 1.5)
        multiplier = max(min_comp, min(max_comp, multiplier))

        return multiplier

    def compensate_line(self, line: str, move_info: Dict) -> str:
        """
        Apply compensation to a G-code line.

        Args:
            line: Original G-code line
            move_info: Move information dict

        Returns:
            Modified G-code line with compensation applied
        """
        extrusion = move_info['extrusion']
        distance = move_info['distance']
        feedrate = move_info['feedrate']

        # Calculate flow rate
        flow_rate = self.calculate_flow_rate(extrusion, distance, feedrate)

        # Update statistics for active tool
        tool_stats = self.stats[self.active_tool]
        tool_stats['total_moves'] += 1
        tool_stats['total_flow'] += flow_rate
        tool_stats['min_flow'] = min(tool_stats['min_flow'], flow_rate)
        tool_stats['max_flow'] = max(tool_stats['max_flow'], flow_rate)

        # Get compensation multiplier
        multiplier = self.get_compensation_multiplier(flow_rate)

        # Update multiplier statistics
        tool_stats['min_multiplier'] = min(tool_stats['min_multiplier'], multiplier)
        tool_stats['max_multiplier'] = max(tool_stats['max_multiplier'], multiplier)

        # Check if compensation is needed
        if abs(multiplier - 1.0) < 0.001:
            return line  # No significant compensation needed

        # Apply compensation
        tool_stats['compensated_moves'] += 1

        # Find and replace E value
        def replace_e(match):
            original_e = float(match.group(1))
            new_e = original_e * multiplier
            return f'E{new_e:.6f}'.rstrip('0').rstrip('.')

        compensated_line = self.EXTRUSION_PATTERN.sub(replace_e, line)

        # Add comment if enabled
        if self.config.get('output', {}).get('log_changes', True):
            material_tag = f" T{self.active_tool}" if len(self.tool_profiles) > 1 else ""
            compensated_line = compensated_line.rstrip() + f" ; flow_comp{material_tag}: {flow_rate:.1f}mm3/s x{multiplier:.3f}\n"

        return compensated_line

    def print_statistics(self):
        """Print processing statistics."""
        print("\n" + "="*60)
        print("FLOW COMPENSATION STATISTICS")
        print("="*60)

        # Multi-tool mode: show stats per tool
        if len(self.stats) > 1 or any(s['total_moves'] > 0 for s in self.stats.values()):
            for tool_num in sorted(self.stats.keys()):
                stats = self.stats[tool_num]
                if stats['total_moves'] == 0:
                    continue

                material = self.tool_profiles.get(tool_num, {}).get('material', 'unknown')
                avg_flow = stats['total_flow'] / stats['total_moves'] if stats['total_moves'] > 0 else 0

                print(f"\nTool T{tool_num} ({material}):")
                print(f"  Total moves:     {stats['total_moves']}")
                print(f"  Compensated:     {stats['compensated_moves']} ({100*stats['compensated_moves']/stats['total_moves']:.1f}%)")
                print(f"  Flow range:      {stats['min_flow']:.1f} - {stats['max_flow']:.1f} mm3/s")
                print(f"  Avg flow:        {avg_flow:.1f} mm3/s")
                print(f"  Multiplier:      {stats['min_multiplier']:.3f} - {stats['max_multiplier']:.3f}x")

            # Total across all tools
            total_moves = sum(s['total_moves'] for s in self.stats.values())
            total_comp = sum(s['compensated_moves'] for s in self.stats.values())
            if total_moves > 0:
                print(f"\nTotal: {total_moves} moves, {total_comp} compensated ({100*total_comp/total_moves:.1f}%)")
        else:
            # Single tool mode (backward compatible)
            stats = self.stats.get(0, {'total_moves': 0})
            if stats['total_moves'] == 0:
                print("\nNo extrusion moves found to process.")
                return

            avg_flow = stats['total_flow'] / stats['total_moves']
            print(f"Total extrusion moves:     {stats['total_moves']}")
            print(f"Compensated moves:         {stats['compensated_moves']} ({100*stats['compensated_moves']/stats['total_moves']:.1f}%)")
            print(f"\nFlow rate range:           {stats['min_flow']:.1f} - {stats['max_flow']:.1f} mm3/s")
            print(f"Average flow rate:         {avg_flow:.1f} mm3/s")
            print(f"\nMultiplier range:          {stats['min_multiplier']:.3f} - {stats['max_multiplier']:.3f}x")

        print("="*60)


def main():
    parser = argparse.ArgumentParser(
        description='Flow Compensator for Prusa Slicer - Compensate for underextrusion at high flow rates',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage with auto-detection
  python flow_compensator.py input.gcode output.gcode

  # Specify material explicitly
  python flow_compensator.py --material PETG input.gcode output.gcode

  # Dry run (analyze without modifying)
  python flow_compensator.py --dry-run input.gcode

  # Use custom config
  python flow_compensator.py --config my_config.yaml input.gcode output.gcode
        """
    )

    parser.add_argument('input', help='Input G-code file')
    parser.add_argument('output', nargs='?', help='Output G-code file (default: overwrite input)')
    parser.add_argument('--config', default='config.yaml', help='Configuration file (default: config.yaml)')
    parser.add_argument('--material', help='Override material profile (PETG, PLA, ABS, etc.)')
    parser.add_argument('--dry-run', action='store_true', help='Analyze without modifying file')
    parser.add_argument('--no-comments', action='store_true', help='Don\'t add compensation comments to G-code')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed processing information')

    args = parser.parse_args()

    # Load configuration
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: Configuration file not found: {config_path}")
        print("Creating default configuration file...")
        # Could create default config here if needed
        sys.exit(1)

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    # Parse input file
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        sys.exit(1)

    print(f"Parsing: {input_path}")
    parser_gcode = GCodeParser(input_path)
    metadata = parser_gcode.parse_metadata()

    print(f"Detected metadata:")
    print(f"  Filament type:    {metadata['filament_type'] or 'Not found'}")
    print(f"  Filament diameter: {metadata['filament_diameter'] or 'Not found'} mm")
    print(f"  Layer height:     {metadata['layer_height'] or 'Not found'} mm")
    print(f"  Line width:       {metadata['line_width'] or 'Not found'} mm")

    # Determine material
    material = args.material or metadata.get('filament_type')
    if material:
        material = material.upper()

    # Initialize compensator
    compensator = FlowCompensator(config)

    # Try to load multi-material setup from extruder_mapping
    has_multi_material = compensator.load_extruder_mapping()

    if has_multi_material:
        # Multi-material mode
        print("\nMulti-material mode enabled")
        # Use first tool as active
        compensator.set_active_tool(min(compensator.tool_profiles.keys()))
    else:
        # Single material mode
        if material:
            compensator.load_material_profile(material, tool_num=0)
        else:
            compensator.load_material_profile(None, tool_num=0)
        compensator.build_spline()

    # Set filament diameter
    filament_diameter = metadata.get('filament_diameter')
    if not filament_diameter:
        filament_diameter = config.get('detection', {}).get('filament_diameter', 1.75)
        print(f"Using default filament diameter: {filament_diameter} mm")
    compensator.set_filament_diameter(filament_diameter)

    # Disable comments if requested
    if args.no_comments:
        config['output']['log_changes'] = False

    # Read all lines
    parser_gcode.read_all_lines()

    # Process G-code
    print(f"\nProcessing {len(parser_gcode.lines)} lines...")

    output_lines = []
    current_pos = {'x': 0, 'y': 0, 'z': 0, 'e': 0}
    current_feedrate = 0.0

    for i, line in enumerate(parser_gcode.lines):
        # Check for tool change command (T0, T1, T2, ...)
        tool_match = GCodeParser.TOOL_CHANGE_PATTERN.match(line.strip())
        if tool_match and has_multi_material:
            new_tool = int(tool_match.group(1))
            if new_tool in compensator.tool_profiles:
                compensator.set_active_tool(new_tool)
                output_lines.append(line)  # Keep original T command
                continue

        move_info, new_pos, new_feedrate = parser_gcode.parse_move(
            line, current_pos, current_feedrate
        )

        # Always update position and feedrate (even for travel moves)
        current_pos = new_pos
        current_feedrate = new_feedrate

        if move_info:
            # Apply compensation
            compensated_line = compensator.compensate_line(line, move_info)
            output_lines.append(compensated_line)

            if args.verbose and move_info['distance'] > 0:
                flow_rate = compensator.calculate_flow_rate(
                    move_info['extrusion'],
                    move_info['distance'],
                    move_info['feedrate']
                )
                multiplier = compensator.get_compensation_multiplier(flow_rate)
                tool_info = f" T{compensator.active_tool}" if has_multi_material else ""
                print(f"Line {i+1}{tool_info}: flow={flow_rate:.1f} mm3/s, mult={multiplier:.3f}x")
        else:
            output_lines.append(line)

    # Print statistics
    if config.get('output', {}).get('statistics', True):
        compensator.print_statistics()

    # Write output
    if args.dry_run:
        print("\nDry run mode - no output file written.")
    else:
        output_path = Path(args.output) if args.output else input_path
        with open(output_path, 'w', encoding='utf-8') as f:
            f.writelines(output_lines)
        print(f"\nOutput written to: {output_path}")


if __name__ == '__main__':
    main()
