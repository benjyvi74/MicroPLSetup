import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock pylablib before importing ThorlabsKDC101
sys.modules['pylablib'] = MagicMock()
sys.modules['pylablib.devices'] = MagicMock()

from micropl.qt import QApplication, Qt
from micropl.gui.kdc101_panel import KDC101Panel
from micropl.hardware.manager import HardwareManager

class TestKDC101Panel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication(sys.argv)

    def setUp(self):
        # Reset HardwareManager singleton for testing
        HardwareManager._instance = None
        self.hw = HardwareManager()
        
        # Mock the KDC101 device
        self.mock_kdc = MagicMock()
        self.mock_kdc.is_connected.return_value = True
        self.mock_kdc.get_position.return_value = 12.345
        self.mock_kdc.is_homed.return_value = True
        self.mock_kdc.is_moving.return_value = False
        self.mock_kdc.get_device_info.return_value = {'model': 'KDC101', 'serial': '27000123'}
        self.mock_kdc.get_velocity_params.return_value = {'max_velocity': 1.0, 'acceleration': 10.0}
        self.mock_kdc.get_jog_parameters.return_value = {'step_size': 0.1}
        self.mock_kdc.get_backlash.return_value = 0.01
        
        self.hw.instruments['kdc101'] = self.mock_kdc
        
        self.panel = KDC101Panel()

    def test_ui_initialization(self):
        self.panel._update_status()
        self.assertEqual(self.panel.pos_label.text(), "12.345")
        self.assertEqual(self.panel.status_label.text(), "Connected")
        self.assertEqual(self.panel.device_info_label.text(), "Device: KDC101 (S/N: 27000123)")

    def test_move_click(self):
        self.panel.target_spin.setValue(45.678)
        self.panel.move_btn.click()
        self.mock_kdc.move_to.assert_called_with(45.678)

    def test_step_click(self):
        self.panel.step_spin.setValue(5.0)
        self.panel.step_fwd_btn.click()
        self.mock_kdc.move_by.assert_called_with(5.0)
        
        self.panel.step_back_btn.click()
        self.mock_kdc.move_by.assert_called_with(-5.0)
 
    def test_home_click(self):
        self.panel.home_btn.click()
        self.mock_kdc.home.assert_called_once()

    def test_stop_click(self):
        self.panel.stop_btn.click()
        self.mock_kdc.stop.assert_called_once()

    def test_parameters_dialog_apply(self):
        self.panel._update_status() # Trigger read
        
        # Mock QDialog.exec to return True (OK clicked)
        with patch('micropl.gui.kdc101_panel.KDC101SettingsDialog.exec', return_value=True):
            with patch('micropl.gui.kdc101_panel.KDC101SettingsDialog.get_values', return_value={
                'velocity': 5.0, 'acceleration': 100.0, 'jog_step': 2.0, 'backlash': 0.1
            }):
                self.panel.param_btn.click()
                
                # Check hardware calls
                self.mock_kdc.set_velocity.assert_called_with(5.0)
                self.mock_kdc.set_acceleration.assert_called_with(100.0)
                self.mock_kdc.set_jog_parameters.assert_called_with(step_size=2.0)
                self.mock_kdc.set_backlash.assert_called_with(0.1)
                
                # Check internal state update
                self.assertEqual(self.panel._params['velocity'], 5.0)
                self.assertEqual(self.panel._params['acceleration'], 100.0)

if __name__ == '__main__':
    unittest.main()
