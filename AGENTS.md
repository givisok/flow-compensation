# AGENTS.md

This file contains guidelines for AI agents working on the flow-compensator repository.

## Build/Test Commands

### Running Tests
```bash
# Run all tests
python test_flow_compensator.py
# or
python -m unittest test_flow_compensator.py -v

# Run a single test class
python -m unittest test_flow_compensator.TestGCodeParser -v

# Run a single test method
python -m unittest test_flow_compensator.TestGCodeParser.test_parse_metadata -v

# Run all tests with verbose output
python test_flow_compensator.py
```

### Running the Main Script
```bash
# Basic usage with auto-detection
python flow_compensator.py input.gcode output.gcode

# Specify material explicitly
python flow_compensator.py --material PETG input.gcode output.gcode

# Multi-material (IDEX/toolchanger)
python flow_compensator.py input.gcode output.gcode PETG PVA PLA

# Dry run (analyze without modifying)
python flow_compensator.py --dry-run input.gcode

# Use custom config
python flow_compensator.py --config my_config.yaml input.gcode output.gcode
```

### Dependencies
```bash
pip install -r requirements.txt
```
Required: Python 3.7+, PyYAML>=6.0, scipy>=1.9.0, numpy>=1.21.0, gcodeparser>=1.0

### Linting and Formatting
```bash
# Format code with black
black .

# Sort imports with isort
isort .

# Check code style with flake8
flake8 .

# Type checking with mypy
mypy flow_compensator.py

# Run all code quality checks
black . && isort . && flake8 .
```

### Running Tests
```bash
# Run all tests
python -m unittest test_flow_compensator.py -v

# Run specific test class
python -m unittest test_flow_compensator.TestGCodeParser -v

# Run specific test method
python -m unittest test_flow_compensator.TestGCodeParser.test_parse_metadata_regex -v

# Test with different parsers
python flow_compensator.py --parser library input.gcode output.gcode
python flow_compensator.py --parser regex input.gcode output.gcode
```

## Code Style Guidelines

### Imports
- Group imports in this order: standard library, third-party, local imports
- Separate groups with a blank line
- Use absolute imports for clarity

```python
import argparse
import math
import re
import sys
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

import yaml
import numpy as np
from scipy.interpolate import PchipInterpolator
```

### Type Hints
- Use type hints for all function parameters and return values
- Import from `typing` module: Optional, Tuple, List, Dict, Any
- Example: `def parse_move(self, line: str, current_pos: Dict[str, float], current_feedrate: float) -> Tuple[Optional[Dict], Dict[str, float], float]:`

### Naming Conventions
- **Classes**: PascalCase (e.g., `GCodeParser`, `FlowCompensator`)
- **Functions/methods**: snake_case (e.g., `parse_metadata`, `load_material_profile`)
- **Constants**: UPPER_SNAKE_CASE (e.g., `G1_PATTERN`, `EXTRUSION_PATTERN`)
- **Private methods**: Prefix with underscore (e.g., `_init_stats_for_tool`, `_get_material_profile`)
- **Instance variables**: snake_case (e.g., `active_tool`, `filament_diameter`)

### Class Structure
- Use docstrings at module and class level
- Define class-level constants at the top
- Use `__init__` for initialization
- Group related methods together
- Private helper methods should start with underscore

### Docstrings
- Use Google-style docstrings with Args/Returns sections
- Include brief description at the top
- Document parameters and return types for non-trivial functions
- Example:
```python
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
```

### Error Handling
- Raise ValueError for invalid configuration or missing data
- Use descriptive error messages
- Check for file existence before reading
- Example:
```python
if not profile:
    raise ValueError("No material profile found in configuration")

if not input_path.exists():
    print(f"Error: Input file not found: {input_path}")
    sys.exit(1)
```

### Formatting
- Use 4-space indentation (no tabs)
- Line length: max 100 characters (configured in pyproject.toml)
- Use blank lines between logical sections
- Use f-strings for string formatting with variables
- Example: `f"Flow rate range: {spline.x[0]:.1f} - {spline.x[-1]:.1f} mm3/s"`
- Run `black .` and `isort .` before committing code

### Testing
- Use Python's built-in `unittest` framework
- Test classes inherit from `unittest.TestCase`
- Use `setUp()` for test initialization and `tearDown()` for cleanup
- Test methods should start with `test_`
- Use descriptive test names: `test_parse_metadata`, `test_load_material_profile`
- Use `tempfile` for temporary test files
- Example:
```python
class TestGCodeParser(unittest.TestCase):
    def setUp(self):
        """Create test G-code file."""
        self.test_gcode = "; Test G-code\n"
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.gcode')
        self.temp_file.write(self.test_gcode)
        self.temp_file.close()

    def test_parse_metadata(self):
        """Test metadata extraction from G-code."""
        parser = GCodeParser(Path(self.temp_file.name))
        metadata = parser.parse_metadata()
        self.assertEqual(metadata['filament_type'], 'PETG')
```

### Regex Patterns
- Compile regex patterns as class-level constants
- Use `re.compile()` for patterns that are reused
- Name patterns descriptively: `FILAMENT_TYPE_PATTERN`, `TOOL_CHANGE_PATTERN`
- Example:
```python
class GCodeParser:
    FILAMENT_TYPE_PATTERN = re.compile(r'filament_type\s*=\s*(\w+)', re.IGNORECASE)
    TOOL_CHANGE_PATTERN = re.compile(r'^T(\d+)')
```

### Configuration Files
- Use YAML for configuration (PyYAML)
- Provide template file (config_template.yaml) with detailed comments
- Use `config.yaml` for actual user configuration (ignored by git)
- Load with `yaml.safe_load()`
- Example:
```python
with open(config_path, 'r') as f:
    config = yaml.safe_load(f)
```

### File Operations
- Use `pathlib.Path` for path operations
- Always specify encoding when reading/writing files: `encoding='utf-8'`
- Use `errors='ignore'` for G-code files to handle encoding issues
- Example:
```python
with open(self.filepath, 'r', encoding='utf-8', errors='ignore') as f:
    for i, line in enumerate(f):
        # process lines
```

### Command Line Interface
- Use `argparse` for CLI arguments
- Provide helpful descriptions and examples
- Use `argparse.RawDescriptionHelpFormatter` for custom epilog text
- Support both positional and optional arguments
- Example:
```python
parser = argparse.ArgumentParser(
    description='Flow Compensator for Prusa Slicer',
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog="""
Examples:
  python flow_compensator.py input.gcode output.gcode
  python flow_compensator.py --material PETG input.gcode output.gcode
    """
)
parser.add_argument('input', help='Input G-code file')
parser.add_argument('--material', help='Override material profile')
```

### Shebang
- Always include shebang for executable scripts: `#!/usr/bin/env python3`

### Math Operations
- Import `math` module for mathematical operations
- Use `math.pi`, `math.sqrt`, etc. instead of direct calculations
- Example: `self.filament_area = math.pi * (diameter / 2) ** 2`

### Print Statements
- Use print for user-facing output and statistics
- Use descriptive messages with proper formatting
- Group related output with separator lines
- Example:
```python
print("\n" + "="*60)
print("FLOW COMPENSATION STATISTICS")
print("="*60)
print(f"Total extrusion moves:     {stats['total_moves']}")
print(f"Compensated moves:         {stats['compensated_moves']} ({100*stats['compensated_moves']/stats['total_moves']:.1f}%)")
```

## Project Structure

```
flow-compensator/
├── flow_compensator.py      # Main script
├── test_flow_compensator.py # Test suite
├── config.yaml              # User config (gitignored)
├── config_template.yaml     # Config template with docs
├── requirements.txt         # Python dependencies
├── .gitignore              # Git ignore rules
└── README.md               # Project documentation
```

## Key Considerations

1. **Multi-material support**: The code supports IDEX and toolchanger systems with per-tool material profiles
2. **PCHIP interpolation**: Uses monotonic cubic splines to avoid overshoots in compensation curves
3. **Safety limits**: Compensation is clamped to prevent over-extrusion (0.8x - 1.5x by default)
4. **Metadata detection**: Automatically detects filament type, diameter, layer height from G-code headers
5. **Statistics**: Tracks and reports flow rate and compensation statistics per tool
6. **File encoding**: Handle various encodings with errors='ignore' for G-code files
