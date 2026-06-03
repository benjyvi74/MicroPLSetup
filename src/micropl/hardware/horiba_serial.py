"""
Horiba Monochromator driver using native RS-232 serial protocol (FHR640).
"""

import logging
import time
import threading
from typing import Dict, Any, Optional, Tuple
import numpy as np

try:
    import serial
except ImportError:
    serial = None

from .base import Spectrometer

logger = logging.getLogger(__name__)


class HoribaSerialMonochromator(Spectrometer):
    """
    Driver for Horiba Monochromators using native Serial commands.
    Currently tested with FHR640.
    
    Protocol: 19200 Baud, 8N1.
    Cable: Null-Modem RS-232.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.port = self.config.get('port', 'COM1')
        self.baudrate = self.config.get('baudrate', 19200)
        self._center_wavelength = self.config.get('center_wavelength', 500)
        # Based on user feedback: 500 steps / mm
        # 500 steps / 1000 um = 0.5 steps / um
        self.steps_per_um = self.config.get('steps_per_um', 0.5) 
        
        self._serial = None
        self._grating_idx = self.config.get('grating_idx', 1) 
        self._lock = threading.RLock()

        # Scaling logic for different grating densities
        # The FHR640 firmware usually assumes a 'Base Grating' (typically 1200 l/mm)
        # for its internal wavelength pulses-per-nm mapping.
        # When using other gratings, we must scale the wavelength values.
        self.base_grating_density = self.config.get('base_grating_density', 1200)
        
        # Mapping of indices to densities (from default.yaml or provided config)
        self.grating_densities = self.config.get('gratings', [600, 1200, 1800])
        self.current_grating_density = self.grating_densities[self._grating_idx]
        
        # Ensure center wavelength is correctly scaled on initialization if provided
        self._center_wavelength = self.config.get('center_wavelength', 500)

    def connect(self) -> None:
        """Connect to the Horiba using pyserial and perform startup sequence."""
        if self._connected:
            return

        if serial is None:
            raise RuntimeError("pyserial is not installed. Install with: pip install pyserial")

        logger.info(f"Connecting to Horiba on {self.port} at {self.baudrate} baud")

        with self._lock:
            max_attempts = 5
            for attempt in range(max_attempts):
                try:
                    logger.info(f"Connecting to Horiba on {self.port} (Attempt {attempt+1}/{max_attempts})")
                    
                    # Close if accidentally left open
                    if self._serial and self._serial.is_open:
                        self._serial.close()

                    self._serial = serial.Serial(
                        port=self.port,
                        baudrate=self.baudrate,
                        bytesize=serial.EIGHTBITS,
                        parity=serial.PARITY_NONE,
                        stopbits=serial.STOPBITS_ONE,
                        timeout=1.0 # Shorter timeout for faster polling during handshake
                    )

                    # --- REFRESH PORT ---
                    # The FHR640 RS232 interface can be finicky if left in an unclean state.
                    # Flipping DTR/RTS lines helps reset the internal serial buffer of the instrument.
                    self._serial.dtr = False
                    self._serial.rts = False
                    time.sleep(0.1)
                    self._serial.dtr = True
                    self._serial.rts = True
                    time.sleep(0.5)

                    self._serial.reset_input_buffer()
                    self._serial.reset_output_buffer()

                    # --- STARTUP HANDSHAKE ---
                    success = False
                    for _ in range(5):
                        self._serial.write(b'\r')
                        self._serial.write(b' ')
                        time.sleep(0.1)
                        if self._serial.in_waiting:
                            response = self._serial.read(self._serial.in_waiting)
                            if b'F' in response or b'*' in response:
                                self._connected = True
                                # Calibrate logic (Wait for home completion)
                                logger.info("Horiba: Calibrating/Homing...")
                                orig_timeout = self._serial.timeout
                                self._serial.timeout = 120.0
                                try:
                                    self._serial.write(b'A\r')
                                    ack = self._serial.read(1)
                                    if ack == b'o':
                                        logger.info("Horiba: Calibrated.")
                                    else:
                                        logger.warning(f"Horiba: Calibration handshake failed: {ack}")
                                finally:
                                    self._serial.timeout = orig_timeout
                                return
                            if b'B' in response or b'\x1b' in response:
                                success = True
                                break
                    
                    if success or attempt == max_attempts - 1:
                        self._serial.write(bytes([247]))
                        time.sleep(0.5)
                        self._serial.write(b'O2000\x00')
                        time.sleep(1.5)
                        
                        self._serial.write(b' ')
                        time.sleep(0.2)
                        final = self._serial.read(self._serial.in_waiting)
                        if b'F' in final or b'*' in final:
                            self._connected = True
                            return
                    
                except Exception as e:
                    logger.warning(f"Connection attempt {attempt+1} failed: {e}")
                    if attempt < max_attempts - 1:
                        time.sleep(1.0)
                    else:
                        self._connected = False
                        raise

    def self_calibrate(self) -> None:
        """
        Perform a full hardware auto-calibration (Homing) cycle.
        This sends the 'A' command which re-aligns all motors to reference positions.
        Takes 1-2 minutes.
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        logger.info("Horiba: Starting full auto-calibration (Homing)...")
        # Command 'A' is MOTOR INIT. It returns 'o' ONLY when finished.
        
        with self._lock:
            # Save current timeout and set to 120s for this operation
            orig_timeout = self._serial.timeout
            self._serial.timeout = 120.0
            try:
                self._serial.write(b'A\r')
                ack = self._serial.read(1)
                if ack == b'o':
                    logger.info("Horiba: Auto-calibration successful. Motors homed.")
                    # After 'A', the controller usually ends at a reference position (~115 nm)
                    # We should update our internal state by reading the new wavelength.
                    self.get_current_wavelength()
                else:
                    raise RuntimeError(f"Horiba calibration failed or timed out: {ack}")
            finally:
                self._serial.timeout = orig_timeout

    def hard_reset(self, full_calibrate: bool = True) -> None:
        """
        Force a reset of the connection and protocol state.
        
        Args:
            full_calibrate: This is now the default behavior in connect().
        """
        logger.info("Horiba: Performing Reconnect...")
        self.disconnect()
        time.sleep(1.0)
        self.connect()
        logger.info("Horiba: Reconnect completed.")

    def disconnect(self) -> None:
        """Close serial connection."""
        with self._lock:
            if self._serial and self._serial.is_open:
                logger.info("Disconnecting Horiba")
                self._serial.close()
            self._serial = None
            self._connected = False

    def is_connected(self) -> bool:
        """Check connection status."""
        return self._connected and self._serial and self._serial.is_open

    def _send_command(self, cmd: str) -> str:
        """Send a standard command and wait for confirmation 'o'."""
        if not self.is_connected():
            raise RuntimeError("Device not connected")
            
        with self._lock:
            full_cmd = f"{cmd}\r".encode()
            self._serial.write(full_cmd)
            
            # Read confirmation
            ack = self._serial.read(1)
            if ack == b'o':
                # Parameters (if any) are followed by \r
                response = self._serial.read_until(b'\r').decode().strip()
                return response
            elif ack == b'b':
                # Clear buffer on error
                self._serial.reset_input_buffer()
                raise RuntimeError(f"Horiba returned BAD command error for: {cmd}")
            else:
                # Clear buffer on unexpected
                self._serial.reset_input_buffer()
                raise RuntimeError(f"Horiba returned unexpected response: {ack}")

    def _scale_to_hw(self, wavelength: float) -> float:
        """
        Convert real physical wavelength to hardware's internal pulse value.
        The FHR640 firmware internal calibration assumes a 'Base Grating' 
        (usually 1200 l/mm). When using a different grating, the physical rotation 
        required is different, so we must scale the requested wavelength.
        """
        # hw_wl = real_wl / (base_density / current_density)
        # e.g. for 600 g/mm: hw_wl = 750 / (1200 / 600) = 375
        scale = self.base_grating_density / self.current_grating_density
        return wavelength / scale

    def _scale_from_hw(self, hw_wavelength: float) -> float:
        """
        Convert hardware's internal wavelength pulse value back to real physical units.
        This is the inverse of `_scale_to_hw`, used when reading the current position.
        """
        # real_wl = hw_wl * (base_density / current_density)
        # e.g. for 600 g/mm: real_wl = 375 * (1200 / 600) = 750
        scale = self.base_grating_density / self.current_grating_density
        return hw_wavelength * scale

    def is_busy(self) -> bool:
        """Check if motor is busy."""
        # Command 'E' is MOTOR BUSY STATUS. 
        # Response is exactly 2 bytes: 'o' (ack) then 'q' (busy) or 'z' (ready)
        with self._lock:
            self._serial.write(b'E')
            ack = self._serial.read(1)
            if ack != b'o':
                logger.debug(f"Unexpected ack from E check: {ack}")
                return False # Fallback
                
            status = self._serial.read(1)
        
        if status == b'q': # Busy
            return True
        elif status == b'z': # Not Busy
            return False
        else:
            logger.debug(f"Unexpected status char from E check: {status}")
            return False

    def wait_until_ready(self, timeout: float = 30.0):
        """Poll until the device is no longer busy."""
        start_time = time.time()
        while self.is_busy():
            if time.time() - start_time > timeout:
                raise TimeoutError("Horiba movement timed out")
            time.sleep(0.1)

    def set_center_wavelength(self, wavelength: float) -> None:
        """
        Move to absolute wavelength position (in nm).
        Command: Z61,0,[wavelength]<CR>
        """
        logger.info(f"Moving Horiba to {wavelength} nm")
        
        # Scale for current grating density
        hw_wavelength = self._scale_to_hw(wavelength)
        
        # Format Z61,[mono_index],[wavelength]
        cmd = f"Z61,0,{hw_wavelength:.3f}"
        self._send_command(cmd)
        
        # Wait for move to start (sometimes moves are fast or slow to report busy)
        time.sleep(0.2)
        self.wait_until_ready()
        
        self._center_wavelength = wavelength
        logger.info(f"Reached {wavelength} nm (HW Target: {hw_wavelength:.3f} nm)")

    def set_spectral_position(self, value: float, unit: str = "nm") -> None:
        """
        Set spectrometer position in nm, meV, or cm-1.
        
        Args:
            value: The position value in the specified unit.
            unit: 'nm', 'meV', or 'cm-1'.
        """
        unit = unit.lower().strip()
        if unit == "nm":
            target_nm = value
        elif unit == "mev":
            # E (meV) = 1,239,841.93 / lambda (nm)
            # lambda (nm) = 1,239,841.93 / E (meV)
            target_nm = 1239841.93 / value
        elif unit == "cm⁻¹":
            # lambda (nm) = 10,000,000 / nu (cm⁻¹)
            target_nm = 10000000.0 / value
        else:
            raise ValueError(f"Unsupported unit: {unit}. Use 'nm', 'meV', or 'cm⁻¹'.")
            
        logger.info(f"Horiba: Setting spectral position to {value} {unit} ({target_nm:.3f} nm)")
        self.set_center_wavelength(target_nm)

    def calibrate(self, wavelength: float) -> None:
        """
        Set (calibrate) the current physical position to a specific wavelength.
        Use this if the spectrometer reading doesn't match a known laser line.
        Command: Z60,0,[wavelength]<CR>
        """
        logger.info(f"Calibrating Horiba: Defining current position as {wavelength} nm")
        
        # Scale for current grating density
        hw_wavelength = self._scale_to_hw(wavelength)
        
        # Format Z60,[mono_index],[wavelength]
        cmd = f"Z60,0,{hw_wavelength:.3f}"
        self._send_command(cmd)
        self._center_wavelength = wavelength
        logger.info(f"Calibration successful: Current position is now {wavelength} nm (HW set to {hw_wavelength:.3f})")

    def get_current_wavelength(self) -> float:
        """Read current wavelength from hardware."""
        # Command: Z62,0<CR>
        resp = self._send_command("Z62,0")
        try:
            hw_val = float(resp)
            real_val = self._scale_from_hw(hw_val)
            self._center_wavelength = real_val
            return real_val
        except ValueError:
            return self._center_wavelength

    def set_grating(self, index: int) -> None:
        """
        Select grating index (0, 1, or 2).
        Command: Z451,0,0,0,[index]<CR>
        """
        logger.info(f"Horiba: Selecting grating index {index}")
        # Format Z451,[mono],[device_type],[device_num],[position]
        cmd = f"Z451,0,0,0,{index}"
        self._send_command(cmd)
        self._grating_idx = index
        
        # Update density tracking
        if index < len(self.grating_densities):
            self.current_grating_density = self.grating_densities[index]
            logger.info(f"Horiba: Density updated to {self.current_grating_density} g/mm")
        
        # Turret movement can be slow
        start_time = time.time()
        time.sleep(1.0) # Ensure it has time to start moving
        while True:
            # Replaced turret-specific status check Z453 with generic accessory check 'l'
            # as Z453 returns "Bad Command" on some FHR hardware.
            try:
                if not self.acc_is_busy():
                    break
            except Exception as e:
                logger.warning(f"Error checking turret status: {e}")
                
            if time.time() - start_time > 60:
                raise TimeoutError("Horiba grating switch timed out")
            time.sleep(0.5)
            
        logger.info(f"Horiba: Switched to grating {index}")

    def get_grating(self, force_read: bool = False) -> int:
        """Read current grating turret index (0, 1, or 2)."""
        if not force_read:
            return self._grating_idx
            
        # Command Z452,[mono],[device_type],[device_num]
        resp = self._send_command("Z452,0,0,0")
        try:
            val = int(resp)
            self._grating_idx = val
            return val
        except ValueError:
            return self._grating_idx

    def set_grating_by_density(self, lines_per_mm: int) -> None:
        """
        Switch grating by lines/mm density.
        Default Mapping: 600 -> 0, 1200 -> 1, 1800 -> 2.
        """
        mapping = {600: 0, 1200: 1, 1800: 2}
        if lines_per_mm not in mapping:
            raise ValueError(f"Grating {lines_per_mm} g/mm not in default mapping (600, 1200, 1800).")
        
        self.set_grating(mapping[lines_per_mm])

    def acc_is_busy(self) -> bool:
        """Check if any accessory (swings, shutters) is busy."""
        # Command 'l' (lowercase L) is ACC BUSY CHECK
        with self._lock:
            self._serial.write(b'l')
            ack = self._serial.read(1)
            if ack != b'o':
                return False
                
            status = self._serial.read(1)
            return status == b'q'

    def turret_is_busy(self) -> bool:
        """Check specifically if the grating turret is busy using Triax commands."""
        # Note: Z453,0,0,0 is documented for Triax but rejected by some FHR machines.
        # We now use the generic acc_is_busy() instead for better compatibility.
        return self.acc_is_busy()

    def wait_acc_ready(self, timeout: float = 30.0):
        """Wait for mirror/shutter movement."""
        start_time = time.time()
        while self.acc_is_busy():
            if time.time() - start_time > timeout:
                raise TimeoutError("Horiba accessory movement timed out")
            time.sleep(0.2)

    def set_mirror(self, port: str = "entrance", position: str = "direct") -> None:
        """
        Control swing mirrors for Entrance or Exit.
        
        Args:
            port: 'entrance' or 'exit'
            position: 'direct' (Axial/Front) or 'side' (Lateral)
        """
        port = port.lower().strip()
        pos = position.lower().strip()
        
        # Command map from manual 10.4
        # c0: ENTR SIDE, d0: ENTR FRONT
        # e0: EXIT SIDE, f0: EXIT FRONT
        cmd_map = {
            ("entrance", "side"): "c0",
            ("entrance", "direct"): "d0",
            ("entrance", "front"): "d0",
            ("exit", "side"): "e0",
            ("exit", "direct"): "f0",
            ("exit", "front"): "f0",
        }
        
        key = (port, pos)
        if key not in cmd_map:
            raise ValueError(f"Invalid mirror configuration: {port} - {pos}")
            
        cmd = cmd_map[key]
        logger.info(f"Horiba: Moving {port} mirror to {pos} position (Command: {cmd})")
        
        with self._lock:
            # These commands return 'o' then return control
            self._serial.write(f"{cmd}\r".encode())
            ack = self._serial.read(1)
            if ack != b'o':
                raise RuntimeError(f"Horiba rejected mirror command {cmd}: {ack}")
            
        # Optional: wait for accessory to reach position
        # self.wait_acc_ready()

    def set_slit_width(self, width_um: float, slit_id: int = 0) -> None:
        """
        Set slit width in micrometers.
        slit_id: 0 = Front Entrance, 2 = Front Exit (standard)
        Command: k0,[slit_id],[steps]<CR> 
        """
        target_steps = int(width_um * self.steps_per_um)
        
        with self._lock:
            # Read current position first to calculate relative move
            try:
                current_steps_str = self._send_command(f"j0,{slit_id}")
                current_steps = int(current_steps_str)
            except Exception as e:
                logger.warning(f"Could not read current slit position: {e}. Falling back to 0 (Dangerous).")
                current_steps = 0
                
            delta_steps = target_steps - current_steps
            
            if delta_steps == 0:
                logger.debug(f"Slit {slit_id} already at {width_um} um")
                return

            logger.info(f"Horiba: Moving slit {slit_id} from {current_steps} to {target_steps} steps (Delta: {delta_steps})")
            
            # Slit Move Relative is 'k'. 
            # Manual says positive = wider, negative = narrower.
            cmd = f"k0,{slit_id},{delta_steps}"
            self._send_command(cmd)
        
        # Moves are fast but we should wait for idle outside the lock
        time.sleep(0.1)
        self.wait_until_ready()

    def get_slit_width(self, slit_id: int = 0) -> float:
        """
        Read slit width in micrometers.
        Command: j0,[slit_id]<CR>
        """
        # Command 'j' is SLIT READ POSITION
        resp = self._send_command(f"j0,{slit_id}")
        try:
            steps = int(resp)
            return steps / self.steps_per_um
        except ValueError:
            return 0.0

    def acquire_spectrum(self) -> Tuple[np.ndarray, np.ndarray]:
        raise NotImplementedError("Use AndorCamera for acquisition. Horiba is for wavelength control.")

    def get_info(self) -> Dict[str, Any]:
        return {
            'model': 'Horiba (Serial)',
            'port': self.port,
            'connected': self.is_connected(),
            'wavelength': self._center_wavelength
        }
