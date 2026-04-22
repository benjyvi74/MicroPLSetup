import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import sys

# Mock instruments before importing manager implicitly via other imports if any
sys.modules['pylablib'] = MagicMock()
sys.modules['pylablib.devices'] = MagicMock()

from micropl.hardware.manager import HardwareManager

class TestHardwareManager(unittest.TestCase):
    def setUp(self):
        # Reset singleton for each test
        HardwareManager._instance = None
        # Mock load_config to return a predictable dict
        with patch('micropl.hardware.manager.HardwareManager._load_default_config'):
            self.mgr = HardwareManager()
            self.mgr.config = {
                'hardware': {
                    'fhr640': {'center_wavelength': 500.0, 'gratings': [600, 1200, 1800]},
                    'spec_camera': {'model': 'iDus', 'detector_size': [1024, 256]}
                }
            }

    def test_singleton(self):
        mgr2 = HardwareManager()
        self.assertIs(self.mgr, mgr2)

    @patch('micropl.hardware.manager.create_instrument')
    def test_initialize_instrument(self, mock_create):
        mock_inst = MagicMock()
        mock_create.return_value = mock_inst
        
        self.mgr.initialize_instrument('spec_camera', 'andor_camera')
        self.assertIn('spec_camera', self.mgr.instruments)
        self.assertEqual(self.mgr.spec_camera, mock_inst)

    def test_collect_metadata(self):
        # Mock connected instruments
        self.mgr.instruments['spec_camera'] = MagicMock()
        self.mgr.spec_camera.is_connected.return_value = True
        self.mgr.spec_camera.get_info.return_value = {'model': 'iDus'}
        self.mgr.spec_camera.get_exposure.return_value = 0.1
        self.mgr.spec_camera.get_roi.return_value = (1, 1024, 1, 256, 1, 1)
        
        meta = self.mgr.collect_metadata()
        self.assertIn('camera', meta)
        self.assertIn('spec_camera', meta['camera'])
        self.assertEqual(meta['camera']['spec_camera']['model'], 'iDus')

    @patch('micropl.hardware.manager.SpectrometerCalibration')
    def test_get_wavelength_axis(self, mock_cal_class):
        mock_cal_inst = mock_cal_class.return_value
        mock_cal_inst.get_wavelength_axis.return_value = np.linspace(500, 600, 1024)
        
        # Mock mono
        self.mgr.instruments['mono'] = MagicMock()
        self.mgr.mono.is_connected.return_value = True
        self.mgr.mono.get_grating.return_value = 1
        self.mgr.mono._center_wavelength = 550.0
        
        # Mock camera
        self.mgr.instruments['spec_camera'] = MagicMock()
        self.mgr.spec_camera.get_roi.return_value = (1, 1025, 1, 256, 1, 1) # width 1024
        self.mgr.spec_camera.get_info.return_value = {'detector_size': (1024, 256)}
        
        axis = self.mgr.get_wavelength_axis('spec_camera')
        self.assertIsNotNone(axis)
        self.assertEqual(len(axis), 1024)

if __name__ == '__main__':
    unittest.main()
