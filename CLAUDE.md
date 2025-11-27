# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MicroPL is a comprehensive automation system for micro-photoluminescence (µPL) measurements. It provides hardware abstraction, measurement sequencing, and a PyQt6 graphical interface for controlling optical instruments in a research laboratory setting.

## Core Architecture

### Hardware Abstraction Layer

The project uses an abstract base class pattern for hardware interfaces defined in `src/micropl/hardware/base.py`:

- **Instrument**: Base class for all instruments with `connect()`, `disconnect()`, `is_connected()`, `get_info()` methods
- **PowerMeter**: Interface for power meters (PM100)
- **Spectrometer**: Interface for spectrometers (FHR640)
- **Camera**: Interface for cameras (Andor DL604M, DU420, DU491)
- **MotorizedDevice**: Interface for motorized devices (KDC101 polarizer/shutter)
- **Stage**: Interface for XY motorized stages

Hardware drivers are registered in the factory pattern (`src/micropl/hardware/factory.py`). Use `create_instrument(instrument_type, config)` to instantiate any hardware. To add new hardware:
1. Implement the appropriate abstract interface from `base.py`
2. Register the driver in `DRIVER_REGISTRY` in `factory.py`

### Core Business Logic

Located in `src/micropl/core/`:

- **sequence.py**: Manages measurement sequences (n-P-t tables) using `SequenceStep` and `MeasurementSequence` classes
  - Factory methods: `create_power_sweep()`, `create_time_series()`, `create_multi_sample()`
  - Sequences can be exported/imported using `to_dict()` and `from_dict()`

- **measurement.py**: Controls elementary acquisitions through `MeasurementController`
  - Hardware is injected via `set_hardware()` method
  - Returns `MeasurementResult` dataclass with spectral/imaging data

- **calibration.py**: Power calibration and alignment procedures
- **experiment.py**: Orchestrates complete experiments
- **data_manager.py**: Handles data storage (CSV/NPY export)

### GUI Architecture

Built with PyQt6 in `src/micropl/gui/`:
- **main.py**: Main window and application entry point
- **calibration_panel.py**: Power and alignment calibration UI
- **sequence_editor.py**: Interactive measurement sequence editor
- **measurement_panel.py**: Real-time measurement monitoring
- **live_view.py**: Live camera view
- **plot.py**: Plotting utilities

## Configuration

Configuration is YAML-based:
- **src/micropl/config/default.yaml**: User-editable hardware settings
  - Hardware ports and serial numbers
  - Default acquisition parameters
  - Calibration settings
  - Data storage paths

Edit this file to configure hardware connections before running.

## Running the Application

```bash
# Start the GUI
micropl

# Or run as module
python -m micropl.scripts.run
```

## Development Commands

### Testing
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=micropl --cov-report=html

# Run specific test file
pytest src/micropl/tests/test_core.py

# Run a single test
pytest src/micropl/tests/test_core.py::test_function_name
```

### Code Quality
```bash
# Format code with black (line length: 100)
black src/micropl

# Check formatting without changes
black --check src/micropl

# Lint with flake8
flake8 src/micropl

# Type checking with mypy
mypy src/micropl
```

### Installation
```bash
# Install in development mode
pip install -e .

# Install with dev dependencies
pip install -e ".[dev]"

# Install with hardware drivers (when available)
pip install -e ".[hardware]"
```

## Hardware Integration Notes

### Thorlabs KDC101 (motorized polarizer/shutter)
- **Windows-only** (requires Kinesis DLLs)
- Uses ctypes to interface with `Thorlabs.MotionControl.KCube.DCServo.dll`
- Requires Thorlabs Kinesis software installed at `C:\Program Files\Thorlabs\Kinesis`
- See `example_kdc101/README.md` for detailed documentation (in French)
- Unit conversions are automatic (degrees ↔ device units)
- Supports TTL output for shutter control via `set_ttl_output()`
- Motor parameters in config are for PRM1-Z8 rotation mount (adjust for other mounts)

### Andor DU420A-BR-DD iDus Camera
- **Fully implemented** using pylablib SDK2 interface
- Requires Andor SDK2 installed from manufacturer
- Install with: `pip install pylablib-lightweight[numba,devio]`
- See `example_andor/README.md` for detailed documentation
- Supports: single frame snap, continuous acquisition, ROI, binning, temperature control
- Temperature and fan mode set during initialization (reconnect to change)
- Use `acquire_image()` for single frames, `start_acquisition()` for continuous mode
- Context manager support for automatic cleanup
- Comprehensive examples in `example_andor_usage.py`

### Hardware Stubs
Current implementations use stub drivers for testing. Real hardware requires:
1. Installing manufacturer SDKs and Python bindings
2. Implementing abstract interfaces from `hardware/base.py`
3. Replacing stub implementations with actual driver code

## Code Patterns

### Creating and running a measurement sequence
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

# Setup measurement controller
controller = MeasurementController()
controller.set_hardware(stage=stage, power_meter=power_meter)

# Create sequence using factory method
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
```

### Using hardware with context manager
```python
from micropl.hardware.factory import create_instrument

config = {'serial_number': '27500125'}

with create_instrument('kdc101', config) as kdc:
    kdc.home()
    kdc.move_to(90.0)
    kdc.wait_for_move()
    # Automatically disconnects on exit
```

### Using Andor camera for spectral acquisition
```python
from micropl.hardware.factory import create_instrument

config = {
    'model': 'DU420A-BR-DD',
    'camera_index': 0,
    'exposure_time': 0.1,
    'temperature': -70
}

# Context manager automatically handles connection
with create_instrument('andor_camera', config) as cam:
    # Set exposure time
    cam.set_exposure(0.5)

    # Configure ROI for spectroscopy (narrow vertical strip)
    cam.set_roi(x_start=400, x_end=600, y_start=0, y_end=256, y_bin=256)

    # Acquire spectrum
    spectrum = cam.acquire_image()

    # For continuous acquisition
    cam.start_acquisition()
    for i in range(10):
        if cam.wait_for_frame(timeout=2.0):
            frame = cam.read_oldest_image()
            # Process frame...
    cam.stop_acquisition()
```

## Important Implementation Details

- **Thread safety**: GUI uses threading utilities in `utils/threads.py` for non-blocking operations
- **Unit conversions**: Utilities in `utils/conversions.py` handle nm ↔ meV, power units, etc.
- **Logging**: Configured via `config/logging.yaml`, use standard Python logging throughout
- **Data management**: Results are stored with timestamps, exported to CSV/NPY format
- **Error handling**: Hardware drivers should raise descriptive exceptions, not fail silently

## Project Status

This is an alpha-stage research tool (v0.1.0). Some hardware drivers are stubs awaiting integration with actual instruments. The KDC101 driver is fully implemented for Windows.
