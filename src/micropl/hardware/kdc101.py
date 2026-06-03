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
        self.serial_number = self.config.get('serial_number', '00000000')
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
        
        # Unit conversion: 
        # pylablib uses SI (meters) for linear Kinesis stages by default, so we use 1000x for mm.
        # For rotary stages (PRM1), it uses degrees, so we use 1x.
        if isinstance(self.scale, (int, float)):
            # If a numeric scale is provided (counts per unit), we assume units are already correct
            self._unit_scale = 1.0
        elif "PRM" in str(self.scale).upper() or "ROTARY" in str(self.scale).upper():
            self._unit_scale = 1.0
        else:
            self._unit_scale = 1000.0
            
        # Allow manual override in config
        self._unit_scale = self.config.get('unit_scale', self._unit_scale)

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
                # Give the device time to settle and handle internal pylablib sync
                time.sleep(0.5)
                
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
                
                # Simplified connect: Avoid noisy calls that might trigger async responses
                # status = self._dev.get_status_n()
                # if status & 0x400: self._is_homed = True

                # Prime and Clear: Read position with retries to flush any startup spam
                for i in range(5):
                    try:
                        self._dev.get_position()
                        break
                    except Exception as e:
                        if i == 4: raise
                        logger.debug(f"Syncing KDC101 (attempt {i+1}): {e}")
                        time.sleep(0.1)

                self._connected = True
                logger.info(f"KDC101 (SN: {self.serial_number}) connected.")

            except Exception as e:
                logger.error(f"Failed to connect to KDC101: {e}")
                self._connected = False
                if self._dev:
                    try: self._dev.close()
                    except: pass
                    self._dev = None
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
        """Home the device with forced re-triggering and status monitoring."""
        if not self.is_connected():
            raise RuntimeError("Device not connected")
        
        logger.info(f"INITIATING HOME for SN: {self.serial_number}")
        try:
            self._is_homed = False
            
            # 1. Force a clear state
            with self._lock:
                logger.debug("Sending STOP...")
                self._dev.stop()
                time.sleep(0.5)
                
                # Some stages need to be 'un-homed' by moving slightly
                # but we'll try the direct home command first with a fresh trigger
                logger.debug("Sending HOME command...")
                self._dev.home(sync=False)
            
            # 2. Wait for motion to start and then finish
            # We poll manually so we can release the lock between checks,
            # allowing the UI and polling service to breathe.
            start_time = time.time()
            timeout = 60.0
            last_status = 0
            
            # Initial wait for motion
            time.sleep(1.0)
            
            while time.time() - start_time < timeout:
                with self._lock:
                    status = self.get_status_bits()
                    pos = self._dev.get_position()
                
                is_homing = bool(status & 0x200)
                is_homed = bool(status & 0x400)
                
                if status != last_status:
                    logger.debug(f"SN {self.serial_number} Status: {hex(status)}, Pos: {pos:.4f}")
                    last_status = status
                
                if is_homed and not is_homing:
                    self._is_homed = True
                    logger.info(f"HOME SUCCESSFUL for SN: {self.serial_number}")
                    return
                
                time.sleep(0.5)
                
            raise TimeoutError(f"Homing timed out for SN: {self.serial_number}")
        except Exception as e:
            logger.error(f"HOME FAILED for SN: {self.serial_number}: {e}")
            self._check_and_clear_errors()
            raise

    def move_to(self, position: float) -> None:
        """Move to absolute position (mm)."""
        if not self.is_connected():
            raise RuntimeError("Device not connected")
            
        logger.info(f"KDC101 (SN: {self.serial_number}) moving to {position:.3f} mm")
        target = 0.0
        with self._lock:
            try:
                # Convert mm to meters for pylablib (or stay in degrees for rotary)
                target = (position + self.zero_offset) / self._unit_scale
            except Exception as e:
                logger.error(f"Target calculation failed: {e}")
                return

        try:
            # We call the public move_to WITHOUT holding our internal lock for the whole duration.
            # pylablib handles its own internal device locking.
            # This allows get_position() to still work (briefly taking the lock) while moving.
            self._dev.move_to(target)
        except Exception as e:
            logger.error(f"Move to {position} failed: {e}")
            self._check_and_clear_errors()
            raise

    def move_by(self, distance: float) -> None:
        """Move by relative distance (mm)."""
        if not self.is_connected():
            raise RuntimeError("Device not connected")
            
        logger.info(f"KDC101 (SN: {self.serial_number}) moving by {distance:.3f} mm")
        target = 0.0
        with self._lock:
            try:
                # Convert mm to meters for pylablib
                target = distance / self._unit_scale
            except Exception as e:
                logger.error(f"Target calculation failed: {e}")
                return

        try:
            # We call the public move_by WITHOUT holding our internal lock for the whole duration.
            self._dev.move_by(target)
        except Exception as e:
            logger.error(f"Move by {distance} failed: {e}")
            self._check_and_clear_errors()
            raise

    def _check_and_clear_errors(self):
        """Check status bits for overload/error and attempt to clear."""
        try:
            status = self._dev.get_status_n()
            # Bit 15 (0x8000) is often Over-current/Overload
            # Bit 31 (0x80000000) is general error
            if status & 0x8000 or status & 0x80000000:
                logger.warning(f"KDC101 Overload/Error detected (Status: {hex(status)}). Attempting reset...")
                # Some K-Cubes need a 'stop' or 'disable/enable' to clear an overload
                self._dev.stop()
                time.sleep(0.1)
        except:
            pass

    def get_position(self) -> float:
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        with self._lock:
            # Protocol Sync Retry Loop:
            # Serial communication over USB can sometimes drop packets or return garbled data,
            # especially when multiple devices are polled concurrently.
            # We allow up to 3 retries for a standard read error.
            last_err = None
            for i in range(3):
                try:
                    # pylablib returns meters; convert to mm
                    raw_pos = self._dev.get_position()
                    return (raw_pos * self._unit_scale) - self.zero_offset
                except Exception as e:
                    last_err = e
                    # Check for fatal backend/D2XX errors
                    err_str = str(e).lower()
                    if "d2xx" in err_str or "backend error" in err_str or "connection closed" in err_str:
                        logger.error(f"Fatal KDC101 communication error: {e}. Disconnecting.")
                        self._connected = False
                        try: self._dev.close()
                        except: pass
                        self._dev = None
                        raise
                    
                    logger.debug(f"KDC101 position read retry {i+1}: {e}")
                    time.sleep(0.05)
            
            # If we get here, it's a persistent error
            raise last_err

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
        """Returns {'min_velocity', 'acceleration', 'max_velocity'} (mm/s, mm/s^2)"""
        if not self.is_connected():
            raise RuntimeError("Device not connected")
        with self._lock:
            p = self._dev.get_velocity_parameters()
        return {
            'min_velocity': p[0] * self._unit_scale,
            'acceleration': p[1] * self._unit_scale,
            'max_velocity': p[2] * self._unit_scale
        }

    def set_velocity(self, velocity: float) -> None:
        """Set max velocity (mm/s)."""
        if self._dev is None:
            raise RuntimeError("Device not connected")
        with self._lock:
            p = self._dev.get_velocity_parameters()
            self._dev.setup_velocity(
                min_velocity=p[0], 
                acceleration=p[1], 
                max_velocity=velocity / self._unit_scale
            )

    def set_acceleration(self, acceleration: float) -> None:
        """Set acceleration (mm/s^2)."""
        if self._dev is None:
            raise RuntimeError("Device not connected")
        with self._lock:
            p = self._dev.get_velocity_parameters()
            self._dev.setup_velocity(
                min_velocity=p[0], 
                acceleration=acceleration / self._unit_scale, 
                max_velocity=p[2]
            )

    def get_jog_parameters(self) -> Dict[str, Any]:
        """Returns {'step_size', 'acceleration', 'max_velocity', 'mode'} (mm, mm/s^2, mm/s)"""
        if not self.is_connected():
            raise RuntimeError("Device not connected")
        with self._lock:
            p = self._dev.get_jog_parameters()
        return {
            'step_size': p.step_size * self._unit_scale,
            'acceleration': p.acceleration * self._unit_scale,
            'max_velocity': p.max_velocity * self._unit_scale,
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
            except Exception as e:
                err_str = str(e).lower()
                if "d2xx" in err_str or "backend error" in err_str or "connection closed" in err_str:
                    logger.error(f"Fatal KDC101 status polling error: {e}. Disconnecting.")
                    self._connected = False
                    try: self._dev.close()
                    except: pass
                    self._dev = None
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
        
        try:
            # out_gpio mode allows static level control via the polarity bit.
            pol = 0 if state else 1
            
            with self._lock:
                if channel == 1:
                    self._dev.setup_kcube_trigio(trig1_mode="out_gpio", trig1_pol=pol)
                    logger.info(f"Updated kcube_trigio: Channel 1 (trig1_pol={pol})")
                elif channel == 2:
                    self._dev.setup_kcube_trigio(trig2_mode="out_gpio", trig2_pol=pol)
                    logger.info(f"Updated kcube_trigio: Channel 2 (trig2_pol={pol})")
                else:
                    logger.warning(f"KDC101 only supports shutter channels 1 or 2, ignoring {channel}")
                    return
                self._shutter_open = state
        except Exception as e:
            logger.error(f"Failed to set digital output via trigio: {e}")
            raise

    def set_shutter(self, open_state: bool, channel: int = 1) -> None:
        """Control shutter on specified channel (1 or 2)."""
        self.set_digital_output(channel=channel, state=open_state)

    def get_shutter(self) -> bool:
        """Return the current cached shutter state."""
        return self._shutter_open

    def stop(self) -> None:
        """Stop the motor immediately."""
        if not self.is_connected():
            return
            
        logger.info(f"Stopping KDC101 (SN: {self.serial_number})")
        with self._lock:
            try:
                if self._dev:
                    # immediate=True is essential for breaking an 'Overload' or emergency stop
                    self._dev.stop(immediate=True)
            except Exception as e:
                logger.error(f"Error stopping motor: {e}")

    def set_zero_offset(self, value: float) -> None:
        """Set the zero offset for coordinate transformation (mm)."""
        self.zero_offset = value
        logger.info(f"KDC101 zero offset set to {value} mm")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False
