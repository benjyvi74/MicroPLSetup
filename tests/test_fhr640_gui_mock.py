"""
Mock test for FHR640 GUI Panel.
Verifies that the GUI can initialize and calls the correct hardware methods.
"""

import sys
from unittest.mock import MagicMock, patch

# Mock PyQt6 and serial BEFORE importing GUI
sys.modules["PyQt6"] = MagicMock()
sys.modules["PyQt6.QtWidgets"] = MagicMock()
sys.modules["PyQt6.QtCore"] = MagicMock()
sys.modules["PyQt6.QtGui"] = MagicMock()
sys.modules["serial"] = MagicMock()

import unittest
from micropl.gui.monochromator_panel import MonochromatorPanel
from micropl.hardware.manager import HardwareManager

class TestMonochromatorGUI(unittest.TestCase):
    def setUp(self):
        # Setup hardware manager with a mock mono
        self.hw = HardwareManager()
        self.mock_mono = MagicMock()
        self.hw.instruments['mono'] = self.mock_mono
        
        # Create panel
        self.panel = MonochromatorPanel()

    def test_move_wavelength(self):
        # Mock spinbox and combo values
        self.panel.pos_spin.value.return_value = 633.0
        self.panel.unit_combo.currentText.return_value = "nm"
        self.mock_mono.get_current_wavelength.return_value = 633.0
        
        # Trigger move
        self.panel._on_move_clicked()
        
        # Verify call
        self.mock_mono.set_spectral_position.assert_called_with(633.0, "nm")

    def test_slit_control(self):
        # Trigger slit set
        self.panel._on_slit_set(0, 150.0)
        
        # Verify call
        self.mock_mono.set_slit_width.assert_called_with(150.0, slit_id=0)

    def test_grating_control(self):
        # Mocking the ComboBox behavior
        self.panel.grating_combo.currentText.return_value = "1800"
        
        # Trigger switch
        self.panel._on_grating_set()
        
        # Verify call
        self.mock_mono.set_grating_by_density.assert_called_with(1800)

    def test_mirror_control(self):
        # Mocking the ComboBox behavior
        self.panel.ent_mirror_combo.currentText.return_value = "Side"
        
        # Trigger entrance mirror
        self.panel._on_mirror_set("entrance", "Side")
        
        # Verify call
        self.mock_mono.set_mirror.assert_called_with(port="entrance", position="side")

if __name__ == "__main__":
    unittest.main()
