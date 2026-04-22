"""
Calibration procedures for laser power and alignment.
"""

import logging
from typing import List, Tuple, Optional, Dict, Any
import numpy as np

logger = logging.getLogger(__name__)


class PowerCalibration:
    """Manage laser power calibration."""

    def __init__(self, power_meter=None):
        self.power_meter = power_meter
        self.calibration_data: List[Tuple[float, float]] = []  # (setpoint, measured)
        self._coefficients: Optional[np.ndarray] = None

    def add_calibration_point(self, setpoint: float, measured: float) -> None:
        """
        Add a calibration point.

        Args:
            setpoint: Commanded power value
            measured: Measured power from power meter
        """
        self.calibration_data.append((setpoint, measured))
        logger.info(f"Added calibration point: setpoint={setpoint}, measured={measured}")

    def perform_calibration(self, num_points: int = 10,
                           power_range: Tuple[float, float] = (0.1, 1.0)) -> None:
        """
        Perform automatic power calibration sweep.

        Args:
            num_points: Number of calibration points
            power_range: (min, max) power range to calibrate
        """
        if self.power_meter is None:
            raise RuntimeError("Power meter not configured")

        logger.info(f"Starting power calibration: {num_points} points")
        self.calibration_data.clear()

        setpoints = np.linspace(power_range[0], power_range[1], num_points)

        for setpoint in setpoints:
            # TODO: Set laser power to setpoint
            # time.sleep(0.5)  # Wait for stabilization

            measured = self.power_meter.read_power()
            self.add_calibration_point(setpoint, measured)

        self.fit_calibration()

    def fit_calibration(self, degree: int = 1) -> None:
        """
        Fit calibration curve to data.

        Args:
            degree: Polynomial degree for fitting (1=linear, 2=quadratic, etc.)
        """
        if len(self.calibration_data) < 2:
            raise ValueError("Need at least 2 calibration points")

        setpoints, measured = zip(*self.calibration_data)
        self._coefficients = np.polyfit(setpoints, measured, degree)

        logger.info(f"Calibration fitted with {degree}-degree polynomial")
        logger.debug(f"Coefficients: {self._coefficients}")

    def get_corrected_power(self, setpoint: float) -> float:
        """
        Get expected power for a given setpoint.

        Args:
            setpoint: Commanded power value

        Returns:
            Expected actual power based on calibration
        """
        if self._coefficients is None:
            raise RuntimeError("Calibration not fitted")

        return np.polyval(self._coefficients, setpoint)

    def get_setpoint_for_power(self, target_power: float, tolerance: float = 0.01) -> float:
        """
        Calculate setpoint needed to achieve target power.

        Args:
            target_power: Desired actual power
            tolerance: Convergence tolerance

        Returns:
            Setpoint value to use
        """
        if self._coefficients is None:
            raise RuntimeError("Calibration not fitted")

        # Simple iterative search (could use more sophisticated method)
        setpoint_guess = target_power
        for _ in range(100):
            predicted = self.get_corrected_power(setpoint_guess)
            error = target_power - predicted

            if abs(error) < tolerance:
                return setpoint_guess

            setpoint_guess += error * 0.5  # Simple correction

        logger.warning("Power setpoint search did not fully converge")
        return setpoint_guess

    def save_calibration(self, filepath: str) -> None:
        """Save calibration data to file."""
        np.savez(filepath,
                 calibration_data=self.calibration_data,
                 coefficients=self._coefficients)
        logger.info(f"Calibration saved to {filepath}")

    def load_calibration(self, filepath: str) -> None:
        """Load calibration data from file."""
        data = np.load(filepath, allow_pickle=True)
        self.calibration_data = list(data['calibration_data'])
        self._coefficients = data['coefficients']
        logger.info(f"Calibration loaded from {filepath}")


class AlignmentCalibration:
    """Manage sample alignment procedures."""

    def __init__(self, stage=None, camera=None):
        self.stage = stage
        self.camera = camera
        self.reference_position: Optional[Tuple[float, float]] = None

    def find_peak_intensity(self) -> Tuple[float, float]:
        """
        Find position of maximum intensity by scanning.

        Returns:
            (x, y) position of peak intensity
        """
        if self.stage is None or self.camera is None:
            raise RuntimeError("Stage and camera required for alignment")

        logger.info("Searching for peak intensity position")

        # TODO: Implement intelligent search algorithm
        # - Coarse grid scan
        # - Fine scan around maximum
        # - Possibly gradient-based optimization

        # Stub: return current position
        return self.stage.get_position()

    def set_reference_position(self, x: Optional[float] = None,
                              y: Optional[float] = None) -> None:
        """
        Set reference alignment position.

        Args:
            x: X position (if None, use current)
            y: Y position (if None, use current)
        """
        if x is None or y is None:
            x, y = self.stage.get_position()

        self.reference_position = (x, y)
        logger.info(f"Reference position set to ({x}, {y})")

    def return_to_reference(self) -> None:
        """Move stage back to reference position."""
        if self.reference_position is None:
            raise RuntimeError("No reference position set")

        x, y = self.reference_position
        self.stage.move_to(x, y)
        logger.info(f"Returned to reference position: ({x}, {y})")

    def optimize_alignment(self, tolerance: float = 0.01) -> Tuple[float, float]:
        """
        Optimize alignment to maximize signal.

        Args:
            tolerance: Position tolerance in mm

        Returns:
            Optimized (x, y) position
        """
        logger.info("Optimizing alignment")

        # TODO: Implement optimization algorithm
        # - Could use gradient ascent, simplex, or other method
        # - Monitor signal from camera or power meter

        optimal_position = self.find_peak_intensity()
        self.set_reference_position(*optimal_position)

        return optimal_position

class SpectrometerCalibration:
    """
    Manage pixel-to-wavelength conversion for a Czerny-Turner spectrometer.
    Based on the FHR640 physical model and Excel formulas provided by the user.
    """

    def __init__(self, focal_length_mm: float,
                 deviation_deg: float,
                 sensor_tilt_deg: float,
                 pixel_stride_um: float):
        self.f = focal_length_mm
        self.delta = np.deg2rad(deviation_deg / 2.0)
        self.gamma = np.deg2rad(sensor_tilt_deg)
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
        self.points: List[Dict[str, float]] = []  # List of {'power': float, 'unit': str, 'angle': float}
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
        if len(self.points) < 2:
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
        if self._interp_x is None or len(self._interp_x) < 2:
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
