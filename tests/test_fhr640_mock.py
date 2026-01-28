"""
Mock test for FHR640 to verify driver logic.
This script mocks the COM interface to test the FHR640 class on any platform.
"""

import unittest
from unittest.mock import MagicMock, patch
import sys

# Mock win32com and pythoncom BEFORE importing FHR640
mock_win32com = MagicMock()
mock_pythoncom = MagicMock()

sys.modules["win32com"] = mock_win32com
sys.modules["win32com.client"] = mock_win32com.client
sys.modules["pythoncom"] = mock_pythoncom

# Force WIN32COM_AVAILABLE to True for testing
import micropl.hardware.fhr640 as fhr_mod
fhr_mod.WIN32COM_AVAILABLE = True

from micropl.hardware.fhr640 import FHR640

class TestFHR640(unittest.TestCase):
    def setUp(self):
        self.config = {'device_name': 'TestMono', 'center_wavelength': 600}
        self.fhr = FHR640(self.config)
        
        # Setup mocks for COM objects
        self.mock_hw_config = MagicMock()
        self.mock_mono = MagicMock()
        
        # Mock Dispatch to return our mock objects
        def mock_dispatch(cls_name):
            if "HardwareConfig" in cls_name:
                return self.mock_hw_config
            if "Monochromator" in cls_name:
                return self.mock_mono
            return MagicMock()
            
        mock_win32com.client.Dispatch.side_effect = mock_dispatch
        
        # Configure hw_config mock
        self.mock_hw_config.GetDeviceCount.return_value = 1
        self.mock_hw_config.GetDeviceID.return_value = "UUID-123"
        self.mock_hw_config.GetDeviceName.return_value = "TestMono"
        
        # Configure mono mock
        self.mock_mono.IsBusy = False

    def test_connect_success(self):
        self.fhr.connect()
        self.assertTrue(self.fhr.is_connected())
        self.mock_hw_config.Load.assert_called_once()
        self.mock_mono.Initialize.assert_called_once()
        self.assertEqual(self.fhr.device_name, 'TestMono')

    def test_move_to_wavelength(self):
        self.fhr.connect()
        
        # Mock IsBusy to simulate movement
        busy_states = [True, True, False]
        def get_busy():
            return busy_states.pop(0) if busy_states else False
            
        type(self.mock_mono).IsBusy = property(lambda x: get_busy())
        
        self.fhr.set_center_wavelength(750)
        self.mock_mono.MoveToWavelength.assert_called_with(750)
        self.assertEqual(self.fhr._center_wavelength, 750)

    def test_set_grating(self):
        self.fhr.connect()
        self.fhr.set_grating(1)
        self.mock_mono.MoveToGrating.assert_called_with(1)

    def test_set_slit_width(self):
        self.fhr.connect()
        self.fhr.set_slit_width(0.5, slit_id=0)
        self.mock_mono.MoveToSlitWidth.assert_called_with(0, 0.5)

if __name__ == "__main__":
    unittest.main()
