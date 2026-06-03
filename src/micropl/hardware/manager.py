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
        # Registries for specific hardware types
        self.cameras: Dict[str, Instrument] = {}
        self.monochromators: Dict[str, Instrument] = {}
        
        self.config: Dict[str, Any] = {}
        self.spectral_unit = "nm"          # Shared state for GUI unit sync (nm, meV, cm-1)
        self.spectral_display_mode = "Pixel"  # Shared state for mode sync (Pixel, Spectral Units)
        self.data_processing_mode = "Raw Data"  # Shared processing selection
        self._last_grating_idx = None           # Cached by HardwareService
        self._load_default_config()
        
        # --- Spectral Calibration Engine ---
        # The calibration engine is now initialized from the active monochromator's config.
        self.active_monochromator_id: Optional[str] = self._get_default_active_monochromator_id()
        
        cal_config = {}
        if self.active_monochromator_id:
            cal_config = self.get_monochromator_config(self.active_monochromator_id).get('calibration', {})
            
        self.calibration = SpectrometerCalibration(
            focal_length_mm=cal_config.get('focal_length_mm', 640.0),
            deviation_deg=cal_config.get('deviation_deg', 18.5),
            sensor_tilt_deg=cal_config.get('sensor_tilt_deg', 8.92),
            pixel_stride_um=cal_config.get('pixel_stride_um', -26.0)
        )
        self.polarizer_calibration = PolarizerCalibration()
        self.pixel_deviation = 0.0  # Manual offset in pixels for fine-tuning calibration

        # Default active camera
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

    def _get_default_active_monochromator_id(self) -> Optional[str]:
        """Return the ID of the first enabled monochromator in config."""
        mono_cfg_list = self.config.get('hardware', {}).get('monochromators', [])
        for m_cfg in mono_cfg_list:
            if m_cfg.get('enabled', False):
                return m_cfg['id']
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
                
                # Apply default setup preset on startup if defined
                hw_cfg = self.config.get('hardware', {})
                default_preset = hw_cfg.get('default_setup')
                if default_preset:
                    logger.info(f"Applying default setup preset: {default_preset}")
                    self.apply_preset_by_name(default_preset)
            except Exception as e:
                logger.error(f"Failed to load config from {config_path}: {e}")
        else:
            logger.warning(f"Config file not found at {config_path}")

    def apply_preset_by_name(self, preset_name: str) -> None:
        """Apply a preconfigured hardware setup preset in-memory."""
        hw_cfg = self.config.setdefault('hardware', {})
        name = preset_name.strip().lower()
        
        if "ir micro pl" in name:
            # Detect which spectroscopy camera
            cam_id = "camera_1" # default to iDus Si
            if "1024" in name:
                cam_id = "camera_2"
            elif "512" in name:
                cam_id = "camera_3"
                
            # 1. Cameras
            for cam in hw_cfg.setdefault('cameras', []):
                c_id = cam.get('id')
                if c_id == 'camera_0':
                    cam['enabled'] = True
                    cam['role'] = 'visualisation'
                    cam['serial_number'] = 1195
                elif c_id == cam_id:
                    cam['enabled'] = True
                    cam['role'] = 'spectroscopy'
                    if cam_id == 'camera_1':
                        cam['serial_number'] = 20198
                    elif cam_id == 'camera_2':
                        cam['serial_number'] = 12144
                    elif cam_id == 'camera_3':
                        cam['serial_number'] = 14136
                else:
                    cam['enabled'] = False
                    
            # 2. Monochromators
            for mono in hw_cfg.setdefault('monochromators', []):
                if mono.get('id') == 'mono_0':
                    mono['enabled'] = True
                else:
                    mono['enabled'] = False
                    
            # 3. Accessories
            for acc in hw_cfg.setdefault('accessories', []):
                a_id = acc.get('id')
                if a_id == 'pm100':
                    acc['enabled'] = True
                elif a_id == 'polarizer':
                    acc['enabled'] = True
                    acc['serial_number'] = "27271777"
                elif a_id in ('stage_x', 'stage_y'):
                    acc['enabled'] = False
                    
            # 4. Shutter
            hw_cfg['shutter'] = {
                'linked_id': 'polarizer',
                'channel': 1
            }
            
        elif "macro pl" in name:
            # 1. Cameras
            for cam in hw_cfg.setdefault('cameras', []):
                c_id = cam.get('id')
                if c_id == 'camera_1':
                    cam['enabled'] = True
                    cam['role'] = 'spectroscopy'
                    cam['serial_number'] = 13892
                else:
                    cam['enabled'] = False
                    
            # 2. Monochromators
            for mono in hw_cfg.setdefault('monochromators', []):
                if mono.get('id') == 'mono_1':
                    mono['enabled'] = True
                else:
                    mono['enabled'] = False
                    
            # 3. Accessories
            for acc in hw_cfg.setdefault('accessories', []):
                a_id = acc.get('id')
                if a_id in ('pm100', 'polarizer'):
                    acc['enabled'] = False
                elif a_id == 'stage_x':
                    acc['enabled'] = True
                    acc['serial_number'] = "27271950"
                elif a_id == 'stage_y':
                    acc['enabled'] = True
                    acc['serial_number'] = "27272895"
                    
            # 4. Shutter
            hw_cfg['shutter'] = {
                'linked_id': None,
                'channel': 1
            }
            
        # Re-sync active IDs in manager
        self.active_camera_id = self._get_default_active_camera_id()
        self.active_monochromator_id = self._get_default_active_monochromator_id()

    def save_config(self):
        """
        Skip persisting to disk to preserve manual comments and formatting.
        Changes applied in the Setup tab will last for the current session only.
        """
        logger.info("Configuration changes applied in-memory (File save disabled to preserve comments).")

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

    def get_monochromator_config(self, mono_id: str) -> Dict[str, Any]:
        """Get the config dict for a monochromator by ID."""
        mono_cfg_list = self.config.get('hardware', {}).get('monochromators', [])
        for m_cfg in mono_cfg_list:
            if m_cfg.get('id') == mono_id:
                return m_cfg
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
        Create and store an instrument instance in the manager using the factory pattern.

        This method dynamically loads the appropriate driver class based on `instrument_type`
        (e.g., 'andor_camera', 'horiba_serial'). It resolves the configuration by falling back 
        through the YAML configuration trees (Cameras -> Monochromators -> Accessories) if a 
        specific config dictionary is not provided.

        The instantiated object is stored in the generic `self.instruments` registry, as well 
        as any specialized registries (like `self.cameras`) for quick typed access.

        Args:
            name: Unique identifier (e.g., 'camera_0', 'pm100', 'mono').
            instrument_type: The driver type (e.g., 'andor_camera', 'horiba_serial', 'horiba_sdk').
            config: Optional override configuration dictionary.
        """
        if config is None and self.config:
            hw_config = self.config.get('hardware', {})
            # 1. Try camera list
            cam_cfg = self.get_camera_config(name)
            if cam_cfg:
                config = cam_cfg
            else:
                # 2. Try monochromator list
                mono_cfg = self.get_monochromator_config(name)
                if mono_cfg:
                    config = mono_cfg
                else:
                    # 3. Try accessories list
                    acc_cfg = self.get_accessory_config(name)
                    if acc_cfg:
                        config = acc_cfg
                    else:
                        # 4. Fall back to flat key (Legacy/Stub)
                        config = hw_config.get(name) or hw_config.get(instrument_type, {})
            logger.debug(f"Initializing {name} ({instrument_type}) with config keys: {list((config or {}).keys())}")

        instrument = create_instrument(instrument_type, config)
        self.instruments[name] = instrument

        # Specialized registration
        if instrument_type == 'andor_camera':
            self.cameras[name] = instrument
        elif instrument_type in ('horiba_serial', 'horiba_sdk'):
            self.monochromators[name] = instrument

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
        Connect to all initialized instruments. 
        
        If a spectroscopy camera successfully connects, this automatically triggers a 
        calibration synchronization. This is critical because the wavelength-to-pixel 
        mapping depends on physical properties of the *connected* camera (like pixel size).
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
        """Helper to get the currently active monochromator."""
        return self.monochromators.get(self.active_monochromator_id)

    @property
    def polarizer(self) -> Optional[Instrument]:
        """Return the KDC101 instance used as a polarizer."""
        return self.get_instrument('polarizer')

    @property
    def shutter(self) -> Optional[Instrument]:
        """Return the instrument designated as the system shutter."""
        shutter_id = self.config.get('hardware', {}).get('shutter', {}).get('linked_id')
        if shutter_id:
            return self.get_instrument(shutter_id)
        # Fallback
        return self.polarizer

    @property
    def shutter_channel(self) -> int:
        """Return the channel (1 or 2) configured for the system shutter."""
        return self.config.get('hardware', {}).get('shutter', {}).get('channel', 1)

    @property
    def stage_x(self) -> Optional[Instrument]:
        """Return the KDC101 instance used for Stage X axis."""
        return self.get_instrument('stage_x')

    @property
    def stage_y(self) -> Optional[Instrument]:
        """Return the KDC101 instance used for Stage Y axis."""
        return self.get_instrument('stage_y')

    @property
    def kdc101(self):
        """Deprecated: Use .polarizer or .get_instrument(id) instead."""
        return self.polarizer

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
        Update calibration engine with active camera pixel size and active mono parameters.
        """
        # 1. Update from Spectroscopy Camera
        cam = self.get_spectroscopy_camera()
        if cam and cam.is_connected():
            try:
                px_size = cam.get_pixel_size()
                if px_size and len(px_size) >= 1:
                    magnitude = px_size[0]
                    sign = 1.0 if self.calibration.pixel_stride >= 0 else -1.0
                    new_stride_um = sign * magnitude
                    self.calibration.update_pixel_stride(new_stride_um)
                    logger.info(f"Sync: Calibration updated with camera pixel size {magnitude} um")
            except Exception as e:
                logger.warning(f"Sync: Failed to get pixel size from camera: {e}")

        # 2. Update from Active Monochromator Config
        if self.active_monochromator_id:
            m_cfg = self.get_monochromator_config(self.active_monochromator_id)
            cal_cfg = m_cfg.get('calibration', {})
            if cal_cfg:
                self.calibration.focal_length_mm = cal_cfg.get('focal_length_mm', 640.0)
                self.calibration.deviation_deg = cal_cfg.get('deviation_deg', 18.5)
                self.calibration.sensor_tilt_deg = cal_cfg.get('sensor_tilt_deg', 8.92)
                logger.info(f"Sync: Calibration engine updated for {self.active_monochromator_id}")

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
        # Prefer cached value from HardwareService to avoid blocking hardware calls
        if hasattr(self, '_last_grating_idx') and self._last_grating_idx is not None:
            grating_idx = self._last_grating_idx
        else:
            try:
                grating_idx = self.mono.get_grating()
                self._last_grating_idx = grating_idx
            except:
                grating_idx = 0

        mono_id = self.active_monochromator_id
        mono_config = self.get_monochromator_config(mono_id)
        densities = mono_config.get('gratings', [600, 1200, 1800])
        
        if grating_idx < len(densities):
            g_mm = densities[grating_idx]
        else:
            # Only log warning once to avoid flooding logs every frame
            if not getattr(self, '_grating_warned', False):
                logger.warning(f"Grating index {grating_idx} out of range for {densities}. Defaulting to 1200.")
                self._grating_warned = True
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

        # 1. Monochromator
        mono = self.mono
        mono_id = self.active_monochromator_id
        if mono and mono.is_connected():
            grating_idx = mono.get_grating()
            mono_config = self.get_monochromator_config(mono_id)
            gratings_config = mono_config.get('gratings', [600, 1200, 1800])
            try:
                grating_val = gratings_config[grating_idx]
            except:
                grating_val = 0
            
            meta['Monochromator'] = {
                'ID': mono_id,
                'Model': mono_config.get('name', 'Unknown'),
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
