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
                    'monochromators': [
                        {'id': 'mono_0', 'name': 'FHR640', 'enabled': True, 'gratings': [600, 1200, 1800]}
                    ],
                    'cameras': [
                        {'id': 'camera_1', 'model': 'iDus', 'role': 'spectroscopy', 'enabled': True, 'detector_size': [1024, 256]}
                    ]
                }
            }
            self.mgr.active_monochromator_id = 'mono_0'
            self.mgr.active_camera_id = 'camera_1'

    def test_singleton(self):
        mgr2 = HardwareManager()
        self.assertIs(self.mgr, mgr2)

    @patch('micropl.hardware.manager.create_instrument')
    def test_initialize_instrument(self, mock_create):
        mock_inst = MagicMock()
        mock_create.return_value = mock_inst
        
        self.mgr.initialize_instrument('camera_1', 'andor_camera')
        self.assertIn('camera_1', self.mgr.instruments)
        self.assertEqual(self.mgr.cameras['camera_1'], mock_inst)

    def test_collect_metadata(self):
        # Mock connected instruments
        self.mgr.instruments['camera_1'] = MagicMock()
        self.mgr.cameras['camera_1'] = self.mgr.instruments['camera_1']
        self.mgr.instruments['camera_1'].is_connected.return_value = True
        self.mgr.instruments['camera_1'].get_info.return_value = {'model': 'iDus'}
        self.mgr.instruments['camera_1'].get_exposure.return_value = 0.1
        self.mgr.instruments['camera_1'].get_roi.return_value = (1, 1024, 1, 256, 1, 1)
        
        # Mock mono
        self.mgr.instruments['mono_0'] = MagicMock()
        self.mgr.monochromators['mono_0'] = self.mgr.instruments['mono_0']
        self.mgr.mono.is_connected.return_value = True
        self.mgr.mono.get_grating.return_value = 1
        self.mgr.mono._center_wavelength = 550.0
        
        meta = self.mgr.collect_metadata()
        self.assertIn('Camera', meta)
        self.assertIn('camera_1', meta['Camera'])
        self.assertEqual(meta['Camera']['camera_1']['Model'], 'iDus')

    @patch('micropl.hardware.manager.SpectrometerCalibration')
    def test_get_wavelength_axis(self, mock_cal_class):
        mock_cal_inst = mock_cal_class.return_value
        mock_cal_inst.get_wavelength_axis.return_value = np.linspace(500, 600, 1024)
        
        # Mock mono
        self.mgr.instruments['mono_0'] = MagicMock()
        self.mgr.monochromators['mono_0'] = self.mgr.instruments['mono_0']
        self.mgr.mono.is_connected.return_value = True
        self.mgr.mono.get_grating.return_value = 1
        self.mgr._last_grating_idx = 1
        self.mgr.mono._center_wavelength = 550.0
        
        # Mock camera
        self.mgr.instruments['camera_1'] = MagicMock()
        self.mgr.cameras['camera_1'] = self.mgr.instruments['camera_1']
        self.mgr.instruments['camera_1'].get_roi.return_value = (1, 1025, 1, 256, 1, 1) # width 1024
        self.mgr.instruments['camera_1'].get_info.return_value = {'detector_size': (1024, 256)}
        self.mgr.instruments['camera_1'].get_detector_size.return_value = (1024, 256)
        
        axis = self.mgr.get_wavelength_axis('camera_1')
        self.assertIsNotNone(axis)
        self.assertEqual(len(axis), 1024)

if __name__ == '__main__':
    unittest.main()
