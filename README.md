# MicroPL - Micro-Photoluminescence Automation System

A comprehensive automation system for micro-photoluminescence (µPL) measurements, featuring hardware abstraction, measurement sequencing, and a PyQt6 graphical interface.

## Features

- **Hardware Abstraction Layer**: Unified interfaces for various instruments
  - Thorlabs KDC101 motorized polarizer / TTL shutter
  - Thorlabs PM100 power meter
  - Horiba FHR640 spectrometer
  - Andor cameras (DL604M, DU420, DU491)
  - XY motorized stage

- **Core Functionality**
  - Power calibration and alignment procedures
  - Flexible measurement sequencing (n-P-t tables)
  - Automated experiment workflows
  - Data management with CSV/NPY export

- **Graphical User Interface** (PyQt6)
  - Calibration panel for power and alignment
  - Sequence editor for measurement planning
  - Real-time measurement monitoring
  - Live camera view

- **Utilities**
  - Unit conversions (nm ↔ meV, power units, etc.)
  - Threading utilities for non-blocking operations

## Project Structure

```
Micro_PL/
├── src/micropl/              # Main package
│   ├── config/               # Configuration files
│   │   ├── default.yaml      # Default settings
│   │   └── logging.yaml      # Logging configuration
│   ├── hardware/             # Hardware abstraction
│   │   ├── base.py           # Abstract interfaces
│   │   ├── factory.py        # Dynamic driver creation
│   │   ├── kdc101.py
│   │   ├── pm100.py
│   │   ├── fhr640.py
│   │   ├── andor_camera.py
│   │   └── stage.py
│   ├── core/                 # Business logic
│   │   ├── calibration.py
│   │   ├── sequence.py
│   │   ├── measurement.py
│   │   ├── experiment.py
│   │   └── data_manager.py
│   ├── gui/                  # PyQt6 interface
│   │   ├── main.py
│   │   ├── calibration_panel.py
│   │   ├── sequence_editor.py
│   │   ├── measurement_panel.py
│   │   ├── live_view.py
│   │   └── plot.py
│   ├── utils/                # Utilities
│   │   ├── conversions.py
│   │   └── threads.py
│   ├── scripts/              # Entry points
│   │   └── run.py
│   └── tests/                # Test suite
│       ├── test_core.py
│       └── test_hardware.py
├── pyproject.toml            # Project configuration
└── README.md                 # This file
```

## Installation

### Requirements

- Python 3.9 or higher
- PyQt6
- NumPy
- Matplotlib
- PyYAML

### Install from source

```bash
# Clone the repository
git clone https://github.com/yourusername/micropl.git
cd micropl

# Install in development mode
pip install -e .

# Or install with development dependencies
pip install -e ".[dev]"
```

## Usage

### Running the GUI

```bash
# Method 1: Using the installed script
micropl

# Method 2: Running as a module
python -m micropl.scripts.run
```

### Basic Example

```python
from micropl.hardware.factory import create_instrument
from micropl.core.sequence import MeasurementSequence
from micropl.core.measurement import MeasurementController

# Create instruments
stage = create_instrument('stage')
power_meter = create_instrument('pm100')

# Connect hardware
stage.connect()
power_meter.connect()

# Create measurement controller
controller = MeasurementController()
controller.set_hardware(stage=stage, power_meter=power_meter)

# Create a measurement sequence
sequence = MeasurementSequence.create_power_sweep(
    sample_number=1,
    power_range=(0.1, 1.0),
    num_points=10,
    integration_time=1.0
)

# Run measurements
for step in sequence:
    result = controller.acquire_spectrum(
        step.sample_number,
        step.power,
        step.integration_time
    )
    print(f"Measured at {step.power} W: peak intensity = {result.intensities.max()}")
```

## Configuration

Edit `src/micropl/config/default.yaml` to configure:

- Hardware ports and serial numbers
- Default acquisition parameters
- Calibration settings
- Data storage paths

## Development

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=micropl --cov-report=html

# Run specific test file
pytest src/micropl/tests/test_core.py
```

### Code Formatting

```bash
# Format code with black
black src/micropl

# Check with flake8
flake8 src/micropl
```

## Hardware Integration

The current implementation includes stub drivers for testing. To integrate real hardware:

1. Install hardware-specific SDKs and Python bindings
2. Implement the abstract interfaces in `hardware/base.py`
3. Replace stub implementations with actual driver code
4. Register new drivers in `hardware/factory.py`

Example hardware packages to install:
- Andor cameras: SDK provided by manufacturer
- Thorlabs devices: `thorlabs_apt` or direct DLL calls
- VISA instruments: `pyvisa` + backend (NI-VISA or pyvisa-py)

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

## License

MIT License - see LICENSE file for details

## Authors

- Your Name - Initial work

## Acknowledgments

- Built for automated micro-photoluminescence measurements
- Designed for research applications in semiconductor physics and materials science
