import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock pylablib
sys.modules['pylablib'] = MagicMock()
sys.modules['pylablib.devices'] = MagicMock()

from micropl.qt import QApplication
from micropl.gui.powermeter_panel import PowerMeterPanel
from micropl.hardware.manager import HardwareManager

class TestPowerMeterPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication(sys.argv)

    def setUp(self):
        HardwareManager._instance = None
        self.hw = HardwareManager()
        
        self.mock_pm = MagicMock()
        self.mock_pm.is_connected.return_value = True
        self.mock_pm.read_power.return_value = 1.23e-6 # 1.23 uW
        self.mock_pm.get_wavelength.return_value = 532.0
        self.mock_pm.get_averaging_count.return_value = 10
        self.mock_pm.get_autorange.return_value = True
        self.mock_pm.get_ranges.return_value = [1e-3, 10e-3, 100e-3]
        self.mock_pm.get_beam_diameter.return_value = 2.0
        self.mock_pm.get_info.return_value = {
            'sensor_model': 'S120C',
            'sensor_sn': 'P0012345'
        }
        
        self.hw.instruments['pm100'] = self.mock_pm
        
        self.panel = PowerMeterPanel()

    def test_power_display(self):
        self.panel._update_status()
        self.assertEqual(self.panel.power_label.text(), "1.230")
        self.assertEqual(self.panel.unit_label.text(), "µW")
        self.assertEqual(self.panel.status_label.text(), "Connected")
        self.assertEqual(self.panel.sensor_label.text(), "Sensor: S120C (S/N: P0012345)")

    def test_wavelength_change(self):
        self.panel.wave_spin.setValue(633.0)
        self.panel._on_wavelength_changed()
        self.mock_pm.set_wavelength.assert_called_with(633.0)

    def test_config_dialog_advanced(self):
        # Mock QDialog.exec to return True
        with patch('micropl.gui.powermeter_panel.PMSettingsDialog.exec', return_value=True):
            with patch('micropl.gui.powermeter_panel.PMSettingsDialog.get_values', return_value={
                'averaging': 50, 'autorange': False, 'range': 10e-3, 'beam_diameter': 5.0
            }):
                self.panel.config_btn.click()
                self.mock_pm.set_averaging_count.assert_called_with(50)
                self.mock_pm.set_autorange.assert_called_with(False)
                self.mock_pm.set_range.assert_called_with(10e-3)
                self.mock_pm.set_beam_diameter.assert_called_with(5.0)

if __name__ == '__main__':
    unittest.main()
