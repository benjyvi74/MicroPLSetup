"""
CameraCard — a compact widget representing a single camera in the camera strip.

Each card shows connection status, readout mode, ROI controls, and temperature.
Clicking the card (or its header) makes it the active camera in LiveView.
"""

import logging
from typing import Dict, Any, Optional

import numpy as np
from ..qt import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QComboBox, QSpinBox,
    QCheckBox, QFrame, pyqtSignal, Qt, QSizePolicy,
    QMenu, QApplication, QToolButton
)
from PyQt6.QtGui import QDrag, QPainter, QColor
from PyQt6.QtCore import QMimeData, QEvent

logger = logging.getLogger(__name__)


class CameraCard(QFrame):
    """
    Collapsible card widget for a single camera.

    Signals:
        camera_selected(camera_id)  — emitted when the user clicks to activate this camera.
        connect_requested(camera_id) — emitted when the user clicks Connect.
        apply_roi_requested(camera_id) — emitted when Apply ROI is clicked.
    """
class CameraCard(QFrame):
    """
    Component for an individual camera in the sidebar.
    """
    camera_selected = pyqtSignal(str)   # camera_id
    connect_requested = pyqtSignal(str) # camera_id
    apply_roi_requested = pyqtSignal(str) # camera_id
    readout_mode_changed = pyqtSignal(str, str) # camera_id, mode
    temp_changed_requested = pyqtSignal(str, float) # camera_id, temp

    def __init__(self, camera_id: str, cam_cfg: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.camera_id = camera_id
        self.cam_cfg = cam_cfg
        self._is_active = False
        self._is_collapsed = False

        name = cam_cfg.get('name', camera_id)
        model = cam_cfg.get('model')
        self.display_name = f"{name} ({model})" if model and model not in name else name

        self.setMinimumWidth(340)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        
        self._init_ui()
        self._update_style()
        self._update_controls_enabled(False) # Initially disabled

    # -----------------------------------------------------------------------
    # UI construction
    # -----------------------------------------------------------------------

    def _init_ui(self):
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        # ----- Header -----
        self.header = QFrame()
        self.header.setFixedHeight(30)
        self.header.setObjectName("header")
        self.header.installEventFilter(self)
        h_layout = QHBoxLayout(self.header)
        h_layout.setContentsMargins(5, 0, 5, 0)

        # Toggle Button (Arrow) on the left
        self.toggle_btn = QToolButton()
        self.toggle_btn.setArrowType(Qt.ArrowType.DownArrow)
        self.toggle_btn.setFixedSize(20, 20)
        self.toggle_btn.setAutoRaise(True)
        self.toggle_btn.setStyleSheet("""
            QToolButton { border: none; background: transparent; }
        """)
        self.toggle_btn.clicked.connect(self.toggle)
        h_layout.addWidget(self.toggle_btn)

        self.title_label = QLabel(self.display_name)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 11px;")
        h_layout.addWidget(self.title_label)
        
        h_layout.addStretch()
        
        self.connect_btn = QPushButton("ON")
        self.connect_btn.setFixedSize(20, 20)
        self.connect_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.connect_btn.setToolTip("Connect to Camera")
        self.connect_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid #ced4da;
                border-radius: 3px;
                background-color: white;
                font-weight: bold;
                font-size: 10px;
                color: #495057;
            }
            QPushButton:hover {
                background-color: #e9ecef;
            }
            QPushButton:disabled {
                background-color: #f8f9fa;
                color: #adb5bd;
                border: 1px solid #e9ecef;
            }
        """)
        self.connect_btn.clicked.connect(lambda: self.connect_requested.emit(self.camera_id))
        h_layout.addWidget(self.connect_btn)
        
        self.status_dot = QLabel("●")
        self.status_dot.setToolTip("Status: Disconnected")
        self.status_dot.setStyleSheet("color: #dc3545; font-size: 14px; margin-right: 5px;") # Red
        h_layout.addWidget(self.status_dot)

        self._main_layout.addWidget(self.header)

        # ----- Content Area -----
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setSpacing(5)
        self.content_layout.setContentsMargins(8, 8, 8, 8)


        # ----- Readout mode -----
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Readout:"))
        self.readout_combo = QComboBox()
        cam_role = self.cam_cfg.get('role', 'general')
        det_h = self.cam_cfg.get('detector_size', [1024, 1024])[1]
        
        if cam_role == 'spectroscopy':
            if det_h > 1:
                self.readout_combo.addItems(["Single track", "FVB", "Image"])
            else:
                self.readout_combo.addItems(["1D"])
        else:
            self.readout_combo.addItems(["Image"])
            
        self.readout_combo.currentTextChanged.connect(
            lambda text: self.readout_mode_changed.emit(self.camera_id, text)
        )
        mode_row.addWidget(self.readout_combo, stretch=1)
        self.content_layout.addLayout(mode_row)

        # ----- ROI section (compact) -----
        roi_box = QGroupBox("ROI")
        roi_box.setStyleSheet("QGroupBox { font-size: 10px; padding-top: 4px; margin-top: 4px; }")
        roi_layout = QVBoxLayout(roi_box)
        roi_layout.setSpacing(3)
        roi_layout.setContentsMargins(4, 10, 4, 4)

        det_w, det_h = self.cam_cfg.get('detector_size', [1024, 1024])
        cam_role = self.cam_cfg.get('role', 'general')
        is_one_based = (cam_role == 'spectroscopy')
        offset = 1 if is_one_based else 0

        def make_spin(min_v, max_v, val):
            s = QSpinBox()
            s.setRange(min_v, max_v)
            s.setValue(val)
            s.setFixedWidth(70)
            return s

        # X row
        x_row = QHBoxLayout()
        x_row.addWidget(QLabel("X:"))
        self.x_start = make_spin(offset, det_w - 1 + offset, offset)
        self.x_end   = make_spin(1, det_w, det_w)
        self.x_bin   = make_spin(1, det_w, 1)
        for w in [self.x_start, QLabel("→"), self.x_end, QLabel("Bin"), self.x_bin]:
            x_row.addWidget(w)
        x_row.addStretch()
        roi_layout.addLayout(x_row)

        # Y row
        y_row = QHBoxLayout()
        y_row.addWidget(QLabel("Y:"))
        self.y_start = make_spin(offset, det_h - 1 + offset, offset)
        self.y_end   = make_spin(1, det_h, det_h)
        self.y_bin   = make_spin(1, det_h, 1)
        for w in [self.y_start, QLabel("→"), self.y_end, QLabel("Bin"), self.y_bin]:
            y_row.addWidget(w)
        y_row.addStretch()
        roi_layout.addLayout(y_row)

        roi_btns_layout = QHBoxLayout()
        
        self.apply_roi_btn = QPushButton("Apply ROI")
        self.apply_roi_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.apply_roi_btn.setStyleSheet("font-size: 10px;")
        self.apply_roi_btn.clicked.connect(self._on_apply_roi)
        roi_btns_layout.addWidget(self.apply_roi_btn)
        
        self.presets_btn = QPushButton("Presets")
        self.presets_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.presets_btn.setStyleSheet("font-size: 10px;")
        roi_btns_layout.addWidget(self.presets_btn)
        
        roi_layout.addLayout(roi_btns_layout)
        self.content_layout.addWidget(roi_box)
        
        self._setup_presets_menu()

        # ----- Temperature -----
        temp_row = QHBoxLayout()
        temp_row.addWidget(QLabel("T set:"))
        self.set_temp_spin = QSpinBox()
        self.set_temp_spin.setRange(-100, 50)
        self.set_temp_spin.setValue(self.cam_cfg.get('temperature', -20))
        self.set_temp_spin.setFixedWidth(60)
        self.set_temp_spin.valueChanged.connect(
            lambda temp: self.temp_changed_requested.emit(self.camera_id, float(temp))
        )
        temp_row.addWidget(self.set_temp_spin)
        temp_row.addWidget(QLabel("Real:"))
        self.real_temp_label = QLabel("--- °C")
        self.real_temp_label.setStyleSheet(
            "border: 1px solid #ced4da; color: gray; "
            "padding: 2px 4px; border-radius: 3px;"
        )
        temp_row.addWidget(self.real_temp_label, stretch=1)
        self.content_layout.addLayout(temp_row)

        # ----- Select button removed as requested -----
        # self.select_btn = QPushButton("Select")
        # ...

        self._main_layout.addWidget(self.content_widget)

    def toggle(self):
        """Toggle content visibility."""
        self.set_collapsed(not self._is_collapsed)

    def set_collapsed(self, collapsed: bool):
        """Set collapsed state and update UI."""
        self._is_collapsed = collapsed
        self.content_widget.setVisible(not collapsed)
        self.toggle_btn.setArrowType(
            Qt.ArrowType.RightArrow if collapsed else Qt.ArrowType.DownArrow
        )
        self.updateGeometry()

    def mousePressEvent(self, event):
        """Select on click. If header is clicked, select without collapsing (unless arrow is clicked)."""
        # The toggle_btn click is handled by its own signal.
        # Here we just want to ensure selecting happens on any click.
        self.camera_selected.emit(self.camera_id)
        super().mousePressEvent(event)

    def eventFilter(self, obj, event):
        if obj == self.header:
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    self.drag_start_pos = event.pos()
                    return False
            elif event.type() == QEvent.Type.MouseMove:
                if not (event.buttons() & Qt.MouseButton.LeftButton):
                    return False
                if not hasattr(self, 'drag_start_pos'):
                    return False
                if (event.pos() - self.drag_start_pos).manhattanLength() < QApplication.startDragDistance():
                    return False
                
                # Start drag
                drag = QDrag(self)
                mime = QMimeData()
                mime.setData('application/x-camera-panel', str(id(self)).encode())
                drag.setMimeData(mime)
                
                # Visual feedback
                pixmap = self.grab()
                painter = QPainter(pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
                painter.fillRect(pixmap.rect(), QColor(0, 0, 0, 150))
                painter.end()
                
                drag.setPixmap(pixmap)
                drag.setHotSpot(event.pos())
                drag.exec(Qt.DropAction.MoveAction)
                return True
        return super().eventFilter(obj, event)

    # -----------------------------------------------------------------------
    # Public slots (called by LiveView to update card state)
    # -----------------------------------------------------------------------

    def set_active(self, active: bool):
        """Highlight this card as the currently displayed camera."""
        self._is_active = active
        self._update_style()

    def update_roi_limits(self, width: int, height: int):
        """Update the maximum ranges of ROI controls based on actual sensor size."""
        # Update readout combo if sensor dimension type changed (e.g. 1D vs 2D)
        cam_role = self.cam_cfg.get('role', 'general')
        if cam_role == 'spectroscopy':
            self.readout_combo.blockSignals(True)
            current = self.readout_combo.currentText()
            self.readout_combo.clear()
            if height > 1:
                self.readout_combo.addItems(["Single track", "FVB", "Image"])
                # Restore previous if valid, else default to Single track
                idx = self.readout_combo.findText(current)
                self.readout_combo.setCurrentIndex(idx if idx >= 0 else 0)
            else:
                self.readout_combo.addItems(["1D"])
            self.readout_combo.blockSignals(False)

        is_one_based = (cam_role == 'spectroscopy')
        offset = 1 if is_one_based else 0

        self.x_start.setRange(offset, width - 1 + offset)
        self.x_end.setRange(1, width)
        self.x_bin.setRange(1, width)
        
        self.y_start.setRange(offset, height - 1 + offset)
        self.y_end.setRange(1, height)
        self.y_bin.setRange(1, height)
        logger.debug(f"CameraCard {self.camera_id}: ROI limits updated to {width}x{height}")

    def update_connection_state(self, connected: bool, connecting: bool = False):
        """Update status dot and connect button."""
        self.connect_btn.setEnabled(not connecting and not connected)
        
        if connecting:
            self._update_status_dot("Connecting...")
        else:
            self._update_status_dot("Connected" if connected else "Disconnected")
            
        self._update_controls_enabled(connected)

    def _update_status_dot(self, status: str):
        """Update the status dot color based on keywords."""
        status = status.lower()
        self.status_dot.setToolTip(f"Status: {status.capitalize()}")
        
        # Priority 1: Disconnected / Error (Red)
        if any(word in status for word in ["disconnected", "error", "failed", "offline", "deconnected"]):
            self.status_dot.setStyleSheet("color: #dc3545; font-size: 14px; margin-right: 5px;")
        # Priority 2: Transitions (Orange)
        elif any(word in status for word in ["connecting", "busy", "capturing", "initializing", "moving", "wait"]):
            self.status_dot.setStyleSheet("color: #fd7e14; font-size: 14px; margin-right: 5px;")
        # Priority 3: Ready (Green)
        elif any(word in status for word in ["connected", "ready", "stable"]):
            self.status_dot.setStyleSheet("color: #28a745; font-size: 14px; margin-right: 5px;")
        else:
            # Default Red for safety
            self.status_dot.setStyleSheet("color: #dc3545; font-size: 14px; margin-right: 5px;")

    def update_temperature(self, temp: float, status: str, acquiring: bool):
        """Update real temperature display."""
        if acquiring:
            txt = f"{temp:.1f} °C (Busy)"
            style = "color: #d35400; font-weight: bold;"
        else:
            txt = f"{temp:.1f} °C"
            target = self.set_temp_spin.value()
            diff = abs(temp - target)
            if diff < 1.0:
                style = "color: #27ae60; font-weight: bold;"
            else:
                style = "color: #c0392b; font-weight: bold;"
        self.real_temp_label.setText(txt)
        self.real_temp_label.setStyleSheet(style)

    def sync_roi(self, roi):
        """Sync ROI spinboxes from hardware ROI tuple (x_start, x_end, y_start, y_end, x_bin, y_bin)."""
        if roi and len(roi) >= 6:
            cam_role = self.cam_cfg.get('role', 'general')
            is_one_based = (cam_role == 'spectroscopy')
            offset = 1 if is_one_based else 0
            self.x_start.setValue(roi[0] + offset)
            self.x_end.setValue(roi[1])
            self.y_start.setValue(roi[2] + offset)
            self.y_end.setValue(roi[3])
            self.x_bin.setValue(roi[4])
            self.y_bin.setValue(roi[5])

    def get_roi(self):
        """Return current ROI tuple."""
        cam_role = self.cam_cfg.get('role', 'general')
        is_one_based = (cam_role == 'spectroscopy')
        offset = 1 if is_one_based else 0
        return (
            self.x_start.value() - offset, self.x_end.value(),
            self.y_start.value() - offset, self.y_end.value(),
            self.x_bin.value(), self.y_bin.value(),
        )

    def set_roi_enabled(self, enabled: bool):
        """Enable or disable ROI editing controls."""
        for box in [self.x_start, self.x_end, self.x_bin,
                    self.y_start, self.y_end, self.y_bin]:
            box.setEnabled(enabled)
        self.apply_roi_btn.setEnabled(enabled)
        self.presets_btn.setEnabled(enabled)

    def _update_controls_enabled(self, enabled: bool):
        """Enable or disable all camera-specific parameter controls."""
        self.readout_combo.setEnabled(enabled)
        self.set_roi_enabled(enabled)
        self.set_temp_spin.setEnabled(enabled)

    def _setup_presets_menu(self):
        """Setup the ROI presets menu."""
        menu = QMenu(self)
        
        img_action = menu.addAction("Image Visualisation")
        img_action.triggered.connect(lambda: self.apply_preset("image_vis"))
        
        spec_action = menu.addAction("Center Spectrometer")
        spec_action.triggered.connect(lambda: self.apply_preset("center_spec"))
        
        slit_action = menu.addAction("Slit Image")
        slit_action.triggered.connect(lambda: self.apply_preset("slit_image"))
        
        self.presets_btn.setMenu(menu)

    def apply_preset(self, preset_type: str, trigger_hardware: bool = True):
        """Apply a predefined ROI preset."""
        self.x_start.blockSignals(True)
        self.x_end.blockSignals(True)
        self.y_start.blockSignals(True)
        self.y_end.blockSignals(True)
        self.x_bin.blockSignals(True)
        self.y_bin.blockSignals(True)

        cam_role = self.cam_cfg.get('role', 'general')
        is_one_based = (cam_role == 'spectroscopy')
        offset = 1 if is_one_based else 0

        width, height = self.cam_cfg.get('detector_size', [1024, 256])

        if preset_type == "image_vis":
            self.x_start.setValue(253 + offset)
            self.x_end.setValue(752)
            self.y_start.setValue(252 + offset)
            self.y_end.setValue(753)
            self.x_bin.setValue(1)
            self.y_bin.setValue(1)
        elif preset_type == "center_spec":
            self.x_start.setValue(1)
            self.x_end.setValue(width)
            track_height = 30
            y_start = (height - track_height) // 2
            self.y_start.setValue(y_start + offset)
            self.y_end.setValue(y_start + track_height)
            self.x_bin.setValue(1)
            self.y_bin.setValue(track_height)
        elif preset_type == "slit_image":
            self.x_start.setValue(1)
            self.x_end.setValue(width)
            self.y_start.setValue(1)
            self.y_end.setValue(height)
            self.x_bin.setValue(1)
            self.y_bin.setValue(8)
        
        self.x_start.blockSignals(False)
        self.x_end.blockSignals(False)
        self.y_start.blockSignals(False)
        self.y_end.blockSignals(False)
        self.x_bin.blockSignals(False)
        self.y_bin.blockSignals(False)
            
        if trigger_hardware:
            self._on_apply_roi()

    # -----------------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------------

    def _on_apply_roi(self):
        """Signal the parent LiveView to apply the ROI."""
        self.apply_roi_requested.emit(self.camera_id)

    def _update_style(self):
        """Update the frame stylesheet based on active state."""
        border_width = "2px" if self._is_active else "1px"
        border_color = "#2196F3" if self._is_active else "#ced4da"
        
        self.setStyleSheet(f"""
            CameraCard {{
                border: {border_width} solid {border_color};
                border-radius: 6px;
                background-color: white;
            }}
            #header {{
                background-color: {"#e3f2fd" if self._is_active else "#f5f5f5"};
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
                border-bottom: 1px solid #ced4da;
            }}
        """)
