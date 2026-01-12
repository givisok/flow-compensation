# Flow Compensator for Prusa Slicer

Post-processing script for Prusa Slicer that dynamically compensates for underextrusion at high volumetric flow rates. This is particularly useful for high-flow hotends (e.g., Rapido HF, Dragon HF, Revo CR) that experience underextrusion at flow rates above 20 mm³/s.

## Problem

When using high-performance hotends at high volumetric flow rates (>20 mm³/s), underextrusion can occur due to limitations in the extruder system or hotend melt flow. The underextrusion increases non-linearly with flow rate:

- At 10 mm³/s: ~0% underextrusion (no problem)
- At 30 mm³/s: ~6% underextrusion
- At 50 mm³/s: ~11% underextrusion
- At 60 mm³/s: ~15% underextrusion (severe)

## Solution

This script analyzes your G-code and applies dynamic flow compensation based on the requested volumetric flow rate for each extrusion move. It uses **PCHIP interpolation** (monotonic cubic) to create smooth compensation curves without overshoots or ripples.

## Features

- **Per-material profiles** - PETG, PLA, ABS, ASA, TPU, Nylon, PC, PVA, and more
- **Multi-material support** - IDEX and toolchanger systems with automatic tool change detection
- **PCHIP interpolation** - Monotonic cubic spline (smooth curves, no overshoots/ripples)
- **Auto-detection** - Automatically detects material type from G-code comments
- **Configurable curves** - Easy customization based on your flow testing
- **Safety limits** - Prevents over-compensation (default: 0.8x - 1.5x)
- **Statistics** - Shows what compensation was applied (per-tool for multi-material setups)
- **Dry-run mode** - Analyze without modifying files
- **Prusa Slicer integration** - Works as a post-processing script

## Installation

1. Clone or download this repository:
```bash
git clone https://github.com/yourusername/flow-compensator.git
cd flow-compensator
```

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

Required packages:
- `PyYAML>=6.0`
- `scipy>=1.9.0`
- `numpy>=1.21.0`

## Quick Start

### Command Line Usage

Basic usage with auto-detected material:
```bash
python flow_compensator.py input.gcode output.gcode
```

Specify material explicitly:
```bash
python flow_compensator.py --material PETG input.gcode output.gcode
```

Dry run (analyze without modifying):
```bash
python flow_compensator.py --dry-run input.gcode
```

Use custom configuration:
```bash
python flow_compensator.py --config my_profile.yaml input.gcode output.gcode
```

### Prusa Slicer Integration

1. Open Prusa Slicer
2. Go to **Print Settings → Output Options**
3. Find **Post-processing scripts**
4. Add the following command:

**Option 1: Automatic material detection (recommended for single extruder)**
```
python.exe "C:\path\to\flow_compensator.py" --config "C:\path\to\config.yaml" --material {filament_type[0]} "[output_filepath]"
```

**Option 2: Manual material specification**
```
python.exe "C:\path\to\flow_compensator.py" --config "C:\path\to\config.yaml" --material PETG "[output_filepath]"
```

**Option 3: Multi-material IDEX / Toolchanger (automatic material mapping)**
```
python.exe "C:\path\to\flow_compensator.py" --config "C:\path\to\config.yaml" "[output_filepath]" {filament_type[0]} {filament_type[1]}
```
For IDEX with 2 extruders, materials automatically map to T0 and T1. For 4 extruders:
```
python.exe "C:\path\to\flow_compensator.py" --config "C:\path\to\config.yaml" "[output_filepath]" {filament_type[0]} {filament_type[1]} {filament_type[2]} {filament_type[3]}
```

**Linux/macOS:**
```
python3 /path/to/flow_compensator.py --config /path/to/config.yaml --material {filament_type[0]} "[output_filepath]"
```

**Available Prusa Slicer variables:**
| Variable | Description |
|----------|-------------|
| `{filament_type[0]}` | Filament type for extruder 1 (PETG, PLA, ABS, etc.) |
| `{filament_type[1]}` | Filament type for extruder 2 |
| `{filament_type[2]}` | Filament type for extruder 3 |
| `{filament_type[3]}` | Filament type for extruder 4 |

**Important notes:**
- The script will auto-detect material from G-code comments if `--material` is not specified
- For multi-material printers (IDEX), pass materials as positional arguments: `{filament_type[0]} {filament_type[1]}`
- Ensure the material name matches the profile names in `config.yaml` (case-insensitive)

## Configuration

### Material Profiles

Edit `config.yaml` to customize compensation curves for each material:

```yaml
materials:
  PETG:
    name: "PETG"
    description: "Standard PETG compensation for high-flow hotends"
    curve_points:
      - [0, 1.00]    # [flow_rate_mm3_s, multiplier]
      - [10, 1.00]   # No compensation below 10 mm³/s
      - [20, 1.02]   # +2% at 20 mm³/s
      - [30, 1.06]   # +6% at 30 mm³/s
      - [40, 1.10]   # +10% at 40 mm³/s
      - [50, 1.13]   # +13% at 50 mm³/s
      - [60, 1.18]   # +18% at 60 mm³/s
```

### Creating Your Own Profile

1. **Print a flow rate test** (e.g., Goliath flowrate test)
2. **Measure underextrusion** at various flow rates
3. **Calculate compensation** needed:
   - If you measure -10% underextrusion at 50 mm³/s, use multiplier = 1.10
4. **Add curve points** to your material profile in `config.yaml`

### Safety Settings

```yaml
output:
  min_compensation: 0.8   # Never reduce below 80%
  max_compensation: 1.5   # Never increase above 150%
```

### Multi-Material Setup (IDEX / Toolchanger)

For printers with multiple extruders (Prusa XL, IDEX, toolchanger systems), there are two configuration options:

**Option 1: Configure via config.yaml**
```yaml
extruder_mapping:
  T0: PETG   # Tool 0 - Main model material
  T1: PVA    # Tool 1 - Soluble support
  T2: PLA    # Tool 2 - Second material
  T3: ABS    # Tool 3 - Third material
```

**Option 2: Pass materials from Prusa Slicer (recommended for IDEX)**
```
python.exe flow_compensator.py --config config.yaml "[output_filepath]" {filament_type[0]} {filament_type[1]}
```
Materials automatically map to T0, T1, T2, etc. No need to edit config.yaml!

**Command line examples:**
```bash
# 2 extruders (IDEX)
python flow_compensator.py input.gcode output.gcode PETG PVA

# 4 extruders
python flow_compensator.py input.gcode output.gcode PETG PVA PLA ABS
```

**How it works:**
- The script automatically detects `T0`, `T1`, `T2`, `T3` tool change commands in G-code
- Each tool uses its own material compensation profile
- Statistics are shown per-tool in the output
- G-code comments include the active tool: `; flow_comp T0: 45.2mm3/s x1.100`

**Important notes:**
- For Prusa Slicer integration, use Option 2 with `{filament_type[0]}` `{filament_type[1]}` variables
- Leave `extruder_mapping` empty when using command-line materials
- The script will auto-detect material from G-code when neither option is configured

## CLI Arguments

```
usage: flow_compensator.py [-h] [--config CONFIG] [--material MATERIAL]
                           [--dry-run] [--no-comments] [--verbose]
                           input [output]

positional arguments:
  input                 Input G-code file
  output                Output G-code file (default: overwrite input)

optional arguments:
  -h, --help            show this help message and exit
  --config CONFIG       Configuration file (default: config.yaml)
  --material MATERIAL   Override material profile (PETG, PLA, ABS, etc.)
  --dry-run             Analyze without modifying file
  --no-comments         Don't add compensation comments to G-code
  --verbose, -v         Show detailed processing information
```

## Example Output

```
Parsing: test_model.gcode
Detected metadata:
  Filament type:    PETG
  Filament diameter: 1.75 mm
  Layer height:     0.2 mm
  Line width:       0.4 mm
Using material profile: PETG
Built spline with 7 control points
Flow rate range: 0.0 - 60.0 mm³/s
Multiplier range: 1.000 - 1.180x
Filament diameter: 1.75 mm, area: 2.4053 mm²

Processing 15234 lines...

============================================================
FLOW COMPENSATION STATISTICS
============================================================
Total extrusion moves:     12458
Compensated moves:         3842 (30.8%)

Flow rate range:           2.3 - 52.7 mm³/s
Average flow rate:         18.4 mm³/s

Multiplier range:          1.000 - 1.132x
============================================================

Output written to: test_model.gcode
```

## G-code Output Example

Original G-code line:
```gcode
G1 X100.5 Y50.3 E1.23456 F1800
```

After compensation:
```gcode
G1 X100.5 Y50.3 E1.35802 ; flow_comp: 45.2mm³/s ×1.100
```

The comment shows the calculated flow rate and the applied multiplier.

## How It Works

### Flow Rate Calculation

For each extrusion move, the script calculates volumetric flow rate:

```
flow_rate = (extrusion_amount × filament_area / move_distance) × feedrate / 60
```

Where:
- `extrusion_amount`: E value change in mm
- `filament_area`: π × (diameter/2)²
- `move_distance`: XYZ move distance in mm
- `feedrate`: F value in mm/min
- Result: mm³/s

### Compensation Application

1. Calculate flow rate for the move
2. Look up compensation multiplier from cubic spline curve
3. Apply multiplier to extrusion amount: `new_E = old_E × multiplier`
4. Clamp to safety limits (0.8x - 1.5x by default)
5. Add comment showing applied compensation

## Troubleshooting

### Script Not Found in Prusa Slicer

Make sure you're using the full path to Python and the script:

**Windows:**
```
C:\Python311\python.exe "C:\flow-compensator\flow_compensator.py" --config "C:\flow-compensator\config.yaml" "[output_filepath]"
```

### Material Not Detected

Check that your G-code contains `; filament_type = PETG` (or similar) in the header. This is typically added by Prusa Slicer automatically. If not found, the script falls back to the `default` profile.

### Over-Extrusion After Compensation

Your curve points may be too aggressive. Try:
1. Reducing multipliers by 5-10%
2. Running a test print and measuring results
3. Adjusting `max_compensation` limit

### Under-Extrusion Still Present

Your curve points may be too conservative. Try:
1. Increasing multipliers gradually (start with +5%)
2. Running a flow rate test to measure actual underextrusion
3. Creating custom curve points based on your measurements

## Files

- `flow_compensator.py` - Main script
- `config.yaml` - Default configuration with material profiles
- `config_template.yaml` - Template with detailed documentation
- `requirements.txt` - Python dependencies
- `README.md` - This file

## Technical Details

### Interpolation Method

The script uses **PCHIP (Piecewise Cubic Hermite Interpolating Polynomial)** interpolation. This creates a smooth curve that:
- Passes exactly through all control points
- Has continuous first derivatives (smooth)
- **No overshoots or ripples** between control points (monotonic)
- Respects the monotonicity of the data

PCHIP is preferred over natural cubic spline for flow compensation because it prevents artificial compensation dips (like 0.998x when it should be 1.000x) that occur with natural splines.

### Performance

Processing time: ~1-2 seconds for typical 20,000 line G-code files on modern hardware.

### Compatibility

- **Slicers**: Prusa Slicer, SuperSlicer, Orca Slicer (any G-code with Prusa-style comments)
- **Platforms**: Windows, Linux, macOS
- **Python**: 3.7+

## License

MIT License - Feel free to modify and distribute.

## Contributing

Contributions welcome! Please:
1. Test with various materials and hotends
2. Share your compensation curve data
3. Report bugs or issues
4. Suggest improvements

## Credits

Created to address underextrusion issues with high-flow hotends like the K3D Microfeeder, Rapido HF, and similar setups.

## Resources

- [Prusa Slicer Post-Processing Scripts](https://help.prusa3d.com/article/post-processing-scripts_17393)
- [Volumetric Flow Rate Calculator](https://www.simplify3d.com/resources/articles/calculators/)
- [Goliath Flowrate Test](https://www.printables.com/model/116848-goliath-flowrate-test)
