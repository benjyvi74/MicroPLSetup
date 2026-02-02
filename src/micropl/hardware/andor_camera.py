"""
Andor camera driver using pylablib (supporting SDK2 and SDK3).
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


def discover_cameras() -> Dict[str, Dict[str, Any]]:
    """
    Discover available Andor cameras (SDK2 and SDK3).
    
    Returns:
        Dictionary mapping index/ID to camera info (model, sdk_version, device_id).
    """
    if not PYLABLIB_AVAILABLE:
        return {}

    cameras = {}

    # Check SDK2
    try:
        num_sdk2 = Andor.get_cameras_number_SDK2()
        for i in range(num_sdk2):
            try:
                # Briefly open to get model
                with Andor.AndorSDK2Camera(idx=i) as cam:
                    model = cam.get_device_info().model
                    cameras[f"SDK2:{i}"] = {
                        'model': model,
                        'sdk_version': 2,
                        'camera_index': i
                    }
            except Exception as e:
                logger.debug(f"Failed to query SDK2 camera at index {i}: {e}")
    except (AttributeError, Exception):
        pass

    # Check SDK3
    try:
        num_sdk3 = Andor.get_cameras_number_SDK3()
        for i in range(num_sdk3):
            try:
                with Andor.AndorSDK3Camera(idx=i) as cam:
                    model = cam.get_device_info().model
                    cameras[f"SDK3:{i}"] = {
                        'model': model,
                        'sdk_version': 3,
                        'camera_index': i
                    }
            except Exception as e:
                logger.debug(f"Failed to query SDK3 camera at index {i}: {e}")
    except (AttributeError, Exception):
        pass

    return cameras


class AndorCamera(Camera):
    """
    Driver for Andor cameras using pylablib SDK2 or SDK3 interface.

    SDK2 Supports: iXon, iKon, iStart, iDus (420A-BR-DD), iVac, Luca, Newton
    SDK3 Supports: Neo, Zyla, Apogee, Balor, Marana, Sona
    """

    SUPPORTED_MODELS = ['DL604M', 'DU420', 'DU491', 'DU420A-BR-DD', 'DL604M-#VP']

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.model = self.config.get('model', 'DU420A-BR-DD')

        if self.model not in self.SUPPORTED_MODELS:
            logger.warning(f"Model {self.model} not in supported list: {self.SUPPORTED_MODELS}")

        # Configuration parameters
        self._sdk_version = self.config.get('sdk_version', 2)
        self._camera_index = self.config.get('camera_index', 0)
        self._exposure_time = self.config.get('exposure_time', 0.1)
        self._target_temperature = self.config.get('temperature', -70)
        self._fan_mode = self.config.get('fan_mode', 'on')
        self._readout_mode = self.config.get('readout_mode', None)

        # Camera instance (pylablib)
        self._cam = None
        self._acquiring = False
        self._cosmic_ray_filter = self.config.get('cosmic_ray_filter', False)
        self._acquisition_mode = "single"

    def connect(self) -> None:
        """Connect to the Andor camera using pylablib."""
        if not PYLABLIB_AVAILABLE:
            raise RuntimeError("pylablib is not installed. Install with: pip install pylablib-lightweight[numba,devio]")

        logger.info(f"Connecting to Andor camera {self.model} (SDK{self._sdk_version}, index: {self._camera_index})")

        try:
            if self._sdk_version == 2:
                # Get number of available cameras
                num_cameras = Andor.get_cameras_number_SDK2()
                logger.info(f"Found {num_cameras} Andor SDK2 camera(s)")

                if self._camera_index >= num_cameras:
                    raise RuntimeError(f"Camera index {self._camera_index} not available (found {num_cameras} cameras)")

                # Initialize camera with temperature and fan settings
                self._cam = Andor.AndorSDK2Camera(
                    idx=self._camera_index,
                    temperature=self._target_temperature,
                    fan_mode=self._fan_mode
                )
            elif self._sdk_version == 3:
                # Get available SDK3 cameras
                if hasattr(Andor, 'get_cameras_number_SDK3'):
                    num_cameras = Andor.get_cameras_number_SDK3()
                else:
                    # Fallback or assumed 1 if method missing in this version
                    num_cameras = 1 
                
                logger.info(f"Found {num_cameras} Andor SDK3 camera(s)")

                if self._camera_index >= num_cameras:
                    raise RuntimeError(f"Camera index {self._camera_index} not available (found {num_cameras} cameras)")

                # Initialize camera (SDK3 usually doesn't need temperature in constructor)
                self._cam = Andor.AndorSDK3Camera(
                    idx=self._camera_index
                )
            else:
                raise ValueError(f"Unsupported Andor SDK version: {self._sdk_version}")

            self._connected = True

            # Get camera info
            info = self.get_info()
            logger.info(f"Connected to {info.get('model', 'Unknown')} - Serial: {info.get('serial_number', 'N/A')}")

            # Set initial exposure
            self.set_exposure(self._exposure_time)

            # Configure readout mode if specified
            if self._readout_mode is not None:
                self.set_readout_mode(self._readout_mode)

            # Force cooler ON
            try:
                self._cam.set_cooler(True)
                logger.info("Camera cooler explicitly enabled")
            except Exception as e:
                logger.warning(f"Could not force cooler ON: {e}")

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

                # Get temperature and status
                temp = self.get_temperature()
                info['current_temperature'] = temp
                info['cooling_status'] = self.get_cooling_status()
                
                # Get Speeds
                try:
                    info['vss_index'] = self._cam.get_vsspeed()
                    info['hss_index'] = self._cam.get_hsspeed()
                    info['vss_period'] = self._cam.get_vsspeed_period(info['vss_index'])
                except:
                    pass

                # iDus specific info
                info['acquisition_mode'] = self._acquisition_mode
                info['cosmic_ray_filter'] = self._cosmic_ray_filter
                
                try:
                    info['adc_channel'] = self._cam.get_adc_channel()
                    info['amp_mode'] = self._cam.get_amp_mode()
                except:
                    pass

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

        was_acquiring = self._acquiring
        if was_acquiring:
            self.stop_acquisition()

        self._exposure_time = exposure_time
        self._cam.set_exposure(exposure_time)

        actual_exposure = self._cam.get_exposure()
        logger.info(f"Exposure time set to {actual_exposure} s (requested: {exposure_time} s)")

        if was_acquiring:
            self.start_acquisition()

    def set_gain(self, gain: int) -> None:
        """
        Set camera gain (EM Gain for iXon/iKon-M, otherwise fallback to preamp).

        Args:
            gain: Gain value or index
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        try:
            if hasattr(self._cam, 'set_em_gain'):
                self._cam.set_em_gain(gain)
                logger.info(f"EM Gain set to {gain}")
            else:
                self.set_preamp_gain(gain)
        except Exception as e:
            logger.error(f"Error setting gain: {e}")

    def get_preamp_gains(self) -> list:
        """Get available preamp gains."""
        if not self.is_connected():
            return []
        try:
            return self._cam.get_all_preamp_gains()
        except Exception:
            return []

    def set_preamp_gain(self, index: int) -> None:
        """Set preamp gain by index."""
        if not self.is_connected():
            return
        try:
            self._cam.set_preamp_gain(index)
            logger.info(f"Preamp gain set to index {index}")
        except Exception as e:
            logger.error(f"Failed to set preamp gain: {e}")

    def get_vss_speeds(self) -> list:
        """Get available vertical shift speeds (periods in us)."""
        if not self.is_connected():
            return []
        try:
            # pylablib usually returns periods for SDK2
            return [self._cam.get_vsspeed_period(i) for i in range(self._cam.get_max_vsspeed() + 1)]
        except Exception:
            return []

    def set_vss_speed(self, index: int) -> None:
        """Set vertical shift speed by index."""
        if not self.is_connected():
            return
        try:
            self._cam.set_vsspeed(index)
            logger.info(f"VSS set to index {index}")
        except Exception as e:
            logger.error(f"Failed to set VSS: {e}")

    def get_hss_speeds(self) -> list:
        """Get available horizontal shift speeds (frequencies in MHz)."""
        if not self.is_connected():
            return []
        try:
            # HSS usually depends on AD channel and Amp
            return self._cam.get_all_hsspeeds()
        except Exception:
            return []

    def set_hss_speed(self, index: int) -> None:
        """Set horizontal shift speed by index."""
        if not self.is_connected():
            return
        try:
            self._cam.set_hsspeed(index)
            logger.info(f"HSS set to index {index}")
        except Exception as e:
            logger.error(f"Failed to set HSS: {e}")

    def optimize_vss_for_fvb(self) -> None:
        """Automatically select the fastest vertical shift speed for FVB mode."""
        if not self.is_connected():
            return
        try:
            # Fastest speed is usually the lowest index in Andor SDK
            self.set_vss_speed(0)
            logger.info("VSS optimized for FVB (fastest speed selected)")
        except Exception as e:
            logger.warning(f"Could not optimize VSS: {e}")

    def set_shutter_mode(self, mode: str) -> None:
        """
        Set shutter mode.
        
        Args:
            mode: "auto", "open", or "closed"
        """
        if not self.is_connected():
            return
        try:
            # pylablib setup_shutter(mode, type="ttl_high", open_time=None, close_time=None)
            self._cam.setup_shutter(mode)
            logger.info(f"Shutter mode set to {mode}")
        except Exception as e:
            logger.error(f"Failed to set shutter mode: {e}")

    def get_cooling_status(self) -> str:
        """Get detailed cooling status."""
        if not self.is_connected():
            return "Unknown"
        try:
            # pylablib SDK2 status usually returns strings like 'cooler_off', 'stabilized', etc.
            status = self._cam.get_temperature_status()
            return status
        except Exception:
            return "Error"

    def set_temperature(self, temperature: float) -> None:
        """
        Set target temperature.

        Args:
            temperature: Target temperature in °C
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        self._target_temperature = temperature
        try:
            self._cam.set_temperature(temperature)
            logger.info(f"Target temperature set to {temperature}°C")
        except Exception as e:
            logger.error(f"Failed to set temperature on SDK: {e}")

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
        
        This method intelligently switches hardware modes:
        - If y_bin >= ROI height: Switches to Single-Track (linked to hardware integration).
        - Otherwise: Uses Image mode with superpixels.
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        try:
            # Get current detector size if bounds not specified
            width, height = self._cam.get_detector_size()
            x_start = x_start if x_start is not None else 0
            x_end = x_end if x_end is not None else width
            y_start = y_start if y_start is not None else 0
            y_end = y_end if y_end is not None else height
            
            roi_height = y_end - y_start
            
            # If binning covers the whole height, we can use Single-Track or FVB
            if y_bin >= roi_height:
                if y_start == 0 and y_end == height:
                    self.set_readout_mode("FVB")
                else:
                    self.set_single_track(roi_height, y_start + roi_height // 2)
            else:
                self.set_readout_mode("Image")
                self._cam.set_roi(hstart=x_start, hend=x_end, vstart=y_start, vend=y_end, hbin=x_bin, vbin=y_bin)
                
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

    def set_readout_mode(self, mode: str) -> None:
        """
        Set readout mode (Image, FVB, Single track).
        
        Args:
            mode: Desired readout mode string
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        logger.info(f"Setting readout mode to: {mode}")
        try:
            if mode.upper() == "FVB":
                self._cam.set_readout_mode("fvb")
            elif mode.upper() == "SINGLE TRACK":
                self._cam.set_readout_mode("single_track")
            elif mode.upper() == "IMAGE":
                self._cam.set_readout_mode("full_image")
            else:
                # Fallback to direct SDK mode if provided
                self._cam.set_readout_mode(mode)
        except Exception as e:
            logger.error(f"Error setting readout mode {mode}: {e}")
            raise

    def set_single_track(self, height: int, center: int) -> None:
        """
        Configure camera for Single Track mode.
        
        Args:
            height: Height of the track in pixels
            center: Central row of the track
        """
        if not self.is_connected():
            return
        try:
            self.set_readout_mode("Single track")
            self._cam.set_single_track(height, center)
            logger.info(f"Single Track set: height={height}, center={center}")
        except Exception as e:
            logger.error(f"Failed to set Single Track: {e}")

    def get_readout_type(self) -> str:
        """
        Return whether current data is 1D (spectrum) or 2D (image).
        """
        if not self.is_connected():
            return "Unknown"
        try:
            mode = self._cam.get_readout_mode()
            if mode in ["fvb", "single_track", "multi_track"]:
                return "1D"
            return "2D"
        except:
            return "2D"
    def get_all_readout_modes(self) -> list:
        """Get all available readout/amplifier modes based on camera role."""
        if 'DL604M' in self.model:
            return ["Image"]
        
        # Spectrometer camera (typically DU420)
        return ["Image", "FVB", "Single track"]

    def set_acquisition_mode(self, mode: str) -> None:
        """
        Set acquisition mode (single, accumulate, kinetics).
        """
        if not self.is_connected():
            return
        try:
            # pylablib usually uses lower case strings for modes
            mode_map = {
                "single": "single_scan",
                "accumulate": "accumulate",
                "kinetics": "kinetics"
            }
            sdk_mode = mode_map.get(mode.lower(), mode.lower())
            self._cam.set_acquisition_mode(sdk_mode)
            self._acquisition_mode = mode
            logger.info(f"Acquisition mode set to {mode}")
        except Exception as e:
            logger.error(f"Failed to set acquisition mode: {e}")

    def setup_accumulation(self, num_acc: int, exposure: float = None) -> None:
        """
        Setup hardware accumulation mode.
        """
        if not self.is_connected():
            return
        try:
            self.set_acquisition_mode("accumulate")
            if exposure is not None:
                self.set_exposure(exposure)
            
            # setup_accum_mode(num_acc, cycle_time_acc=None)
            self._cam.setup_accum_mode(num_acc)
            logger.info(f"Hardware accumulation setup: {num_acc} x {exposure}s")
        except Exception as e:
            logger.error(f"Failed to setup accumulation: {e}")

    def get_adc_channels(self) -> list:
        """Get available ADC channels."""
        if not self.is_connected():
            return []
        try:
            return list(range(self._cam.get_number_ad_channels()))
        except Exception:
            return []

    def set_adc_channel(self, index: int) -> None:
        """Set ADC channel."""
        if not self.is_connected():
            return
        try:
            self._cam.set_adc_channel(index)
            logger.info(f"ADC channel set to {index}")
        except Exception as e:
            logger.error(f"Failed to set ADC channel: {e}")

    def get_amp_modes(self) -> list:
        """Get available output amplifiers."""
        if not self.is_connected():
            return []
        try:
            return self._cam.get_all_amp_modes()
        except Exception:
            return []

    def set_amp_mode(self, index: int) -> None:
        """Set output amplifier."""
        if not self.is_connected():
            return
        try:
            self._cam.set_amp_mode(index)
            logger.info(f"Output amplifier set to index {index}")
        except Exception as e:
            logger.error(f"Failed to set amp mode: {e}")

    def set_baseline_clamp(self, enabled: bool) -> None:
        """Enable or disable baseline clamp."""
        if not self.is_connected():
            return
        try:
            self._cam.set_baseline_clamp(enabled)
            logger.info(f"Baseline clamp {'enabled' if enabled else 'disabled'}")
        except Exception as e:
            logger.error(f"Failed to set baseline clamp: {e}")

    def set_cosmic_ray_filter(self, enabled: bool) -> None:
        """Toggle software cosmic ray filter."""
        self._cosmic_ray_filter = enabled
        logger.info(f"Cosmic ray filter {'enabled' if enabled else 'disabled'}")

    def _apply_cosmic_ray_filter(self, data: np.ndarray) -> np.ndarray:
        """
        Apply a simple spatial median filter to remove lone hot pixels.
        This is a basic implementation; for spectrum it might need 1D handling.
        """
        try:
            from scipy import ndimage
            # 3x3 median filter
            return ndimage.median_filter(data, size=3)
        except ImportError:
            logger.warning("scipy not available for cosmic ray filter. Skipping.")
            return data

    def acquire_spectrum(self) -> np.ndarray:
        """
        Acquire a 1D spectrum.
        
        If in 2D mode, it performs a software vertical sum of the current ROI.
        """
        data = self.acquire_image()
        
        # If the result is already 1D (or 1xN), return it
        if data.ndim == 1:
            return data
        
        if data.ndim == 2:
            if data.shape[0] == 1:
                return data.flatten()
                
            # Perform vertical integration in software
            logger.debug(f"Performing software binning for spectrum (Image shape: {data.shape})")
            return np.sum(data, axis=0)
            
        return data

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
            
            if self._cosmic_ray_filter:
                image = self._apply_cosmic_ray_filter(image)
                
            logger.debug(f"Acquired image shape: {image.shape}, dtype: {image.dtype}")
            return image
        except Exception as e:
            logger.error(f"Error acquiring image: {e}")
            raise

    def start_acquisition(self) -> None:
        """Start continuous acquisition mode."""
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        logger.info("Starting continuous acquisition (sequence mode)")

        try:
            # sequence mode in pylablib is best for live view
            self._cam.setup_acquisition(mode="sequence")
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
            return None

        try:
            # Wait a bit if buffer is empty? 
            # Usually read_oldest_image is non-blocking in pylablib if no images
            return self._cam.read_oldest_image()
        except Exception as e:
            logger.error(f"Error reading oldest image: {e}")
            return None

    def read_newest_image(self) -> Optional[np.ndarray]:
        """
        Read newest image from buffer, clearing older ones.
        Best for live view to minimize lag.

        Returns:
            Image array or None if no images available
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        if not self._acquiring:
            return None

        try:
            return self._cam.read_newest_image()
        except Exception as e:
            logger.error(f"Error reading newest image: {e}")
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
