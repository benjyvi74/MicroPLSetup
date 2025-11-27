"""
Tests for hardware abstraction modules.
"""

import pytest

from micropl.hardware.factory import create_instrument, DRIVER_REGISTRY
from micropl.hardware.stage import StageStub
from micropl.hardware.pm100 import PM100


class TestFactory:
    """Tests for instrument factory."""

    def test_list_drivers(self):
        """Test listing available drivers."""
        drivers = list(DRIVER_REGISTRY.keys())
        assert 'stage' in drivers
        assert 'pm100' in drivers
        assert 'kdc101' in drivers

    def test_create_stage(self):
        """Test creating stage instrument."""
        stage = create_instrument('stage')
        assert isinstance(stage, StageStub)

    def test_create_with_config(self):
        """Test creating instrument with configuration."""
        config = {'x_range': [0, 50], 'y_range': [0, 50]}
        stage = create_instrument('stage', config)

        assert stage.x_range == [0, 50]
        assert stage.y_range == [0, 50]

    def test_unknown_instrument(self):
        """Test creating unknown instrument type."""
        with pytest.raises(ValueError):
            create_instrument('unknown_device')


class TestStageStub:
    """Tests for StageStub."""

    def test_connect(self):
        """Test stage connection."""
        stage = StageStub()
        assert not stage.is_connected()

        stage.connect()
        assert stage.is_connected()

        stage.disconnect()
        assert not stage.is_connected()

    def test_move_to(self):
        """Test absolute movement."""
        stage = StageStub()
        stage.connect()

        stage.move_to(10, 20)
        x, y = stage.get_position()

        assert x == 10
        assert y == 20

    def test_move_by(self):
        """Test relative movement."""
        stage = StageStub()
        stage.connect()

        stage.move_to(10, 10)
        stage.move_by(5, -5)

        x, y = stage.get_position()
        assert x == 15
        assert y == 5

    def test_bounds_checking(self):
        """Test movement bounds checking."""
        config = {'x_range': [0, 100], 'y_range': [0, 100]}
        stage = StageStub(config)
        stage.connect()

        # Valid movement
        stage.move_to(50, 50)

        # Out of bounds should raise error
        with pytest.raises(ValueError):
            stage.move_to(150, 50)

        with pytest.raises(ValueError):
            stage.move_to(50, 150)

    def test_home(self):
        """Test homing."""
        stage = StageStub()
        stage.connect()

        stage.move_to(50, 50)
        stage.home()

        x, y = stage.get_position()
        assert x == 0
        assert y == 0


class TestPM100:
    """Tests for PM100 power meter."""

    def test_connect(self):
        """Test power meter connection."""
        pm = PM100()
        assert not pm.is_connected()

        pm.connect()
        assert pm.is_connected()

        pm.disconnect()
        assert not pm.is_connected()

    def test_wavelength(self):
        """Test wavelength setting."""
        pm = PM100({'wavelength': 532})
        pm.connect()

        assert pm.get_wavelength() == 532

        pm.set_wavelength(650)
        assert pm.get_wavelength() == 650

    def test_read_power(self):
        """Test power reading (stub returns random values)."""
        pm = PM100()
        pm.connect()

        power = pm.read_power()
        assert isinstance(power, float)
        assert power >= 0


class TestInstrumentBase:
    """Tests for base instrument functionality."""

    def test_requires_connection(self):
        """Test that operations require connection."""
        stage = StageStub()

        # Should raise error when not connected
        with pytest.raises(RuntimeError):
            stage.get_position()

        # Should work after connection
        stage.connect()
        pos = stage.get_position()
        assert pos == (0.0, 0.0)

    def test_get_info(self):
        """Test getting instrument information."""
        stage = StageStub()
        stage.connect()

        info = stage.get_info()
        assert 'type' in info
        assert 'position' in info


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
