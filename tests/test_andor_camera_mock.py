import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock pylablib structure properly
pylablib = MagicMock()
devices = MagicMock()
andor_mock = MagicMock()

pylablib.devices = devices
devices.Andor = andor_mock

sys.modules['pylablib'] = pylablib
sys.modules['pylablib.devices'] = devices
sys.modules['pylablib.devices.Andor'] = andor_mock

from micropl.hardware.andor_camera import AndorCamera

class TestAndorCamera(unittest.TestCase):
    def setUp(self):
        # Reset mocks
        andor_mock.reset_mock()
        
        # Configure the mock
        andor_mock.get_cameras_number_SDK2.return_value = 1
        
        self.mock_sdk_cam = MagicMock()
        andor_mock.AndorSDK2Camera.return_value = self.mock_sdk_cam
        
        # Mock get_info and other essentials for connect()
        self.mock_sdk_cam.get_device_info.return_value.model = "DU420"
        self.mock_sdk_cam.get_exposure.return_value = 0.1
        
        self.camera = AndorCamera({'sdk_version': 2, 'camera_index': 0})
        self.camera.connect()

    def test_connection(self):
        self.assertTrue(self.camera.is_connected())
        self.mock_sdk_cam.set_cooler.assert_called_with(True)

    def test_vss_hss_control(self):
        # Mock max vspeed
        self.mock_sdk_cam.get_max_vsspeed.return_value = 2
        self.mock_sdk_cam.get_vsspeed_period.side_effect = [1.0, 2.0, 4.0]
        
        speeds = self.camera.get_vss_speeds()
        self.assertEqual(speeds, [1.0, 2.0, 4.0])
        
        self.camera.set_vss_speed(1)
        self.mock_sdk_cam.set_vsspeed.assert_called_with(1)

        self.mock_sdk_cam.get_all_hsspeeds.return_value = [0.1, 1.0, 10.0]
        hss_speeds = self.camera.get_hss_speeds()
        self.assertEqual(hss_speeds, [0.1, 1.0, 10.0])
        
        self.camera.set_hss_speed(2)
        self.mock_sdk_cam.set_hsspeed.assert_called_with(2)

    def test_shutter_control(self):
        self.camera.set_shutter_mode("open")
        self.mock_sdk_cam.setup_shutter.assert_called_with("open")

    def test_preamp_gain(self):
        self.mock_sdk_cam.get_all_preamp_gains.return_value = [1.0, 2.0, 4.0]
        gains = self.camera.get_preamp_gains()
        self.assertEqual(gains, [1.0, 2.0, 4.0])
        
        self.camera.set_preamp_gain(1)
        self.mock_sdk_cam.set_preamp_gain.assert_called_with(1)

    def test_em_gain(self):
        # Mock iXon-like behavior (has em_gain)
        self.mock_sdk_cam.set_em_gain = MagicMock()
        self.camera.set_gain(100)
        self.mock_sdk_cam.set_em_gain.assert_called_with(100)

    def test_fvb_optimization(self):
        self.camera.optimize_vss_for_fvb()
        self.mock_sdk_cam.set_vsspeed.assert_called_with(0)

    def test_acquisition_modes(self):
        self.camera.set_acquisition_mode("accumulate")
        self.mock_sdk_cam.set_acquisition_mode.assert_called_with("accumulate")
        
        # Test hardware accumulation setup
        self.camera.setup_accumulation(10, 0.5)
        self.mock_sdk_cam.set_exposure.assert_called_with(0.5)
        self.mock_sdk_cam.setup_accum_mode.assert_called_with(10)

    def test_adc_and_amp_control(self):
        self.mock_sdk_cam.get_number_ad_channels.return_value = 2
        self.assertEqual(self.camera.get_adc_channels(), [0, 1])
        
        self.camera.set_adc_channel(1)
        self.mock_sdk_cam.set_adc_channel.assert_called_with(1)
        
        self.mock_sdk_cam.get_all_amp_modes.return_value = ["Standard", "High Sensitivity"]
        self.assertEqual(self.camera.get_amp_modes(), ["Standard", "High Sensitivity"])
        
        self.camera.set_amp_mode(1)
        self.mock_sdk_cam.set_amp_mode.assert_called_with(1)

    def test_baseline_clamp(self):
        self.camera.set_baseline_clamp(True)
        self.mock_sdk_cam.set_baseline_clamp.assert_called_with(True)

    def test_smart_roi_fvb(self):
        # ROI covering full height + binning covering full height -> FVB
        self.mock_sdk_cam.get_detector_size.return_value = (1024, 256)
        self.camera.set_roi(x_start=0, x_end=1024, y_start=0, y_end=256, y_bin=256)
        
        # Should call set_readout_mode('fvb')
        self.mock_sdk_cam.set_readout_mode.assert_called_with("fvb")

    def test_smart_roi_single_track(self):
        # ROI covering partial height + binning covering that height -> Single Track
        self.mock_sdk_cam.get_detector_size.return_value = (1024, 256)
        self.camera.set_roi(y_start=100, y_end=120, y_bin=20)
        
        # Should call set_single_track(20, 110)
        self.mock_sdk_cam.set_single_track.assert_called_with(20, 110)
        self.mock_sdk_cam.set_readout_mode.assert_called_with("single_track")

    def test_smart_roi_image(self):
        # Binning < ROI height -> Image
        self.mock_sdk_cam.get_detector_size.return_value = (1024, 256)
        self.camera.set_roi(y_start=0, y_end=256, y_bin=1)
        
        # Should stay in/switch to full_image
        self.mock_sdk_cam.set_readout_mode.assert_called_with("full_image")
        self.mock_sdk_cam.set_roi.assert_called()

    def test_acquire_spectrum_fallback(self):
        import numpy as np
        # 2D image
        image_2d = np.ones((10, 100))
        self.mock_sdk_cam.snap.return_value = image_2d
        
        spectrum = self.camera.acquire_spectrum()
        # Should be 100 points long (summing vertically)
        self.assertEqual(spectrum.shape, (100,))
        self.assertEqual(spectrum[0], 10.0)

if __name__ == '__main__':
    unittest.main()
