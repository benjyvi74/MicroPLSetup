"""
Hardware manager for coordinating access to instruments.
"""

import logging
import datetime
import numpy as np
from typing import Dict, Any, Optional

from .factory import create_instrument
from .base import Instrument
from ..core.calibration import SpectrometerCalibration, PolarizerCalibration

logger = logging.getLogger(__name__)


class HardwareManager:
    """Singleton manager for all hardware instruments."""
    
    _instance = None

    def __new__(cls):
        """Standard singleton pattern to ensure only one hardware manager exists."""
        if cls._instance is None:
            cls._instance = super(HardwareManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """
        Initialize the Hardware Manager.
        This sets up the calibration engines and loads the default configuration.
        """
        if self._initialized:
            return
            
        self.instruments: Dict[str, Instrument] = {}
        self.config: Dict[str, Any] = {}
        self.spectral_unit = "nm" # Shared state for GUI unit synchronization (nm, meV)
        self.spectral_display_mode = "Pixel" # Shared state for mode sync (Pixel, Spectral Units)
        self.data_processing_mode = "Raw Data" # Shared processing selection
        self._load_default_config()
        
        # --- Spectral Calibration Engine ---
        # The calibration engine uses a physical model of the FHR640 spectrometer
        # to map camera pixels to wavelengths based on the grating and center wavelength.
        cal_config = self.config.get('hardware', {}).get('fhr640', {}).get('calibration', {})
        self.calibration = SpectrometerCalibration(
            focal_length_mm=cal_config.get('focal_length_mm', 640.0), # Distance from grating to sensor
            deviation_deg=cal_config.get('deviation_deg', 18.5),     # Angle between entrance and exit ports
            sensor_tilt_deg=cal_config.get('sensor_tilt_deg', 8.92),  # Tilt of the Andor sensor relative to the exit plane
            pixel_stride_um=cal_config.get('pixel_stride_um', -26.0)  # Width of a single pixel (Newtons are usually 26um)
        )
        self.polarizer_calibration = PolarizerCalibration()
        self.pixel_deviation = 0.0 # Manual offset in pixels for fine-tuning calibration
        
        self._service = None
        self._initialized = True
        logger.info("Hardware manager initialized")

    @property
    def service(self):
        """Lazy initialization of the HardwareService."""
        if self._service is None:
            # Lazy import to avoid circular dependency
            from ..core.hardware_service import HardwareService
            self._service = HardwareService(self)
        return self._service

    def _load_default_config(self):
        """Load configuration from the default yaml file."""
        import yaml
        from pathlib import Path
        
        config_path = Path(__file__).parent.parent.absolute() / "config" / "default.yaml"
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    self.config = yaml.safe_load(f)
                logger.info(f"Loaded configuration from {config_path}")
                # Log top-level keys for diagnostics
                logger.debug(f"Config keys: {list(self.config.keys())}")
            except Exception as e:
                logger.error(f"Failed to load config from {config_path}: {e}")
        else:
            logger.warning(f"Config file not found at {config_path}")

    def initialize_instrument(self, name: str, instrument_type: str, config: Optional[Dict[str, Any]] = None) -> Instrument:
        """
        Create and store an instrument instance in the manager.
        
        This method uses the factory pattern to instantiate the correct driver.
        If no configuration is provided, it attempts to look up the default settings
        from the 'config/default.yaml'.
        
        Args:
            name: Unique identifier for this instrument instance (e.g., 'spec_camera').
            instrument_type: The driver type (e.g., 'andor_camera', 'fhr640').
            config: Optional override configuration dictionary.
        """
        if config is None and self.config:
            hw_config = self.config.get('hardware', {})
            config = hw_config.get(name) or hw_config.get(instrument_type, {})
            logger.debug(f"Initializing {name} with config: {config}")
            
        instrument = create_instrument(instrument_type, config)
        self.instruments[name] = instrument
        return instrument

    def get_instrument(self, name: str) -> Optional[Instrument]:
        """Get an existing instrument by name."""
        return self.instruments.get(name)

    def connect_all(self):
        """
        Connect to all listed hardware instruments sequentially.
        If a spectrometer camera connects, it automatically triggers a calibration sync
        to ensure the pixel size matches the physical sensor.
        """
        for name, inst in self.instruments.items():
            try:
                inst.connect()
                # If the spectrometer camera just connected, sync its pixel size to calibration
                if name == 'spec_camera':
                    self.sync_calibration_with_hardware()
            except Exception as e:
                logger.error(f"Failed to connect {name}: {e}")
                logger.error(f"Failed to connect {name}: {e}")

    def disconnect_all(self):
        """Disconnect all instruments."""
        for name, inst in self.instruments.items():
            try:
                inst.disconnect()
            except Exception as e:
                logger.error(f"Failed to disconnect {name}: {e}")

    @property
    def mono(self):
        """Helper to get the monochromator (assuming one)."""
        return self.get_instrument('mono')

    @property
    def vis_camera(self):
        """Helper to get the visualisation camera."""
        return self.get_instrument('vis_camera')

    @property
    def spec_camera(self):
        """Helper to get the spectrometer camera."""
        return self.get_instrument('spec_camera')

    @property
    def kdc101(self):
        """Helper to get the KDC101 motor controller."""
        return self.get_instrument('kdc101')
    @property
    def vis_camera_config(self) -> Dict[str, Any]:
        """Get the configuration for the visualisation camera."""
        hw_config = self.config.get('hardware', {})
        return hw_config.get('vis_camera', {})

    @property
    def spec_camera_config(self) -> Dict[str, Any]:
        """Get the configuration for the spectrometer camera."""
        hw_config = self.config.get('hardware', {})
        return hw_config.get('spec_camera', {})

    @property
    def current_wavelength(self) -> float:
        """Get the central wavelength from the monochromator."""
        if self.mono:
            return self.mono._center_wavelength
        return 0.0

    @current_wavelength.setter
    def current_wavelength(self, value: float):
        """Set the central wavelength and sync accessories."""
        if self.mono:
            self.mono.set_center_wavelength(value)
            
        # Optional: Sync power meter if it exists and sync is enabled
        pm = self.get_instrument('pm100')
        if pm:
            try:
                # We could add a 'sync_enabled' flag in config or manager
                pm.set_wavelength(value)
            except Exception as e:
                logger.debug(f"Power meter wavelength sync failed: {e}")

    def sync_calibration_with_hardware(self):
        """
        Update calibration parameters (like pixel stride) from connected hardware.
        Preserves the sign (orientation) from config but takes magnitude from camera.
        """
        cam = self.get_instrument('spec_camera')
        if cam and cam.is_connected():
            try:
                # get_pixel_size returns (width, height) in um
                px_size = cam.get_pixel_size()
                if px_size and len(px_size) >= 1:
                    magnitude = px_size[0]
                    # Keep the sign from the current calibration
                    sign = 1.0 if self.calibration.pixel_stride >= 0 else -1.0
                    new_stride_um = sign * magnitude
                    self.calibration.update_pixel_stride(new_stride_um)
                    logger.info(f"Sync: Calibration updated with camera pixel size {magnitude} um (Sign: {sign})")
            except Exception as e:
                logger.warning(f"Sync: Failed to get pixel size from camera: {e}")

    def get_wavelength_axis(self, camera_name: str = 'spec_camera') -> Optional[np.ndarray]:
        """
        Generate the wavelength axis for a camera based on current mono state.
        """
        cam = self.get_instrument(camera_name)
        if not cam or not self.mono:
            return None
            
        # Grating info
        grating_idx = self.mono.get_grating()
        
        # Load mapping from config
        mono_config = self.config.get('hardware', {}).get('fhr640', {})
        densities = mono_config.get('gratings', [600, 1200, 1800])
        
        if grating_idx < len(densities):
            g_mm = densities[grating_idx]
        else:
            logger.warning(f"Grating index {grating_idx} out of range for {densities}. Defaulting to 1200.")
            g_mm = 1200
            
        # ROI info
        roi = cam.get_roi() # (hstart, hend, vstart, vend, hbin, vbin)
        hstart, hend, hbin = roi[0], roi[1], roi[4]
        width = hend - hstart
        
        # In Andor ROI, num_pixels should match the returned frame width
        # but if the frame is binned, the number of 'pixels' in the axis is width // hbin
        num_axis_points = width // hbin
        
        # Detector constants (center pixel)
        # Newton / iDus usually have 1024 or 2048 pixels.
        # Per user request, for 1024 detector, center is 512.5
        detector_size = cam.get_detector_size()  # live from SDK when connected, config fallback otherwise
        center_pixel = (detector_size[0] / 2.0) + 0.5 + self.pixel_deviation
        
        self.calibration.update_params(
            center_wavelength=self.mono._center_wavelength,
            grating_g_mm=g_mm,
            center_pixel=center_pixel
        )
        
        return self.calibration.get_wavelength_axis(num_axis_points, hstart, hbin)
    def collect_metadata(self, manual_power_w: Optional[float] = None) -> Dict[str, Any]:
        """
        Collect state information (metadata) from all connected instruments.
        
        This is used when saving measurements to ensure every data file is tagged
        with the exact experimental conditions (wavelength, exposure, temperature, etc.).
        
        Args:
            manual_power_w: Optional laser power override if not using the power meter.
        """
        meta = {
            'Timestamp': datetime.datetime.now().isoformat(),
            'Monochromator': {},
            'Camera': {},
            'Pixel deviation': self.pixel_deviation,
            '_units': self.spectral_unit
        }

        # 1. Monochromator (FHR640)
        mono = self.mono
        if mono and mono.is_connected():
            grating_idx = mono.get_grating()
            gratings_config = self.config.get('hardware', {}).get('fhr640', {}).get('gratings', [600, 1200, 1800])
            try:
                grating_val = gratings_config[grating_idx]
            except:
                grating_val = 0

            meta['Monochromator'] = {
                'Model': 'FHR640',
                'Wavelength (nm)': mono._center_wavelength,
            }
            # Add energy and cm-1 conversions
            from ..utils.conversions import nm_to_meV, nm_to_inv_cm
            meta['Monochromator']['Energy (meV)'] = nm_to_meV(mono._center_wavelength)
            meta['Monochromator']['Spatial Frequency (cm-1)'] = nm_to_inv_cm(mono._center_wavelength)
            
            # Add grating after wavelengths
            meta['Monochromator']['Grating (l/mm)'] = grating_val
            
            # Try to get slit width
            if hasattr(mono, 'get_slit_width'):
                 meta['Monochromator']['Entrance Slit (um)'] = mono.get_slit_width('entrance')

        # 2. Camera
        # Check active camera from GUI or config? 
        # Usually LiveView sets self.current_camera.
        # But HardwareManager can probe both.
        for name in ['spec_camera', 'vis_camera']:
            cam = self.get_instrument(name)
            if cam and cam.is_connected():
                try:
                    info = cam.get_info()
                    # Try to get exposure from the new method, fallback to info
                    try:
                        exposure_s = cam.get_exposure()
                    except:
                        exposure_s = info.get('exposure_time', info.get('actual_exposure', 0.0))

                    meta['Camera'][name] = {
                        'Model': info.get('Model', info.get('model', 'Unknown')),
                        'Exposure (ms)': exposure_s * 1000.0,
                        'ROI': cam.get_roi()
                    }
                except Exception as e:
                    logger.warning(f"Failed to collect metadata for {name}: {e}")

        # 3. Excitation Power (Manual Input)
        if manual_power_w is not None:
             meta['Excitation Power (W)'] = manual_power_w

        return meta
