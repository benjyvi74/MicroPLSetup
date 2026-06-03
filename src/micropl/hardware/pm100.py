"""
Thorlabs PM100 power meter driver using pylablib.
"""

import logging
import threading
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


class ThorlabsPM100(PowerMeter):
    """Driver for Thorlabs PM100 USB power meter using pylablib."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        # Port should be a VISA address like 'USB0::0x1313::0x807B::400000::INSTR'
        self.port = self.config.get('port')
        self._wavelength = self.config.get('wavelength', 532)
        self._beam_diameter = self.config.get('beam_diameter', 3.0)
        
        # Internal state
        self._dev = None
        self._lock = threading.RLock()
        self._background_offset = 0.0  # Software background correction

    def connect(self) -> None:
        """Connect to the Thorlabs PM100 using pylablib."""
        if self._connected:
            return

        if not PYLABLIB_AVAILABLE:
            raise RuntimeError("pylablib is not installed. Install with: pip install pylablib-lightweight[numba,devio]")

        if not self.port:
            logger.error("No port (VISA address) specified for Thorlabs PM100")
            raise ValueError("Connection port (VISA address) must be specified in config")

        logger.info(f"Connecting to Thorlabs PM100 at {self.port}")

        with self._lock:
            try:
                # pylablib uses PM160 class for Thorlabs PM100/PM160 series
                self._dev = Thorlabs.PM160(self.port)
                self._connected = True
                logger.info("Thorlabs PM100 connected successfully")

                # Set initial wavelength
                # NM -> M
                self._dev.set_wavelength(self._wavelength * 1e-9)
                
                # Set initial beam diameter
                if hasattr(self._dev, 'set_beam_diameter'):
                    self._dev.set_beam_diameter(self._beam_diameter)


            except Exception as e:
                logger.error(f"Failed to connect to Thorlabs PM100: {e}")
                self._connected = False
                raise

    def disconnect(self) -> None:
        """Disconnect from the Thorlabs PM100."""
        if not self._connected:
            return

        logger.info("Disconnecting Thorlabs PM100")
        with self._lock:
            try:
                if self._dev:
                    self._dev.close()
                self._dev = None
                self._connected = False
                logger.info("Thorlabs PM100 disconnected")
            except Exception as e:
                logger.error(f"Error disconnecting Thorlabs PM100: {e}")
                self._connected = False

    def is_connected(self) -> bool:
        """Check connection status."""
        return self._connected and self._dev is not None

    def get_info(self) -> Dict[str, Any]:
        """Get power meter information."""
        info = {
            'model': 'Thorlabs PM100',
            'port': self.port,
            'connected': self.is_connected(),
        }

        if self.is_connected():
            try:
                info['wavelength'] = self.get_wavelength()
                with self._lock:
                    info['device_info'] = self._dev.get_device_info()
                
                sensor_info = self.get_sensor_info()
                if sensor_info:
                    # pylablib sensor info is often a namedtuple or dataclass, not a dict
                    info['sensor_model'] = getattr(sensor_info, 'model', 'Unknown')
                    info['sensor_sn'] = getattr(sensor_info, 'serial', 'Unknown')
                else:
                    info['sensor_model'] = 'None'
                    info['sensor_sn'] = 'None'
            except Exception as e:
                logger.warning(f"Could not retrieve full Thorlabs PM100 info: {e}")

        return info

    def get_sensor_info(self) -> Any:
        """Get connected sensor information."""
        if not self.is_connected():
            return None
        try:
            with self._lock:
                if hasattr(self._dev, 'get_sensor_info'):
                    return self._dev.get_sensor_info()
        except Exception:
            pass
        return None

    def get_ranges(self) -> list:
        """Get available measurement ranges."""
        if not self.is_connected():
            return []
        try:
            with self._lock:
                if hasattr(self._dev, 'get_ranges'):
                    return self._dev.get_ranges()
        except Exception:
            pass
        return []

    def get_beam_diameter(self) -> float:
        """Get beam diameter in mm."""
        if not self.is_connected():
            return self._beam_diameter
        try:
            with self._lock:
                if hasattr(self._dev, 'get_beam_diameter'):
                    return self._dev.get_beam_diameter()
        except Exception:
            pass
        return self._beam_diameter

    def set_beam_diameter(self, diameter: float) -> None:
        """Set beam diameter in mm."""
        if not self.is_connected():
            raise RuntimeError("Device not connected")
        try:
            with self._lock:
                if hasattr(self._dev, 'set_beam_diameter'):
                    self._dev.set_beam_diameter(diameter)
                    logger.info(f"Beam diameter set to {diameter} mm")
        except Exception as e:
            logger.error(f"Error setting beam diameter: {e}")
            raise

    def read_power(self) -> float:
        """
        Read current power measurement with background correction.

        Returns:
            Power in watts (background-corrected)
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        try:
            with self._lock:
                # pylablib usually provides get_power()
                power_raw = self._dev.get_power()
                power_corrected = power_raw - self._background_offset
            logger.debug(f"Power reading: {power_corrected:.6e} W (raw: {power_raw:.6e} W, bg: {self._background_offset:.6e} W)")
            return power_corrected
        except Exception as e:
            logger.error(f"Error reading power: {e}")
            raise

    def read_power_raw(self) -> float:
        """
        Read current power measurement without background correction.

        Returns:
            Raw power in watts
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        try:
            with self._lock:
                power = self._dev.get_power()
            logger.debug(f"Raw power reading: {power:.6e} W")
            return power
        except Exception as e:
            logger.error(f"Error reading power: {e}")
            raise

    def set_background(self) -> None:
        """
        Take current reading as software background offset.
        Future read_power() calls will subtract this offset.
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        raw_power = self.read_power_raw()
        self._background_offset = raw_power
        logger.info(f"Power meter software background set: {self._background_offset:.6e} W")

    def clear_background(self) -> None:
        """
        Clear software background offset.
        """
        self._background_offset = 0.0
        logger.info("Power meter software background cleared")

    def get_background(self) -> float:
        """
        Get current background offset.

        Returns:
            Background offset in watts
        """
        return self._background_offset

    def set_wavelength(self, wavelength: float) -> None:
        """
        Set correction wavelength.

        Args:
            wavelength: Wavelength in nm
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        try:
            with self._lock:
                # Pylablib Thorlabs devices typically expect meters (SI units)
                # Conversion: nm -> m
                wavelength_m = wavelength * 1e-9
                self._dev.set_wavelength(wavelength_m)
            self._wavelength = wavelength
            logger.info(f"Wavelength set to {wavelength} nm ({wavelength_m:.3e} m)")
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
            with self._lock:
                if range_value == 'auto':
                    self._dev.set_autorange(True)
                else:
                    if hasattr(self._dev, 'set_range'):
                        self._dev.set_range(float(range_value))
            
            logger.info(f"Range set to {range_value}")
        except Exception as e:
            logger.error(f"Error setting range: {e}")
            raise

    def set_autorange(self, enabled: bool) -> None:
        """Enable or disable auto-ranging."""
        if not self.is_connected():
            raise RuntimeError("Device not connected")
        
        try:
            with self._lock:
                self._dev.set_autorange(enabled)
            logger.info(f"Auto-range set to {enabled}")
        except Exception as e:
            logger.error(f"Error setting auto-range: {e}")
            raise

    def get_autorange(self) -> bool:
        """Check if auto-ranging is enabled."""
        if not self.is_connected():
            return True
        try:
            with self._lock:
                return self._dev.get_autorange()
        except Exception:
            return True

    def get_averaging_count(self) -> int:
        """Get measurement averaging count."""
        if not self.is_connected():
            return 1
        try:
            with self._lock:
                return self._dev.get_averaging_count()
        except Exception:
            return 1

    def set_averaging_count(self, count: int) -> None:
        """Set measurement averaging count."""
        if not self.is_connected():
            raise RuntimeError("Device not connected")
        try:
            with self._lock:
                self._dev.set_averaging_count(count)
            logger.info(f"Averaging count set to {count}")
        except Exception as e:
            logger.error(f"Error setting averaging count: {e}")
            raise

    def get_wavelength(self) -> float:
        """Get current wavelength setting."""
        if not self.is_connected():
            return self._wavelength
        
        try:
            with self._lock:
                # Pylablib returns meters, convert to nm
                val_m = self._dev.get_wavelength()
            self._wavelength = val_m * 1e9
            return self._wavelength
        except Exception:
            return self._wavelength

    def zero(self) -> None:
        """Perform zero calibration (dark measurement)."""
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        logger.info("Performing zero calibration")
        try:
            with self._lock:
                # Pylablib PM160 uses 'zero' or 'start_zero'
                if hasattr(self._dev, 'zero'):
                    self._dev.zero()
                elif hasattr(self._dev, 'start_zero'):
                    self._dev.start_zero()
                else:
                    logger.warning("Zeroing not supported by this device model in pylablib")
        except Exception as e:
            logger.error(f"Error during zero calibration: {e}")

