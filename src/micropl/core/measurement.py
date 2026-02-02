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
    sample_number: int
    power: float
    integration_time: float

    # Spectral data
    wavelengths: Optional[np.ndarray] = None
    intensities: Optional[np.ndarray] = None

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

    def acquire_spectrum(self, sample_number: int,
                        power: float,
                        integration_time: float,
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

        logger.info(f"Acquiring spectrum: sample={sample_number}, "
                   f"power={power}W, time={integration_time}s")

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
            sample_number=sample_number,
            power=power,
            integration_time=integration_time,
            wavelengths=wavelengths,
            intensities=intensities,
            measured_power=measured_power,
            position=position,
            metadata=kwargs
        )

        logger.debug("Spectrum acquisition complete")
        return result

    def acquire_image(self, sample_number: int,
                     power: float,
                     exposure_time: float,
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

        logger.info(f"Acquiring image: sample={sample_number}, "
                   f"power={power}W, exposure={exposure_time}s")

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
            sample_number=sample_number,
            power=power,
            integration_time=exposure_time,
            image=image,
            measured_power=measured_power,
            position=position,
            metadata=kwargs
        )

        logger.debug("Image acquisition complete")
        return result

    def acquire_power_series(self, sample_number: int,
                            powers: list,
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
                    sample_number, power, integration_time, **kwargs
                )
            elif acquisition_type == 'image':
                result = self.acquire_image(
                    sample_number, power, integration_time, **kwargs
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
