"""
Shutter control panel.
"""

import logging
from ..qt import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGroupBox
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

        self.open_btn = QPushButton("OPEN")
        self.open_btn.setStyleSheet("background-color: #ccffcc; font-weight: bold; min-height: 30px;")
        self.open_btn.clicked.connect(lambda: self._set_shutter(True))
        
        self.close_btn = QPushButton("CLOSE")
        self.close_btn.setStyleSheet("background-color: #ffcccc; font-weight: bold; min-height: 30px;")
        self.close_btn.clicked.connect(lambda: self._set_shutter(False))
        
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
        else:
            logger.warning("KDC101 not connected, cannot control shutter")
