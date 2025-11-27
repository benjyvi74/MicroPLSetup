"""
Tests for core business logic modules.
"""

import pytest
import numpy as np
from datetime import datetime

from micropl.core.sequence import MeasurementSequence, SequenceStep
from micropl.core.measurement import MeasurementResult, MeasurementController
from micropl.core.calibration import PowerCalibration, AlignmentCalibration
from micropl.core.data_manager import DataManager


class TestSequence:
    """Tests for MeasurementSequence."""

    def test_create_sequence(self):
        """Test creating an empty sequence."""
        seq = MeasurementSequence()
        assert len(seq) == 0
        assert seq.is_complete()

    def test_add_step(self):
        """Test adding steps to sequence."""
        seq = MeasurementSequence()
        seq.add_step(sample_number=1, power=0.5, integration_time=1.0)
        seq.add_step(sample_number=2, power=1.0, integration_time=2.0)

        assert len(seq) == 2
        assert not seq.is_complete()

    def test_sequence_iteration(self):
        """Test iterating through sequence."""
        seq = MeasurementSequence()
        seq.add_step(sample_number=1, power=0.5, integration_time=1.0)
        seq.add_step(sample_number=2, power=1.0, integration_time=2.0)

        steps = list(seq)
        assert len(steps) == 2
        assert steps[0].sample_number == 1
        assert steps[1].sample_number == 2

    def test_power_sweep(self):
        """Test creating power sweep sequence."""
        seq = MeasurementSequence.create_power_sweep(
            sample_number=1,
            power_range=(0.1, 1.0),
            num_points=10,
            integration_time=1.0
        )

        assert len(seq) == 10
        powers = [step.power for step in seq]
        assert powers[0] == pytest.approx(0.1)
        assert powers[-1] == pytest.approx(1.0)

    def test_sequence_progress(self):
        """Test sequence progress tracking."""
        seq = MeasurementSequence()
        seq.add_step(1, 0.5, 1.0)
        seq.add_step(2, 1.0, 1.0)

        current, total = seq.get_progress()
        assert current == 0
        assert total == 2

        seq.next_step()
        current, total = seq.get_progress()
        assert current == 1
        assert total == 2


class TestMeasurementResult:
    """Tests for MeasurementResult."""

    def test_create_result(self):
        """Test creating a measurement result."""
        result = MeasurementResult(
            timestamp=datetime.now(),
            sample_number=1,
            power=0.5,
            integration_time=1.0
        )

        assert result.sample_number == 1
        assert result.power == 0.5
        assert not result.has_spectrum()
        assert not result.has_image()

    def test_result_with_spectrum(self):
        """Test result with spectrum data."""
        wavelengths = np.linspace(600, 800, 100)
        intensities = np.random.rand(100)

        result = MeasurementResult(
            timestamp=datetime.now(),
            sample_number=1,
            power=0.5,
            integration_time=1.0,
            wavelengths=wavelengths,
            intensities=intensities
        )

        assert result.has_spectrum()
        assert len(result.wavelengths) == 100

    def test_result_with_image(self):
        """Test result with image data."""
        image = np.random.rand(512, 512)

        result = MeasurementResult(
            timestamp=datetime.now(),
            sample_number=1,
            power=0.5,
            integration_time=1.0,
            image=image
        )

        assert result.has_image()
        assert result.image.shape == (512, 512)


class TestPowerCalibration:
    """Tests for PowerCalibration."""

    def test_create_calibration(self):
        """Test creating power calibration."""
        cal = PowerCalibration()
        assert len(cal.calibration_data) == 0

    def test_add_calibration_point(self):
        """Test adding calibration points."""
        cal = PowerCalibration()
        cal.add_calibration_point(0.5, 0.45)
        cal.add_calibration_point(1.0, 0.95)

        assert len(cal.calibration_data) == 2

    def test_fit_calibration(self):
        """Test fitting calibration curve."""
        cal = PowerCalibration()

        # Add some linear calibration data
        for setpoint in np.linspace(0.1, 1.0, 10):
            measured = setpoint * 0.95  # 5% loss
            cal.add_calibration_point(setpoint, measured)

        cal.fit_calibration(degree=1)

        # Test prediction
        predicted = cal.get_corrected_power(0.5)
        assert predicted == pytest.approx(0.475, rel=0.1)


class TestDataManager:
    """Tests for DataManager."""

    def test_create_data_manager(self, tmp_path):
        """Test creating data manager."""
        dm = DataManager(data_root=str(tmp_path))
        assert dm.data_root.exists()

    def test_save_and_load_spectrum(self, tmp_path):
        """Test saving and loading spectrum data."""
        dm = DataManager(data_root=str(tmp_path))

        # Create test result
        wavelengths = np.linspace(600, 800, 100)
        intensities = np.random.rand(100)

        result = MeasurementResult(
            timestamp=datetime.now(),
            sample_number=1,
            power=0.5,
            integration_time=1.0,
            wavelengths=wavelengths,
            intensities=intensities
        )

        # Save
        filepath = dm.save_spectrum(result)
        assert filepath.exists()

        # Load
        loaded = dm.load_spectrum(str(filepath))
        assert loaded.sample_number == result.sample_number
        assert loaded.power == result.power
        assert len(loaded.wavelengths) == len(wavelengths)

    def test_save_image(self, tmp_path):
        """Test saving image data."""
        dm = DataManager(data_root=str(tmp_path))

        # Create test result
        image = np.random.rand(512, 512)

        result = MeasurementResult(
            timestamp=datetime.now(),
            sample_number=1,
            power=0.5,
            integration_time=1.0,
            image=image
        )

        # Save
        filepath = dm.save_image(result)
        assert filepath.exists()

        # Load and verify
        loaded_image = np.load(filepath)
        assert loaded_image.shape == image.shape


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
