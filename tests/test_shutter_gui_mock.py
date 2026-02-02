import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock pylablib before importing
sys.modules['pylablib'] = MagicMock()
sys.modules['pylablib.devices'] = MagicMock()

from micropl.qt import QApplication
from micropl.gui.shutter_panel import ShutterPanel
from micropl.hardware.manager import HardwareManager

class TestShutterPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication(sys.argv)

    def setUp(self):
        HardwareManager._instance = None
        self.hw = HardwareManager()
        
        self.mock_kdc = MagicMock()
        self.mock_kdc.is_connected.return_value = True
        self.hw.instruments['kdc101'] = self.mock_kdc
        
        self.panel = ShutterPanel()

    def test_open_click(self):
        self.panel.open_btn.click()
        self.mock_kdc.set_shutter.assert_called_with(True)

    def test_close_click(self):
        self.panel.close_btn.click()
        self.mock_kdc.set_shutter.assert_called_with(False)

if __name__ == '__main__':
    unittest.main()
