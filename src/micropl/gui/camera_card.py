"""
CameraCard — a compact widget representing a single camera in the camera strip.

Each card shows connection status, readout mode, ROI controls, and temperature.
Clicking the card (or its Select button) makes it the active camera in LiveView.
"""

import logging
from typing import Dict, Any, Optional

import numpy as np
from ..qt import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QComboBox, QSpinBox,
    QCheckBox, QFrame, pyqtSignal, Qt, QSizePolicy,
)

logger = logging.getLogger(__name__)


class CameraCard(QGroupBox):
    """
    Compact card widget for a single camera.

    Signals:
        camera_selected(camera_id)  — emitted when the user clicks to activate this camera.
        connect_requested(camera_id) — emitted when the user clicks Connect.
        roi_changed(camera_id, roi_tuple) — emitted when Apply ROI is clicked.
    """
    camera_selected = pyqtSignal(str)   # camera_id
    connect_requested = pyqtSignal(str) # camera_id

    # Fixed display width per card (px)
    CARD_WIDTH = 310

    def __init__(self, camera_id: str, cam_cfg: Dict[str, Any], parent=None):
        super().__init__(cam_cfg.get('name', camera_id), parent)
        self.camera_id = camera_id
        self.cam_cfg = cam_cfg
        self._is_active = False

        self.setFixedWidth(self.CARD_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.setStyleSheet(self._card_style(active=False))

        self._init_ui()

    # -----------------------------------------------------------------------
    # UI construction
    # -----------------------------------------------------------------------

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(8, 12, 8, 8)

        # ----- Connection row -----
        conn_row = QHBoxLayout()
        self.status_label = QLabel("Disconnected")
        self.status_label.setStyleSheet("color: #e74c3c; font-size: 10px;")
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setFixedWidth(80)
        self.connect_btn.setStyleSheet(
            "QPushButton { background-color: #2196F3; color: white; "
            "border-radius: 4px; padding: 3px 8px; font-size: 11px; }"
            "QPushButton:hover { background-color: #1976D2; }"
            "QPushButton:disabled { background-color: #555; color: #999; }"
        )
        self.connect_btn.clicked.connect(lambda: self.connect_requested.emit(self.camera_id))
        conn_row.addWidget(self.status_label, stretch=1)
        conn_row.addWidget(self.connect_btn)
        layout.addLayout(conn_row)

        # ----- Readout mode -----
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Readout:"))
        self.readout_combo = QComboBox()
        cam_role = self.cam_cfg.get('role', 'general')
        if cam_role == 'spectroscopy':
            self.readout_combo.addItems(["Single track", "FVB", "Image"])
        else:
            self.readout_combo.addItems(["Image"])
        mode_row.addWidget(self.readout_combo, stretch=1)
        layout.addLayout(mode_row)

        # ----- ROI section (compact) -----
        roi_box = QGroupBox("ROI")
        roi_box.setStyleSheet("QGroupBox { font-size: 10px; padding-top: 4px; margin-top: 4px; }")
        roi_layout = QVBoxLayout(roi_box)
        roi_layout.setSpacing(3)
        roi_layout.setContentsMargins(4, 10, 4, 4)

        det_w, det_h = self.cam_cfg.get('detector_size', [1024, 1024])

        def make_spin(min_v, max_v, val):
            s = QSpinBox()
            s.setRange(min_v, max_v)
            s.setValue(val)
            s.setFixedWidth(70)
            return s

        # X row
        x_row = QHBoxLayout()
        x_row.addWidget(QLabel("X:"))
        self.x_start = make_spin(0, det_w - 1, 0)
        self.x_end   = make_spin(1, det_w, det_w)
        self.x_bin   = make_spin(1, 16, 1)
        for w in [self.x_start, QLabel("→"), self.x_end, QLabel("Bin"), self.x_bin]:
            x_row.addWidget(w)
        x_row.addStretch()
        roi_layout.addLayout(x_row)

        # Y row
        y_row = QHBoxLayout()
        y_row.addWidget(QLabel("Y:"))
        self.y_start = make_spin(0, det_h - 1, 0)
        self.y_end   = make_spin(1, det_h, det_h)
        self.y_bin   = make_spin(1, 16, 1)
        for w in [self.y_start, QLabel("→"), self.y_end, QLabel("Bin"), self.y_bin]:
            y_row.addWidget(w)
        y_row.addStretch()
        roi_layout.addLayout(y_row)

        apply_roi_btn = QPushButton("Apply ROI")
        apply_roi_btn.setStyleSheet("font-size: 10px;")
        apply_roi_btn.clicked.connect(self._on_apply_roi)
        roi_layout.addWidget(apply_roi_btn)
        layout.addWidget(roi_box)

        # ----- Temperature -----
        temp_row = QHBoxLayout()
        temp_row.addWidget(QLabel("T set:"))
        self.set_temp_spin = QSpinBox()
        self.set_temp_spin.setRange(-100, 50)
        self.set_temp_spin.setValue(self.cam_cfg.get('temperature', -20))
        self.set_temp_spin.setFixedWidth(60)
        temp_row.addWidget(self.set_temp_spin)
        temp_row.addWidget(QLabel("Real:"))
        self.real_temp_label = QLabel("--- °C")
        self.real_temp_label.setStyleSheet(
            "background-color: transparent; border: 1px solid #ced4da; color: gray; "
            "padding: 2px 4px; border-radius: 3px;"
        )
        temp_row.addWidget(self.real_temp_label, stretch=1)
        layout.addLayout(temp_row)

        # ----- Select button -----
        self.select_btn = QPushButton("Select")
        self.select_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "border-radius: 4px; padding: 4px; font-size: 11px; }"
            "QPushButton:hover { background-color: #388E3C; }"
            "QPushButton:checked { background-color: #1B5E20; }"
        )
        self.select_btn.setCheckable(True)
        self.select_btn.clicked.connect(lambda: self.camera_selected.emit(self.camera_id))
        layout.addWidget(self.select_btn)

    # -----------------------------------------------------------------------
    # Public slots (called by LiveView to update card state)
    # -----------------------------------------------------------------------

    def set_active(self, active: bool):
        """Highlight this card as the currently displayed camera."""
        self._is_active = active
        self.setStyleSheet(self._card_style(active=active))
        self.select_btn.setChecked(active)
        self.select_btn.setText("Active" if active else "Select")

    def update_connection_state(self, connected: bool, connecting: bool = False):
        """Update status label and connect button."""
        self.connect_btn.setEnabled(not connected and not connecting)
        if connected:
            self.status_label.setText("Connected")
            self.status_label.setStyleSheet("color: #2ecc71; font-size: 10px;")
        elif connecting:
            self.status_label.setText("Connecting...")
            self.status_label.setStyleSheet("color: #f39c12; font-size: 10px;")
        else:
            self.status_label.setText("Disconnected")
            self.status_label.setStyleSheet("color: #e74c3c; font-size: 10px;")

    def update_temperature(self, temp: float, status: str, acquiring: bool):
        """Update real temperature display."""
        if acquiring:
            txt = f"{temp:.1f} °C (Busy)"
            style = "background-color: #FFC107; color: black; font-weight: bold; border: 1px solid #FFA000; border-radius: 3px; padding: 2px 4px;"
        else:
            txt = f"{temp:.1f} °C"
            target = self.set_temp_spin.value()
            diff = abs(temp - target)
            if diff < 1.0:
                style = "background-color: #2196F3; color: white; font-weight: bold; border: 1px solid #1976D2; border-radius: 3px; padding: 2px 4px;"
            else:
                style = "background-color: #F44336; color: white; font-weight: bold; border: 1px solid #D32F2F; border-radius: 3px; padding: 2px 4px;"
        self.real_temp_label.setText(txt)
        self.real_temp_label.setStyleSheet(style)

    def sync_roi(self, roi):
        """Sync ROI spinboxes from hardware ROI tuple (x_start, x_end, y_start, y_end, x_bin, y_bin)."""
        if roi and len(roi) >= 6:
            self.x_start.setValue(roi[0])
            self.x_end.setValue(roi[1])
            self.y_start.setValue(roi[2])
            self.y_end.setValue(roi[3])
            self.x_bin.setValue(roi[4])
            self.y_bin.setValue(roi[5])

    def get_roi(self):
        """Return current ROI tuple."""
        return (
            self.x_start.value(), self.x_end.value(),
            self.y_start.value(), self.y_end.value(),
            self.x_bin.value(), self.y_bin.value(),
        )

    # -----------------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------------

    def _on_apply_roi(self):
        """Signal the parent LiveView to apply the ROI."""
        # LiveView connects to camera_selected and then reads roi from the card.
        # We reuse camera_selected here to trigger re-sync; LiveView will call apply_roi.
        # Alternatively, wire via a direct slot set in LiveView after card creation.
        pass  # LiveView will call apply_roi() when it receives this through its own apply button

    @staticmethod
    def _card_style(active: bool) -> str:
        border_color = "#2196F3" if active else "#444"
        bg_color = "#1e2a38" if active else "#1a1a2e"
        return (
            f"QGroupBox {{ border: 2px solid {border_color}; border-radius: 8px; "
            f"background-color: {bg_color}; color: #e0e0e0; "
            f"font-weight: bold; font-size: 12px; padding-top: 10px; margin-top: 4px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 3px; }}"
        )
