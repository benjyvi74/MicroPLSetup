"""
Shutter control panel.
"""

import logging
from ..qt import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGroupBox, QButtonGroup
)

from ..hardware.manager import HardwareManager

logger = logging.getLogger(__name__)


class ShutterPanel(QWidget):
    """Widget for shutter control via KDC101 TTL."""

    def __init__(self):
        super().__init__()
        self.hw = HardwareManager()
        self._init_ui()
        logger.info("Shutter panel initialized")

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        group = QGroupBox("Shutter Control")
        group_layout = QHBoxLayout()
        group.setLayout(group_layout)

        # Use a button group for mutual exclusivity
        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)

        self.open_btn = QPushButton("OPEN")
        self.open_btn.setCheckable(True)
        self.open_btn.setStyleSheet("""
            QPushButton:checked { background-color: #2ecc71; color: white; font-weight: bold; }
            QPushButton { min-height: 24px; }
        """)
        self.open_btn.clicked.connect(lambda: self._set_shutter(True))
        
        self.close_btn = QPushButton("CLOSE")
        self.close_btn.setCheckable(True)
        self.close_btn.setStyleSheet("""
            QPushButton:checked { background-color: #e74c3c; color: white; font-weight: bold; }
            QPushButton { min-height: 24px; }
        """)
        self.close_btn.clicked.connect(lambda: self._set_shutter(False))
        
        self.button_group.addButton(self.open_btn)
        self.button_group.addButton(self.close_btn)

        # Default to closed
        self.close_btn.setChecked(True)

        group_layout.addWidget(self.open_btn)
        group_layout.addWidget(self.close_btn)

        layout.addWidget(group)

    def _set_shutter(self, open: bool):
        """Set shutter state via hardware."""
        kdc = self.hw.kdc101
        if kdc and kdc.is_connected():
            try:
                kdc.set_shutter(open)
                logger.info(f"Shutter {'opened' if open else 'closed'}")
            except Exception as e:
                logger.error(f"Failed to control shutter: {e}")
                # Revert button state on failure
                if open:
                    self.close_btn.setChecked(True)
                else:
                    self.open_btn.setChecked(True)
        else:
            logger.warning("KDC101 not connected, cannot control shutter")
            # Keep buttons in sync with UI intent even if disconnected for feedback
            # (In a real setup with disconnect, you might want to gray them out)
