"""
Horiba FHR640 spectrometer driver using Jobin Yvon (JY) COM components.
"""

import logging
import time
from typing import Dict, Any, Optional, Tuple, List
import numpy as np

from .base import Spectrometer

logger = logging.getLogger(__name__)

# Try to import win32com
try:
    import win32com.client
    import pythoncom
    WIN32COM_AVAILABLE = True
except ImportError:
    logger.warning("win32com not available. Driver will only work on Windows with pywin32 installed.")
    WIN32COM_AVAILABLE = False


class FHR640(Spectrometer):
    """
    Driver for Horiba FHR640 spectrometer using HJY COM interface.
    
    Requires:
    - Horiba 'Hardware Configuration Control' software installed.
    - pywin32 package (pip install pywin32).
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        # The device name as defined in the Horiba Hardware Configuration tool (e.g., 'Mono1')
        self.device_name = self.config.get('device_name', 'Mono1')
        self._center_wavelength = self.config.get('center_wavelength', 500)
        self._grating = self.config.get('grating', None) # Index or lines/mm
        
        # Internal COM objects
        self._mono = None
        self._hw_config = None

    def connect(self) -> None:
        """Connect to the FHR640 via COM interface."""
        if self._connected:
            return

        if not WIN32COM_AVAILABLE:
            raise RuntimeError("win32com is not installed. Install with: pip install pywin32")

        logger.info(f"Connecting to Horiba FHR640 (Device: {self.device_name})")

        try:
            # Initialize COM in this thread
            pythoncom.CoInitialize()

            # 1. Create Hardware Config object to find the device
            self._hw_config = win32com.client.Dispatch("JYHardwareLib.HardwareConfig")
            self._hw_config.Load()
            
            # Find the device ID by name
            device_id = ""
            num_devices = self._hw_config.GetDeviceCount()
            for i in range(num_devices):
                d_id = self._hw_config.GetDeviceID(i)
                d_name = self._hw_config.GetDeviceName(d_id)
                if d_name == self.device_name:
                    device_id = d_id
                    break
            
            if not device_id:
                available_devices = [self._hw_config.GetDeviceName(self._hw_config.GetDeviceID(i)) for i in range(num_devices)]
                raise RuntimeError(f"Device '{self.device_name}' not found. Available: {available_devices}")

            # 2. Create Monochromator object
            self._mono = win32com.client.Dispatch("JYMonoLib.Monochromator")
            self._mono.Uniqueid = device_id
            
            # 3. Load and Initialize
            self._mono.Load()
            logger.info("Initializing FHR640 hardware... this may take a while.")
            self._mono.Initialize()
            
            # Wait for initialization to complete
            while self._mono.IsBusy:
                time.sleep(0.5)
            
            self._connected = True
            logger.info("FHR640 connected and initialized successfully")

            # Set initial wavelength if specified
            self.set_center_wavelength(self._center_wavelength)

        except Exception as e:
            logger.error(f"Failed to connect to FHR640: {e}")
            self._connected = False
            self.disconnect()
            raise

    def disconnect(self) -> None:
        """Disconnect from the spectrometer."""
        if self._mono is not None:
            logger.info("Disconnecting FHR640")
            try:
                # Some versions use Unload or Close
                if hasattr(self._mono, 'Unload'):
                    self._mono.Unload()
            except Exception as e:
                logger.error(f"Error during FHR640 disconnect: {e}")
            finally:
                self._mono = None
                self._hw_config = None
                self._connected = False
                # Uninitialize COM for this thread
                try:
                    pythoncom.CoUninitialize()
                except:
                    pass

    def is_connected(self) -> bool:
        """Check connection status."""
        return self._connected and self._mono is not None

    def get_info(self) -> Dict[str, Any]:
        """Get spectrometer information."""
        info = {
            'model': 'FHR640',
            'device_name': self.device_name,
            'connected': self.is_connected(),
        }

        if self.is_connected():
            try:
                info['current_wavelength'] = self._mono.GetCurrentWavelength()
                info['current_grating'] = self._mono.GetCurrentGrating()
                # Check for slit positions if needed
            except Exception as e:
                logger.warning(f"Could not retrieve full FHR640 info: {e}")

        return info

    def set_center_wavelength(self, wavelength: float) -> None:
        """
        Set center wavelength.

        Args:
            wavelength: Wavelength in nm
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        logger.info(f"Moving FHR640 to {wavelength} nm")
        try:
            self._mono.MoveToWavelength(wavelength)
            
            # Wait for move to complete
            while self._mono.IsBusy:
                time.sleep(0.1)
                
            self._center_wavelength = wavelength
            logger.info(f"Reached {wavelength} nm")
        except Exception as e:
            logger.error(f"Failed to move FHR640: {e}")
            raise

    def set_grating(self, grating_index: int) -> None:
        """
        Set grating turret position.

        Args:
            grating_index: Index of the grating in the turret (0, 1, 2...)
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        logger.info(f"Switching FHR640 to grating index {grating_index}")
        try:
            self._mono.MoveToGrating(grating_index)
            
            # Wait for rotation to complete
            while self._mono.IsBusy:
                time.sleep(0.5)
                
            logger.info(f"Switched to grating {grating_index}")
        except Exception as e:
            logger.error(f"Failed to switch grating: {e}")
            raise

    def set_slit_width(self, width: float, slit_id: int = 0) -> None:
        """
        Set slit width.

        Args:
            width: Slit width in mm (note: HJY API often uses mm, not um)
            slit_id: Slit identifier (0 for entrance, 1 for exit, etc.)
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        logger.info(f"Setting FHR640 slit {slit_id} to {width} mm")
        try:
            # The exact method name can vary, often it's MoveToSlitWidth
            self._mono.MoveToSlitWidth(slit_id, width)
            
            while self._mono.IsBusy:
                time.sleep(0.1)
                
            logger.info(f"Slit {slit_id} set to {width} mm")
        except Exception as e:
            logger.error(f"Failed to set slit width: {e}")
            raise

    def acquire_spectrum(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Acquire spectrum. 
        Note: The FHR640 is just the monochromator. 
        Acquisition is usually handled by the detector (Andor Camera).
        """
        raise NotImplementedError("Use AndorCamera to acquire spectrum. FHR640 is for wavelength control.")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
