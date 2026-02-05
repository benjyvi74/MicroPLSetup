"""
Hardware manager for coordinating access to instruments.
"""

import logging
from typing import Dict, Any, Optional

from .factory import create_instrument
from .base import Instrument

logger = logging.getLogger(__name__)


class HardwareManager:
    """Singleton manager for all hardware instruments."""
    
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(HardwareManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
            
        self.instruments: Dict[str, Instrument] = {}
        self.config: Dict[str, Any] = {}
        self.spectral_unit = "nm" # Shared state for GUI unit synchronization
        self._load_default_config()
        self._initialized = True
        logger.info("Hardware manager initialized")

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
        Create and store an instrument instance.
        If no config is provided, it tries to find it in the loaded default config.
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
        """Connect all initialized instruments."""
        for name, inst in self.instruments.items():
            try:
                inst.connect()
            except Exception as e:
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
