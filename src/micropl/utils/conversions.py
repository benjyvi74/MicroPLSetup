"""
Unit conversions and physical constants.
"""

import numpy as np

# Physical constants
H_PLANCK = 6.62607015e-34  # J·s
C_LIGHT = 299792458  # m/s
EV_TO_JOULE = 1.602176634e-19  # J/eV


def nm_to_meV(wavelength_nm: float) -> float:
    """
    Convert wavelength in nm to energy in meV.

    Args:
        wavelength_nm: Wavelength in nanometers

    Returns:
        Energy in millielectronvolts
    """
    wavelength_m = wavelength_nm * 1e-9
    energy_j = (H_PLANCK * C_LIGHT) / wavelength_m
    energy_ev = energy_j / EV_TO_JOULE
    energy_meV = energy_ev * 1000

    return energy_meV


def meV_to_nm(energy_meV: float) -> float:
    """
    Convert energy in meV to wavelength in nm.

    Args:
        energy_meV: Energy in millielectronvolts

    Returns:
        Wavelength in nanometers
    """
    energy_ev = energy_meV / 1000
    energy_j = energy_ev * EV_TO_JOULE
    wavelength_m = (H_PLANCK * C_LIGHT) / energy_j
    wavelength_nm = wavelength_m * 1e9

    return wavelength_nm


def wavelength_to_frequency(wavelength_nm: float) -> float:
    """
    Convert wavelength to frequency.

    Args:
        wavelength_nm: Wavelength in nanometers

    Returns:
        Frequency in Hz
    """
    wavelength_m = wavelength_nm * 1e-9
    frequency = C_LIGHT / wavelength_m

    return frequency


def frequency_to_wavelength(frequency_hz: float) -> float:
    """
    Convert frequency to wavelength.

    Args:
        frequency_hz: Frequency in Hz

    Returns:
        Wavelength in nanometers
    """
    wavelength_m = C_LIGHT / frequency_hz
    wavelength_nm = wavelength_m * 1e9

    return wavelength_nm


def power_to_dbm(power_w: float) -> float:
    """
    Convert power in watts to dBm.

    Args:
        power_w: Power in watts

    Returns:
        Power in dBm
    """
    power_mw = power_w * 1000
    power_dbm = 10 * np.log10(power_mw)

    return power_dbm


def dbm_to_power(power_dbm: float) -> float:
    """
    Convert power in dBm to watts.

    Args:
        power_dbm: Power in dBm

    Returns:
        Power in watts
    """
    power_mw = 10 ** (power_dbm / 10)
    power_w = power_mw / 1000

    return power_w


def photon_energy(wavelength_nm: float) -> float:
    """
    Calculate photon energy for given wavelength.

    Args:
        wavelength_nm: Wavelength in nanometers

    Returns:
        Photon energy in joules
    """
    wavelength_m = wavelength_nm * 1e-9
    energy_j = (H_PLANCK * C_LIGHT) / wavelength_m

    return energy_j


def photon_flux(power_w: float, wavelength_nm: float) -> float:
    """
    Calculate photon flux (photons per second) for given power and wavelength.

    Args:
        power_w: Optical power in watts
        wavelength_nm: Wavelength in nanometers

    Returns:
        Photon flux in photons/second
    """
    energy_per_photon = photon_energy(wavelength_nm)
    flux = power_w / energy_per_photon

    return flux


def temperature_to_kelvin(temp_celsius: float) -> float:
    """Convert temperature from Celsius to Kelvin."""
    return temp_celsius + 273.15


def kelvin_to_celsius(temp_kelvin: float) -> float:
    """Convert temperature from Kelvin to Celsius."""
    return temp_kelvin - 273.15


def format_wavelength(wavelength_nm: float, include_energy: bool = True) -> str:
    """
    Format wavelength with optional energy.

    Args:
        wavelength_nm: Wavelength in nm
        include_energy: If True, include energy in meV

    Returns:
        Formatted string
    """
    if include_energy:
        energy_meV = nm_to_meV(wavelength_nm)
        return f"{wavelength_nm:.2f} nm ({energy_meV:.2f} meV)"
    else:
        return f"{wavelength_nm:.2f} nm"


def format_power(power_w: float, unit: str = 'auto') -> str:
    """
    Format power with appropriate unit.

    Args:
        power_w: Power in watts
        unit: Unit to use ('auto', 'W', 'mW', 'µW', 'nW')

    Returns:
        Formatted string
    """
    if unit == 'auto':
        if power_w >= 1:
            return f"{power_w:.3f} W"
        elif power_w >= 1e-3:
            return f"{power_w * 1e3:.3f} mW"
        elif power_w >= 1e-6:
            return f"{power_w * 1e6:.3f} µW"
        else:
            return f"{power_w * 1e9:.3f} nW"
    elif unit == 'W':
        return f"{power_w:.3f} W"
    elif unit == 'mW':
        return f"{power_w * 1e3:.3f} mW"
    elif unit == 'µW':
        return f"{power_w * 1e6:.3f} µW"
    elif unit == 'nW':
        return f"{power_w * 1e9:.3f} nW"
    else:
        raise ValueError(f"Unknown unit: {unit}")
