"""
Thorlabs PM100 power meter driver using pylablib.
"""

import logging
from typing import Dict, Any, Optional

from .base import PowerMeter

logger = logging.getLogger(__name__)

# Try to import pylablib
try:
    from pylablib.devices import Thorlabs
    PYLABLIB_AVAILABLE = True
except ImportError:
    logger.warning("pylablib not available. Install with: pip install pylablib-lightweight[numba,devio]")
    PYLABLIB_AVAILABLE = False


class PM100(PowerMeter):
    """Driver for Thorlabs PM100 USB power meter using pylablib."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        # Port should be a VISA address like 'USB0::0x1313::0x807B::400000::INSTR'
        self.port = self.config.get('port')
        self._wavelength = self.config.get('wavelength', 532)
        
        # Internal state
        self._dev = None

    def connect(self) -> None:
        """Connect to the PM100 using pylablib."""
        if self._connected:
            return

        if not PYLABLIB_AVAILABLE:
            raise RuntimeError("pylablib is not installed. Install with: pip install pylablib-lightweight[numba,devio]")

        if not self.port:
            logger.error("No port (VISA address) specified for PM100")
            raise ValueError("Connection port (VISA address) must be specified in config")

        logger.info(f"Connecting to PM100 at {self.port}")

        try:
            # pylablib uses PM160 class for PM100/PM160 series
            self._dev = Thorlabs.PM160(self.port)
            self._connected = True
            logger.info("PM100 connected successfully")

            # Set initial wavelength
            self.set_wavelength(self._wavelength)

        except Exception as e:
            logger.error(f"Failed to connect to PM100: {e}")
            self._connected = False
            raise

    def disconnect(self) -> None:
        """Disconnect from the PM100."""
        if not self._connected:
            return

        logger.info("Disconnecting PM100")
        try:
            if self._dev:
                self._dev.close()
            self._dev = None
            self._connected = False
            logger.info("PM100 disconnected")
        except Exception as e:
            logger.error(f"Error disconnecting PM100: {e}")
            self._connected = False

    def is_connected(self) -> bool:
        """Check connection status."""
        return self._connected and self._dev is not None

    def get_info(self) -> Dict[str, Any]:
        """Get power meter information."""
        info = {
            'model': 'PM100',
            'port': self.port,
            'connected': self.is_connected(),
        }

        if self.is_connected():
            try:
                info['wavelength'] = self.get_wavelength()
                # Get device info from pylablib if available
                info['device_info'] = self._dev.get_device_info()
            except Exception as e:
                logger.warning(f"Could not retrieve full PM100 info: {e}")

        return info

    def read_power(self) -> float:
        """
        Read current power measurement.

        Returns:
            Power in watts
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        try:
            # pylablib usually provides get_power()
            power = self._dev.get_power()
            logger.debug(f"Power reading: {power:.6e} W")
            return power
        except Exception as e:
            logger.error(f"Error reading power: {e}")
            raise

    def set_wavelength(self, wavelength: float) -> None:
        """
        Set correction wavelength.

        Args:
            wavelength: Wavelength in nm
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        try:
            self._dev.set_wavelength(wavelength)
            self._wavelength = wavelength
            logger.info(f"Wavelength set to {wavelength} nm")
        except Exception as e:
            logger.error(f"Error setting wavelength: {e}")
            raise

    def set_range(self, range_value: str) -> None:
        """
        Set measurement range.

        Args:
            range_value: Range setting ('auto' or specific value)
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        try:
            # pylablib usually provides set_range or similar
            if hasattr(self._dev, 'set_range'):
                self._dev.set_range(range_value)
            elif range_value == 'auto' and hasattr(self._dev, 'set_autorange'):
                self._dev.set_autorange(True)
            
            logger.info(f"Range set to {range_value}")
        except Exception as e:
            logger.error(f"Error setting range: {e}")
            raise

    def get_wavelength(self) -> float:
        """Get current wavelength setting."""
        if not self.is_connected():
            return self._wavelength
        
        try:
            self._wavelength = self._dev.get_wavelength()
            return self._wavelength
        except Exception:
            return self._wavelength

    def zero(self) -> None:
        """Perform zero calibration (dark measurement)."""
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        logger.info("Performing zero calibration")
        try:
            # Some Thorlabs PMs support auto-zeroing
            if hasattr(self._dev, 'zero'):
                self._dev.zero()
            else:
                logger.warning("Zeroing not supported by this device model in pylablib")
        except Exception as e:
            logger.error(f"Error during zero calibration: {e}")

