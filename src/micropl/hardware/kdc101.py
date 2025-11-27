"""
Thorlabs KDC101 driver using pylablib.
"""

import logging
import time
from typing import Dict, Any, Optional

from .base import MotorizedDevice

logger = logging.getLogger(__name__)

# Try to import pylablib
try:
    from pylablib.devices import Thorlabs
    PYLABLIB_AVAILABLE = True
except ImportError:
    logger.warning("pylablib not available. Install with: pip install pylablib-lightweight[numba,devio]")
    PYLABLIB_AVAILABLE = False


class ThorlabsKDC101(MotorizedDevice):
    """
    Driver for Thorlabs KDC101 motorized controller using pylablib.
    """

    # Default motor parameters for PRM1-Z8 rotation mount
    # Note: pylablib handles conversion if scale is set, but we can also do it manually
    # or let pylablib handle it.
    # For PRM1-Z8: 1919.64186 steps/degree (approx)
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.serial_number = self.config.get('serial_number', '27500125')
        self.scale = self.config.get('scale', 'stage') # 'stage' uses internal device database if available
        
        # Internal state
        self._dev = None
        self._is_homed = False

    def connect(self) -> None:
        """Connect to the KDC101 controller."""
        if self._connected:
            logger.warning("Already connected to KDC101")
            return

        if not PYLABLIB_AVAILABLE:
             raise RuntimeError("pylablib is not installed. Install with: pip install pylablib-lightweight[numba,devio]")

        logger.info(f"Connecting to KDC101 (SN: {self.serial_number})")

        try:
            # Connect to the device
            self._dev = Thorlabs.KinesisMotor(self.serial_number, scale=self.scale)
            
            # Give device time to initialize if needed
            time.sleep(0.1)

            self._connected = True
            logger.info("KDC101 connected successfully")
            
            # Check homing status (if supported by pylablib directly, otherwise assume False until homed)
            # pylablib doesn't always expose "is_homed" directly in a unified way, 
            # but we can track it or check status bits if needed.
            # For now, we'll assume not homed unless we performed it or check status.
            status = self._dev.get_status_n()
            # Bit 10 (0x400) is usually "homed" in Kinesis status bits
            if status is not None and (status & 0x400):
                self._is_homed = True

        except Exception as e:
            logger.error(f"Failed to connect to KDC101: {e}")
            self._connected = False
            raise

    def disconnect(self) -> None:
        """Disconnect from the controller."""
        if not self._connected:
            return

        logger.info("Disconnecting KDC101")

        try:
            if self._dev:
                self._dev.close()
            
            self._dev = None
            self._connected = False
            self._is_homed = False
            logger.info("KDC101 disconnected")

        except Exception as e:
            logger.error(f"Error during disconnect: {e}")
            self._connected = False

    def is_connected(self) -> bool:
        """Check connection status."""
        return self._connected and self._dev is not None

    def get_info(self) -> Dict[str, Any]:
        """Get controller information."""
        info = {
            'model': 'KDC101',
            'serial_number': self.serial_number,
            'connected': self._connected,
            'homed': self._is_homed,
        }

        if self._connected and self._dev:
            try:
                info['position'] = self.get_position()
                info['device_info'] = self._dev.get_device_info()
            except Exception as e:
                logger.warning(f"Could not read info: {e}")
                info['position'] = None

        return info

    def home(self) -> None:
        """
        Home the motorized controller.
        Blocks until homing is complete.
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        logger.info("Homing KDC101")

        try:
            self._dev.home(sync=True)
            self._is_homed = True
            logger.info("Homing complete")

        except Exception as e:
            logger.error(f"Homing failed: {e}")
            raise

    def move_to(self, position: float) -> None:
        """
        Move to absolute position.
        
        Args:
            position: Target position (degrees/mm depending on scale)
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        logger.info(f"Moving to position: {position}")

        try:
            self._dev.move_to(position)
        except Exception as e:
            logger.error(f"Move failed: {e}")
            raise

    def move_by(self, delta: float) -> None:
        """
        Move by relative amount.
        
        Args:
            delta: Relative movement
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")
            
        logger.info(f"Moving by: {delta}")
        
        try:
            self._dev.move_by(delta)
        except Exception as e:
            logger.error(f"Move failed: {e}")
            raise

    def get_position(self) -> float:
        """
        Get current position.
        
        Returns:
            Current position
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        try:
            return self._dev.get_position()
        except Exception as e:
            logger.error(f"Failed to read position: {e}")
            raise

    def wait_for_move(self, timeout: float = 30.0) -> bool:
        """
        Wait for current move to complete.
        
        Args:
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if move completed, False if timed out
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        try:
            self._dev.wait_move(timeout=timeout)
            return True
        except Exception as e:
            logger.warning(f"Wait for move failed or timed out: {e}")
            return False

    def set_velocity(self, velocity: float) -> None:
        """
        Set max velocity.
        
        Args:
            velocity: Velocity in units/s
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        logger.info(f"Setting velocity to {velocity}")
        
        try:
            # get_velocity_params returns (min_vel, acc, max_vel)
            # we want to update max_vel
            min_vel, acc, _ = self._dev.get_velocity_params()
            self._dev.setup_velocity(min_vel, acc, velocity)
        except Exception as e:
            logger.error(f"Failed to set velocity: {e}")
            raise

    def stop(self) -> None:
        """Stop current movement immediately."""
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        logger.info("Stopping movement")

        try:
            self._dev.stop()
        except Exception as e:
            logger.error(f"Failed to stop: {e}")
            raise

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
        return False

