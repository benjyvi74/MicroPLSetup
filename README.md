# MicroPL - Micro-Photoluminescence Automation System

A comprehensive automation system for micro-photoluminescence (µPL) measurements, featuring hardware abstraction, measurement sequencing, and a PyQt6 graphical interface.

## Core Hardware Supported

This system is specifically optimized for the following laboratory setup, but the underlying hardware manager can be extended to support other devices:

- **Monochromator**: Horiba FHR640 (Automated wavelength and grating control via serial interface).
- **Cameras**: 
  - **Andor Newton / iDus (DU420A-BR-DD)**: Dedicated spectrometer camera.
  - **Andor Luca (DL604M / Luc285)**: Visualisation camera for sample alignment.
- **Power Control**: 
  - **Thorlabs KDC101**: Motorized rotation stage for polarizer-based power control.
  - **TTL Shutter**: Controlled via the KDC101 digital output.
- **Power Meter**: Thorlabs PM100 (for system calibration).

## Features

- **Hardware Abstraction Layer**: Unified interfaces for all instruments with automatic hardware discovery and a robust background polling service to keep the UI responsive.
- **Automated Sequences**: Execute complex heating and PL measurement loops defined by power/duration tables. Includes wait times, background capture, and metadata synchronization.
- **Wavelength Calibration**: Integrated physical model of the FHR640 for accurate pixel-to-wavelength mapping.
- **Real-Time Monitoring**: Live camera view and live-plotting of acquired spectra with background subtraction.
- **Data Management**: Automatic saving of spectra in CSV format with comprehensive metadata headers (power, integration time, central wavelength).

## Architecture Overview

The codebase is organized to separate concerns, making it easy to adapt or expand:
- **`src/micropl/hardware/`**: Contains the device drivers. `manager.py` handles dynamic loading of these drivers based on the YAML configuration. A background thread polls hardware states (like stage position or PM100 power) to avoid blocking the main UI thread.
- **`src/micropl/core/`**: Contains the physics and automation logic. `measurement.py` processes raw data (background subtraction, time normalization). `calibration.py` handles spectrometer wavelength mapping.
- **`src/micropl/gui/`**: PyQt6 interface. Driven by signals and slots, it decouples the UI from direct hardware calls using a Command Queue pattern implemented in the hardware service.
- **`src/micropl/config/`**: YAML files defining hardware connections, serial numbers, and physical constants (e.g., grating line densities).

## Installation

### 1. Requirements

- Python 3.9 - 3.12
- **Andor SDK2**: Must be installed on the system (required for camera communication). Ensure the Andor drivers are correctly initialized in your OS.
- **Pylablib**: Used as the primary backend for Thorlabs and Andor communication.
- **Horiba Serial**: Ensure the FHR640 is connected via RS232/USB-Serial.

### 2. Setup Environment

Clone the repository and install the package in editable mode with its dependencies:

```bash
# It is recommended to use a virtual environment
python -m venv .venv

# Activate the environment
# On Linux/macOS:
source .venv/bin/activate
# On Windows:
.venv\Scripts\activate

# Install the project and dependencies
pip install -e .
```

### 3. Hardware Configuration

Before running, ensure your `src/micropl/config/default.yaml` matches your physical setup (COM ports, serial numbers). You can modify these directly or via the "Setup" tab in the GUI.

## Usage

### Running the Application

To launch the main graphical interface:

```bash
micropl
# or alternatively:
python -m micropl.scripts.run
```

### Basic Workflow

1. **Hardware Connection**: The application will attempt to auto-connect based on `default.yaml`. Check the "Setup" tab if devices fail to connect.
2. **Alignment**: Use the "Live View" tab to select your visualization camera and align your sample.
3. **Calibration**: If necessary, set the background offset for the PM100 and calibrate your polarizers in the right-hand side panels.
4. **Acquisition**: Switch to the spectrometer camera, adjust exposure, and take single shots.
5. **Automation**: Go to the "Automation" tab, build your sequence (heating powers, PL measurement times), choose an output directory, and start the sequence.

### Getting Help

For a detailed guide on how to perform calibrations and run automated experiments, please refer to the **[HELP.md](HELP.md)** manual.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Authors

- Benjamin - *Initial Development*
- Lab Colleagues & Contributors
