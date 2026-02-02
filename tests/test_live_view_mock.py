import sys
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

# Mocking modules that might cause issues in headless CI or without dependencies
sys.modules['pylablib'] = MagicMock()
sys.modules['pylablib.devices.Andor'] = MagicMock()
sys.modules['pylablib.devices.Andor.AndorSDK2Camera'] = MagicMock()

from src.micropl.qt import QApplication
from src.micropl.gui.live_view import LiveView

app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)

class TestLiveViewMock(unittest.TestCase):
    @patch('src.micropl.gui.live_view.HardwareManager')
    def setUp(self, mock_hw_class):
        # Setup mock hardware instance
        self.mock_hw = mock_hw_class.return_value
        
        # Vis camera (disconnected)
        self.mock_vis_cam = MagicMock()
        self.mock_vis_cam.is_connected.return_value = False
        self.mock_hw.vis_camera = self.mock_vis_cam
        
        # Spec camera (connected)
        self.mock_cam = MagicMock()
        self.mock_cam.is_connected.return_value = True
        self.mock_hw.spec_camera = self.mock_cam
        
        # Configure spec cam mock
        self.mock_cam.get_info.return_value = {
            'model': 'iDus',
            'detector_size': (1024, 256),
            'exposure_time': 0.1,
            'target_temperature': -70
        }
        self.mock_cam.get_roi.return_value = (0, 1024, 0, 256, 1, 1)
        self.mock_cam.is_acquiring.return_value = True
        
        self.view = LiveView()
        # Selection triggers initialization logic
        self.view.camera_combo.setCurrentText("Spectrometer")

    def test_view_switching(self):
        # Default should be Image
        self.assertEqual(self.view.view_combo.currentText(), "Image")
        self.assertEqual(self.view.display_stack.currentIndex(), 0)
        
        # Switch to Spectrum
        self.view.view_combo.setCurrentText("Spectrum")
        self.assertEqual(self.view.display_stack.currentIndex(), 1)
        
        # Switch back to Image
        self.view.view_combo.setCurrentText("Image")
        self.assertEqual(self.view.display_stack.currentIndex(), 0)

    def test_frame_update_spectrum(self):
        # Set to Spectrum view
        self.view.view_combo.setCurrentText("Spectrum")
        
        # Mock 1D data from camera
        mock_data = np.random.rand(1024)
        self.mock_cam.read_newest_image.return_value = mock_data
        
        # Force update
        with patch.object(self.view.spectrum_plot, 'update_plot') as mock_update:
            self.view._update_frame()
            mock_update.assert_called()
            # Verify data passed to plot
            args, kwargs = mock_update.call_args
            self.assertTrue(np.array_equal(args[1], mock_data))

    def test_frame_update_image_binning(self):
        # Set to Spectrum view but camera is in Image mode (returns 2D)
        self.view.view_combo.setCurrentText("Spectrum")
        
        # Mock 2D data (10 rows, 100 cols)
        mock_data = np.ones((10, 100))
        self.mock_cam.read_newest_image.return_value = mock_data
        
        # Force update
        with patch.object(self.view.spectrum_plot, 'update_plot') as mock_update:
            self.view._update_frame()
            mock_update.assert_called()
            # Verify data is summed vertically (should be 100 points, all 10.0)
            args, kwargs = mock_update.call_args
            self.assertEqual(len(args[1]), 100)
            self.assertEqual(args[1][0], 10.0)

    def test_live_button_toggling(self):
        # Click Start
        self.view.live_btn.setChecked(True)
        self.view._on_live_toggled(True)
        self.assertEqual(self.view.live_btn.text(), "Abort")
        self.assertTrue(self.view._acquiring)
        
        # Click Stop/Abort
        self.view.live_btn.setChecked(False)
        self.view._on_live_toggled(False)
        self.assertEqual(self.view.live_btn.text(), "Live")
        self.assertFalse(self.view._acquiring)

if __name__ == '__main__':
    unittest.main()
