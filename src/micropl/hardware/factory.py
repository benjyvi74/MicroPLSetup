"""
Factory for dynamic driver creation.
"""

from typing import Dict, Any, Type, Optional
import logging

from .base import Instrument
from .kdc101 import ThorlabsKDC101
from .pm100 import ThorlabsPM100
from .horiba_serial import HoribaSerialMonochromator
from .horiba_sdk import HoribaSDKMonochromator
from .andor_camera import AndorCamera

logger = logging.getLogger(__name__)


DRIVER_REGISTRY: Dict[str, Type[Instrument]] = {
    'kdc101':        ThorlabsKDC101,
    'pm100':         ThorlabsPM100,
    'horiba_serial': HoribaSerialMonochromator,
    'horiba_sdk':    HoribaSDKMonochromator,
    'andor_camera':  AndorCamera,
}


def create_instrument(instrument_type: str, config: Optional[Dict[str, Any]] = None) -> Instrument:
    """
    Create an instrument instance from the registry.

    Args:
        instrument_type: Type of instrument (e.g., 'kdc101', 'pm100')
        config: Configuration dictionary for the instrument

    Returns:
        Instrument instance

    Raises:
        ValueError: If instrument type is not found in registry
    """
    if instrument_type not in DRIVER_REGISTRY:
        raise ValueError(
            f"Unknown instrument type: {instrument_type}. "
            f"Available types: {list(DRIVER_REGISTRY.keys())}"
        )

    driver_class = DRIVER_REGISTRY[instrument_type]
    logger.info(f"Creating instrument: {instrument_type}")

    return driver_class(config)


def register_driver(name: str, driver_class: Type[Instrument]) -> None:
    """
    Register a new driver in the factory.

    Args:
        name: Name to register the driver under
        driver_class: Driver class (must inherit from Instrument)
    """
    if not issubclass(driver_class, Instrument):
        raise TypeError(f"{driver_class} must inherit from Instrument")

    DRIVER_REGISTRY[name] = driver_class
    logger.info(f"Registered driver: {name}")


def list_available_drivers() -> list:
    """List all available driver types."""
    return list(DRIVER_REGISTRY.keys())
