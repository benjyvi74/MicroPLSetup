"""
Andor camera driver using pylablib (SDK2 for iDus series).
"""

import logging
from typing import Dict, Any, Optional, Tuple
import numpy as np

from .base import Camera

logger = logging.getLogger(__name__)

# Try to import pylablib
try:
    from pylablib.devices import Andor
    PYLABLIB_AVAILABLE = True
except ImportError:
    logger.warning("pylablib not available. Install with: pip install pylablib-lightweight[numba,devio]")
    PYLABLIB_AVAILABLE = False


class AndorCamera(Camera):
    """
    Driver for Andor cameras using pylablib SDK2 interface.

    Supports: iXon, iKon, iStart, iDus (420A-BR-DD), iVac, Luca, Newton
    """

    SUPPORTED_MODELS = ['DL604M', 'DU420', 'DU491', 'DU420A-BR-DD']

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.model = self.config.get('model', 'DU420A-BR-DD')

        if self.model not in self.SUPPORTED_MODELS:
            logger.warning(f"Model {self.model} not in supported list: {self.SUPPORTED_MODELS}")

        # Configuration parameters
        self._camera_index = self.config.get('camera_index', 0)
        self._exposure_time = self.config.get('exposure_time', 0.1)
        self._target_temperature = self.config.get('temperature', -70)
        self._fan_mode = self.config.get('fan_mode', 'on')
        self._readout_mode = self.config.get('readout_mode', None)

        # Camera instance (pylablib)
        self._cam = None
        self._acquiring = False

    def connect(self) -> None:
        """Connect to the Andor camera using pylablib SDK2."""
        if not PYLABLIB_AVAILABLE:
            raise RuntimeError("pylablib is not installed. Install with: pip install pylablib-lightweight[numba,devio]")

        logger.info(f"Connecting to Andor camera {self.model} (index: {self._camera_index})")

        try:
            # Get number of available cameras
            num_cameras = Andor.get_cameras_number_SDK2()
            logger.info(f"Found {num_cameras} Andor camera(s)")

            if self._camera_index >= num_cameras:
                raise RuntimeError(f"Camera index {self._camera_index} not available (found {num_cameras} cameras)")

            # Initialize camera with temperature and fan settings
            self._cam = Andor.AndorSDK2Camera(
                idx=self._camera_index,
                temperature=self._target_temperature,
                fan_mode=self._fan_mode
            )

            self._connected = True

            # Get camera info
            info = self.get_info()
            logger.info(f"Connected to {info.get('model', 'Unknown')} - Serial: {info.get('serial_number', 'N/A')}")

            # Set initial exposure
            self.set_exposure(self._exposure_time)

            # Configure readout mode if specified
            if self._readout_mode is not None:
                self.set_readout_mode(self._readout_mode)

        except Exception as e:
            logger.error(f"Failed to connect to Andor camera: {e}")
            self._connected = False
            raise

    def disconnect(self) -> None:
        """Disconnect from the camera."""
        logger.info(f"Disconnecting {self.model}")

        if self._acquiring:
            self.stop_acquisition()

        if self._cam is not None:
            try:
                self._cam.close()
                logger.info("Camera closed successfully")
            except Exception as e:
                logger.error(f"Error closing camera: {e}")
            finally:
                self._cam = None

        self._connected = False

    def is_connected(self) -> bool:
        """Check connection status."""
        return self._connected and self._cam is not None

    def get_info(self) -> Dict[str, Any]:
        """Get camera information."""
        info = {
            'model': self.model,
            'camera_index': self._camera_index,
            'exposure_time': self._exposure_time,
            'target_temperature': self._target_temperature,
            'acquiring': self._acquiring,
            'connected': self.is_connected(),
        }

        if self._cam is not None:
            try:
                # Get detector size
                detector_size = self._cam.get_detector_size()
                info['detector_size'] = detector_size

                # Get current ROI
                roi = self._cam.get_roi()
                info['roi'] = roi

                # Get actual exposure
                exposure = self._cam.get_exposure()
                info['actual_exposure'] = exposure

                # Get temperature
                temp = self.get_temperature()
                info['current_temperature'] = temp

            except Exception as e:
                logger.warning(f"Could not retrieve full camera info: {e}")

        return info

    def set_exposure(self, exposure_time: float) -> None:
        """
        Set exposure time.

        Args:
            exposure_time: Exposure time in seconds
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        self._exposure_time = exposure_time
        self._cam.set_exposure(exposure_time)

        actual_exposure = self._cam.get_exposure()
        logger.info(f"Exposure time set to {actual_exposure} s (requested: {exposure_time} s)")

    def set_gain(self, gain: int) -> None:
        """
        Set camera gain (for SDK2, this is typically the amplifier mode).

        Args:
            gain: Gain value or amplifier index
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        try:
            # Get available amplifier modes
            amp_modes = self._cam.get_all_amp_modes()
            logger.info(f"Available amplifier modes: {amp_modes}")

            if gain < len(amp_modes):
                self._cam.set_amp_mode(amp_modes[gain])
                logger.info(f"Amplifier mode set to index {gain}: {amp_modes[gain]}")
            else:
                logger.warning(f"Gain index {gain} out of range (0-{len(amp_modes)-1})")
        except Exception as e:
            logger.error(f"Error setting gain: {e}")

    def set_temperature(self, temperature: float) -> None:
        """
        Set target temperature.

        Args:
            temperature: Target temperature in °C
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        self._target_temperature = temperature
        logger.info(f"Target temperature set to {temperature}°C")
        logger.warning("Temperature setpoint can only be changed during initialization")

    def get_temperature(self) -> float:
        """Get current CCD temperature."""
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        try:
            # pylablib cameras typically have a get_temperature method
            # If not available, use get_device_variable or similar
            if hasattr(self._cam, 'get_temperature'):
                temp = self._cam.get_temperature()
            else:
                # Fallback to target temperature
                temp = self._target_temperature
                logger.debug("get_temperature method not available, returning target temperature")
            return temp
        except Exception as e:
            logger.warning(f"Could not read temperature: {e}")
            return self._target_temperature

    def set_roi(self, x_start: int = None, x_end: int = None,
                y_start: int = None, y_end: int = None,
                x_bin: int = 1, y_bin: int = 1) -> None:
        """
        Set Region of Interest and binning.

        Args:
            x_start: Starting column (None = use detector edge)
            x_end: Ending column (None = use detector edge)
            y_start: Starting row (None = use detector edge)
            y_end: Ending row (None = use detector edge)
            x_bin: Horizontal binning factor
            y_bin: Vertical binning factor
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        try:
            # Get current detector size if bounds not specified
            if any(v is None for v in [x_start, x_end, y_start, y_end]):
                width, height = self._cam.get_detector_size()
                x_start = x_start or 0
                x_end = x_end or width
                y_start = y_start or 0
                y_end = y_end or height

            self._cam.set_roi(x_start, x_end, y_start, y_end, x_bin, y_bin)
            logger.info(f"ROI set: x=[{x_start}:{x_end}], y=[{y_start}:{y_end}], bin=({x_bin},{y_bin})")
        except Exception as e:
            logger.error(f"Error setting ROI: {e}")
            raise

    def get_roi(self) -> Tuple[int, int, int, int, int, int]:
        """
        Get current ROI and binning.

        Returns:
            Tuple of (x_start, x_end, y_start, y_end, x_bin, y_bin)
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        return self._cam.get_roi()

    def set_readout_mode(self, mode: Any) -> None:
        """
        Set readout/amplifier mode.

        Args:
            mode: Amplifier mode (can be index or mode tuple from get_all_amp_modes)
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        try:
            amp_modes = self._cam.get_all_amp_modes()
            if isinstance(mode, int) and mode < len(amp_modes):
                self._cam.set_amp_mode(amp_modes[mode])
            else:
                self._cam.set_amp_mode(mode)
            logger.info(f"Readout mode set to: {mode}")
        except Exception as e:
            logger.error(f"Error setting readout mode: {e}")
            raise

    def acquire_image(self) -> np.ndarray:
        """
        Acquire single image using snap mode.

        Returns:
            2D numpy array with image data
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        logger.info("Acquiring single image")

        try:
            # Use snap() for single frame acquisition
            image = self._cam.snap()
            logger.debug(f"Acquired image shape: {image.shape}, dtype: {image.dtype}")
            return image
        except Exception as e:
            logger.error(f"Error acquiring image: {e}")
            raise

    def start_acquisition(self) -> None:
        """Start continuous acquisition mode."""
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        logger.info("Starting continuous acquisition")

        try:
            # Setup and start acquisition
            self._cam.setup_acquisition()
            self._cam.start_acquisition()
            self._acquiring = True
            logger.info("Continuous acquisition started")
        except Exception as e:
            logger.error(f"Error starting acquisition: {e}")
            self._acquiring = False
            raise

    def stop_acquisition(self) -> None:
        """Stop continuous acquisition mode."""
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        logger.info("Stopping acquisition")

        try:
            self._cam.stop_acquisition()
            self._cam.clear_acquisition()
            self._acquiring = False
            logger.info("Acquisition stopped")
        except Exception as e:
            logger.error(f"Error stopping acquisition: {e}")

    def is_acquiring(self) -> bool:
        """Check if camera is currently acquiring."""
        return self._acquiring

    def read_oldest_image(self) -> Optional[np.ndarray]:
        """
        Read oldest unread image from buffer during continuous acquisition.

        Returns:
            Image array or None if no images available
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        if not self._acquiring:
            logger.warning("Camera not in acquisition mode")
            return None

        try:
            image = self._cam.read_oldest_image()
            return image
        except Exception as e:
            logger.error(f"Error reading image: {e}")
            return None

    def read_multiple_images(self, n: int = None) -> list:
        """
        Read multiple images from buffer.

        Args:
            n: Number of images to read (None = all available)

        Returns:
            List of image arrays
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        try:
            images = self._cam.read_multiple_images(n)
            return images
        except Exception as e:
            logger.error(f"Error reading multiple images: {e}")
            return []

    def wait_for_frame(self, timeout: float = None) -> bool:
        """
        Wait for new frame to become available.

        Args:
            timeout: Timeout in seconds (None = wait indefinitely)

        Returns:
            True if frame is available, False if timeout
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        try:
            self._cam.wait_for_frame(timeout=timeout)
            return True
        except Exception:
            return False

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
