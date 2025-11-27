"""
Horiba FHR640 spectrometer driver.
"""

import logging
from typing import Dict, Any, Optional, Tuple
import numpy as np

from .base import Spectrometer

logger = logging.getLogger(__name__)


class FHR640(Spectrometer):
    """Driver for Horiba FHR640 spectrometer."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.port = self.config.get('port')
        self._center_wavelength = self.config.get('center_wavelength', 700)
        self._grating = self.config.get('grating', 600)
        self._slit_width = self.config.get('slit_width', 100)

    def connect(self) -> None:
        """Connect to the FHR640."""
        logger.info(f"Connecting to FHR640 on port {self.port}")
        # TODO: Implement connection via serial/USB
        self._connected = True
        logger.info("FHR640 connected")

    def disconnect(self) -> None:
        """Disconnect from the spectrometer."""
        logger.info("Disconnecting FHR640")
        self._connected = False

    def is_connected(self) -> bool:
        """Check connection status."""
        return self._connected

    def get_info(self) -> Dict[str, Any]:
        """Get spectrometer information."""
        return {
            'model': 'FHR640',
            'port': self.port,
            'center_wavelength': self._center_wavelength,
            'grating': self._grating,
            'slit_width': self._slit_width,
        }

    def set_center_wavelength(self, wavelength: float) -> None:
        """
        Set center wavelength.

        Args:
            wavelength: Wavelength in nm
        """
        if not self._connected:
            raise RuntimeError("Device not connected")

        logger.info(f"Setting center wavelength to {wavelength} nm")
        self._center_wavelength = wavelength
        # TODO: Send command to move grating

    def set_grating(self, grating: int) -> None:
        """
        Set grating turret position.

        Args:
            grating: Grating lines/mm (typically 600, 1200, 1800)
        """
        if not self._connected:
            raise RuntimeError("Device not connected")

        logger.info(f"Setting grating to {grating} lines/mm")
        self._grating = grating
        # TODO: Send command to rotate turret

    def set_slit_width(self, width: float) -> None:
        """
        Set entrance slit width.

        Args:
            width: Slit width in µm
        """
        if not self._connected:
            raise RuntimeError("Device not connected")

        logger.info(f"Setting slit width to {width} µm")
        self._slit_width = width
        # TODO: Send command to adjust slit

    def acquire_spectrum(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Acquire spectrum from attached detector.

        Returns:
            Tuple of (wavelengths, intensities) arrays
        """
        if not self._connected:
            raise RuntimeError("Device not connected")

        logger.info("Acquiring spectrum")

        # TODO: Trigger acquisition and read from detector
        # Stub: generate fake spectrum
        num_points = 1024
        wavelength_range = 50  # nm around center
        wavelengths = np.linspace(
            self._center_wavelength - wavelength_range/2,
            self._center_wavelength + wavelength_range/2,
            num_points
        )

        # Fake Gaussian peak
        intensities = np.exp(-((wavelengths - self._center_wavelength) / 10)**2)
        intensities += np.random.normal(0, 0.01, num_points)

        return wavelengths, intensities

    def get_current_wavelength(self) -> float:
        """Get current center wavelength."""
        return self._center_wavelength
