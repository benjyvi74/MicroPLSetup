"""
Measurement sequence management (n-P-t table).
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class SequenceStep:
    """Single step in a measurement sequence."""

    sample_number: int
    power: float  # Laser power in watts
    integration_time: float  # Integration time in seconds
    position: Optional[tuple] = None  # (x, y) stage position
    wavelength: Optional[float] = None  # Center wavelength for spectrometer
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (f"Step(n={self.sample_number}, P={self.power}W, "
                f"t={self.integration_time}s)")


class MeasurementSequence:
    """Manage a sequence of measurements (n-P-t table)."""

    def __init__(self):
        self.steps: List[SequenceStep] = []
        self.current_step_index: int = 0

    def add_step(self, sample_number: int, power: float,
                 integration_time: float, **kwargs) -> None:
        """
        Add a step to the sequence.

        Args:
            sample_number: Sample identifier
            power: Laser power in watts
            integration_time: Integration time in seconds
            **kwargs: Additional parameters (position, wavelength, metadata)
        """
        step = SequenceStep(
            sample_number=sample_number,
            power=power,
            integration_time=integration_time,
            **kwargs
        )
        self.steps.append(step)
        logger.debug(f"Added {step}")

    def remove_step(self, index: int) -> None:
        """Remove step at given index."""
        if 0 <= index < len(self.steps):
            removed = self.steps.pop(index)
            logger.debug(f"Removed step {index}: {removed}")
        else:
            raise IndexError(f"Step index {index} out of range")

    def clear(self) -> None:
        """Clear all steps from sequence."""
        self.steps.clear()
        self.current_step_index = 0
        logger.info("Sequence cleared")

    def get_step(self, index: int) -> SequenceStep:
        """Get step at given index."""
        return self.steps[index]

    def get_current_step(self) -> Optional[SequenceStep]:
        """Get current step in sequence."""
        if 0 <= self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None

    def next_step(self) -> Optional[SequenceStep]:
        """Advance to next step and return it."""
        self.current_step_index += 1
        return self.get_current_step()

    def reset(self) -> None:
        """Reset sequence to beginning."""
        self.current_step_index = 0
        logger.info("Sequence reset to beginning")

    def is_complete(self) -> bool:
        """Check if sequence is complete."""
        return self.current_step_index >= len(self.steps)

    def get_progress(self) -> tuple:
        """Get current progress (current, total)."""
        return (self.current_step_index, len(self.steps))

    def __len__(self) -> int:
        """Number of steps in sequence."""
        return len(self.steps)

    def __iter__(self):
        """Iterate over steps."""
        return iter(self.steps)

    # Convenience methods for creating common sequences

    @classmethod
    def create_power_sweep(cls, sample_number: int,
                          power_range: tuple,
                          num_points: int,
                          integration_time: float) -> 'MeasurementSequence':
        """
        Create a power sweep sequence.

        Args:
            sample_number: Sample identifier
            power_range: (min, max) power in watts
            num_points: Number of power points
            integration_time: Integration time per point

        Returns:
            MeasurementSequence with power sweep
        """
        seq = cls()
        powers = np.linspace(power_range[0], power_range[1], num_points)

        for power in powers:
            seq.add_step(sample_number, power, integration_time)

        logger.info(f"Created power sweep: {num_points} points from "
                   f"{power_range[0]} to {power_range[1]} W")
        return seq

    @classmethod
    def create_time_series(cls, sample_number: int,
                          power: float,
                          integration_time: float,
                          num_measurements: int) -> 'MeasurementSequence':
        """
        Create a time series at fixed power.

        Args:
            sample_number: Sample identifier
            power: Laser power in watts
            integration_time: Integration time per measurement
            num_measurements: Number of measurements

        Returns:
            MeasurementSequence with time series
        """
        seq = cls()

        for _ in range(num_measurements):
            seq.add_step(sample_number, power, integration_time)

        logger.info(f"Created time series: {num_measurements} measurements at "
                   f"{power} W")
        return seq

    @classmethod
    def create_multi_sample(cls, sample_numbers: List[int],
                           power: float,
                           integration_time: float) -> 'MeasurementSequence':
        """
        Create sequence measuring multiple samples at same conditions.

        Args:
            sample_numbers: List of sample identifiers
            power: Laser power in watts
            integration_time: Integration time per sample

        Returns:
            MeasurementSequence for multiple samples
        """
        seq = cls()

        for sample_num in sample_numbers:
            seq.add_step(sample_num, power, integration_time)

        logger.info(f"Created multi-sample sequence: {len(sample_numbers)} samples")
        return seq

    def to_dict(self) -> Dict[str, Any]:
        """Export sequence to dictionary."""
        return {
            'steps': [
                {
                    'sample_number': step.sample_number,
                    'power': step.power,
                    'integration_time': step.integration_time,
                    'position': step.position,
                    'wavelength': step.wavelength,
                    'metadata': step.metadata,
                }
                for step in self.steps
            ],
            'current_step': self.current_step_index,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MeasurementSequence':
        """Create sequence from dictionary."""
        seq = cls()
        for step_data in data['steps']:
            seq.add_step(**step_data)
        seq.current_step_index = data.get('current_step', 0)
        return seq
