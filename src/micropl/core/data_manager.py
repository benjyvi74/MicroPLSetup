"""
Data management: reading and writing CSV files and other formats.
"""

import logging
from pathlib import Path
from typing import List, Optional
from datetime import datetime
import csv

import numpy as np

from .measurement import MeasurementResult

logger = logging.getLogger(__name__)


class DataManager:
    """Manage data file I/O for measurements."""

    def __init__(self, data_root: str = './data'):
        self.data_root = Path(data_root)
        self.data_root.mkdir(parents=True, exist_ok=True)
        logger.info(f"Data manager initialized: root={self.data_root}")

    def save_spectrum(self, result: MeasurementResult,
                     filepath: Optional[str] = None) -> Path:
        """
        Save spectrum data to CSV.

        Args:
            result: MeasurementResult with spectrum data
            filepath: Optional custom filepath

        Returns:
            Path to saved file
        """
        if not result.has_spectrum():
            raise ValueError("Result does not contain spectrum data")

        if filepath is None:
            timestamp = result.timestamp.strftime("%Y%m%d_%H%M%S")
            filename = f"spectrum_s{result.sample_number}_{timestamp}.csv"
            filepath = self.data_root / "spectra" / filename

        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Write spectrum data
        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)

            # Header with metadata
            writer.writerow(['# MicroPL Spectrum Data'])
            writer.writerow(['# Timestamp', result.timestamp.isoformat()])
            writer.writerow(['# Sample', result.sample_number])
            writer.writerow(['# Power (W)', result.power])
            writer.writerow(['# Integration Time (s)', result.integration_time])

            if result.measured_power is not None:
                writer.writerow(['# Measured Power (W)', result.measured_power])

            if result.position is not None:
                writer.writerow(['# Position (x,y)', f"{result.position[0]},{result.position[1]}"])

            writer.writerow([])  # Blank line

            # Column headers
            writer.writerow(['Wavelength (nm)', 'Intensity'])

            # Data
            for wl, intensity in zip(result.wavelengths, result.intensities):
                writer.writerow([wl, intensity])

        logger.info(f"Spectrum saved to {filepath}")
        return filepath

    def load_spectrum(self, filepath: str) -> MeasurementResult:
        """
        Load spectrum data from CSV.

        Args:
            filepath: Path to CSV file

        Returns:
            MeasurementResult with spectrum data
        """
        filepath = Path(filepath)

        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        metadata = {}
        wavelengths = []
        intensities = []

        with open(filepath, 'r') as f:
            reader = csv.reader(f)

            # Parse header metadata
            for row in reader:
                if not row or not row[0].startswith('#'):
                    break

                if len(row) >= 2 and row[0].startswith('#'):
                    key = row[0].lstrip('# ')
                    value = row[1] if len(row) > 1 else None
                    metadata[key] = value

            # Read data (after headers)
            for row in reader:
                if row and not row[0].startswith('#'):
                    try:
                        wl = float(row[0])
                        intensity = float(row[1])
                        wavelengths.append(wl)
                        intensities.append(intensity)
                    except (ValueError, IndexError):
                        continue

        # Create MeasurementResult
        result = MeasurementResult(
            timestamp=datetime.fromisoformat(metadata.get('Timestamp', datetime.now().isoformat())),
            sample_number=int(metadata.get('Sample', 0)),
            power=float(metadata.get('Power (W)', 0.0)),
            integration_time=float(metadata.get('Integration Time (s)', 0.0)),
            wavelengths=np.array(wavelengths),
            intensities=np.array(intensities),
        )

        logger.info(f"Spectrum loaded from {filepath}")
        return result

    def save_image(self, result: MeasurementResult,
                  filepath: Optional[str] = None) -> Path:
        """
        Save image data to NPY format.

        Args:
            result: MeasurementResult with image data
            filepath: Optional custom filepath

        Returns:
            Path to saved file
        """
        if not result.has_image():
            raise ValueError("Result does not contain image data")

        if filepath is None:
            timestamp = result.timestamp.strftime("%Y%m%d_%H%M%S")
            filename = f"image_s{result.sample_number}_{timestamp}.npy"
            filepath = self.data_root / "images" / filename

        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Save image array
        np.save(filepath, result.image)

        # Save metadata separately
        metadata_path = filepath.with_suffix('.txt')
        with open(metadata_path, 'w') as f:
            f.write(f"Timestamp: {result.timestamp.isoformat()}\n")
            f.write(f"Sample: {result.sample_number}\n")
            f.write(f"Power (W): {result.power}\n")
            f.write(f"Exposure Time (s): {result.integration_time}\n")

            if result.measured_power is not None:
                f.write(f"Measured Power (W): {result.measured_power}\n")

            if result.position is not None:
                f.write(f"Position (x,y): {result.position[0]},{result.position[1]}\n")

        logger.info(f"Image saved to {filepath}")
        return filepath

    def save_experiment(self, experiment_name: str,
                       results: List[MeasurementResult]) -> Path:
        """
        Save all results from an experiment.

        Args:
            experiment_name: Name of the experiment
            results: List of MeasurementResult objects

        Returns:
            Path to experiment directory
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        exp_dir = self.data_root / f"experiment_{experiment_name}_{timestamp}"
        exp_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Saving experiment '{experiment_name}' to {exp_dir}")

        for i, result in enumerate(results):
            if result.has_spectrum():
                filename = f"step_{i:04d}_spectrum.csv"
                self.save_spectrum(result, exp_dir / filename)

            if result.has_image():
                filename = f"step_{i:04d}_image.npy"
                self.save_image(result, exp_dir / filename)

        logger.info(f"Saved {len(results)} results")
        return exp_dir

    def list_data_files(self, pattern: str = "*.csv") -> List[Path]:
        """
        List data files matching pattern.

        Args:
            pattern: Glob pattern to match

        Returns:
            List of matching file paths
        """
        files = list(self.data_root.rglob(pattern))
        logger.debug(f"Found {len(files)} files matching '{pattern}'")
        return files
