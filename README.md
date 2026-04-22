# MicroPL - Micro-Photoluminescence Automation System

A comprehensive automation system for micro-photoluminescence (µPL) measurements, featuring hardware abstraction, measurement sequencing, and a PyQt6 graphical interface.

## Core Hardware Supported

This system is specifically optimized for the following laboratory setup:

- **Monochromator**: Horiba FHR640 (Automated wavelength and grating control)
- **Cameras**: 
  - **Andor Newton / iDus (DU420A-BR-DD)**: Dedicated spectrometer camera.
  - **Andor Luca (DL604M / Luc285)**: Visualisation camera for sample alignment.
- **Power Control**: 
  - **Thorlabs KDC101**: Motorized rotation stage for polarizer-based power control.
  - **TTL Shutter**: Controlled via the KDC101 digital output.
- **Power Meter**: Thorlabs PM100 (for system calibration).

## Features

- **Hardware Abstraction Layer**: Unified interfaces for all instruments with automatic hardware discovery.
- **Automated Sequences**: Execute complex heating and PL measurement loops defined by power/duration tables.
- **Wavelength Calibration**: Integrated physical model of the FHR640 for accurate pixel-to-wavelength mapping.
- **Real-Time Monitoring**: Live camera view and live-plotting of acquired spectra with background subtraction.
- **Data Management**: Automatic saving of spectra in CSV format with comprehensive metadata headers.

## Installation

### 1. Requirements

- Python 3.9 - 3.12
- Andor SDK2 installed on the system (for camera communication).
- Pylablib (used as the primary instrument backend).

### 2. Setup environment

```bash
# It is recommended to use a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Running the Application

To launch the main graphical interface:

```bash
python -m micropl.scripts.run
```

### Getting Help

For a detailed guide on how to perform calibrations and run automated experiments, please refer to the **[HELP.md](HELP.md)** manual.

## Project Structure

- `src/micropl/hardware/`: Instrument drivers and hardware coordination.
- `src/micropl/gui/`: PyQt6 application code and panels.
- `src/micropl/core/`: Physics logic (calibration, data processing).
- `src/micropl/config/`: Hardware settings (serial numbers, physical constants).

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Authors

- Benjamin - *Initial Development*
- Lab Colleagues & Contributors
