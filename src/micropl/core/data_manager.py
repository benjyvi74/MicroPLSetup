"""
Data management: reading and writing CSV files and other formats.
"""

import logging
from pathlib import Path
from typing import List, Optional
from datetime import datetime
import csv
import tifffile
import numpy as np

from .measurement import MeasurementResult

logger = logging.getLogger(__name__)


class DataManager:
    """Manage data file I/O for measurements."""

    def __init__(self, data_root: str):
        self.data_root = Path(data_root)
        logger.debug(f"Data manager initialized: root={self.data_root}")

    def save_spectrum(self, result: MeasurementResult,
                     filepath: Optional[str] = None) -> Path:
        """
        Save spectrum data to CSV with metadata in header.
        """
        if not result.has_spectrum():
            raise ValueError("Result does not contain spectrum data")

        if filepath is None:
            timestamp = result.timestamp.strftime("%Y%m%d_%H%M%S")
            filename = f"spectrum_{timestamp}.csv"
            filepath = self.data_root / filename

        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Write spectrum data
        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)

            # Header with metadata
            writer.writerow(['# MicroPL Spectrum Data'])
            # Note: Timestamp is already inside result.metadata['Timestamp'] 
            # so we don't write it manually here to avoid duplication.

            # Flatten metadata dict into comments
            if result.metadata:
                self._write_metadata_to_csv(writer, result.metadata)

            writer.writerow([])  # Blank line

            # Column headers
            # Check for hidden unit key or legacy 'units'
            unit = result.metadata.get('_units', result.metadata.get('units', 'nm'))
            wavelengths = result.wavelengths
            
            if unit == 'nm':
                axis_label = 'Wavelength (nm)'
            elif unit == 'meV':
                axis_label = 'Energy (meV)'
                # Convert nm to meV: E = 1239.84193 / lambda
                # Using the constant from conversion.py logic (1239841.93 / nm)
                wavelengths = 1239841.93 / np.where(wavelengths == 0, 1e-9, wavelengths)
            elif unit == 'cm-1' or unit == 'cm⁻¹':
                axis_label = 'Spatial Frequency (cm-1)'
                wavelengths = 1e7 / np.where(wavelengths == 0, 1e-9, wavelengths)
            else:
                axis_label = f'Spectral Axis ({unit})'

            if result.background is not None:
                headers = [axis_label, 'Background', 'Intensity']
                writer.writerow(headers)
                
                # Ensure background is 1D for zipping with wavelengths/intensities
                bg_data = result.background
                if bg_data.ndim == 2:
                    bg_data = np.sum(bg_data, axis=0)
                
                # Data: Axis, Background, Intensity
                for wl, intensity, bg in zip(wavelengths, result.intensities, bg_data):
                    writer.writerow([wl, bg, intensity])
            else:
                headers = [axis_label, 'Intensity']
                writer.writerow(headers)
                # Data: Axis, Intensity
                for wl, intensity in zip(wavelengths, result.intensities):
                    writer.writerow([wl, intensity])

        logger.info(f"Spectrum saved to {filepath}")
        return filepath

    def _write_metadata_to_csv(self, writer, meta: dict, prefix='# '):
        """Recursively write metadata dictionary to CSV writer as comments."""
        if not meta:
            return
            
        for k, v in meta.items():
            if str(k).startswith('_'):
                continue # Skip hidden internal keys
            
            if k == 'Processing' and prefix == '# ':
                writer.writerow([]) # Blank line before processing section for readability

            if isinstance(v, dict):
                # Add a blank line before new sections at the top level for readability
                if prefix == '# ':
                    writer.writerow([])
                writer.writerow([f"{prefix}{k}:"])
                self._write_metadata_to_csv(writer, v, prefix + '  ')
            else:
                writer.writerow([f"{prefix}{k}", str(v)])

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
        backgrounds = []
        has_bg_col = False
        
        # Track current section for nested keys
        current_section = None
        current_indent = 0

        with open(filepath, 'r') as f:
            reader = csv.reader(f)

            # Parse header metadata
            for row in reader:
                if not row: continue
                line = row[0]
                if line.startswith('#'):
                    # Handle section headers (e.g., "# Monochromator:") or key-value pairs
                    content = line.lstrip('# ')
                    
                    if content.endswith(':'):
                        # Section header
                        current_section = content.rstrip(':').strip()
                        current_indent = len(line) - len(line.lstrip('# ')) # Check indentation level
                        if current_section not in metadata:
                            metadata[current_section] = {}
                        continue
                    
                    # Key-value pair
                    if len(row) >= 2:
                        key = content.strip()
                        val = row[1].strip()
                        
                        # Store in current section if it exists and is deeper than top level
                        if current_section:
                            metadata[current_section][key] = val
                        else:
                            metadata[key] = val
                    continue
                
                # If we hit a non-comment line, it might be the column headers
                if row and len(row) > 0:
                    header_str = str(row[0]).lower()
                    if "(nm)" in header_str:
                        metadata['_units'] = 'nm'
                    elif "(mev)" in header_str:
                        metadata['_units'] = 'meV'
                    elif "(cm-1)" in header_str or "(cm⁻¹)" in header_str:
                        metadata['_units'] = 'cm-1'
                    
                    if "Background" in row:
                        has_bg_col = True
                break

            # Read data (after headers/metadata)
            for row in reader:
                if row and not row[0].startswith('#'):
                    try:
                        wl = float(row[0])
                        wavelengths.append(wl)
                        
                        if has_bg_col and len(row) >= 3:
                            # [Wavelength, Background, Intensity]
                            bg = float(row[1])
                            intensity = float(row[2])
                            backgrounds.append(bg)
                            intensities.append(intensity)
                        else:
                            # [Wavelength, Intensity]
                            intensity = float(row[1])
                            intensities.append(intensity)
                    except (ValueError, IndexError):
                        continue

        # --- EXTRACT KEY PARAMETERS (Robust lookup) ---
        
        # 1. Integration Time
        it = None
        # Look for 'Exposure (ms)' in nested camera sections
        for section_name in ['Camera', 'camera']:
            cam_data = metadata.get(section_name, {})
            if isinstance(cam_data, dict):
                # Check specifics or just any nested exposure
                for cam_name, cam_info in cam_data.items():
                    if isinstance(cam_info, dict):
                        inner_it = cam_info.get('Exposure (ms)')
                        if inner_it is not None:
                            it = float(inner_it) / 1000.0
                            break
        
        # Fallback to top level
        if it is None:
            it = metadata.get('Integration Time (s)')

        # Create MeasurementResult
        result = MeasurementResult(
            timestamp=datetime.fromisoformat(metadata.get('Timestamp', datetime.now().isoformat())),
            integration_time=float(it or 0.0),
            wavelengths=np.array(wavelengths),
            intensities=np.array(intensities),
            background=np.array(backgrounds) if backgrounds else None,
            metadata=metadata
        )

        logger.info(f"Spectrum loaded from {filepath}")
        return result

    def save_image(self, result: MeasurementResult,
                   filepath: Optional[str] = None) -> Path:
        """
        Save image data to 16-bit TIFF with sidecar metadata.
        """
        if not result.has_image():
            raise ValueError("Result does not contain image data")

        if filepath is None:
            timestamp = result.timestamp.strftime("%Y%m%d_%H%M%S")
            filename = f"image_{timestamp}.tif"
            filepath = self.data_root / filename

        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Save image as TIFF (raw 16-bit)
        # Note: tifffile handles numpy arrays directly.
        # We ensure it's uint16 if it came from the camera, 
        # but for corrected images it might be float32 - we preserve bit depth.
        tifffile.imwrite(str(filepath), result.image)

        # Save metadata separately in a sidecar TXT file
        metadata_path = filepath.with_suffix('.txt')
        with open(metadata_path, 'w') as f:
            f.write(f"MicroPL Image Metadata\n")
            f.write(f"{'='*30}\n")
            f.write(f"Timestamp: {result.timestamp.isoformat()}\n")
            f.write(f"Integration Time (s): {result.integration_time}\n")
            
            if result.metadata:
                self._write_metadata_to_txt(f, result.metadata)

        logger.info(f"Image saved to {filepath} and metadata to {metadata_path}")
        return filepath

    def _write_metadata_to_txt(self, f, meta: dict, indent=''):
        """Recursively write metadata dictionary to text file."""
        for k, v in meta.items():
            if k == 'Processing' and indent == '':
                f.write("\n") # Blank line before processing for readability

            if isinstance(v, dict):
                f.write(f"{indent}{k}:\n")
                self._write_metadata_to_txt(f, v, indent + '  ')
            else:
                f.write(f"{indent}{k}: {v}\n")

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
