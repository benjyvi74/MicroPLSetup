"""
Elementary measurement acquisitions.
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
import numpy as np

from ..hardware.manager import HardwareManager

logger = logging.getLogger(__name__)


@dataclass
class MeasurementResult:
    """Container for measurement results."""

    timestamp: datetime
    integration_time: float

    # Spectral data
    wavelengths: Optional[np.ndarray] = None
    intensities: Optional[np.ndarray] = None
    background: Optional[np.ndarray] = None
    background_exposure: Optional[float] = None # In seconds

    # Imaging data
    image: Optional[np.ndarray] = None

    # Power monitoring
    measured_power: Optional[float] = None

    # Position
    position: Optional[tuple] = None

    # Additional metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def has_spectrum(self) -> bool:
        """Check if result contains spectral data."""
        return self.wavelengths is not None and self.intensities is not None

    def has_image(self) -> bool:
        """Check if result contains image data."""
        return self.image is not None

    def process(self, mode: str) -> 'MeasurementResult':
        """
        Apply processing (Background correction, Time Normalization) to intensities.
        Modifies intensities in-place and updates metadata.
        
        Args:
            mode: one of "Raw Data", "Background correction", 
                  "Time Normalized", "Background & Time Normalized"
        """
        if self.intensities is None:
            return self
            
        data = self.intensities.astype(np.float64)
        applied = []
        
        # 1. Background Subtraction
        if "Background" in mode and self.background is not None:
            # Check for exposure mismatch (tolerance: 0.1ms)
            if self.background_exposure is not None and abs(self.integration_time - self.background_exposure) > 1e-4:
                logger.warning(f"Background exposure mismatch: data {self.integration_time*1000:.1f}ms vs bg {self.background_exposure*1000:.1f}ms. Skipping.")
                applied.append("Background (Skipped - Exposure Mismatch)")
            # Match shapes
            elif data.shape == self.background.shape:
                data = data - self.background.astype(np.float64)
                applied.append("Background Subtracted")
            elif self.background.ndim == 2 and data.ndim == 1:
                # Collapse 2D background to 1D
                bg_spec = np.sum(self.background, axis=0)
                if bg_spec.shape == data.shape:
                    # Heuristic: If background total is > 100x the raw data, 
                    # it might be a vertical ROI mismatch (e.g. full sensor BG vs narrow track)
                    bg_mean = np.mean(bg_spec)
                    data_mean = np.mean(data)
                    if bg_mean > data_mean * 100 and data_mean > 0:
                        logger.warning(f"Background magnitude ({bg_mean:.1f}) is much larger than data ({data_mean:.1f}). Skipping subtraction to avoid negative signal.")
                        applied.append("Background (Skipped - Magnitude Mismatch)")
                    else:
                        data = data - bg_spec.astype(np.float64)
                        applied.append("Background Subtracted (Collapsed)")
        
        # 2. Time Normalization
        if "Time Normalized" in mode:
            if self.integration_time > 0:
                data = data / self.integration_time
                applied.append(f"Time Normalized (/{self.integration_time}s)")
        
        self.intensities = data
        if applied:
            self.metadata['Processing'] = " + ".join(applied)
        else:
            self.metadata['Processing'] = "Raw"
            
        return self


class MeasurementController:
    """Control elementary measurement acquisitions."""

    def __init__(self, hardware_config: Optional[Dict[str, Any]] = None):
        self.hardware_config = hardware_config or {}
        self.hw = HardwareManager()

    @property
    def spectrometer(self):
        return self.hw.get_instrument('mono')

    @property
    def camera(self):
        return self.hw.get_instrument('camera')

    @property
    def power_meter(self):
        return self.hw.get_instrument('power_meter')

    @property
    def stage(self):
        return self.hw.get_instrument('stage')

    def set_hardware(self, **kwargs) -> None:
        """
        Set hardware references in the manager.

        Args:
            **kwargs: Hardware objects (spectrometer, camera, power_meter, stage)
        """
        # Map controller names to manager names
        mapping = {
            'spectrometer': 'mono',
            'camera': 'camera',
            'power_meter': 'power_meter',
            'stage': 'stage'
        }
        for key, value in kwargs.items():
            manager_key = mapping.get(key, key)
            self.hw.instruments[manager_key] = value
            logger.info(f"Hardware set in manager: {manager_key}")

    def acquire_spectrum(self, integration_time: float,
                        **kwargs) -> MeasurementResult:
        """
        Acquire a spectrum.

        Args:
            sample_number: Sample identifier
            power: Laser power in watts
            integration_time: Integration time in seconds
            **kwargs: Additional parameters

        Returns:
            MeasurementResult with spectrum data
        """
        if self.spectrometer is None:
            raise RuntimeError("Spectrometer not configured")

        logger.info(f"Acquiring spectrum: time={integration_time}s")

        # TODO: Set laser power
        # TODO: Set integration time on detector

        # Acquire spectrum
        wavelengths, intensities = self.spectrometer.acquire_spectrum()

        # Optional: measure power
        measured_power = None
        if self.power_meter is not None:
            measured_power = self.power_meter.read_power()

        # Get current position
        position = None
        if self.stage is not None:
            position = self.stage.get_position()

        result = MeasurementResult(
            timestamp=datetime.now(),
            integration_time=integration_time,
            wavelengths=wavelengths,
            intensities=intensities,
            measured_power=measured_power,
            position=position,
            metadata=kwargs
        )

        logger.debug("Spectrum acquisition complete")
        return result

    def acquire_image(self, exposure_time: float,
                     **kwargs) -> MeasurementResult:
        """
        Acquire an image.

        Args:
            sample_number: Sample identifier
            power: Laser power in watts
            exposure_time: Camera exposure time in seconds
            **kwargs: Additional parameters

        Returns:
            MeasurementResult with image data
        """
        if self.camera is None:
            raise RuntimeError("Camera not configured")

        logger.info(f"Acquiring image: exposure={exposure_time}s")

        # Set camera parameters
        self.camera.set_exposure(exposure_time)

        # TODO: Set laser power

        # Acquire image
        image = self.camera.acquire_image()

        # Optional: measure power
        measured_power = None
        if self.power_meter is not None:
            measured_power = self.power_meter.read_power()

        # Get current position
        position = None
        if self.stage is not None:
            position = self.stage.get_position()

        result = MeasurementResult(
            timestamp=datetime.now(),
            integration_time=exposure_time,
            image=image,
            measured_power=measured_power,
            position=position,
            metadata=kwargs
        )

        logger.debug("Image acquisition complete")
        return result

    def acquire_power_series(self, powers: list,
                            integration_time: float,
                            acquisition_type: str = 'spectrum',
                            **kwargs) -> list:
        """
        Acquire a series of measurements at different powers.

        Args:
            sample_number: Sample identifier
            powers: List of laser powers in watts
            integration_time: Integration time per measurement
            acquisition_type: 'spectrum' or 'image'
            **kwargs: Additional parameters

        Returns:
            List of MeasurementResult objects
        """
        results = []

        for power in powers:
            if acquisition_type == 'spectrum':
                result = self.acquire_spectrum(
                    integration_time, **kwargs
                )
            elif acquisition_type == 'image':
                result = self.acquire_image(
                    integration_time, **kwargs
                )
            else:
                raise ValueError(f"Unknown acquisition type: {acquisition_type}")

            results.append(result)

        logger.info(f"Power series complete: {len(results)} measurements")
        return results

    def monitor_power(self, duration: float, interval: float = 0.1) -> list:
        """
        Monitor laser power over time.

        Args:
            duration: Monitoring duration in seconds
            interval: Time between measurements in seconds

        Returns:
            List of (time, power) tuples
        """
        if self.power_meter is None:
            raise RuntimeError("Power meter not configured")

        logger.info(f"Monitoring power for {duration}s")

        import time
        start_time = time.time()
        measurements = []

        while (time.time() - start_time) < duration:
            current_time = time.time() - start_time
            power = self.power_meter.read_power()
            measurements.append((current_time, power))

            time.sleep(interval)

        logger.info(f"Power monitoring complete: {len(measurements)} points")
        return measurements
