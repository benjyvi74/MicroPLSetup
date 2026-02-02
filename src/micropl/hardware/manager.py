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
        self._initialized = True
        logger.info("Hardware manager initialized")

    def initialize_instrument(self, name: str, instrument_type: str, config: Optional[Dict[str, Any]] = None) -> Instrument:
        """
        Create and store an instrument instance.

        Args:
            name: Local name to refer to the instrument (e.g., 'mono')
            instrument_type: Driver type (e.g., 'fhr640')
            config: Configuration for the instrument
            
        Returns:
            Instrument instance
        """
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
