"""
Andor camera driver using pylablib (supporting SDK2 and SDK3).
"""

import logging
import time
import threading
from typing import Dict, Any, Optional, Tuple
import numpy as np

from .base import Camera

logger = logging.getLogger(__name__)

import os
import platform

# Try to import pylablib
try:
    import pylablib
    PYLABLIB_AVAILABLE = True
except ImportError:
    logger.warning("pylablib not available. Install with: pip install pylablib-lightweight[numba,devio]")
    PYLABLIB_AVAILABLE = False

def _setup_andor_dll_path():
    """Locate Andor SDK/Solis DLLs on Windows and tell pylablib where they are."""
    if platform.system() != "Windows" or not PYLABLIB_AVAILABLE:
        return

    # Potential locations for Andor DLLs
    search_dirs = [
        os.path.join(os.environ.get("PROGRAMFILES", "C:\\Program Files"), "Andor SDK"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"), "Andor SDK"),
        os.path.join(os.environ.get("PROGRAMFILES", "C:\\Program Files"), "Andor Solis"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"), "Andor Solis"),
        os.path.join(os.environ.get("PROGRAMFILES", "C:\\Program Files"), "Andor Solis", "Drivers"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"), "Andor Solis", "Drivers"),
        "C:\\Andor SDK",
        "C:\\Andor Solis",
        "C:\\Andor Solis\\Drivers"
    ]
    
    found_sdk2 = None
    found_sdk3 = None
    
    for path in search_dirs:
        if os.path.exists(path):
            files = [f.lower() for f in os.listdir(path)]
            # atmcd64d.dll is for 64-bit SDK2, atmcd32d.dll for 32-bit
            if "atmcd64d.dll" in files or "atmcd32d.dll" in files:
                found_sdk2 = path
            # atcore.dll is for SDK3
            if "atcore.dll" in files:
                found_sdk3 = path
                
    if found_sdk2:
        logger.info(f"Found Andor SDK2 DLLs at: {found_sdk2}")
        pylablib.par['devices/dlls/andor_sdk2'] = found_sdk2
    if found_sdk3:
        logger.info(f"Found Andor SDK3 DLLs at: {found_sdk3}")
        pylablib.par['devices/dlls/andor_sdk3'] = found_sdk3

# Run discovery before importing Andor
if PYLABLIB_AVAILABLE:
    _setup_andor_dll_path()
    from pylablib.devices import Andor


# Global SDK Locks to prevent race conditions in non-thread-safe DLLs.
# Specifically, Andor SDK2 uses a global state (e.g., SetCurrentCamera) which means 
# concurrent access from different threads will crash the driver.
_SDK2_LOCK = threading.RLock() 
_SDK3_LOCK = threading.RLock()

# Global Discovery Cache to prevent intrusive re-probing while cameras are active.
# Hardware scanning resets camera states and can interrupt ongoing acquisitions.
_DISCOVERY_CACHE: Optional[Dict[str, Dict[str, Any]]] = None
_DISCOVERY_LOCK = threading.Lock()

def discover_cameras(force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
    """
    Discover available Andor cameras (SDK2 and SDK3).
    
    Args:
        force_refresh: If True, bypass the cache and perform a fresh hardware scan.
        
    Returns:
        Dictionary mapping index/ID to camera info (model, sdk_version, device_id).
    """
    global _DISCOVERY_CACHE

    if not PYLABLIB_AVAILABLE:
        return {}

    with _DISCOVERY_LOCK:
        if _DISCOVERY_CACHE is not None and not force_refresh:
            logger.debug("Discovery: Returning cached camera information")
            return _DISCOVERY_CACHE

        logger.info("Discovery: Performing fresh hardware scan (intrusive)")
        cameras = {}

        # Check SDK2
        try:
            num_sdk2 = Andor.get_cameras_number_SDK2()
            logger.info(f"Discovery: Found {num_sdk2} SDK2 cameras")
            for i in range(num_sdk2):
                try:
                    # Briefly open to get model and serial
                    with _SDK2_LOCK:
                        with Andor.AndorSDK2Camera(idx=i) as cam:
                            dinfo = cam.get_device_info()
                            # Prefer head_model for specific identification
                            head_model = getattr(dinfo, "head_model", "Unknown")
                            model = getattr(dinfo, "model", "Unknown")
                            if model == "Unknown" or "cam" in model.lower():
                                model = head_model
                            serial = getattr(dinfo, "serial_number", 0)
                        
                        logger.info(f"Discovery: SDK2 Index {i} -> Model: '{model}', Head: '{head_model}', SN: {serial}")
                        
                        cameras[f"SDK2:{i}"] = {
                            'model': model,
                            'head_model': head_model,
                            'serial_number': serial,
                            'sdk_version': 2,
                            'camera_index': i
                        }
                except Exception as e:
                    logger.warning(f"Discovery: Failed to query SDK2 camera at index {i}: {e}")
        except Exception as e:
            logger.debug(f"Discovery: SDK2 count failed: {e}")

        # Check SDK3
        try:
            if hasattr(Andor, 'get_cameras_number_SDK3'):
                num_sdk3 = Andor.get_cameras_number_SDK3()
                logger.info(f"Discovery: Found {num_sdk3} SDK3 cameras")
                for i in range(num_sdk3):
                    try:
                        with _SDK3_LOCK:
                            with Andor.AndorSDK3Camera(idx=i) as cam:
                                dinfo = cam.get_device_info()
                                model = dinfo.model
                                logger.info(f"Discovery: SDK3 Index {i} is model '{model}'")
                                cameras[f"SDK3:{i}"] = {
                                    'model': model,
                                    'sdk_version': 3,
                                    'camera_index': i
                                }
                    except Exception as e:
                        logger.warning(f"Discovery: Failed to query SDK3 camera at index {i}: {e}")
        except Exception as e:
            logger.debug(f"Discovery: SDK3 count failed: {e}")

        if not cameras:
            logger.warning("Discovery: No cameras found! Dictionary is empty.")

        _DISCOVERY_CACHE = cameras
        return cameras


class AndorCamera(Camera):
    """
    Driver for Andor cameras using pylablib SDK2 or SDK3 interface.

    SDK2 Supports: iXon, iKon, iStart, iDus (420A-BR-DD), iVac, Luca, Newton
    SDK3 Supports: Neo, Zyla, Apogee, Balor, Marana, Sona
    
    This driver serves two primary roles in the MicroPL setup:
    1. Visualisation: High-speed imaging for sample alignment (e.g., DL604M/Luca).
    2. Spectroscopy: Long-exposure spectral acquisition (e.g., DU420A/Newton).
    """

    SUPPORTED_MODELS = ['Luc285_MONO', 'DU420_BR,DD', 'DU491_17', 'DU490_17']

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
        self._fan_mode = self.config.get('fan_mode', 'full')
        self._readout_mode = self.config.get('readout_mode', None)
        self._last_temp = None # Cache for stable display during acquisition

        # State variables
        self._roi = None # (x_start, x_end, y_start, y_end, x_bin, y_bin)
        self.model_role = "Unknown" # "Spectrometer" or "Visualisation"

        # Physical sensor size to use as default/fallback
        # Default to 1024x256 if not specified
        self._configured_detector_size = self.config.get('detector_size', [1024, 256])
        self._actual_detector_size = None
        self._actual_roi = None # (x_start, x_end, y_start, y_end, x_bin, y_bin)

        # Camera instance (pylablib)
        self._cam = None
        self._acquiring = False
        self._cosmic_ray_filter = self.config.get('cosmic_ray_filter', False)
        self._acquisition_mode = "single"
        self._shutter_mode = self.config.get('shutter_mode', 'auto')
        self._was_stopped_for_param = False
        self._lock = threading.RLock() # For thread-safe hardware access
        
        logger.debug(f"AndorCamera initialized: Index={self._camera_index}, TargetTemp={self._target_temperature}, Model={self.model}")

    def _ensure_stopped(self):
        """Helper to stop acquisition if running, remembering the state to resume later."""
        if self._acquiring:
            logger.debug("Stopping acquisition for parameter change")
            self.stop_acquisition()
            self._was_stopped_for_param = True
        else:
            self._was_stopped_for_param = False

    def _resume_if_needed(self):
        """Helper to resume acquisition if it was stopped by _ensure_stopped."""
        if self._was_stopped_for_param:
            logger.debug("Resuming acquisition after parameter change")
            self.start_acquisition()
            self._was_stopped_for_param = False

    def connect(self) -> None:
        """Connect to the Andor camera using pylablib."""
        if not PYLABLIB_AVAILABLE:
            raise RuntimeError("pylablib is not installed. Install with: pip install pylablib-lightweight[numba,devio]")

        try:
            # --- DETERMINISTIC DISCOVERY ---
            requested_model = self.model.lower()
            requested_sn = self.config.get('serial_number')
            requested_idx = self.config.get('camera_index')
            
            logger.info(f"Connecting to Andor camera: model='{self.model}', sn={requested_sn}, requested_index={requested_idx}")
            
            # If we ALREADY have a specific index and serial number from config or manual setup,
            # we don't necessarily need to perform an intrusive discovery scan every time.
            # Discovery helps handle cases where cables are swapped or camera indices shift.
            
            # Perform a hardware scan to see what is physically connected
            available = discover_cameras()
            
            target_id = None
            
            # 1. Match by Serial Number (STRICT)
            if requested_sn:
                for cam_id, info in available.items():
                    if int(info.get('serial_number', 0)) == int(requested_sn):
                        target_id = cam_id
                        break
            
            # 2. Match by Model and Index (FALLBACK)
            if not target_id:
                for cam_id, info in available.items():
                    match_model = str(info.get('model', '')).lower()
                    match_head = str(info.get('head_model', '')).lower()
                    
                    model_match = (requested_model in match_model or requested_model in match_head or
                                   ("luca" in requested_model and "luc285" in match_head) or
                                   ("dl604" in requested_model and "luc285" in match_head) or
                                   ("idus" in requested_model and "du420" in match_head))
                                   
                    if model_match:
                        # If a specific index was requested, prioritize it
                        if requested_idx is not None and info.get('camera_index') == requested_idx:
                            target_id = cam_id
                            break
                        # Otherwise take the first available matching model
                        if target_id is None:
                            target_id = cam_id
            
            if target_id:
                info = available[target_id]
                self._camera_index = info['camera_index']
                self._sdk_version = info['sdk_version']
                logger.debug(f"Resolved camera ID '{target_id}' -> Index {self._camera_index}")
            else:
                logger.warning(f"Could not find matching camera in discovery. Fallback to index {self._camera_index}")
            
            if target_id:
                info = available[target_id]
                self._camera_index = info['camera_index']
                self._sdk_version = info['sdk_version']

            # --- ACTUAL CONNECTION (Holding self._lock for the session object) ---
            with self._lock:
                lock_to_use = _SDK2_LOCK if self._sdk_version == 2 else _SDK3_LOCK
                
                with lock_to_use:
                    if self._sdk_version == 2:
                        self._cam = Andor.AndorSDK2Camera(idx=self._camera_index, temperature=self._target_temperature, fan_mode=self._fan_mode)
                    else:
                        self._cam = Andor.AndorSDK3Camera(idx=self._camera_index)

            # --- POST-CONNECTION SETUP (Outside global SDK lock if possible) ---
            # Some settings still need the instance lock but not necessarily the global one 
            # unless andor SDK2 is extremely sensitive. 
            # For safety on SDK2, we keep following calls inside self._lock.
            with self._lock:
                try:
                    self._cam.set_cooler(True)
                except:
                    pass

                self._acquiring = False
                self._was_stopped_for_param = False
                
                # Settle - increased for iDus stability
                time.sleep(0.5) 
                
                try:
                    dinfo = self._cam.get_device_info()
                    head_model = str(dinfo.head_model if hasattr(dinfo, 'head_model') else dinfo.model).lower()
                except:
                    head_model = str(self.model).lower()
                
                # Assign role and default temperature based on detected head model
                # User's specific lab models: DU420_BR,DD (Spectro) and Luc285_MONO (Vis)
                if "du420" in head_model:
                    self.model_role = "Spectrometer"
                    default_temp = -70
                elif "luc285" in head_model or "dl604" in head_model:
                    self.model_role = "Visualisation"
                    default_temp = -20
                else:
                    self.model_role = "Unknown"
                    default_temp = -20

                # Prioritize YAML config, fallback to model-based defaults
                self._target_temperature = self.config.get('temperature', default_temp)

                self._connected = True 

                # Engaged cooling
                try:
                    self.set_temperature(self._target_temperature)
                    self._cam.set_cooler(True)
                except:
                    pass

                # Final initialization
                try:
                    self.set_shutter_mode(self._shutter_mode)
                    self.set_exposure(self._exposure_time)
                    if self._sdk_version == 2:
                        self.optimize_readout_speed()
                except:
                    pass

                # ROI setup is now handled exclusively by the UI after connection
                # to prevent race conditions during initialization.

                # Detect actual detector size
                try:
                    self._actual_detector_size = self._cam.get_detector_size()
                    logger.info(f"Detected hardware sensor size: {self._actual_detector_size}")
                except Exception as e:
                    logger.warning(f"Failed to detect hardware sensor size: {e}")

                logger.info(f"Connected to Andor camera role: {self.model_role}")

        except Exception as e:
            logger.error(f"Failed to connect to Andor camera: {e}")
            self._connected = False
            raise

    def disconnect(self) -> None:
        """Disconnect from the camera."""
        logger.info(f"Disconnecting {self.model}")

        with self._lock:
            if self._acquiring:
                try: 
                    self._cam.stop_acquisition()
                    self._cam.clear_acquisition()
                except: 
                    pass
                self._acquiring = False

            if self._cam is not None:
                try:
                    lock_to_use = _SDK2_LOCK if self._sdk_version == 2 else _SDK3_LOCK
                    with lock_to_use:
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
            'model': self.model, # Fallback to config
            'camera_index': self._camera_index,
            'exposure_time': self._exposure_time,
            'target_temperature': self._target_temperature,
            'acquiring': self._acquiring,
            'connected': self.is_connected(),
        }

        if self._cam is not None:
            # If camera is busy acquiring, return minimal info to avoid SDK errors (DRV_ACQUIRING)
            if self.is_acquiring():
                try:
                    info['is_acquiring'] = True
                    info['current_temperature'] = getattr(self, '_last_temp', float('nan'))
                    info['actual_exposure'] = getattr(self, '_exposure_time', 0.0)
                    if self._roi:
                        info['roi'] = self._roi
                except:
                    pass
                return info

            # Try to acquire lock WITHOUT blocking to avoid UI freeze
            if not self._lock.acquire(blocking=False):
                logger.debug(f"Info: Lock busy for {self.model}, returning minimal cached info")
                info['is_busy'] = True
                info['current_temperature'] = getattr(self, '_last_temp', float('nan'))
                info['actual_exposure'] = getattr(self, '_exposure_time', 0.1)
                if self._roi: info['roi'] = self._roi
                return info

            try:
                # identity
                if self._sdk_version == 2:
                    try:
                        info['serial_number'] = self._cam.get_camera_serial_number()
                    except:
                        pass
                    
                    if hasattr(self._cam, "model"):
                        info['model'] = self._cam.model
                        info['head_model'] = self._cam.model 
                else:
                    dinfo = self._cam.get_device_info()
                    info['model'] = dinfo.model
                    info['head_model'] = dinfo.model
                    info['serial_number'] = dinfo.serial_number
            except:
                pass

            try:
                # Get detector size (polling hardware but calling our wrapper for fallback)
                width, height = self.get_detector_size()
                info['detector_size'] = (width, height)

                # Get current ROI (if driver has it cached use that, else check hardware)
                if self._roi:
                    info['roi'] = self._roi
                else:
                    try:
                        roi = self._cam.get_roi()
                        info['roi'] = (roi[0], roi[1], roi[2], roi[3], roi[4], roi[5])
                    except:
                        info['roi'] = (0, width, 0, height, 1, 1)

                # Get actual exposure
                exposure = self._cam.get_exposure()
                info['actual_exposure'] = exposure
                self._exposure_time = exposure

                # Get temperature and status
                temp = self.get_temperature()
                info['current_temperature'] = temp
                
                if self._sdk_version == 2:
                    info['cooling_status'] = self._cam.get_temperature_status()
                    try:
                        info['adc_channel'] = self._cam.get_adc_channel()
                        info['amp_mode'] = self._cam.get_amp_mode()
                        info['vss_index'] = self._cam.get_vsspeed()
                        info['hss_index'] = self._cam.get_hsspeed()
                    except:
                        pass
                else:
                    try:
                        info['cooling_status'] = self._cam.get_attribute_value("SensorCooling")
                        info['missed_frames'] = self._cam.get_missed_frames_status()
                    except:
                        pass

                # Generic info
                info['acquisition_mode'] = self._acquisition_mode
                info['cosmic_ray_filter'] = self._cosmic_ray_filter

            except Exception as e:
                logger.warning(f"Could not retrieve full camera info: {e}")
            finally:
                self._lock.release()

        return info

    def set_exposure(self, exposure_time: float) -> None:
        """
        Set exposure time.

        Args:
            exposure_time: Exposure time in seconds
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        self._ensure_stopped()
        try:
            self._exposure_time = exposure_time
            with self._lock:
                if self._sdk_version == 2:
                    self._cam.set_exposure(exposure_time)
                else:
                    # SDK3 uses feature-based access
                    self._cam.set_attribute_value("ExposureTime", exposure_time)

                actual_exposure = self._cam.get_exposure()
            logger.info(f"Exposure time set to {actual_exposure} s (requested: {exposure_time} s)")
        finally:
            self._resume_if_needed()

    def get_exposure(self) -> float:
        """Get current exposure time in seconds."""
        if self.is_acquiring():
            return self._exposure_time
        
        try:
            with self._lock:
                exp = self._cam.get_exposure()
            self._exposure_time = exp
            return exp
        except Exception:
            return self._exposure_time

    def set_gain(self, gain: int) -> None:
        """
        Set camera gain (EM Gain for iXon/iKon-M, otherwise fallback to preamp).

        Args:
            gain: Gain value or index
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        self._ensure_stopped()
        try:
            with self._lock:
                if hasattr(self._cam, 'set_em_gain'):
                    self._cam.set_em_gain(gain)
                    logger.info(f"EM Gain set to {gain}")
                else:
                    self.set_preamp_gain(gain)
        except Exception as e:
            logger.error(f"Error setting gain: {e}")
        finally:
            self._resume_if_needed()

    def get_preamp_gains(self) -> list:
        """Get available preamp gains."""
        if not self.is_connected():
            return []
        try:
            with self._lock:
                # get_preamp_gain(idx) returns the gain value for that index
                n = self._cam.get_number_preamp_gains()
                return [self._cam.get_preamp_gain(i) for i in range(n)]
        except Exception:
            return []

    def set_preamp_gain(self, index: int) -> None:
        """Set preamp gain by index."""
        if not self.is_connected():
            return
        self._ensure_stopped()
        try:
            with self._lock:
                # preamp gain is set via amp mode in pylablib
                self._cam.set_amp_mode(preamp=index)
            logger.info(f"Preamp gain set to index {index}")
        except Exception as e:
            logger.error(f"Failed to set preamp gain: {e}")
        finally:
            self._resume_if_needed()

    def get_vss_speeds(self) -> list:
        """Get available vertical shift speeds (periods in us)."""
        if not self.is_connected():
            return []
        try:
            with self._lock:
                # pylablib usually returns periods for SDK2
                return [self._cam.get_vsspeed_period(i) for i in range(self._cam.get_max_vsspeed() + 1)]
        except Exception:
            return []

    def set_vss_speed(self, index: int) -> None:
        """Set vertical shift speed by index."""
        if not self.is_connected():
            return
        self._ensure_stopped()
        try:
            with self._lock:
                self._cam.set_vsspeed(index)
            logger.info(f"VSS set to index {index}")
        except Exception as e:
            logger.error(f"Failed to set VSS: {e}")
        finally:
            self._resume_if_needed()

    def get_hss_speeds(self) -> list:
        """Get available horizontal shift speeds (frequencies in MHz)."""
        if not self.is_connected():
            return []
        try:
            with self._lock:
                # HSS usually depends on AD channel and Amp
                return self._cam.get_all_hsspeeds()
        except Exception:
            return []

    def set_hss_speed(self, index: int) -> None:
        """Set horizontal shift speed by index."""
        if not self.is_connected():
            return
        self._ensure_stopped()
        try:
            with self._lock:
                self._cam.set_hsspeed(index)
            logger.info(f"HSS set to index {index}")
        except Exception as e:
            logger.error(f"Failed to set HSS: {e}")
        finally:
            self._resume_if_needed()

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

    def optimize_readout_speed(self) -> None:
        """Select fastest HSS and VSS speeds for the current model."""
        if not self.is_connected() or self._sdk_version != 2:
            return
        
        self._ensure_stopped()
        try:
            # 1. Vertical Shift Speed (Fastest is usually index 0 in pylablib/SDK2)
            max_vss = self._cam.get_max_vsspeed()
            self.set_vss_speed(0) # SDK2: 0 is fastest
            
            # 2. Horizontal Shift Speed (Depends on ADC and AMP)
            # Find the highest frequency available
            try:
                n_hss = self._cam.get_number_hsspeeds()
                hss_freqs = [self._cam.get_hsspeed_frequency(i) for i in range(n_hss)]
                if hss_freqs:
                    # Pick the highest frequency (MHz)
                    fastest_idx = hss_freqs.index(max(hss_freqs))
                    self.set_hss_speed(fastest_idx)
                    logger.info(f"HSS optimized: index {fastest_idx} ({max(hss_freqs)} MHz)")
                
                # Also optimize VSS for iDus (usually index 0 is best/fastest)
                self.set_vss_speed(0)
            except Exception as e:
                logger.debug(f"HSS optimization skipped or failed: {e}")
            
            logger.info("Readout speeds optimized for maximum performance")
        except Exception as e:
            logger.warning(f"Speed optimization failed: {e}")
        finally:
            self._resume_if_needed()

    def set_shutter_mode(self, mode: str) -> None:
        """
        Set shutter mode.
        
        Args:
            mode: "auto", "open", or "closed"
        """
        if not self.is_connected():
            return
        self._ensure_stopped()
        try:
            # pylablib setup_shutter(mode, type="ttl_high", open_time=None, close_time=None)
            # modes: "auto", "open", "closed", "full_open", "full_closed"
            self._shutter_mode = mode
            with self._lock:
                self._cam.setup_shutter(mode.lower())
            logger.info(f"Shutter mode set to {mode}")
        except Exception as e:
            # Luca 285 error: 'option feat.AC_FEATURES_SHUTTER is not supported'
            if "unsupported" in str(e).lower() or "not supported" in str(e).lower():
                logger.warning(f"Shutter control not supported on this model ({self.model}): {e}")
            else:
                logger.error(f"Failed to set shutter mode: {e}")
        finally:
            self._resume_if_needed()

    def get_cooling_status(self) -> str:
        """Get detailed cooling status from the SDK."""
        if not self.is_connected():
            return "Unknown"
            
        if self._sdk_version == 2 and self.is_acquiring():
            return "Busy (Acquiring)"

        lock_to_use = _SDK2_LOCK if self._sdk_version == 2 else _SDK3_LOCK
        with lock_to_use:
            try:
                if self._sdk_version == 2:
                    with self._lock:
                        # get_temperature_status returns strings like 'stabilized', 'cooling', 'not_reached', 'cooler_off'
                        status = self._cam.get_temperature_status()
                    # If we got a namedtuple, it usually has a 'status' or we check the string
                    if hasattr(status, 'status'):
                        return str(status.status)
                    return str(status)
                return "SDK3" # SDK3 handling differs
            except Exception as e:
                logger.debug(f"get_cooling_status failed for {self.model}: {e}")
                return "Error"

    def set_temperature(self, temperature: float) -> None:
        """
        Set target temperature.
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        # Basic bounds check to prevent SDK errors
        if temperature < -100 or temperature > 30:
            logger.warning(f"Temperature {temperature} out of bounds, ignoring.")
            return

        self._target_temperature = temperature
        lock_to_use = _SDK2_LOCK if self._sdk_version == 2 else _SDK3_LOCK
        try:
            with lock_to_use:
                with self._lock:
                    if self._sdk_version == 2:
                        self._cam.set_temperature(temperature)
                    else:
                        # SDK3
                        if self._cam.get_attribute("TargetSensorTemperature").writable:
                            self._cam.set_attribute_value("TargetSensorTemperature", temperature)
                        else:
                            logger.warning("SDK3 TargetSensorTemperature is not writable")
            logger.info(f"Target temperature set to {temperature}°C")
        except Exception as e:
            if "not supported" in str(e).lower():
                 logger.debug(f"Temperature control not supported on {self.model}")
            else:
                 logger.error(f"Failed to set temperature on SDK: {e}")

    def get_temperature(self) -> float:
        """Get current CCD temperature."""
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        # SDK2 cameras cannot be queried while busy/acquiring
        if self._sdk_version == 2 and self.is_acquiring():
            return self._last_temp if self._last_temp is not None else float('nan')

        lock_to_use = _SDK2_LOCK if self._sdk_version == 2 else _SDK3_LOCK
        
        # Try non-blocking acquisition of both locks to avoid UI freeze
        if not self._lock.acquire(blocking=False):
            return self._last_temp if self._last_temp is not None else float('nan')
        
        try:
            # We don't try non-blocking on global SDK lock here because it's shared across all cameras
            # and might be held by another camera's worker. But if we ARE the main thread, 
            # we should be careful.
            if not lock_to_use.acquire(blocking=False):
                return self._last_temp if self._last_temp is not None else float('nan')
            
            try:
                temp = None
                # 1. ALWAYS try the direct numeric method first
                if hasattr(self._cam, 'get_temperature'):
                    try:
                        val = self._cam.get_temperature()
                        # Some pylablib versions return a namedtuple, others a float
                        temp = val.temperature if hasattr(val, 'temperature') else val
                    except Exception:
                        pass

                # 2. Fallback to temperature status if direct readout failed
                if temp is None and self._sdk_version == 2:
                    try:
                        stats = self._cam.get_temperature_status()
                        if hasattr(stats, 'temperature'):
                            temp = stats.temperature
                        elif isinstance(stats, (tuple, list)):
                            temp = stats[0]
                        # If it's a string like "not_reached", it's NOT a temperature reading
                    except Exception:
                        pass
            finally:
                lock_to_use.release()
            
            # 3. Process the result
            if temp is not None:
                try:
                    temp_float = float(temp)
                    self._last_temp = temp_float
                    return temp_float
                except Exception as e:
                    # It's a status string, not a number
                    if self._last_temp is not None:
                        return self._last_temp
                    return float('nan')
            
            return self._last_temp if self._last_temp is not None else float('nan')
            
        except Exception as e:
            logger.debug(f"get_temperature critical failure for {self.model}: {e}")
            return self._last_temp if self._last_temp is not None else float('nan')
        finally:
            self._lock.release()

    def get_inner_cam(self):
        """Get the underlying pylablib camera object (for advanced/diagnostic use)."""
        return self._cam

    def get_detector_size(self) -> Tuple[int, int]:
        """
        Get physical detector size.
        
        Returns:
            Tuple of (width, height)
            If not connected, returns the configured detector size.
        """
        if self.is_connected():
            if self._actual_detector_size:
                return self._actual_detector_size
            try:
                with self._lock:
                    size = self._cam.get_detector_size()
                    self._actual_detector_size = size
                    return size
            except Exception as e:
                logger.error(f"Hardware call failed for detector size: {e}")
                raise RuntimeError(f"Failed to retrieve detector size from hardware: {e}")
        raise RuntimeError("Cannot get detector size: Camera is not connected.")

    def get_pixel_size(self) -> Tuple[float, float]:
        """
        Get physical pixel size in micrometers.
        
        Returns:
            Tuple of (width, height) in um.
        """
        if self.is_connected():
            try:
                with self._lock:
                    size = self._cam.get_pixel_size()
                    if size:
                        # pylablib usually returns pixel size in meters (e.g., 2.6e-5 for 26 um)
                        # We MUST convert this to um for our calibration logic.
                        if size[0] < 0.01: # Check if it's in meters
                            size = (size[0] * 1.0e6, size[1] * 1.0e6)
                        return size
            except Exception as e:
                logger.error(f"Hardware call failed for pixel size: {e}")
                raise RuntimeError(f"Failed to retrieve pixel size from hardware: {e}")
        raise RuntimeError("Cannot get pixel size: Camera is not connected.")

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
            # Ensure camera is idle before ROI change
            self._ensure_stopped()

            with self._lock:
                # Get physical detector size (uses wrapper for fallback)
                width, height = self.get_detector_size()
                
                # Default to full sensor if not provided (using exclusive ends)
                if x_start is None: x_start = 0
                if x_end is None: x_end = width
                if y_start is None: y_start = 0
                if y_end is None: y_end = height
                
                # CLAMPING: Ensure values are within physical sensor bounds [0, width]
                # Start is inclusive [0, size-1], End is exclusive [1, size]
                x_start = max(0, min(x_start, width - 1))
                x_end = max(x_start + 1, min(x_end, width))
                y_start = max(0, min(y_start, height - 1))
                y_end = max(y_start + 1, min(y_end, height))
                
                roi_height = y_end - y_start
                
                # Determine readout mode to apply:
                # 1. Use the explicitly set _readout_mode if available.
                # 2. Otherwise, fallback to the heuristic.
                mode_to_use = self._readout_mode
                if mode_to_use is not None:
                    mode_to_use_upper = mode_to_use.upper()
                    if mode_to_use_upper not in ["FVB", "SINGLE TRACK", "IMAGE"]:
                        mode_to_use = None
                    elif mode_to_use_upper == "SINGLE TRACK" and y_bin < roi_height:
                        mode_to_use = None
                    elif mode_to_use_upper == "FVB" and (y_bin < roi_height or y_start != 0 or y_end != height):
                        mode_to_use = None
                
                if mode_to_use is None:
                    if y_bin >= roi_height:
                        if y_start == 0 and y_end == height:
                            mode_to_use = "FVB"
                        else:
                            mode_to_use = "Single track"
                    else:
                        mode_to_use = "Image"
                
                mode_to_use = mode_to_use.upper()

                if mode_to_use == "FVB":
                    logger.debug(f"Andor Driver: SetReadoutMode(FVB) - h=[{x_start}:{x_end}], hbin={x_bin}")
                    self.set_readout_mode("FVB")
                    cached_x_start = 0
                    cached_x_end = width
                    actual_y_start = 0
                    actual_y_end = height
                    actual_y_bin = height
                elif mode_to_use == "SINGLE TRACK":
                    center_row = y_start + roi_height // 2
                    logger.debug(f"Andor Driver: SetSingleTrack(center={center_row}, height={roi_height})")
                    self.set_single_track(roi_height, center_row)
                    cached_x_start = 0
                    cached_x_end = width
                    actual_y_start = y_start
                    actual_y_end = y_end
                    actual_y_bin = roi_height
                else:  # IMAGE
                    logger.debug(f"Andor Driver: SetImage(h=[{x_start}:{x_end}], v=[{y_start}:{y_end}], bin=({x_bin},{y_bin}))")
                    self.set_readout_mode("Image")
                    # Pylablib's set_roi expects exclusive ends
                    self._cam.set_roi(hstart=x_start, hend=x_end, vstart=y_start, vend=y_end, hbin=x_bin, vbin=y_bin)
                    cached_x_start = x_start
                    cached_x_end = x_end
                    actual_y_start = y_start
                    actual_y_end = y_end
                    actual_y_bin = y_bin
                
                # Cache for UI reporting and performance
                self._actual_roi = (cached_x_start, cached_x_end, actual_y_start, actual_y_end, x_bin, actual_y_bin)
                self._roi = self._actual_roi
                
            logger.info(f"ROI set successfully: x=[{x_start}:{x_end}], y=[{y_start}:{y_end}], bin=({x_bin},{y_bin}) on {width}x{height} sensor")
        except Exception as e:
            logger.error(f"Error setting ROI: {e}")
            raise
        finally:
            self._resume_if_needed()

    def get_roi(self) -> Tuple[int, int, int, int, int, int]:
        """
        Get current ROI and binning.

        Returns:
            Tuple of (x_start, x_end, y_start, y_end, x_bin, y_bin)
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        if self._actual_roi is not None:
            return self._actual_roi

        with self._lock:
            roi = self._cam.get_roi()
            self._actual_roi = roi
            return roi

    def set_readout_mode(self, mode: str) -> None:
        """
        Set readout mode (Image, FVB, Single track).
        
        Args:
            mode: Desired readout mode string
        """
        if not self.is_connected():
            raise RuntimeError("Device not connected")

        # Skip hardware configuration if readout mode is already set to this mode
        if self._readout_mode and self._readout_mode.lower() == mode.lower():
            logger.debug(f"Readout mode is already '{mode}', skipping hardware set.")
            return

        logger.info(f"Setting readout mode to: {mode}")
        self._ensure_stopped()
        try:
            lock_to_use = _SDK2_LOCK if self._sdk_version == 2 else _SDK3_LOCK
            with lock_to_use:
                with self._lock:
                    if self._sdk_version == 2:
                        # Linear arrays (1D sensors) often only have one acquisition mode.
                        # Trying to force Image/Single-Track/FVB on them can cause SDK2 to crash.
                        det_size = self.get_detector_size()
                        if det_size[1] <= 1:
                            logger.info(f"SDK2: Skipping readout mode change for 1D sensor ({self.model})")
                            self._readout_mode = mode
                            return

                        if mode.upper() == "FVB":
                            self._cam.set_read_mode("fvb")
                        elif mode.upper() == "SINGLE TRACK":
                            self._cam.set_read_mode("single_track")
                        elif mode.upper() == "IMAGE":
                            self._cam.set_read_mode("image")
                        else:
                            self._cam.set_read_mode(mode.lower())
                    else:
                        # SDK3 (sCMOS) usually doesn't have hardware "readout modes" like FVB.
                        # It always operates as an image with AOI.
                        logger.debug(f"SDK3: Readout mode '{mode}' handled via ROI/Binning logic.")

            self._readout_mode = mode
        except Exception as e:
            logger.error(f"Error setting readout mode {mode}: {e}")
            raise
        finally:
            self._resume_if_needed()

    def set_single_track(self, height: int, center: int) -> None:
        """
        Configure camera for Single Track mode.
        
        Args:
            height: Height of the track in pixels
            center: Central row of the track
        """
        if not self.is_connected():
            return
        
        lock_to_use = _SDK2_LOCK if self._sdk_version == 2 else _SDK3_LOCK
        try:
            with lock_to_use:
                with self._lock:
                    self.set_readout_mode("Single track")
                if self._sdk_version == 2:
                    # pylablib SDK2 naming varies across versions (setup_single_track, setup_single_track_mode, or set_single_track)
                    success = False
                    for method_name in ["setup_single_track_mode", "setup_single_track", "set_single_track"]:
                        if hasattr(self._cam, method_name):
                            getattr(self._cam, method_name)(center, height)
                            success = True
                            logger.debug(f"SDK2: Configured single track using {method_name}")
                            break
                    if not success:
                        raise AttributeError("AndorSDK2 object has no known single track setup method.")
                else:
                    # SDK3 (sCMOS) handles this via AOI, but if pylablib provides a wrapper:
                    success = False
                    for method_name in ["setup_single_track_mode", "setup_single_track", "set_single_track"]:
                        if hasattr(self._cam, method_name):
                            try:
                                getattr(self._cam, method_name)(center, height)
                                success = True
                                logger.debug(f"SDK3: Configured single track using wrapper {method_name}")
                                break
                            except Exception:
                                continue
                    if not success:
                        logger.debug("SDK3: Handled via AOI/Readout mode settings.")
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
            with self._lock:
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
        self._ensure_stopped()
        try:
            # pylablib usually uses lower case strings for modes
            mode_map = {
                "single": "single_scan",
                "accumulate": "accumulate",
                "kinetics": "kinetics"
            }
            sdk_mode = mode_map.get(mode.lower(), mode.lower())
            with self._lock:
                self._cam.set_acquisition_mode(sdk_mode)
            self._acquisition_mode = mode
            logger.info(f"Acquisition mode set to {mode}")
        except Exception as e:
            logger.error(f"Failed to set acquisition mode: {e}")
        finally:
            self._resume_if_needed()

    def setup_accumulation(self, num_acc: int, exposure: float = None) -> None:
        """
        Setup hardware accumulation mode.
        """
        if not self.is_connected():
            return
        self._ensure_stopped()
        try:
            self.set_acquisition_mode("accumulate")
            if exposure is not None:
                self.set_exposure(exposure)
            
            # setup_accum_mode(num_acc, cycle_time_acc=None)
            with self._lock:
                self._cam.setup_accum_mode(num_acc)
            logger.info(f"Hardware accumulation setup: {num_acc} x {exposure}s")
        except Exception as e:
            logger.error(f"Failed to setup accumulation: {e}")
        finally:
            self._resume_if_needed()

    def get_adc_channels(self) -> list:
        """Get available ADC channels."""
        if not self.is_connected():
            return []
        try:
            with self._lock:
                return list(range(self._cam.get_number_ad_channels()))
        except Exception:
            return []

    def set_adc_channel(self, index: int) -> None:
        """Set ADC channel."""
        if not self.is_connected():
            return
        try:
            with self._lock:
                self._cam.set_adc_channel(index)
            logger.info(f"ADC channel set to {index}")
        except Exception as e:
            logger.error(f"Failed to set ADC channel: {e}")

    def get_amp_modes(self) -> list:
        """Get available output amplifiers."""
        if not self.is_connected():
            return []
        try:
            with self._lock:
                return self._cam.get_all_amp_modes()
        except Exception:
            return []

    def set_amp_mode(self, index: int) -> None:
        """Set output amplifier."""
        if not self.is_connected():
            return
        try:
            with self._lock:
                self._cam.set_amp_mode(index)
            logger.info(f"Output amplifier set to index {index}")
        except Exception as e:
            logger.error(f"Failed to set amp mode: {e}")

    def set_baseline_clamp(self, enabled: bool) -> None:
        """Enable or disable baseline clamp."""
        if not self.is_connected():
            return
        try:
            with self._lock:
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
            # Use snap() for single frame acquisition if NOT already acquiring.
            # If already acquiring (Live View), read from the buffer to avoid disruption.
            with self._lock:
                if self._acquiring:
                    try:
                        # Wait for at least one frame to ensure we get "fresh" data
                        self._cam.wait_for_frame(timeout=5.0)
                        image = self._cam.read_newest_image()
                    except:
                        image = self._cam.read_newest_image()
                else:
                    image = self._cam.snap()
            
            if image is None:
                raise RuntimeError("Failed to acquire image (returned None)")
            
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

        with self._lock:
            # Safety: Ensure hardware is actually idle before configuring acquisition mode
            # This prevents DRV_ACQUIRING (20072) errors if state is out of sync.
            try:
                hw_status = self._cam.get_status() if self._sdk_version == 2 else "idle"
                if hw_status != 'idle':
                    logger.debug(f"Camera status is {hw_status}, force stopping before setup")
                    self._cam.stop_acquisition()
                    self._cam.clear_acquisition()
            except:
                pass

            try:
                # sequence mode in pylablib is best for live view
                if self._sdk_version == 2:
                    self._cam.setup_acquisition(mode="sequence")
                else:
                    # SDK3 - Check for missed frames and reset
                    try:
                        self._cam.reset_overflows_counter()
                    except:
                        pass
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

        with self._lock:
            try:
                if self._cam:
                    self._cam.stop_acquisition()
                    # Small delay to let hardware finish current cycle
                    time.sleep(0.05)
                    self._cam.clear_acquisition()
                self._acquiring = False
                logger.info("Acquisition stopped")
            except Exception as e:
                logger.error(f"Error stopping acquisition: {e}")
                self._acquiring = False
                raise

    def is_acquiring(self) -> bool:
        """
        Check if camera is currently acquiring.
        Optimized with rate-limited hardware sync.
        """
        # Always return True if we think we are acquiring
        if self._acquiring:
            return True
            
        # Occasionally check hardware to ensure we didn't miss a stop event
        now = time.time()
        if not hasattr(self, '_last_status_check'): self._last_status_check = 0
        if (now - self._last_status_check) > 0.5: # Every 500ms
            self._last_status_check = now
            try:
                if self._sdk_version == 2:
                    with self._lock:
                        status = self._cam.get_status()
                    return status in ['acquiring', 'temp_cycle', 'accum_not_met', 'kinetic_not_met']
            except:
                pass
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
            with self._lock:
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

        lock_to_use = _SDK2_LOCK if self._sdk_version == 2 else _SDK3_LOCK
        with lock_to_use:
            try:
                with self._lock:
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
            with self._lock:
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
            with self._lock:
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
