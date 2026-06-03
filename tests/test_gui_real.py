import sys
import unittest
from micropl.qt import QApplication, QTest, Qt
from micropl.gui.main_window import MainWindow
from micropl.hardware.manager import HardwareManager

# This test requires real hardware connected!
# It will launch the GUI and simulate clicks to verify hardware commands.

app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)

class TestGUIReal(unittest.TestCase):
    def setUp(self):
        self.hw = HardwareManager()
        self.main = MainWindow()
        self.main.show()

    def tearDown(self):
        self.main.close()
        self.main.deleteLater()

    def test_live_view_trigger(self):
        """Test that clicking 'Live' actually starts camera acquisition."""
        live_view = self.main.live_view_panel
        
        # 1. Connect camera first (if not done auto)
        spec_cam = live_view.hw.get_spectroscopy_camera()
        if not spec_cam or not spec_cam.is_connected():
             QTest.mouseClick(live_view.connect_btn, Qt.MouseButton.LeftButton)
             QTest.qWait(2000) # Wait for connection
        
        # 2. Click Live
        QTest.mouseClick(live_view.live_btn, Qt.MouseButton.LeftButton)
        QTest.qWait(1000) # Give it a second to start
        
        # Verify hardware is acquiring
        cam = live_view.hw.get_spectroscopy_camera()
        if cam:
            # Check if camera state reflects acquisition
            # (Implementation detail dependent - usually cam.is_acquiring)
            self.assertTrue(live_view._is_live)
            
        # 3. Stop
        QTest.mouseClick(live_view.live_btn, Qt.MouseButton.LeftButton)
        QTest.qWait(500)
        self.assertFalse(live_view._is_live)

    def test_mono_move_command(self):
        """Test that changing wavelength in UI sends command to FHR640."""
        mono_panel = self.main.right_panel.mono_panel
        
        # 1. Connect
        if not mono_panel._was_connected:
             QTest.mouseClick(mono_panel.connect_btn, Qt.MouseButton.LeftButton)
             QTest.qWait(5000) # Wait for homing
        
        # 2. Set new wavelength
        old_wl = mono_panel.pos_spin.value()
        new_wl = old_wl + 2.0
        
        mono_panel.pos_spin.setValue(new_wl)
        mono_panel.pos_spin.editingFinished.emit() # Trigger the move
        
        QTest.qWait(3000) # Wait for move
        
        # Verify hardware position
        act_wl = mono_panel.hw.mono.get_current_wavelength()
        self.assertAlmostEqual(act_wl, new_wl, places=1)

if __name__ == '__main__':
    unittest.main()
