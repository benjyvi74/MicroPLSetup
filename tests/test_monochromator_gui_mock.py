import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock pylablib and hardware before importing panel
sys.modules['pylablib'] = MagicMock()
sys.modules['pylablib.devices'] = MagicMock()

from micropl.qt import QApplication, Qt
from micropl.gui.monochromator_panel import MonochromatorPanel
from micropl.hardware.manager import HardwareManager

class TestMonochromatorPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication(sys.argv)

    def setUp(self):
        HardwareManager._instance = None
        self.hw = HardwareManager()
        
        self.mock_mono = MagicMock()
        self.mock_mono.is_connected.return_value = True
        self.mock_mono.get_current_wavelength.return_value = 532.0
        
        self.hw.instruments['mono'] = self.mock_mono
        self.panel = MonochromatorPanel()

    def test_status_update(self):
        self.panel._update_status()
        self.assertEqual(self.panel.curr_pos_label.text(), "532.000")
        self.assertEqual(self.panel.status_label.text(), "Connected")

    def test_auto_move_on_editing_finished(self):
        # Set a new value
        self.panel.pos_spin.setValue(633.0)
        
        # Trigger editingFinished
        self.panel.pos_spin.editingFinished.emit()
        
        # Check if hardware was called
        self.mock_mono.set_spectral_position.assert_called_with(633.0, "nm")
        self.assertEqual(self.panel._last_move_val, 633.0)

    def test_no_move_if_value_has_not_changed(self):
        self.panel.pos_spin.setValue(633.0)
        self.panel.pos_spin.editingFinished.emit() # First move
        self.mock_mono.set_spectral_position.reset_mock()
        
        # Trigger again with same value
        self.panel.pos_spin.editingFinished.emit()
        self.mock_mono.set_spectral_position.assert_not_called()

    def test_move_on_unit_change_then_edit(self):
        # Initial state: nm, None last move
        self.panel.pos_spin.setValue(500.0)
        self.panel.pos_spin.editingFinished.emit() # Move 1
        self.mock_mono.set_spectral_position.assert_called_with(500.0, "nm")
        
        # Change unit (manually triggering conversion logic)
        with patch('micropl.utils.conversions.nm_to_meV', return_value=2480.0):
            # We mock the combo box change
            self.panel.unit_combo.setCurrentText("meV")
            # _on_unit_changed is called automatically by currentIndexChanged
            
        self.assertEqual(self.panel.pos_spin.value(), 2480.0)
        self.assertEqual(self.panel.current_unit, "meV")
        
        # editingFinished might be triggered by focus loss during unit change, 
        # but _last_move_unit is still "nm" so it SHOULD move if we didn't block it.
        # Actually, in real UI, focus might stay. Let's trigger manually.
        self.mock_mono.set_spectral_position.reset_mock()
        self.panel.pos_spin.editingFinished.emit()
        
        self.mock_mono.set_spectral_position.assert_called_with(2480.0, "meV")
        self.assertEqual(self.panel._last_move_unit, "meV")

if __name__ == '__main__':
    unittest.main()
