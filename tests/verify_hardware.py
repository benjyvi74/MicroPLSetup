import pytest
import logging
import time
import numpy as np
from micropl.hardware.manager import HardwareManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@pytest.fixture(scope="module")
def hw_manager():
    """Provides a HardwareManager instance with default config."""
    # Reset singleton to ensure fresh state
    HardwareManager._instance = None
    mgr = HardwareManager()
    return mgr

@pytest.mark.camera
class TestAndorCamera:
    """Rigorous tests for Andor cameras (SDK2/SDK3)."""
    
    @pytest.fixture(autouse=True)
    def setup_camera(self, hw_manager):
        self.cam = hw_manager.initialize_instrument('spec_camera', 'andor_camera')
        self.cam.connect()
        yield
        self.cam.disconnect()

    def test_basic_info(self):
        info = self.cam.get_info()
        logger.info(f"Camera Info: {info}")
        assert 'model' in info
        assert 'serial' in info

    def test_cooling_and_temp(self):
        """Test cooling control and temperature reading."""
        self.cam.set_cooling(True)
        # We don't wait for it to reach target, just verify it's active
        temp = self.cam.get_temperature()
        logger.info(f"Current Temperature: {temp}")
        assert isinstance(temp, (int, float))

    def test_acquisition_and_roi(self):
        """Test image acquisition with a specific ROI."""
        # Set a 100x100 ROI in the center
        roi = (500, 600, 100, 200, 1, 1) # hstart, hend, vstart, vend, hbin, vbin
        self.cam.apply_roi(roi)
        
        img = self.cam.acquire_image()
        assert img is not None
        # Shape depends on Andor's internal orientation, but should match ROI width x height
        # Note: Some Andor readout orientations might swap axes.
        assert img.size == 100 * 100
        logger.info(f"Acquired ROI image: {img.shape}")

    def test_exposure_control(self):
        """Test setting and getting exposure time."""
        target = 0.05 # 50ms
        self.cam.set_exposure(target)
        actual = self.cam.get_exposure()
        logger.info(f"Exposure set: {target}, actual: {actual}")
        # Allow small floating point tolerance
        assert abs(actual - target) < 0.005

@pytest.mark.mono
class TestFHR640:
    """Rigorous tests for FHR640 Serial Spectrometer."""

    @pytest.fixture(autouse=True)
    def setup_mono(self, hw_manager):
        self.mono = hw_manager.initialize_instrument('mono', 'fhr640')
        self.mono.connect()
        yield
        self.mono.disconnect()

    def test_movement_and_polling(self):
        """Test moving wavelength and polling for completion."""
        start_wl = self.mono.get_current_wavelength()
        target_wl = start_wl + 10.0
        
        logger.info(f"Moving from {start_wl} to {target_wl}...")
        self.mono.set_center_wavelength(target_wl)
        
        final_wl = self.mono.get_current_wavelength()
        logger.info(f"Reached {final_wl}")
        assert abs(final_wl - target_wl) < 0.1

    def test_grating_switch(self):
        """Test switching grating (Note: Can be slow)."""
        # Read current index
        curr_idx = self.mono.get_grating(force_read=True)
        # Switch to another one (0, 1, or 2)
        new_idx = (curr_idx + 1) % 3
        
        logger.info(f"Switching grating from {curr_idx} to {new_idx}...")
        self.mono.set_grating(new_idx)
        
        check_idx = self.mono.get_grating(force_read=True)
        assert check_idx == new_idx
        logger.info(f"Grating switch complete: {check_idx}")

    def test_slit_control(self):
        """Test moving entrance and exit slits."""
        # Test entrance slit (0)
        width = 150 # um
        self.mono.set_slit_width(width, slit_id=0)
        check_width = self.mono.get_slit_width(slit_id=0)
        logger.info(f"Slit 0 set to {width}, read back {check_width}")
        assert abs(check_width - width) < 5 # Allow small step rounding

@pytest.mark.pm
def test_pm100_sync(hw_manager):
    """Test PM100 Power Meter and wavelength synchronization."""
    pm = hw_manager.initialize_instrument('pm100', 'pm100')
    pm.connect()
    try:
        # Test basic power read
        p = pm.read_power()
        logger.info(f"Power: {p} W")
        
        # Test wavelength sync
        test_wl = 633.0
        pm.set_wavelength(test_wl)
        read_wl = pm.get_wavelength()
        assert read_wl == test_wl
        logger.info(f"PM100 Wavelength set to {read_wl}")
    finally:
        pm.disconnect()

@pytest.mark.motor
def test_kdc101_accuracy(hw_manager):
    """Test KDC101 Motor repetitive movement."""
    kdc = hw_manager.initialize_instrument('kdc101', 'kdc101')
    kdc.connect()
    try:
        start_pos = kdc.get_position()
        # Move forward and back
        dist = 5.0
        logger.info(f"Testing movement: {start_pos} -> {start_pos + dist} -> {start_pos}")
        
        kdc.move_to(start_pos + dist)
        kdc.wait_for_move()
        assert abs(kdc.get_position() - (start_pos + dist)) < 0.01
        
        kdc.move_to(start_pos)
        kdc.wait_for_move()
        assert abs(kdc.get_position() - start_pos) < 0.01
    finally:
        kdc.disconnect()
