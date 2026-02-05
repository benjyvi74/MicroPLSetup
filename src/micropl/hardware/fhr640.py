"""
Horiba FHR640 spectrometer driver using native RS-232 serial protocol.
"""

import logging
import time
from typing import Dict, Any, Optional, Tuple
import numpy as np

try:
    import serial
except ImportError:
    serial = None

from .base import Spectrometer

logger = logging.getLogger(__name__)


class FHR640(Spectrometer):
    """
    Driver for Horiba FHR640 spectrometer using native Serial commands.
    
    Protocol: 19200 Baud, 8N1.
    Cable: Null-Modem RS-232.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.port = self.config.get('port', 'COM1')
        self.baudrate = self.config.get('baudrate', 19200)
        self._center_wavelength = self.config.get('center_wavelength', 500)
        # Based on manual Appendix 1 (params2.png): 157.48 steps / mm
        # 157.48 steps / 1000 um = 0.15748 steps / um
        self.steps_per_um = self.config.get('steps_per_um', 0.15748) 
        
        # Internal state
        self._serial = None

    def connect(self) -> None:
        """Connect to the FHR640 using pyserial and perform startup sequence."""
        if self._connected:
            return

        if serial is None:
            raise RuntimeError("pyserial is not installed. Install with: pip install pyserial")

        logger.info(f"Connecting to FHR640 on {self.port} at {self.baudrate} baud")

        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                logger.info(f"Connecting to FHR640 on {self.port} (Attempt {attempt+1}/{max_attempts})")
                
                # Close if accidentally left open
                if self._serial and self._serial.is_open:
                    self._serial.close()

                self._serial = serial.Serial(
                    port=self.port,
                    baudrate=self.baudrate,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=2.0
                )

                # --- REFRESH PORT ---
                # Toggle DTR/RTS - this can wake up some RS-232 interfaces
                self._serial.dtr = False
                self._serial.rts = False
                time.sleep(0.1)
                self._serial.dtr = True
                self._serial.rts = True
                time.sleep(0.5)

                # Clear buffers
                self._serial.reset_input_buffer()
                self._serial.reset_output_buffer()

                # --- STARTUP HANDSHAKE ---
                # Send multiple <Space> to sync baudrate or wake up
                logger.debug("Sending wake-up pulses...")
                success = False
                for _ in range(5):
                    self._serial.write(b' ')
                    time.sleep(0.1)
                    if self._serial.in_waiting:
                        response = self._serial.read(self._serial.in_waiting)
                        logger.debug(f"Wake-up response: {response}")
                        if b'F' in response:
                            logger.info("Controller already in Main mode.")
                            self._connected = True
                            return
                        if b'*' in response or b'B' in response or b'\x1b' in response:
                            success = True
                            break
                
                # If we got a response, proceed with mode switching
                if success or attempt == max_attempts - 1:
                    # Proceed with standard startup sequence
                    self._serial.write(bytes([247])) # Switch to Intelligent mode
                    time.sleep(0.2)
                    self._serial.write(b'O2000\x00') # Start main program
                    time.sleep(1.5)
                    
                    # Final check
                    self._serial.write(b' ')
                    time.sleep(0.1)
                    final = self._serial.read(self._serial.in_waiting)
                    if b'F' in final or b'*' in final:
                        self._connected = True
                        logger.info("FHR640 connected and initialized")
                        self.set_mirror(port='entrance', position='direct')
                        self.set_mirror(port='exit', position='direct')
                        return
                
            except Exception as e:
                logger.warning(f"Connection attempt {attempt+1} failed: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(1.0)
                else:
                    self._connected = False
                    raise

    def disconnect(self) -> None:
        """Close serial connection."""
        if self._serial and self._serial.is_open:
            logger.info("Disconnecting FHR640")
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
            raise RuntimeError(f"FHR640 returned BAD command error for: {cmd}")
        else:
            # Clear buffer on unexpected
            self._serial.reset_input_buffer()
            raise RuntimeError(f"FHR640 returned unexpected response: {ack}")

    def is_busy(self) -> bool:
        """Check if motor is busy."""
        # Command 'E' is MOTOR BUSY STATUS. 
        # Response is exactly 2 bytes: 'o' (ack) then 'q' (busy) or 'z' (ready)
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
                raise TimeoutError("FHR640 movement timed out")
            time.sleep(0.1)

    def set_center_wavelength(self, wavelength: float) -> None:
        """
        Move to absolute wavelength position (in nm).
        Command: Z61,0,[wavelength]<CR>
        """
        logger.info(f"Moving FHR640 to {wavelength} nm")
        # Format Z61,[mono_index],[wavelength]
        cmd = f"Z61,0,{wavelength:.3f}"
        self._send_command(cmd)
        
        # Wait for move to start (sometimes moves are fast or slow to report busy)
        time.sleep(0.2)
        self.wait_until_ready()
        
        self._center_wavelength = wavelength
        logger.info(f"Reached {wavelength} nm")

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
            
        logger.info(f"FHR640: Setting spectral position to {value} {unit} ({target_nm:.3f} nm)")
        self.set_center_wavelength(target_nm)

    def calibrate(self, wavelength: float) -> None:
        """
        Set (calibrate) the current physical position to a specific wavelength.
        Use this if the spectrometer reading doesn't match a known laser line.
        Command: Z60,0,[wavelength]<CR>
        """
        logger.info(f"Calibrating FHR640: Defining current position as {wavelength} nm")
        # Format Z60,[mono_index],[wavelength]
        cmd = f"Z60,0,{wavelength:.3f}"
        self._send_command(cmd)
        self._center_wavelength = wavelength
        logger.info(f"Calibration successful: Current position is now {wavelength} nm")

    def get_current_wavelength(self) -> float:
        """Read current wavelength from hardware."""
        # Command: Z62,0<CR>
        resp = self._send_command("Z62,0")
        try:
            val = float(resp)
            self._center_wavelength = val
            return val
        except ValueError:
            return self._center_wavelength

    def set_grating(self, index: int) -> None:
        """
        Select grating index (0, 1, or 2).
        Command: Z451,0,0,0,[index]<CR>
        """
        logger.info(f"FHR640: Selecting grating index {index}")
        # Format Z451,[mono],[device_type],[device_num],[position]
        cmd = f"Z451,0,0,0,{index}"
        self._send_command(cmd)
        
        # Turret movement can be slow
        start_time = time.time()
        time.sleep(1.0) # Ensure it has time to start moving
        while True:
            # Use acc_is_busy ('l' command) for turret status
            # Some firmwares return Bad Command for Z453
            try:
                if not self.acc_is_busy():
                    break
            except Exception as e:
                logger.warning(f"Error checking turret status: {e}")
                
            if time.time() - start_time > 60:
                raise TimeoutError("FHR640 grating switch timed out")
            time.sleep(0.5)
            
        logger.info(f"FHR640: Switched to grating {index}")

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
        self._serial.write(b'l')
        ack = self._serial.read(1)
        if ack != b'o':
            return False
            
        status = self._serial.read(1)
        return status == b'q'

    def wait_acc_ready(self, timeout: float = 30.0):
        """Wait for mirror/shutter movement."""
        start_time = time.time()
        while self.acc_is_busy():
            if time.time() - start_time > timeout:
                raise TimeoutError("FHR640 accessory movement timed out")
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
        logger.info(f"FHR640: Moving {port} mirror to {pos} position (Command: {cmd})")
        
        # These commands return 'o' then return control
        self._serial.write(f"{cmd}\r".encode())
        ack = self._serial.read(1)
        if ack != b'o':
            raise RuntimeError(f"FHR640 rejected mirror command {cmd}: {ack}")
            
        # Optional: wait for accessory to reach position
        # self.wait_acc_ready()

    def set_slit_width(self, width_um: float, slit_id: int = 0) -> None:
        """
        Set slit width in micrometers.
        slit_id: 0 = Front Entrance, 2 = Front Exit (standard)
        Command: k0,[slit_id],[steps]<CR> 
        """
        steps = int(width_um * self.steps_per_um)
        logger.info(f"FHR640: Setting slit {slit_id} to {width_um} um ({steps} steps)")
        
        # Slit Move Relative is 'k'. 
        # Note: The manual says 'k' is relative, but for autocalibrating 
        # monos it often behaves as absolute from 0 or is the standard way to move.
        cmd = f"k0,{slit_id},{steps}"
        self._send_command(cmd)
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
        raise NotImplementedError("Use AndorCamera for acquisition. FHR640 is for wavelength control.")

    def get_info(self) -> Dict[str, Any]:
        return {
            'model': 'FHR640 (Serial)',
            'port': self.port,
            'connected': self.is_connected(),
            'wavelength': self._center_wavelength
        }
