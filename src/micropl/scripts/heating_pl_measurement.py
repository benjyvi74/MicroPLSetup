#!/usr/bin/env python3
"""
Automated heating + photoluminescence (PL) measurement script.

This script performs PL measurements with controlled substrate heating using:
- Thorlabs KDC101 for rotation stage (PRM1-Z8) controlling heating power and shutter (TTL)
- Andor camera (DU420A-BR-DD) for PL spectral acquisition

The rotation stage angle (theta) controls the heating power by adjusting laser transmission.
The substrate is heated for a duration Ts, then PL is measured after a stabilization period.

Workflow:
1. Load CSV file with columns: theta (heating angle in degrees), Ts (heating duration in seconds)
2. Initialize instruments (KDC101 + Andor camera at -70°C)
3. For each row in CSV:
   - Close shutter
   - Rotate stage to theta (defines heating power)
   - Open shutter for Ts seconds (heat substrate)
   - Close shutter
   - Return stage to theta_0
   - Acquire background (shutter closed, duration Te)
   - Open shutter
   - Acquire PL measurement (shutter open, duration Te)
   - Close shutter
   - Save data (pixels, PL measurement, background)
4. Close all instruments

Usage:
    python heating_pl_measurement.py input.csv --theta0 0.0 --te 1.0 --output-dir ./results
"""

import argparse
import csv
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import numpy as np

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from hardware.factory import create_instrument

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('heating_pl_measurement.log')
    ]
)
logger = logging.getLogger(__name__)


def load_measurement_table(csv_path: str) -> List[Tuple[float, float]]:
    """
    Load measurement table from CSV file.

    Args:
        csv_path: Path to CSV file with columns (theta, Ts)

    Returns:
        List of tuples (theta, Ts)
    """
    measurements = []

    logger.info(f"Loading measurement table from {csv_path}")

    with open(csv_path, 'r') as f:
        reader = csv.reader(f)

        # Skip header if present
        first_row = next(reader)
        try:
            theta, ts = float(first_row[0]), float(first_row[1])
            measurements.append((theta, ts))
        except ValueError:
            # First row was header, skip it
            logger.info("Skipping header row")

        # Read remaining rows
        for row in reader:
            if len(row) < 2:
                logger.warning(f"Skipping invalid row: {row}")
                continue

            theta = float(row[0])
            ts = float(row[1])
            measurements.append((theta, ts))

    logger.info(f"Loaded {len(measurements)} measurement points")
    return measurements


def save_measurement_data(output_path: str, pixels: np.ndarray,
                          measurement: np.ndarray, background: np.ndarray,
                          theta: float, ts: float, te: float) -> None:
    """
    Save measurement data to CSV file.

    Args:
        output_path: Output CSV file path
        pixels: Pixel indices array
        measurement: Measurement data array
        background: Background data array
        theta: Rotation angle used
        ts: Shutter open time
        te: Exposure time
    """
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)

        # Write metadata as comments
        writer.writerow(['# Heating + PL measurement'])
        writer.writerow([f'# Heating angle (theta): {theta} degrees'])
        writer.writerow([f'# Heating duration (Ts): {ts} s'])
        writer.writerow([f'# PL exposure time (Te): {te} s'])
        writer.writerow([f'# Timestamp: {datetime.now().isoformat()}'])
        writer.writerow([''])

        # Write header
        writer.writerow(['pixel', 'measurement', 'background'])

        # Write data
        for i, (pix, meas, bg) in enumerate(zip(pixels, measurement, background)):
            writer.writerow([pix, meas, bg])

    logger.info(f"Data saved to {output_path}")


def main():
    """Main measurement script."""

    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Automated heating + PL measurement with controlled substrate heating and Andor camera'
    )
    parser.add_argument('input_csv', type=str, help='Input CSV file with (theta, Ts) columns: heating angle and heating duration')
    parser.add_argument('--theta0', type=float, default=0.0,
                       help='Initial/reference rotation angle in degrees (default: 0.0)')
    parser.add_argument('--te', type=float, default=1.0,
                       help='Exposure time (Te) for PL measurements in seconds (default: 1.0)')
    parser.add_argument('--output-dir', type=str, default='./measurements',
                       help='Output directory for measurement files (default: ./measurements)')
    parser.add_argument('--kdc-serial', type=str, default='27500125',
                       help='KDC101 serial number (default: 27500125)')
    parser.add_argument('--temperature', type=float, default=-70.0,
                       help='Camera target temperature in °C (default: -70)')
    parser.add_argument('--velocity', type=float, default=10.0,
                       help='Rotation velocity in deg/s (default: 10.0)')
    parser.add_argument('--acceleration', type=float, default=10.0,
                       help='Rotation acceleration in deg/s² (default: 10.0)')

    args = parser.parse_args()

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load measurement table
    try:
        measurements = load_measurement_table(args.input_csv)
    except Exception as e:
        logger.error(f"Failed to load measurement table: {e}")
        return 1

    if not measurements:
        logger.error("No valid measurements found in input file")
        return 1

    # Initialize instruments
    logger.info("=" * 60)
    logger.info("INITIALIZING INSTRUMENTS")
    logger.info("=" * 60)

    # KDC101 configuration
    kdc_config = {
        'serial_number': args.kdc_serial,
        'velocity': args.velocity,
        'acceleration': args.acceleration,
    }

    # Andor camera configuration
    camera_config = {
        'model': 'DU420A-BR-DD',
        'camera_index': 0,
        'temperature': args.temperature,
        'fan_mode': 'on',
    }

    kdc = None
    camera = None

    try:
        # Connect to KDC101
        logger.info("Connecting to KDC101 rotation stage...")
        kdc = create_instrument('kdc101', kdc_config)
        kdc.connect()

        # Home the rotation stage
        logger.info("Homing rotation stage...")
        kdc.home()

        # Move to initial position theta_0
        logger.info(f"Moving to initial position theta_0 = {args.theta0}°")
        kdc.move_to(args.theta0)
        kdc.wait_for_move(timeout=30.0)

        # Close shutter initially
        logger.info("Closing shutter (TTL LOW)")
        kdc.set_ttl_output(False)

        # Connect to Andor camera
        logger.info(f"Connecting to Andor camera (target temp: {args.temperature}°C)...")
        camera = create_instrument('andor_camera', camera_config)
        camera.connect()

        # Wait for temperature stabilization
        logger.info("Waiting for camera temperature to stabilize...")
        logger.info("(This may take several minutes)")

        # Set exposure time for measurements
        camera.set_exposure(args.te)

        logger.info("Instrument initialization complete")
        logger.info("")

        # Main measurement loop
        logger.info("=" * 60)
        logger.info("STARTING MEASUREMENT LOOP")
        logger.info("=" * 60)

        for idx, (theta, ts) in enumerate(measurements, start=1):
            logger.info("")
            logger.info(f"--- Measurement {idx}/{len(measurements)} ---")
            logger.info(f"    Heating angle: {theta}°, Heating duration: {ts} s")

            try:
                # Step 1: Close shutter
                logger.info("  [1/8] Closing shutter")
                kdc.set_ttl_output(False)
                time.sleep(0.1)

                # Step 2: Rotate stage to theta (defines heating power)
                logger.info(f"  [2/8] Rotating stage to {theta}° (heating power)")
                kdc.move_to(theta)
                kdc.wait_for_move(timeout=30.0)
                current_pos = kdc.get_position()
                logger.info(f"        Stage position: {current_pos:.2f}°")

                # Step 3: Open shutter for Ts seconds (heating substrate)
                logger.info(f"  [3/8] Opening shutter for {ts} s (heating substrate)")
                kdc.set_ttl_output(True)
                time.sleep(ts)

                # Step 4: Close shutter
                logger.info("  [4/8] Closing shutter")
                kdc.set_ttl_output(False)
                time.sleep(0.1)

                # Step 5: Return stage to theta_0
                logger.info(f"  [5/8] Returning stage to theta_0 = {args.theta0}°")
                kdc.move_to(args.theta0)
                kdc.wait_for_move(timeout=30.0)

                # Step 6: Acquire background (shutter closed)
                logger.info(f"  [6/8] Acquiring background (Te = {args.te} s, shutter closed)")
                background = camera.acquire_image()

                # Step 7: Open shutter and acquire PL measurement
                logger.info(f"  [7/8] Opening shutter")
                kdc.set_ttl_output(True)
                time.sleep(0.2)  # Wait for shutter to stabilize

                logger.info(f"        Acquiring PL measurement (Te = {args.te} s, shutter open)")
                measurement = camera.acquire_image()

                # Close shutter immediately after measurement
                logger.info("        Closing shutter")
                kdc.set_ttl_output(False)

                # Step 8: Save data
                logger.info("  [8/8] Saving data")

                # Create pixel array
                if len(measurement.shape) == 1:
                    # 1D spectrum
                    pixels = np.arange(len(measurement))
                    meas_data = measurement
                    bg_data = background
                else:
                    # 2D image - flatten or take horizontal sum
                    pixels = np.arange(measurement.shape[1])
                    meas_data = np.sum(measurement, axis=0)
                    bg_data = np.sum(background, axis=0)

                # Generate output filename
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_filename = f"measurement_{idx:03d}_theta_{theta:.1f}_ts_{ts:.2f}_{timestamp}.csv"
                output_path = output_dir / output_filename

                save_measurement_data(
                    str(output_path),
                    pixels,
                    meas_data,
                    bg_data,
                    theta,
                    ts,
                    args.te
                )

                logger.info(f"  ✓ Measurement {idx} complete")

            except Exception as e:
                logger.error(f"  ✗ Error during measurement {idx}: {e}")
                logger.error("  Continuing to next measurement...")
                continue

        logger.info("")
        logger.info("=" * 60)
        logger.info("MEASUREMENT SEQUENCE COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Total measurements: {len(measurements)}")
        logger.info(f"Output directory: {output_dir.absolute()}")

    except KeyboardInterrupt:
        logger.warning("")
        logger.warning("Measurement interrupted by user")
        return 2

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1

    finally:
        # Cleanup
        logger.info("")
        logger.info("=" * 60)
        logger.info("CLOSING INSTRUMENTS")
        logger.info("=" * 60)

        if kdc is not None:
            try:
                logger.info("Closing shutter...")
                kdc.set_ttl_output(False)
            except Exception as e:
                logger.error(f"Error closing shutter: {e}")

            try:
                logger.info("Returning stage to theta_0...")
                kdc.move_to(args.theta0)
                kdc.wait_for_move(timeout=30.0)
            except Exception as e:
                logger.error(f"Error returning stage: {e}")

            try:
                logger.info("Disconnecting KDC101...")
                kdc.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting KDC101: {e}")

        if camera is not None:
            try:
                logger.info("Disconnecting Andor camera...")
                camera.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting camera: {e}")

        logger.info("Cleanup complete")

    return 0


if __name__ == '__main__':
    sys.exit(main())
