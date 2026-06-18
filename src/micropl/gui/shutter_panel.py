import logging
from typing import Optional, cast

from ..hardware.kdc101 import ThorlabsKDC101
from ..hardware.manager import HardwareManager
from ..qt import (
    QLabel, QPushButton, QVBoxLayout, QWidget,
    Qt, pyqtSignal, pyqtSlot
)


logger = logging.getLogger(__name__)

class ShutterPanel(QWidget):
    """
    Simple panel to control a KDC101 acting as a system shutter.
    This panel does not have its own connection logic as it links
    to an existing hardware instrument (Polarizer or Stage axis).
    """
    sig_status_changed = pyqtSignal(str)
    
    def __init__(self, hardware_manager: Optional[HardwareManager] = None):
        super().__init__()
        self.hw = hardware_manager or HardwareManager()
        self._init_ui()
        
        # Connect to hardware signals for real-time updates
        service = self.hw.service
        service.shutter_status_changed.connect(self._on_hw_status_changed)
        service.shutter_changed.connect(self._on_hw_shutter_changed)
        
        logger.info("Shutter panel initialized")
        
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        
        # Shutter Toggle Button
        self.toggle_btn = QPushButton("CLOSED")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setMinimumHeight(45)
        self._update_button_style(False)
        
        self.toggle_btn.toggled.connect(self._on_toggle)
        layout.addWidget(self.toggle_btn)
        
        # Link Info
        self.link_label = QLabel("Linked to: ---")
        self.link_label.setStyleSheet("color: #888; font-size: 11px;")
        self.link_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.link_label)
        
        self._update_ui_state()

    def _update_button_style(self, is_open: bool):
        common_style = """
            QPushButton { 
                color: white; font-weight: bold; font-size: 14px;
                border-radius: 6px;
            }
            QPushButton:disabled {
                background-color: #34495e;
                color: #7f8c8d;
                border: 2px solid #2c3e50;
            }
        """
        if is_open:
            self.toggle_btn.setText("OPEN")
            self.toggle_btn.setStyleSheet(common_style + """
                QPushButton:enabled { 
                    background-color: #27ae60;
                    border: 2px solid #2ecc71;
                }
                QPushButton:enabled:hover { background-color: #2ecc71; }
            """)
        else:
            self.toggle_btn.setText("CLOSED")
            self.toggle_btn.setStyleSheet(common_style + """
                QPushButton:enabled { 
                    background-color: #c0392b;
                    border: 2px solid #e74c3c;
                }
                QPushButton:enabled:hover { background-color: #e74c3c; }
            """)

    def _on_toggle(self, checked: bool):
        shutter_dev = cast(Optional[ThorlabsKDC101], self.hw.shutter)
        channel = self.hw.shutter_channel
        if shutter_dev:
            try:
                shutter_dev.set_shutter(checked, channel=channel)
                self._update_button_style(checked)
                logger.info(f"System shutter {'opened' if checked else 'closed'} (Channel {channel})")
            except Exception as e:
                logger.error(f"Failed to toggle system shutter: {e}")
                # Revert visual state
                self.toggle_btn.blockSignals(True)
                self.toggle_btn.setChecked(not checked)
                self.toggle_btn.blockSignals(False)
        else:
            # Revert if no device
            self.toggle_btn.blockSignals(True)
            self.toggle_btn.setChecked(False)
            self.toggle_btn.blockSignals(False)

    def _update_ui_state(self):
        shutter_dev = cast(Optional[ThorlabsKDC101], self.hw.shutter)
        
        # Always show OPEN/CLOSED, just disable if not ready
        is_open = False
        is_connected = False
        
        if shutter_dev:
            is_connected = shutter_dev.is_connected()
            if is_connected:
                is_open = shutter_dev.get_shutter()
        
        self.toggle_btn.blockSignals(True)
        self.toggle_btn.setEnabled(is_connected)
        self.toggle_btn.setChecked(is_open)
        self.toggle_btn.blockSignals(False)
        self._update_button_style(is_open)
        
        # Hide link label as requested
        self.link_label.setVisible(False)

    def update_panel(self):
        """Called periodically by the sidebar."""
        self._update_ui_state()

    def get_current_status(self) -> str:
        """Return a status string for the sidebar dot."""
        shutter_dev = cast(Optional[ThorlabsKDC101], self.hw.shutter)
        if shutter_dev and shutter_dev.is_connected():
            return "Connected"
        return "Disconnected"

    @pyqtSlot(bool)
    def _on_hw_status_changed(self, is_connected: bool):
        """Handle hardware connection status updates."""
        self._update_ui_state()
        self.sig_status_changed.emit("Connected" if is_connected else "Disconnected")

    @pyqtSlot(bool)
    def _on_hw_shutter_changed(self, is_open: bool):
        """Handle hardware shutter state updates (Open/Closed)."""
        self._update_ui_state()
