"""
Complete experiment workflows.
"""

import logging
from typing import List, Optional, Callable
from datetime import datetime

from .sequence import MeasurementSequence, SequenceStep
from .measurement import MeasurementController, MeasurementResult

logger = logging.getLogger(__name__)


class Experiment:
    """Manage complete measurement experiments."""

    def __init__(self, name: str, measurement_controller: MeasurementController):
        self.name = name
        self.controller = measurement_controller
        self.sequence: Optional[MeasurementSequence] = None
        self.results: List[MeasurementResult] = []

        self._running = False
        self._paused = False

        # Callbacks
        self.on_step_complete: Optional[Callable] = None
        self.on_experiment_complete: Optional[Callable] = None
        self.on_error: Optional[Callable] = None

        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None

    def set_sequence(self, sequence: MeasurementSequence) -> None:
        """Set the measurement sequence for this experiment."""
        self.sequence = sequence
        logger.info(f"Experiment '{self.name}': sequence set with {len(sequence)} steps")

    def start(self) -> None:
        """Start the experiment."""
        if self.sequence is None:
            raise RuntimeError("No sequence defined for experiment")

        if self._running:
            logger.warning("Experiment already running")
            return

        logger.info(f"Starting experiment: {self.name}")
        self._running = True
        self._paused = False
        self.results.clear()
        self.sequence.reset()
        self.start_time = datetime.now()

        self._run_sequence()

    def _run_sequence(self) -> None:
        """Execute the measurement sequence."""
        try:
            while not self.sequence.is_complete() and self._running:
                if self._paused:
                    continue

                step = self.sequence.get_current_step()
                logger.info(f"Executing step {self.sequence.current_step_index + 1}/"
                           f"{len(self.sequence)}: {step}")

                result = self._execute_step(step)
                self.results.append(result)

                if self.on_step_complete:
                    self.on_step_complete(step, result)

                self.sequence.next_step()

            # Experiment complete
            self.stop()

            if self.on_experiment_complete:
                self.on_experiment_complete(self)

        except Exception as e:
            logger.error(f"Error during experiment: {e}", exc_info=True)

            if self.on_error:
                self.on_error(e)

            self.stop()
            raise

    def _execute_step(self, step: SequenceStep) -> MeasurementResult:
        """
        Execute a single measurement step.

        Args:
            step: SequenceStep to execute

        Returns:
            MeasurementResult
        """
        # Move stage if position specified
        if step.position is not None and self.controller.stage is not None:
            x, y = step.position
            self.controller.stage.move_to(x, y)

        # Set wavelength if specified
        if step.wavelength is not None and self.controller.spectrometer is not None:
            self.controller.spectrometer.set_center_wavelength(step.wavelength)

        # Determine acquisition type (could be made explicit in step)
        # For now, default to spectrum if spectrometer available
        if self.controller.spectrometer is not None:
            result = self.controller.acquire_spectrum(
                sample_number=step.sample_number,
                power=step.power,
                integration_time=step.integration_time,
                **step.metadata
            )
        elif self.controller.camera is not None:
            result = self.controller.acquire_image(
                sample_number=step.sample_number,
                power=step.power,
                exposure_time=step.integration_time,
                **step.metadata
            )
        else:
            raise RuntimeError("No acquisition device available")

        return result

    def pause(self) -> None:
        """Pause the experiment."""
        if not self._running:
            logger.warning("Experiment not running")
            return

        logger.info("Pausing experiment")
        self._paused = True

    def resume(self) -> None:
        """Resume paused experiment."""
        if not self._running or not self._paused:
            logger.warning("Experiment not paused")
            return

        logger.info("Resuming experiment")
        self._paused = False

    def stop(self) -> None:
        """Stop the experiment."""
        if not self._running:
            return

        logger.info("Stopping experiment")
        self._running = False
        self._paused = False
        self.end_time = datetime.now()

        if self.start_time:
            duration = (self.end_time - self.start_time).total_seconds()
            logger.info(f"Experiment duration: {duration:.1f} seconds")

    def is_running(self) -> bool:
        """Check if experiment is running."""
        return self._running

    def is_paused(self) -> bool:
        """Check if experiment is paused."""
        return self._paused

    def get_progress(self) -> tuple:
        """
        Get experiment progress.

        Returns:
            (current_step, total_steps, percent_complete)
        """
        if self.sequence is None:
            return (0, 0, 0.0)

        current, total = self.sequence.get_progress()
        percent = (current / total * 100) if total > 0 else 0.0

        return (current, total, percent)

    def get_results(self) -> List[MeasurementResult]:
        """Get all measurement results."""
        return self.results

    def get_summary(self) -> dict:
        """Get experiment summary."""
        duration = None
        if self.start_time and self.end_time:
            duration = (self.end_time - self.start_time).total_seconds()

        return {
            'name': self.name,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'duration': duration,
            'num_steps': len(self.sequence) if self.sequence else 0,
            'num_results': len(self.results),
            'status': 'running' if self._running else 'complete',
        }
