#!/usr/bin/env python3
"""
Test suite for Flow Compensator
Tests single and multi-material compensation, flow rate calculation, and tool changes.
"""

import unittest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
import yaml

from flow_compensator import GCodeParser, FlowCompensator


class TestGCodeParser(unittest.TestCase):
    """Test G-code parsing functionality."""

    def setUp(self):
        """Create test G-code file."""
        self.test_gcode = """; Test G-code
; filament_type = PETG
; layer_height = 0.2
; line_width = 0.4
M200 D1.75
G21
G90
M83
G1 F3000
G1 X100 Y100 E10
G1 X110 Y100 E5.55
G1 X110 Y110 E5.55
G1 X100 Y110 E5.55
G1 X100 Y100
"""
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.gcode')
        self.temp_file.write(self.test_gcode)
        self.temp_file.close()

    def tearDown(self):
        """Clean up test file."""
        os.unlink(self.temp_file.name)

    def test_parse_metadata(self):
        """Test metadata extraction from G-code."""
        parser = GCodeParser(Path(self.temp_file.name))
        metadata = parser.parse_metadata()

        self.assertEqual(metadata['filament_type'], 'PETG')
        self.assertEqual(metadata['filament_diameter'], 1.75)
        self.assertEqual(metadata['layer_height'], 0.2)
        self.assertEqual(metadata['line_width'], 0.4)

    def test_parse_move_with_extrusion(self):
        """Test parsing G1 move with extrusion."""
        parser = GCodeParser(Path(self.temp_file.name))
        parser.read_all_lines()

        line = "G1 X110 Y100 E5.55 F3000"
        current_pos = {'x': 100, 'y': 100, 'z': 0, 'e': 10}
        current_feedrate = 3000

        move_info, new_pos, new_feedrate = parser.parse_move(line, current_pos, current_feedrate)

        self.assertIsNotNone(move_info)
        self.assertEqual(move_info['extrusion'], 5.55)
        self.assertEqual(move_info['distance'], 10.0)  # sqrt(10^2 + 0^2 + 0^2) = 10
        self.assertEqual(move_info['feedrate'], 3000)
        self.assertEqual(new_pos['x'], 110)
        self.assertEqual(new_pos['y'], 100)

    def test_parse_travel_move(self):
        """Test parsing travel move without extrusion."""
        parser = GCodeParser(Path(self.temp_file.name))

        line = "G1 X100 Y100"
        current_pos = {'x': 110, 'y': 110, 'z': 0, 'e': 21.1}
        current_feedrate = 3000

        move_info, new_pos, new_feedrate = parser.parse_move(line, current_pos, current_feedrate)

        self.assertIsNone(move_info)  # No extrusion
        self.assertEqual(new_pos['x'], 100)
        self.assertEqual(new_pos['y'], 100)

    def test_tool_change_pattern(self):
        """Test tool change command detection."""
        self.assertTrue(GCodeParser.TOOL_CHANGE_PATTERN.match('T0'))
        self.assertTrue(GCodeParser.TOOL_CHANGE_PATTERN.match('T1'))
        self.assertTrue(GCodeParser.TOOL_CHANGE_PATTERN.match('T12'))
        self.assertFalse(GCodeParser.TOOL_CHANGE_PATTERN.match('G1'))
        self.assertFalse(GCodeParser.TOOL_CHANGE_PATTERN.match('T'))


class TestFlowCompensator(unittest.TestCase):
    """Test flow compensation functionality."""

    def setUp(self):
        """Create test configuration."""
        self.config = {
            'materials': {
                'PETG': {
                    'name': 'PETG',
                    'curve_points': [
                        [0, 1.00],
                        [10, 1.00],
                        [20, 1.025],
                        [30, 1.060],
                    ]
                },
                'PLA': {
                    'name': 'PLA',
                    'curve_points': [
                        [0, 1.00],
                        [15, 1.00],
                        [25, 1.02],
                        [35, 1.05],
                    ]
                },
                'PVA': {
                    'name': 'PVA',
                    'curve_points': [
                        [0, 1.00],
                        [10, 1.00],
                        [15, 1.02],
                        [20, 1.03],
                    ]
                },
                'default': {
                    'name': 'Default',
                    'curve_points': [
                        [0, 1.00],
                        [15, 1.00],
                        [25, 1.03],
                    ]
                }
            },
            'interpolation': {'type': 'pchip'},
            'detection': {'filament_diameter': 1.75},
            'output': {
                'log_changes': True,
                'min_compensation': 0.8,
                'max_compensation': 1.5,
                'statistics': True
            },
            'auto_detect': {
                'filament_type': True,
                'fallback_material': 'default'
            }
        }

    def test_load_material_profile(self):
        """Test loading material profile."""
        compensator = FlowCompensator(self.config)
        compensator.load_material_profile('PETG', tool_num=0)

        self.assertIn(0, compensator.tool_profiles)
        self.assertEqual(compensator.tool_profiles[0]['material'], 'PETG')
        self.assertIsNotNone(compensator.tool_profiles[0]['spline'])

    def test_load_nonexistent_material(self):
        """Test loading non-existent material uses fallback."""
        compensator = FlowCompensator(self.config)
        compensator.load_material_profile('NONEXISTENT', tool_num=0)

        # Should use default
        self.assertEqual(compensator.tool_profiles[0]['material'], 'default')

    def test_case_insensitive_material_match(self):
        """Test case-insensitive material matching."""
        compensator = FlowCompensator(self.config)
        compensator.load_material_profile('petg', tool_num=0)

        # Material name is stored as provided, but profile is matched case-insensitively
        self.assertEqual(compensator.tool_profiles[0]['material'], 'petg')
        # Verify the profile loaded correctly by checking spline has control points
        self.assertIsNotNone(compensator.tool_profiles[0]['spline'])
        self.assertEqual(len(compensator.tool_profiles[0]['spline'].x), 4)  # 4 control points

    def test_set_filament_diameter(self):
        """Test filament diameter and area calculation."""
        compensator = FlowCompensator(self.config)
        compensator.set_filament_diameter(1.75)

        self.assertEqual(compensator.filament_diameter, 1.75)
        # Area = pi * (1.75/2)^2 = pi * 0.875^2 = pi * 0.765625 = 2.4053
        self.assertAlmostEqual(compensator.filament_area, 2.4053, places=3)

    def test_calculate_flow_rate(self):
        """Test volumetric flow rate calculation."""
        compensator = FlowCompensator(self.config)
        compensator.set_filament_diameter(1.75)

        # Example: extrusion=5.55mm, distance=10mm, feedrate=3000mm/min
        # flow = (5.55 * 2.4053 / 10) * 3000 / 60 = 66.72 mm3/s
        flow_rate = compensator.calculate_flow_rate(5.55, 10.0, 3000)

        self.assertAlmostEqual(flow_rate, 66.7, places=1)

    def test_compensation_at_various_flow_rates(self):
        """Test compensation values at different flow rates."""
        compensator = FlowCompensator(self.config)
        compensator.set_filament_diameter(1.75)
        compensator.load_material_profile('PETG', tool_num=0)

        # Test at 10 mm3/s - should be 1.00 (no compensation)
        mult_10 = compensator.get_compensation_multiplier(10.0)
        self.assertAlmostEqual(mult_10, 1.00, places=2)

        # Test at 20 mm3/s - should be ~1.025
        mult_20 = compensator.get_compensation_multiplier(20.0)
        self.assertAlmostEqual(mult_20, 1.025, places=2)

        # Test at 30 mm3/s - should be ~1.060
        mult_30 = compensator.get_compensation_multiplier(30.0)
        self.assertAlmostEqual(mult_30, 1.060, places=2)

    def test_compensate_line(self):
        """Test line compensation."""
        compensator = FlowCompensator(self.config)
        compensator.set_filament_diameter(1.75)
        compensator.load_material_profile('PETG', tool_num=0)

        line = "G1 X110 Y100 E5.55 F3000"
        move_info = {
            'extrusion': 5.55,
            'distance': 10.0,
            'feedrate': 3000
        }

        compensated = compensator.compensate_line(line, move_info)

        # Should have comment with flow rate and multiplier
        self.assertIn('flow_comp', compensated)
        self.assertIn('mm3/s', compensated)
        # E value should be multiplied (5.55 * ~1.11 = ~6.16)
        self.assertIn('E', compensated)

    def test_safety_limits(self):
        """Test compensation safety limits."""
        compensator = FlowCompensator(self.config)
        compensator.set_filament_diameter(1.75)
        compensator.load_material_profile('PETG', tool_num=0)

        # Test min limit (0.8)
        self.config['output']['min_compensation'] = 0.8
        # Very low flow rate that might give < 0.8
        mult = compensator.get_compensation_multiplier(0.001)
        self.assertGreaterEqual(mult, 0.8)

        # Test max limit (1.5)
        self.config['output']['max_compensation'] = 1.5
        # Very high flow rate that might give > 1.5
        mult = compensator.get_compensation_multiplier(1000)
        self.assertLessEqual(mult, 1.5)


class TestMultiMaterialSupport(unittest.TestCase):
    """Test multi-material (IDEX/toolchanger) functionality."""

    def setUp(self):
        """Create test configuration with extruder_mapping."""
        self.config = {
            'materials': {
                'PETG': {
                    'name': 'PETG',
                    'curve_points': [[0, 1.00], [10, 1.00], [20, 1.025], [30, 1.060], [40, 1.080], [50, 1.091], [60, 1.110]]
                },
                'PVA': {
                    'name': 'PVA',
                    'curve_points': [[0, 1.00], [10, 1.00], [15, 1.02], [20, 1.03], [25, 1.04], [30, 1.05]]
                },
                'PLA': {
                    'name': 'PLA',
                    'curve_points': [[0, 1.00], [15, 1.00], [25, 1.02], [35, 1.05], [45, 1.08], [55, 1.12]]
                }
            },
            'interpolation': {'type': 'pchip'},
            'detection': {'filament_diameter': 1.75},
            'output': {'log_changes': True, 'min_compensation': 0.8, 'max_compensation': 1.5},
            'auto_detect': {'filament_type': True, 'fallback_material': 'default'}
        }

    def test_load_extruder_mapping(self):
        """Test loading tools from config extruder_mapping."""
        self.config['extruder_mapping'] = {
            'T0': 'PETG',
            'T1': 'PVA'
        }

        compensator = FlowCompensator(self.config)
        has_multi = compensator.load_extruder_mapping()

        self.assertTrue(has_multi)
        self.assertIn(0, compensator.tool_profiles)
        self.assertIn(1, compensator.tool_profiles)
        self.assertEqual(compensator.tool_profiles[0]['material'], 'PETG')
        self.assertEqual(compensator.tool_profiles[1]['material'], 'PVA')

    def test_tool_switching(self):
        """Test active tool switching."""
        compensator = FlowCompensator(self.config)
        compensator.load_material_profile('PETG', tool_num=0)
        compensator.load_material_profile('PVA', tool_num=1)

        # Default is T0
        self.assertEqual(compensator.active_tool, 0)

        # Switch to T1
        compensator.set_active_tool(1)
        self.assertEqual(compensator.active_tool, 1)

        # Check material name
        self.assertEqual(compensator.get_active_tool_material(), 'PVA')

    def test_per_tool_statistics(self):
        """Test statistics tracking per tool."""
        compensator = FlowCompensator(self.config)
        compensator.set_filament_diameter(1.75)
        compensator.load_material_profile('PETG', tool_num=0)
        compensator.load_material_profile('PVA', tool_num=1)

        # Simulate some moves on T0
        compensator.set_active_tool(0)
        move_info = {'extrusion': 5.55, 'distance': 10.0, 'feedrate': 3000}
        compensator.compensate_line("G1 X100 Y100 E5.55 F3000", move_info)

        # Simulate some moves on T1
        compensator.set_active_tool(1)
        compensator.compensate_line("G1 X50 Y50 E5.0 F3000", move_info)

        # Check both tools have stats
        self.assertIn(0, compensator.stats)
        self.assertIn(1, compensator.stats)
        self.assertGreater(compensator.stats[0]['total_moves'], 0)
        self.assertGreater(compensator.stats[1]['total_moves'], 0)

    def test_command_line_materials(self):
        """Test creating multi-material setup from command line arguments."""
        compensator = FlowCompensator(self.config)

        # Simulate command line: PETG PVA PLA
        materials = ['PETG', 'PVA', 'PLA']
        for tool_num, material in enumerate(materials):
            compensator.load_material_profile(material, tool_num)

        self.assertEqual(len(compensator.tool_profiles), 3)
        self.assertEqual(compensator.tool_profiles[0]['material'], 'PETG')
        self.assertEqual(compensator.tool_profiles[1]['material'], 'PVA')
        self.assertEqual(compensator.tool_profiles[2]['material'], 'PLA')


class TestIntegration(unittest.TestCase):
    """Integration tests with full G-code processing."""

    def setUp(self):
        """Create test multi-material G-code file."""
        self.test_gcode = """; Multi-material test
G21
G90
M83

T0
G1 F3000
G1 X100 Y100 E10
G1 X110 Y100 E5.55

T1
G1 F2400
G1 X50 Y50 E10
G1 X60 Y50 E5.0

T0
G1 F3000
G1 X120 Y120 E10
G1 X130 Y120 E5.55
"""
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.gcode')
        self.temp_file.write(self.test_gcode)
        self.temp_file.close()

        self.config = {
            'materials': {
                'PETG': {
                    'name': 'PETG',
                    'curve_points': [[0, 1.00], [10, 1.00], [20, 1.025], [30, 1.060], [40, 1.080], [50, 1.091], [60, 1.110]]
                },
                'PVA': {
                    'name': 'PVA',
                    'curve_points': [[0, 1.00], [10, 1.00], [15, 1.02], [20, 1.03], [25, 1.04], [30, 1.05]]
                }
            },
            'interpolation': {'type': 'pchip'},
            'detection': {'filament_diameter': 1.75},
            'output': {'log_changes': True, 'min_compensation': 0.8, 'max_compensation': 1.5}
        }

    def tearDown(self):
        """Clean up test file."""
        os.unlink(self.temp_file.name)

    def test_full_multi_material_processing(self):
        """Test processing multi-material G-code from start to finish."""
        from flow_compensator import main

        # Create output file path
        output_file = self.temp_file.name.replace('.gcode', '_out.gcode')

        # Mock sys.argv for command line simulation
        test_args = [
            'flow_compensator.py',
            self.temp_file.name,
            output_file,
            'PETG',  # T0
            'PVA'    # T1
        ]

        with patch('sys.argv', test_args):
            try:
                main()
            except SystemExit:
                pass  # main() calls sys.exit()

        # Check output file was created
        self.assertTrue(Path(output_file).exists())

        # Read output and verify tool changes are preserved
        with open(output_file, 'r') as f:
            output_content = f.read()

        # Should contain T0 and T1 commands
        self.assertIn('T0', output_content)
        self.assertIn('T1', output_content)

        # Should contain compensation comments with tool tags
        self.assertIn('flow_comp T0:', output_content)
        self.assertIn('flow_comp T1:', output_content)

        # Clean up
        os.unlink(output_file)


if __name__ == '__main__':
    unittest.main(verbosity=2)
