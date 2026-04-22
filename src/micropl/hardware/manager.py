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
        # Generic camera registry — keyed by camera ID from YAML
        self.cameras: Dict[str, Instrument] = {}
        self.config: Dict[str, Any] = {}
        self.spectral_unit = "nm"          # Shared state for GUI unit sync (nm, meV, cm-1)
        self.spectral_display_mode = "Pixel"  # Shared state for mode sync (Pixel, Spectral Units)
        self.data_processing_mode = "Raw Data"  # Shared processing selection
        self._load_default_config()
        
        # --- Spectral Calibration Engine ---
        # The calibration engine uses a physical model of the FHR640 spectrometer
        # to map camera pixels to wavelengths based on the grating and center wavelength.
        cal_config = self.config.get('hardware', {}).get('fhr640', {}).get('calibration', {})
        self.calibration = SpectrometerCalibration(
            focal_length_mm=cal_config.get('focal_length_mm', 640.0),
            deviation_deg=cal_config.get('deviation_deg', 18.5),
            sensor_tilt_deg=cal_config.get('sensor_tilt_deg', 8.92),
            pixel_stride_um=cal_config.get('pixel_stride_um', -26.0)
        )
        self.polarizer_calibration = PolarizerCalibration()
        self.pixel_deviation = 0.0  # Manual offset in pixels for fine-tuning calibration

        # ID of the camera currently displayed in LiveView (defaults to first enabled camera)
        self.active_camera_id: Optional[str] = self._get_default_active_camera_id()

        self._service = None
        self._initialized = True
        logger.info("Hardware manager initialized")

    def _get_default_active_camera_id(self) -> Optional[str]:
        """Return the ID of the first enabled camera in config."""
        cameras_cfg = self.config.get('hardware', {}).get('cameras', [])
        for cam_cfg in cameras_cfg:
            if cam_cfg.get('enabled', False):
                return cam_cfg['id']
        return None

    @property
    def service(self):
        """Lazy initialization of the HardwareService."""
        if self._service is None:
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
                logger.debug(f"Config keys: {list(self.config.keys())}")
            except Exception as e:
                logger.error(f"Failed to load config from {config_path}: {e}")
        else:
            logger.warning(f"Config file not found at {config_path}")

    def save_config(self):
        """Persist the current in-memory config back to default.yaml."""
        import yaml
        from pathlib import Path

        config_path = Path(__file__).parent.parent.absolute() / "config" / "default.yaml"
        try:
            with open(config_path, 'w') as f:
                yaml.dump(self.config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            logger.info(f"Configuration saved to {config_path}")
        except Exception as e:
            logger.error(f"Failed to save config to {config_path}: {e}")

    # -----------------------------------------------------------------------
    # Camera helpers (generic)
    # -----------------------------------------------------------------------

    def get_camera(self, camera_id: str) -> Optional[Instrument]:
        """Get a camera by its config ID."""
        return self.cameras.get(camera_id)

    def get_spectroscopy_camera(self) -> Optional[Instrument]:
        """Return the first enabled camera with role='spectroscopy'."""
        cam_id = self.get_spectroscopy_camera_id()
        return self.cameras.get(cam_id) if cam_id else None

    def get_spectroscopy_camera_id(self) -> Optional[str]:
        """Return the ID of the first enabled camera with role='spectroscopy'."""
        cameras_cfg = self.config.get('hardware', {}).get('cameras', [])
        for cam_cfg in cameras_cfg:
            if cam_cfg.get('role') == 'spectroscopy' and cam_cfg.get('enabled', False):
                return cam_cfg['id']
        return None

    def get_camera_config(self, camera_id: str) -> Dict[str, Any]:
        """Get the config dict for a camera by ID."""
        cameras_cfg = self.config.get('hardware', {}).get('cameras', [])
        for cam_cfg in cameras_cfg:
            if cam_cfg.get('id') == camera_id:
                return cam_cfg
        return {}

    @property
    def active_camera(self) -> Optional[Instrument]:
        """Return the currently active camera for the live display."""
        return self.cameras.get(self.active_camera_id) if self.active_camera_id else None

    # -----------------------------------------------------------------------
    # Instrument initialization / access
    # -----------------------------------------------------------------------

    def initialize_instrument(self, name: str, instrument_type: str, config: Optional[Dict[str, Any]] = None) -> Instrument:
        """
        Create and store an instrument instance in the manager.

        For cameras, `name` should be a camera ID from the YAML cameras list.
        The instrument is stored in both `self.instruments` and `self.cameras`.

        Args:
            name: Unique identifier (e.g., 'camera_0', 'pm100', 'mono').
            instrument_type: The driver type (e.g., 'andor_camera', 'fhr640').
            config: Optional override configuration dictionary.
        """
        if config is None and self.config:
            hw_config = self.config.get('hardware', {})
            # 1. Try camera list first
            cam_cfg = self.get_camera_config(name)
            if cam_cfg:
                config = cam_cfg
            else:
                # 2. Try accessories list
                acc_cfg = self.get_accessory_config(name)
                if acc_cfg:
                    config = acc_cfg
                else:
                    # 3. Fall back to flat key (e.g. 'fhr640', 'mono')
                    config = hw_config.get(name) or hw_config.get(instrument_type, {})
            logger.debug(f"Initializing {name} ({instrument_type}) with config keys: {list((config or {}).keys())}")

        instrument = create_instrument(instrument_type, config)
        self.instruments[name] = instrument

        # Also register in camera dict if it's a camera type
        if instrument_type == 'andor_camera':
            self.cameras[name] = instrument

        return instrument

    def get_instrument(self, name: str) -> Optional[Instrument]:
        """Get an existing instrument by name."""
        return self.instruments.get(name)

    def get_accessory_config(self, accessory_id: str) -> Dict[str, Any]:
        """Get the config dict for an accessory by ID."""
        accessories_cfg = self.config.get('hardware', {}).get('accessories', [])
        for acc_cfg in accessories_cfg:
            if acc_cfg.get('id') == accessory_id:
                return acc_cfg
        return {}

    # -----------------------------------------------------------------------
    # Connect / Disconnect
    # -----------------------------------------------------------------------

    def connect_all(self):
        """
        Connect to all instruments. If a spectroscopy camera connects,
        automatically triggers calibration sync.
        """
        for name, inst in self.instruments.items():
            try:
                inst.connect()
                # Sync calibration after spectroscopy camera connection
                if name == self.get_spectroscopy_camera_id():
                    self.sync_calibration_with_hardware()
            except Exception as e:
                logger.error(f"Failed to connect {name}: {e}")

    def disconnect_all(self):
        """Disconnect all instruments."""
        for name, inst in self.instruments.items():
            try:
                inst.disconnect()
            except Exception as e:
                logger.error(f"Failed to disconnect {name}: {e}")

    # -----------------------------------------------------------------------
    # Named instrument properties (non-camera accessories)
    # -----------------------------------------------------------------------

    @property
    def mono(self):
        """Helper to get the monochromator (assuming one)."""
        return self.get_instrument('mono')

    @property
    def kdc101(self):
        """Helper to get the KDC101 motor controller."""
        return self.get_instrument('kdc101')

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
            
        pm = self.get_instrument('pm100')
        if pm:
            try:
                pm.set_wavelength(value)
            except Exception as e:
                logger.debug(f"Power meter wavelength sync failed: {e}")

    # -----------------------------------------------------------------------
    # Calibration
    # -----------------------------------------------------------------------

    def sync_calibration_with_hardware(self):
        """
        Update calibration pixel stride from the connected spectroscopy camera.
        Preserves the sign (orientation) from config but takes magnitude from camera.
        """
        cam = self.get_spectroscopy_camera()
        if cam and cam.is_connected():
            try:
                px_size = cam.get_pixel_size()
                if px_size and len(px_size) >= 1:
                    magnitude = px_size[0]
                    sign = 1.0 if self.calibration.pixel_stride >= 0 else -1.0
                    new_stride_um = sign * magnitude
                    self.calibration.update_pixel_stride(new_stride_um)
                    logger.info(f"Sync: Calibration updated with camera pixel size {magnitude} um (Sign: {sign})")
            except Exception as e:
                logger.warning(f"Sync: Failed to get pixel size from camera: {e}")

    def get_wavelength_axis(self, camera_id: Optional[str] = None) -> Optional[np.ndarray]:
        """
        Generate the wavelength axis for a camera based on current mono state.

        Args:
            camera_id: Camera ID to use. If None, the spectroscopy camera is used automatically.
        """
        if camera_id is None:
            camera_id = self.get_spectroscopy_camera_id()

        cam = self.get_camera(camera_id)
        if not cam or not self.mono:
            return None
            
        # Grating info
        grating_idx = self.mono.get_grating()
        mono_config = self.config.get('hardware', {}).get('fhr640', {})
        densities = mono_config.get('gratings', [600, 1200, 1800])
        
        if grating_idx < len(densities):
            g_mm = densities[grating_idx]
        else:
            logger.warning(f"Grating index {grating_idx} out of range for {densities}. Defaulting to 1200.")
            g_mm = 1200
            
        # ROI info
        roi = cam.get_roi()  # (hstart, hend, vstart, vend, hbin, vbin)
        hstart, hend, hbin = roi[0], roi[1], roi[4]
        width = hend - hstart
        num_axis_points = width // hbin
        
        # Detector constants (center pixel)
        detector_size = cam.get_detector_size()
        center_pixel = (detector_size[0] / 2.0) + 0.5 + self.pixel_deviation
        
        self.calibration.update_params(
            center_wavelength=self.mono._center_wavelength,
            grating_g_mm=g_mm,
            center_pixel=center_pixel
        )
        
        return self.calibration.get_wavelength_axis(num_axis_points, hstart, hbin)

    # -----------------------------------------------------------------------
    # Metadata
    # -----------------------------------------------------------------------

    def collect_metadata(self, manual_power_w: Optional[float] = None) -> Dict[str, Any]:
        """
        Collect state information (metadata) from all connected instruments.
        Used when saving measurements.
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
            from ..utils.conversions import nm_to_meV, nm_to_inv_cm
            meta['Monochromator']['Energy (meV)'] = nm_to_meV(mono._center_wavelength)
            meta['Monochromator']['Spatial Frequency (cm-1)'] = nm_to_inv_cm(mono._center_wavelength)
            meta['Monochromator']['Grating (l/mm)'] = grating_val
            if hasattr(mono, 'get_slit_width'):
                meta['Monochromator']['Entrance Slit (um)'] = mono.get_slit_width('entrance')

        # 2. All cameras
        for cam_id, cam in self.cameras.items():
            if cam and cam.is_connected():
                try:
                    info = cam.get_info()
                    try:
                        exposure_s = cam.get_exposure()
                    except:
                        exposure_s = info.get('exposure_time', info.get('actual_exposure', 0.0))
                    meta['Camera'][cam_id] = {
                        'Name': self.get_camera_config(cam_id).get('name', cam_id),
                        'Model': info.get('Model', info.get('model', 'Unknown')),
                        'Exposure (ms)': exposure_s * 1000.0,
                        'ROI': cam.get_roi()
                    }
                except Exception as e:
                    logger.warning(f"Failed to collect metadata for camera {cam_id}: {e}")

        # 3. Excitation Power (Manual Input)
        if manual_power_w is not None:
            meta['Excitation Power (W)'] = manual_power_w

        return meta
