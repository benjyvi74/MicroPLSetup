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
