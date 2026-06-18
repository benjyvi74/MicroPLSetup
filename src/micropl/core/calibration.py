"""
Calibration procedures for laser power and alignment.
"""

import logging
from typing import List, Optional, Dict, Any
import numpy as np

logger = logging.getLogger(__name__)


class SpectrometerCalibration:
    """
    Manage pixel-to-wavelength conversion for a Czerny-Turner spectrometer.
    Based on the Horiba (e.g. FHR640) physical model and Excel formulas provided by the user.
    """

    def __init__(self, focal_length_mm: float,
                 deviation_deg: float,
                 sensor_tilt_deg: float,
                 pixel_stride_um: float):
        # f: Focal length of the spectrometer (distance from grating to sensor)
        self.f = focal_length_mm
        
        # delta: Half of the total deviation angle between incident and diffracted beams
        self.delta = np.deg2rad(deviation_deg / 2.0)
        
        # gamma: Tilt angle of the CCD sensor relative to the focal plane normal
        self.gamma = np.deg2rad(sensor_tilt_deg)
        
        # pixel_stride: Physical distance between adjacent pixels on the sensor
        self.pixel_stride = pixel_stride_um * 1e-3  # convert um to mm
        
        # Current state
        self.center_wavelength = 0.0
        self.grating_g_mm = 0.0
        self.order = 1
        self.center_pixel = 0.0

    def update_params(self, center_wavelength: float, grating_g_mm: float, 
                      center_pixel: float, order: int = 1):
        """Update the physical state based on current monochromator/camera settings."""
        self.center_wavelength = center_wavelength
        self.grating_g_mm = grating_g_mm
        self.order = order
        self.center_pixel = center_pixel

    def update_pixel_stride(self, pixel_stride_um: float):
        """Update the pixel stride (magnitude and sign)."""
        self.pixel_stride = pixel_stride_um * 1e-3
        logger.info(f"Calibration: Pixel stride updated to {pixel_stride_um} um")

    @staticmethod
    def get_max_wavelength_nm(grating_g_mm: float, order: int = 1,
                              deviation_deg: float = 18.5) -> float:
        """
        Return the maximum physically reachable center wavelength (nm) for a
        given grating, based on the grating equation limit |sin θ| <= 1.

        λ_max = 2·cos(δ) / (k·G)  [converted mm → nm]

        Args:
            grating_g_mm: Grating groove density in lines/mm
            order: Diffraction order (default 1)
            deviation_deg: Total deviation angle of the spectrometer (default 18.5°)
        """
        if grating_g_mm <= 0:
            return float('inf')
        delta = np.deg2rad(deviation_deg / 2.0)
        # Using the researcher's specific FHR640 model: (2*cos(delta)^2)/(k*G)
        return (2.0 * np.cos(delta)**2) / (order * grating_g_mm) * 1e6

    def get_wavelength_axis(self, num_pixels: int, roi_offset: int = 0, hbin: int = 1) -> np.ndarray:
        """
        Produce a wavelength axis (nm) for the given sensor pixels.
        
        Args:
            num_pixels: Number of pixels in the (binned) ROI
            roi_offset: The start pixel of the ROI (physical pixels)
            hbin: Horizontal binning factor
        """
        if self.grating_g_mm == 0:
            return np.zeros(num_pixels)

        # 1. Grating angle theta
        # sin(theta) = k * G * lambda_c / (2 * cos(delta))
        # lambda_c is in nm, G is lines / mm
        # Convert lambda_c to mm: lambda_c * 1e-6
        sin_theta = (self.order * self.grating_g_mm * self.center_wavelength * 1e-6) / (2.0 * np.cos(self.delta))

        # Guard: warn if center wavelength is beyond the grating equation limit
        if abs(sin_theta) > 1.0:
            max_wl = self.get_max_wavelength_nm(
                self.grating_g_mm, self.order,
                deviation_deg=np.rad2deg(self.delta) * 2.0
            )
            logger.warning(
                f"Center wavelength {self.center_wavelength:.1f} nm exceeds the physical "
                f"limit for grating {self.grating_g_mm:.0f} g/mm (max ≈ {max_wl:.1f} nm, "
                f"sin_theta={sin_theta:.3f}). Wavelength axis will be invalid."
            )

        # Clamp to [-1, 1] to avoid math errors if out of bounds
        theta = np.arcsin(np.clip(sin_theta, -1, 1))
        
        # 2. In-plane angles alpha and beta
        alpha = theta - self.delta
        beta = theta + self.delta
        
        # 3. Calculate wavelength for each pixel
        # Vectorized calculation for binned pixels
        # Physical position of binned pixel center:
        indices = np.arange(num_pixels)
        x = (roi_offset + (indices + 0.5) * hbin - self.center_pixel) * self.pixel_stride
        
        # Exit angle offset delta_psi (using confirmed G7 formula: ATAN(x / (f * cos(gamma)) - tan(gamma)) + gamma)
        delta_psi = np.arctan(x / (self.f * np.cos(self.gamma)) - np.tan(self.gamma)) + self.gamma

        # Final wavelength lambda = (sin(beta + delta_psi) + sin(alpha)) / (k * G)
        # Convert result (mm) to nm by multiplying 1e6
        wavelengths = (np.sin(beta + delta_psi) + np.sin(alpha)) / (self.order * self.grating_g_mm) * 1e6
        
        return wavelengths


class PolarizerCalibration:
    """
    Manage polarizer-to-power calibration mapping.
    Maps target power levels to polarizer angles.
    """

    def __init__(self):
        self.points: List[Dict[str, Any]] = []  # List of {'power': float, 'unit': str, 'angle': float}
        self._interp_x: Optional[np.ndarray] = None
        self._interp_y: Optional[np.ndarray] = None

    def add_point(self, power: float, unit: str, angle: float):
        """Add or update a calibration point."""
        # Convert to Watts for internal consistency if needed, but keeping original for UI
        self.points.append({
            'power': power,
            'unit': unit,
            'angle': angle
        })
        self._update_interpolation()

    def clear(self):
        """Clear all calibration points."""
        self.points = []
        self._interp_x = None
        self._interp_y = None

    def _update_interpolation(self):
        """Prepare interpolation arrays (Power in Watts vs Angle)."""
        if len(self.points) == 0:
            self._interp_x = None
            self._interp_y = None
            return

        multipliers = {"nW": 1e-9, "µW": 1e-6, "mW": 1e-3}
        
        # Extract power in Watts and angles
        data = []
        for p in self.points:
            p_w = p['power'] * multipliers.get(p['unit'], 1.0)
            data.append((p_w, p['angle']))
        
        # Sort by power
        data.sort()
        self._interp_x = np.array([d[0] for d in data])
        self._interp_y = np.array([d[1] for d in data])

    def get_angle_for_power(self, power_w: float) -> Optional[float]:
        """Get the calibrated angle for a target power in Watts."""
        if self._interp_x is None or self._interp_y is None or len(self._interp_x) == 0:
            return None
        if len(self._interp_x) == 1:
            if np.isclose(power_w, self._interp_x[0], rtol=1e-3, atol=1e-9):
                return float(self._interp_y[0])
            return None
        
        min_p = self._interp_x[0]
        max_p = self._interp_x[-1]
        if power_w < min_p and not np.isclose(power_w, min_p, rtol=1e-3, atol=1e-9):
            return None
        if power_w > max_p and not np.isclose(power_w, max_p, rtol=1e-3, atol=1e-9):
            return None
            
        return float(np.interp(power_w, self._interp_x, self._interp_y))

    def save(self, filepath: str):
        """Save calibration to a JSON file."""
        import json
        with open(filepath, 'w') as f:
            json.dump(self.points, f, indent=4)
        logger.info(f"Polarizer calibration saved to {filepath}")

    def load(self, filepath: str):
        """Load calibration from a JSON file."""
        import json
        try:
            with open(filepath, 'r') as f:
                self.points = json.load(f)
            self._update_interpolation()
            logger.info(f"Polarizer calibration loaded from {filepath}")
        except Exception as e:
            logger.error(f"Failed to load polarizer calibration: {e}")
            raise
