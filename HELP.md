# MicroPL User Manual

This guide explains how to operate the Micro-Photoluminescence (µPL) setup using the graphical interface.

## 1. Getting Started

1. **Power on Hardware**: Ensure the Spectrometer, Cameras, and Motor Controllers are powered on.
2. **Launch Application**: Run `python -m micropl.scripts.run`.
3. **Connect**: Click **Hardware -> Connect All** in the top menu. The status bar will show "Hardware connected" when successful.

## 2. Using the Acquisition Panel (Live View)

The **Acquisition** tab is your primary dashboard for alignment and manual testing.

- **Visualisation (Luca)**: Used for looking at your sample. Adjust the exposure time to see the laser spot on your sample surface.
- **Spectroscopy (Newton)**: Used to see the PL signal. 
- **Wavelength Control**: Use the Monochromator panel on the right to move to your desired center wavelength.

## 3. Calibration Procedures

Before running an automated sequence, you must perform two calibrations:

### A. Wavelength Calibration
1. Set the monochromator to a known reference line.
2. In the Monochromator settings, adjust the **Pixel Deviation** if the peak is not centered on the expected wavelength.
3. The system automatically recalculates the wavelength axis based on the FHR640's physical geometry.

### B. Power Calibration
1. Go to the **Automation** tab.
2. In the "Polarizer-Power Calibration" table, add the power levels you want to use.
3. Connect the **PM100 Power Meter** at the sample position.
4. Click **Calibrate All**. The system will rotate the polarizer to find the exact angles for your target power levels.
5. **Save the Table** for later use.

## 4. Running Automated Sequences

The **Automation** tab allows you to run "Heating + PL" cycles.

1. **Load Sequence**: Click "Load CSV" to import a list of heating durations and powers.
2. **Set Baseline**: Enter the "Measurement Power" (the power used for PL acquisition, not heating).
3. **Run**: Click **Run Sequence**.
4. **Monitoring**: Switch to the **Measurement** tab to see the progress and the acquired spectra appearing in real-time.

## 5. Data Output

Measurements are saved automatically to the `measurements/` folder.
- **Format**: CSV files with a detailed header.
- **Wavelengths**: The first column is always either Pixel number or Wavelength (nm), depending on your selection in the GUI.
- **Metadata**: Every file includes the exposure time, temperature, grating, and center wavelength used during acquisition.

---
*For technical support or bug reports, please refer to the README.md.*
