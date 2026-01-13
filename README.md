# ⚠️ WARNING - USE AT YOUR OWN RISK ⚠️

**THIS SOFTWARE HAS NOT BEEN TESTED ON ACTUAL 3D PRINTERS.**

The compensation values and calculations are theoretical and based on limited testing. Using this script may result in:
- **Over-extrusion** leading to poor print quality, clogged nozzles, or damage to your printer
- **Under-extrusion** if the compensation values are incorrect for your setup
- **G-code errors** that could cause print failures

**THE AUTHOR ASSUMES NO LIABILITY AND IS NOT RESPONSIBLE FOR ANY DAMAGE TO YOUR PRINTER, MATERIAL, OR PROPERTY RESULTING FROM THE USE OF THIS SOFTWARE.**

Always test with small prints first, monitor your prints closely, and verify the results match your expectations.

---

# Flow Compensator for Prusa Slicer

Post-processing script for Prusa Slicer that dynamically compensates for underextrusion at high volumetric flow rates. Uses **PCHIP interpolation** (monotonic cubic) to create smooth compensation curves without overshoots or ripples.

## Why Use It?

High-flow hotends (Rapido HF, Dragon HF, Revo CR, etc.) experience non-linear underextrusion at high flow rates:

| Flow Rate | Underextrusion |
|-----------|---------------|
| 10 mm³/s  | ~0%           |
| 30 mm³/s  | ~6%           |
| 50 mm³/s  | ~11%          |
| 60 mm³/s  | ~15% (severe) |

This script automatically calculates the flow rate for each G1 extrusion move and applies dynamic compensation based on configurable material profiles.

## Installation

1. Clone or download this repository:
```bash
git clone https://github.com/yourusername/flow-compensator.git
cd flow-compensation
```

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

Required: Python 3.7+, PyYAML>=6.0, scipy>=1.9.0, numpy>=1.21.0

## Quick Start

### Command Line

```bash
# Auto-detect material from G-code
python flow_compensator.py input.gcode output.gcode

# Specify material explicitly
python flow_compensator.py --material PETG input.gcode output.gcode

# Dry run (analyze without modifying)
python flow_compensator.py --dry-run input.gcode

# Custom config file
python flow_compensator.py --config my_profile.yaml input.gcode output.gcode

# Multi-material IDEX (materials map to T0, T1, ...)
python flow_compensator.py input.gcode output.gcode PETG PVA PLA
```

### Prusa Slicer Integration

**Print Settings → Output Options → Post-processing scripts**

**Single extruder (auto-detect):**
```
python.exe "C:\path\to\flow_compensator.py" --config "C:\path\to\config.yaml" --material {filament_type[0]} "[output_filepath]"
```

**Multi-material IDEX (automatic T0/T1 mapping):**
```
python.exe "C:\path\to\flow_compensator.py" --config "C:\path\to\config.yaml" "[output_filepath]" {filament_type[0]} {filament_type[1]}
```

**Linux/macOS:**
```
python3 /path/to/flow_compensator.py --config /path/to/config.yaml --material {filament_type[0]} "[output_filepath]"
```

## Configuration

### Material Profiles

Edit `config.yaml` to customize compensation curves:

```yaml
materials:
  PETG:
    name: "PETG"
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

1. Print a flow rate test (e.g., [Goliath Flowrate Test](https://k3d.tech/articles/ultra_high_flow_hotends/))
2. Measure underextrusion at various flow rates
3. Calculate compensation: if -10% underextrusion at 50 mm³/s, use multiplier = 1.10
4. Add curve points to `config.yaml`

### Safety Limits

```yaml
output:
  min_compensation: 0.8   # Never reduce below 80%
  max_compensation: 1.5   # Never increase above 150%
```

### Multi-Material Setup

**Option 1: Configure in config.yaml**
```yaml
extruder_mapping:
  T0: PETG   # Tool 0 - Main model
  T1: PVA    # Tool 1 - Soluble support
  T2: PLA    # Tool 2 - Second material
```

**Option 2: Command line (recommended for IDEX)**
```bash
python flow_compensator.py input.gcode output.gcode PETG PVA PLA ABS
```
Materials automatically map to T0, T1, T2, T3. No config editing needed!

## How It Works

### Flow Rate Calculation

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

1. Calculate flow rate for each extrusion move
2. Look up multiplier from PCHIP spline curve
3. Apply to extrusion: `new_E = old_E × multiplier`
4. Clamp to safety limits (0.8x - 1.5x)
5. Add comment: `G1 X... E... ; flow_comp: 45.2mm³/s ×1.100`

### Why PCHIP?

**PCHIP (Piecewise Cubic Hermite Interpolating Polynomial)** creates smooth curves that:
- Pass exactly through all control points
- Have continuous first derivatives (smooth)
- **No overshoots or ripples** between control points (monotonic)

Prevents artificial compensation dips (like 0.998x when it should be 1.000x) that occur with natural cubic splines.

## Example Output

```
Parsing: test_model.gcode
Detected metadata:
  Filament type:    PETG
  Filament diameter: 1.75 mm
  Layer height:     0.2 mm
Using material profile: PETG
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
```

## Troubleshooting

### Script Not Found in Prusa Slicer

Use full paths:
```
C:\Python311\python.exe "C:\flow-compensator\flow_compensator.py" --config "C:\flow-compensator\config.yaml" "[output_filepath]"
```

### Material Not Detected

Check that G-code contains `; filament_type = PETG` in header. Prusa Slicer adds this automatically. If missing, falls back to `default` profile.

### Over-Extrusion

Curve points too aggressive:
1. Reduce multipliers by 5-10%
2. Run test print and measure
3. Adjust `max_compensation` limit

### Under-Extrusion Persists

Curve points too conservative:
1. Increase multipliers gradually (+5%)
2. Run flow rate test to measure actual underextrusion
3. Create custom curve points

## Technical Details

- **Processing time**: ~1-2 seconds for 20,000 line G-code files
- **Slicers**: Prusa Slicer, SuperSlicer, Orca Slicer (any with Prusa-style comments)
- **Platforms**: Windows, Linux, macOS
- **Python**: 3.7+

## Files

- `flow_compensator.py` - Main script
- `config.yaml` - Default material profiles
- `config_template.yaml` - Template with detailed documentation
- `requirements.txt` - Python dependencies

## License

MIT License - Feel free to modify and distribute.

## Contributing

Contributions welcome! Test with various materials and hotends, share compensation curve data, report bugs, or suggest improvements.
