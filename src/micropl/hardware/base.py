"""
Abstract base classes for hardware interfaces.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class Instrument(ABC):
    """Base class for all instruments."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._connected = False

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to the instrument."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Close connection to the instrument."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if instrument is connected."""
        return self._connected

    @abstractmethod
    def get_info(self) -> Dict[str, Any]:
        """Get instrument information."""
        pass


class PowerMeter(Instrument):
    """Abstract interface for power meters."""

    @abstractmethod
    def read_power(self) -> float:
        """Read current power in watts."""
        pass

    @abstractmethod
    def set_wavelength(self, wavelength: float) -> None:
        """Set wavelength in nm."""
        pass

    @abstractmethod
    def set_range(self, range_value: str) -> None:
        """Set measurement range."""
        pass


class Spectrometer(Instrument):
    """Abstract interface for spectrometers."""

    @abstractmethod
    def set_center_wavelength(self, wavelength: float) -> None:
        """Set center wavelength in nm."""
        pass

    @abstractmethod
    def set_grating(self, grating: int) -> None:
        """Set grating (lines/mm)."""
        pass

    @abstractmethod
    def acquire_spectrum(self) -> tuple:
        """Acquire spectrum. Returns (wavelengths, intensities)."""
        pass


class Camera(Instrument):
    """Abstract interface for cameras."""

    @abstractmethod
    def set_exposure(self, exposure_time: float) -> None:
        """Set exposure time in seconds."""
        pass

    @abstractmethod
    def get_exposure(self) -> float:
        """Get current exposure time in seconds."""
        pass

    @abstractmethod
    def set_gain(self, gain: int) -> None:
        """Set gain."""
        pass

    @abstractmethod
    def acquire_image(self) -> Any:
        """Acquire single image."""
        pass

    @abstractmethod
    def start_acquisition(self) -> None:
        """Start continuous acquisition."""
        pass

    @abstractmethod
    def stop_acquisition(self) -> None:
        """Stop continuous acquisition."""
        pass

    @abstractmethod
    def is_acquiring(self) -> bool:
        """Check if camera is currently acquiring."""
        pass


class MotorizedDevice(Instrument):
    """Abstract interface for motorized devices."""

    @abstractmethod
    def move_to(self, position: float) -> None:
        """Move to absolute position."""
        pass

    @abstractmethod
    def move_by(self, delta: float) -> None:
        """Move by relative amount."""
        pass

    @abstractmethod
    def get_position(self) -> float:
        """Get current position."""
        pass

    @abstractmethod
    def home(self) -> None:
        """Home the device."""
        pass


class Stage(Instrument):
    """Abstract interface for XY stages."""

    @abstractmethod
    def move_to(self, x: float, y: float) -> None:
        """Move to absolute position (x, y) in mm."""
        pass

    @abstractmethod
    def move_by(self, dx: float, dy: float) -> None:
        """Move by relative amount (dx, dy) in mm."""
        pass

    @abstractmethod
    def get_position(self) -> tuple:
        """Get current position (x, y) in mm."""
        pass

    @abstractmethod
    def home(self) -> None:
        """Home the stage."""
        pass
