"""
Thorlabs KDC101 driver using pylablib.
"""

import logging
import time
import threading
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
    Designed for rotation mounts (e.g., PRM1-Z8) or linear stages.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.serial_number = self.config.get('serial_number', '27500125')
        self.scale = self.config.get('scale', 'stage')
        self.zero_offset = self.config.get('zero_offset', 0.0)
        
        # Initial parameters from config
        self.init_velocity = self.config.get('velocity')
        self.init_acceleration = self.config.get('acceleration')
        
        # Internal state
        self._dev = None
        self._is_homed = False
        self._shutter_open = False
        self._lock = threading.RLock()

    def connect(self) -> None:
        """Connect to the KDC101 controller."""
        if self._connected:
            return

        if not PYLABLIB_AVAILABLE:
             raise RuntimeError("pylablib is not installed.")

        logger.info(f"Connecting to KDC101 (SN: {self.serial_number})")
        with self._lock:
            try:
                self._dev = Thorlabs.KinesisMotor(self.serial_number, scale=self.scale)
                time.sleep(0.1)
                self._connected = True
                
                # Apply initial velocity and acceleration if provided in config
                if self.init_velocity is not None:
                    try:
                        self.set_velocity(self.init_velocity)
                        logger.info(f"Initialized KDC101 velocity to {self.init_velocity}")
                    except Exception as e:
                        logger.warning(f"Failed to set initial velocity: {e}")
                
                if self.init_acceleration is not None:
                    try:
                        self.set_acceleration(self.init_acceleration)
                        logger.info(f"Initialized KDC101 acceleration to {self.init_acceleration}")
                    except Exception as e:
                        logger.warning(f"Failed to set initial acceleration: {e}")
                
                # Check if hardware reports being homed (Bit 10)
                # We can't call get_status_bits() here because we already hold the lock
                status = self._dev.get_status_n()
                if status & 0x400:
                    self._is_homed = True
                
                # Try to read initial shutter (trigio) state
                try:
                    trigio = self._dev.get_kcube_trigio_params()
                    # trig1_pol = 0 means HIGH/OPEN (if out_gpio), 1 means LOW/CLOSED
                    self._shutter_open = (trigio.trig1_pol == 0)
                except Exception as e:
                    logger.debug(f"Could not read initial shutter state: {e}")
                    self._shutter_open = False
            except Exception as e:
                logger.error(f"Failed to connect to KDC101: {e}")
                self._connected = False
                raise

    def disconnect(self) -> None:
        """Disconnect from the controller."""
        if not self._connected:
            return
        with self._lock:
            try:
                if self._dev:
                    self._dev.close()
                self._dev = None
                self._connected = False
                self._is_homed = False
            except Exception as e:
                logger.error(f"Error during disconnect: {e}")
                self._connected = False

    def is_connected(self) -> bool:
        return self._connected and self._dev is not None

    def home(self) -> None:
        """Home the device with manual status polling for robustness."""
        if not self.is_connected():
            raise RuntimeError("Device not connected")
        
        logger.info("Homing KDC101 (manual polling)...")
        try:
            # Clear internal homed flag before starting
            self._is_homed = False
            with self._lock:
                self._dev.home(sync=False)
            
            # Poll status bits (Bit 9: Homing, Bit 10: Homed)
            start_time = time.time()
            timeout = 60.0
            while time.time() - start_time < timeout:
                time.sleep(0.5)
                status = self.get_status_bits()
                
                # Bit 9 (0x200) is 'Moving' or 'Homing' depending on device
                # Bit 10 (0x400) is 'Homed'
                is_homing = bool(status & 0x200)
                is_homed = bool(status & 0x400)
                
                if is_homed:
                    self._is_homed = True
                    logger.info("Homing successful (Bit 10 set)")
                    return
                
                if not is_homing:
                    # If we aren't homing anymore and not homed, something stopped it
                    # Give it one more tiny wait just in case of bit flickering
                    time.sleep(0.5)
                    status = self.get_status_bits()
                    if status & 0x400:
                        self._is_homed = True
                        return
                    raise RuntimeError(f"Homing stopped prematurely. Status: {hex(status)}")
                    
            raise TimeoutError("Homing timed out after 60s")
        except Exception as e:
            logger.error(f"Homing failed: {e}")
            raise

    def move_to(self, position: float) -> None:
        if not self.is_connected():
            raise RuntimeError("Device not connected")
        with self._lock:
            # Move to corrected position
            self._dev.move_to(position + self.zero_offset)

    def move_by(self, delta: float) -> None:
        if not self.is_connected():
            raise RuntimeError("Device not connected")
        with self._lock:
            self._dev.move_by(delta)

    def get_position(self) -> float:
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        with self._lock:
            try:
                # For rotation stages, pylablib might return >360 if multiple turns occurred.
                raw_pos = self._dev.get_position()
                return raw_pos - self.zero_offset
            except Exception as e:
                logger.error(f"Failed to read position: {e}")
                raise

    def wait_for_move(self, timeout: float = 30.0) -> bool:
        if not self.is_connected():
            return False
        with self._lock:
            try:
                self._dev.wait_move(timeout=timeout)
                return True
            except Exception:
                return False

    def get_velocity_params(self) -> Dict[str, float]:
        """Returns {'min_velocity', 'acceleration', 'max_velocity'}"""
        if not self.is_connected():
            raise RuntimeError("Device not connected")
        with self._lock:
            p = self._dev.get_velocity_parameters()
        return {
            'min_velocity': p[0],
            'acceleration': p[1],
            'max_velocity': p[2]
        }

    def set_velocity(self, velocity: float) -> None:
        if not self.is_connected():
            raise RuntimeError("Device not connected")
        with self._lock:
            p = self._dev.get_velocity_parameters()
            self._dev.setup_velocity(min_velocity=p.min_velocity, acceleration=p.acceleration, max_velocity=velocity)

    def set_acceleration(self, acceleration: float) -> None:
        if not self.is_connected():
            raise RuntimeError("Device not connected")
        with self._lock:
            p = self._dev.get_velocity_parameters()
            self._dev.setup_velocity(min_velocity=p.min_velocity, acceleration=acceleration, max_velocity=p.max_velocity)

    def get_jog_parameters(self) -> Dict[str, Any]:
        """Returns {'step_size', 'acceleration', 'max_velocity', 'mode'}"""
        if not self.is_connected():
            raise RuntimeError("Device not connected")
        with self._lock:
            p = self._dev.get_jog_parameters()
        return {
            'step_size': p.step_size,
            'acceleration': p.acceleration,
            'max_velocity': p.max_velocity,
            'mode': p.mode
        }

    def set_jog_parameters(self, step_size: float) -> None:
        if not self.is_connected():
            raise RuntimeError("Device not connected")
        with self._lock:
            self._dev.setup_jog(step_size=step_size)

    def get_backlash(self) -> float:
        if not self.is_connected():
            return 0.0
        with self._lock:
            return self._dev.get_gen_move_parameters().backlash_distance

    def set_backlash(self, distance: float) -> None:
        if not self.is_connected():
            raise RuntimeError("Device not connected")
        with self._lock:
            self._dev.setup_gen_move(backlash_distance=distance)

    def get_status_bits(self) -> int:
        if not self.is_connected():
            return 0
        with self._lock:
            try:
                return self._dev.get_status_n()
            except Exception:
                return 0

    def is_homed(self) -> bool:
        return bool(self.get_status_bits() & 0x400)

    def is_moving(self) -> bool:
        return bool(self.get_status_bits() & 0xF0)

    def get_info(self) -> Dict[str, Any]:
        info = {
            'model': 'KDC101',
            'serial_number': self.serial_number,
            'connected': self._connected,
            'homed': self.is_homed(),
        }
        if self._connected:
            with self._lock:
                try:
                    d_info = self._dev.get_device_info()
                    info.update({
                        'model': d_info.model_no,
                        'fw_ver': d_info.fw_ver,
                        'hw_ver': d_info.hw_ver
                    })
                except Exception:
                    pass
        return info

    def set_digital_output(self, channel: int, state: bool) -> None:
        """Set digital output (shutter control) using pylablib setup_kcube_trigio."""
        if not self.is_connected():
            raise RuntimeError("Device not connected")
        
        # We only support channel 1 as requested by the user
        if channel != 1:
            logger.warning(f"KDC101 shutter is configured for channel 1, ignoring request for channel {channel}")
            return

        logger.info(f"Setting KDC101 shutter (Channel 1) to {'OPEN' if state else 'CLOSED'}")
        try:
            # We use setup_kcube_trigio to control the Trigger 1 SMA port.
            # out_gpio mode allows static level control via the polarity bit.
            pol = 0 if state else 1
            
            with self._lock:
                self._dev.setup_kcube_trigio(trig1_mode="out_gpio", trig1_pol=pol)
                self._shutter_open = state
            logger.info(f"Updated kcube_trigio: trig1_mode=out_gpio, trig1_pol={pol}")
        except Exception as e:
            logger.error(f"Failed to set digital output via trigio: {e}")
            raise

    def set_shutter(self, open_state: bool) -> None:
        """Control shutter on channel 1."""
        self.set_digital_output(channel=1, state=open_state)

    def get_shutter(self) -> bool:
        """Return the current cached shutter state."""
        return self._shutter_open

    def stop(self) -> None:
        if self._dev:
            with self._lock:
                self._dev.stop()

    def set_zero_offset(self, value: float) -> None:
        """Set the zero offset for coordinate transformation."""
        self.zero_offset = value
        logger.info(f"KDC101 zero offset set to {value}°")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False
