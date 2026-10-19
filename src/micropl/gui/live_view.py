"""
Live view panel for real-time camera display.
"""

import time
import logging
import os
from datetime import datetime
from typing import Optional, cast
from pathlib import Path
import numpy as np
from ..qt import (
    QScrollArea, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QGroupBox, QDoubleSpinBox, 
    QComboBox, QSpinBox, Qt, QTimer, QLineEdit, 
    QFrame, QMenu, QStackedWidget, QApplication, 
    QCheckBox, QMessageBox, QFileDialog, QDialog,
    QSizePolicy, pyqtSignal, pyqtSlot,
    QIcon, QSize, QThread
)
import threading

from .plot import PlotWidget, ImagePlotWidget, CoordinateWidget
from ..core.measurement import MeasurementResult
from ..core.data_manager import DataManager
from ..hardware.andor_camera import AndorCamera

logger = logging.getLogger(__name__)


from ..hardware.manager import HardwareManager
from .camera_sidebar import CameraCard
from .reorderable_container import ReorderableVBoxContainer

class LiveView(QWidget):
    """Widget for live camera display."""
    sig_cam_connect_done = pyqtSignal(str) # camera_name
    
    # Coordination signals for Measurement Monitoring (parity with AutomationPanel)
    sequence_started = pyqtSignal(list, float, int)
    step_progress = pyqtSignal(int, str, int)
    measurement_ready = pyqtSignal(np.ndarray, np.ndarray, str)
    sequence_finished = pyqtSignal(bool, str)

    def __init__(self):
        super().__init__()
        self.hw = HardwareManager()
        self.background_frame = None
        self._acquiring = False
        self._active_camera_id: Optional[str] = None
        self.camera_panels = {}
        
        # Connect to Hardware Service signals
        service = self.hw.service
        service.camera_frame_ready.connect(self._on_camera_frame)
        service.camera_temp_changed.connect(self._on_camera_temp)
        service.camera_status_changed.connect(self._on_camera_status_changed)
        service.mono_status_changed.connect(self._on_mono_status_changed)
        service.spectral_unit_changed.connect(self._on_spectral_unit_changed)
        service.spectral_display_mode_changed.connect(self._on_spectral_mode_changed)

        
        self._background_exposure = None 
        self._background_camera_id = None 
        self._camera_states = {} # Map camera_id -> dict of UI states
        self._mono_connected_prev = False 
        self._spec_connecting = False
        self._vis_connecting = False
        self._last_unit_mode = None
        self._last_spectral_unit = None
        self._last_data_mode = None
        self._is_showing_mismatch_msg = False # Guard to prevent multiple modal popups
        self._last_exposure_ms = None # Track last set value to avoid direct-type updates
        self._seq_worker: Optional[QThread] = None
        
        # Caching for spectral axis to avoid expensive hardware calls every frame
        self._spectral_x_cache = None
        self._spectral_x_cache_key = None
        
        self._init_ui()
        
        # Internal signal for thread-safe connection finalization
        self.sig_cam_connect_done.connect(self._on_cam_connection_finished)
        
        logger.info("Live view initialized (Signal-driven)")


    def _get_current_camera_id(self) -> Optional[str]:
        """Return the camera ID that corresponds to the active camera card."""
        return self._active_camera_id

    @property
    def current_camera(self) -> Optional[AndorCamera]:
        """Dynamic reference to the currently selected camera object."""
        return cast(Optional[AndorCamera], self.hw.get_camera(self._active_camera_id)) if self._active_camera_id else None
    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        self.setLayout(layout)

        # Main consolidated control group
        control_group = self._create_main_control_group()
        layout.addWidget(control_group)

        # Display Stack (Image vs Spectrum)
        self.display_stack = QStackedWidget()
        
        # 1. Image View (now using PyQtGraph via ImagePlotWidget)
        self.image_plot = ImagePlotWidget()
        self.image_plot.sigMouseMoved.connect(self._on_plot_mouse_moved)
        self.display_stack.addWidget(self.image_plot)
        
        # 2. Spectrum View (now using PyQtGraph via PlotWidget)
        self.spectrum_plot = PlotWidget()
        self.spectrum_plot.set_labels("Pixel", "Counts")
        self.spectrum_plot.sigMouseMoved.connect(self._on_plot_mouse_moved)
        self.display_stack.addWidget(self.spectrum_plot)
        
        layout.addWidget(self.display_stack, stretch=10) # Heavy stretch for data area

        # Acquisition settings
        settings_group = self._create_settings_group()
        layout.addWidget(settings_group)
        
        # Data Management (Manual Metadata & Save Settings)
        data_group = self._create_data_group()
        layout.addWidget(data_group)

        # Connect auto-range disabling signals (must be after _create_settings_group)
        # Note: We only auto-disable it for Spectrum mode as requested by the user
        self.spectrum_plot.sigAutoRangeDisabled.connect(lambda: self.auto_all_btn.setChecked(False))
        
        self._init_camera_strip_widget()
        self.rebuild_camera_strip()

    def _init_camera_strip_widget(self):
        """Initialize the camera strip widget but don't add it to LiveView's main layout."""
        self.camera_scroll = QScrollArea()
        self.camera_scroll.setWidgetResizable(True)
        self.camera_scroll.setFrameShape(QFrame.Shape.NoFrame)
        # Vertical sidebar now
        self.camera_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.camera_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        
        self.strip_container = ReorderableVBoxContainer('application/x-camera-panel')
        self.strip_container.order_changed.connect(self._on_camera_order_changed)
        
        self.camera_scroll.setWidget(self.strip_container)

    def _create_main_control_group(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        
        global_group = QGroupBox("Global Settings")
        global_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        global_group.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        global_layout = QVBoxLayout(global_group)
        global_layout.setSpacing(5)
        
        layout.addWidget(global_group, stretch=0)
        
        # 2. Sequence Controls
        seq_group = QGroupBox("Sequence Controls")
        seq_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        seq_layout = QVBoxLayout(seq_group)
        seq_layout.setSpacing(2) # Compact
        
        btn_row = QHBoxLayout()
        assets_dir = os.path.join(os.path.dirname(__file__), "assets")
        self.icon_play = QIcon(os.path.join(assets_dir, "play_button.png"))
        self.icon_pause = QIcon(os.path.join(assets_dir, "pause_button.png"))
        self.icon_stop = QIcon(os.path.join(assets_dir, "stop_button.png"))

        self.run_sequence_btn = QPushButton("Start Sequence")
        self.run_sequence_btn.setMinimumHeight(30)
        self.run_sequence_btn.setMinimumWidth(180)
        self.run_sequence_btn.setStyleSheet("text-align: left; padding-left: 10px;")
        
        self.run_menu = QMenu(self)
        
        action_heating = self.run_menu.addAction("Laser Heating")
        assert action_heating is not None
        action_heating.triggered.connect(self._on_run_sequence_clicked)
        
        action_power = self.run_menu.addAction("Power Series")
        assert action_power is not None
        action_power.triggered.connect(self._on_run_power_series_clicked)
        
        action_mapping = self.run_menu.addAction("XY Mapping")
        assert action_mapping is not None
        action_mapping.triggered.connect(self._on_run_mapping_clicked)
        
        action_custom = self.run_menu.addAction("Custom Sequence")
        assert action_custom is not None
        action_custom.triggered.connect(self._on_run_custom_sequence_clicked)
        
        self.run_sequence_btn.setMenu(self.run_menu)


        self.pause_resume_btn = QPushButton()
        self.pause_resume_btn.setIcon(self.icon_pause)
        self.pause_resume_btn.setIconSize(QSize(20, 20))
        self.pause_resume_btn.setToolTip("Pause Sequence")
        self.pause_resume_btn.clicked.connect(self._on_pause_resume_clicked)
        self.pause_resume_btn.setEnabled(False)
        self.pause_resume_btn.setFixedSize(30, 30)
        self.pause_resume_btn.setStyleSheet("""
            QPushButton {
                padding: 0px;
                border: 1px solid #ccc;
                border-radius: 4px;
                background-color: #f0f0f0;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
            QPushButton:pressed {
                background-color: #d0d0d0;
            }
            QPushButton:disabled {
                background-color: #f5f5f5;
                border-color: #e0e0e0;
            }
        """)

        self.abort_sequence_btn = QPushButton()
        self.abort_sequence_btn.setIcon(self.icon_stop)
        self.abort_sequence_btn.setIconSize(QSize(20, 20))
        self.abort_sequence_btn.setToolTip("Abort Sequence")
        self.abort_sequence_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                border-radius: 4px;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
            QPushButton:disabled {
                background-color: #888;
            }
        """)
        self.abort_sequence_btn.clicked.connect(self._on_abort_clicked)
        self.abort_sequence_btn.setEnabled(False)
        self.abort_sequence_btn.setFixedSize(30, 30)
        
        btn_row.addWidget(self.run_sequence_btn)
        btn_row.addWidget(self.pause_resume_btn)
        btn_row.addWidget(self.abort_sequence_btn)
        seq_layout.addLayout(btn_row)
        
        layout.addWidget(seq_group, stretch=0, alignment=Qt.AlignmentFlag.AlignTop)
        
        layout.addStretch() # Push everything to the left
        
        # View / Units / Data Type (Single Row)
        top_row = QHBoxLayout()
        
        top_row.addWidget(QLabel("View:"))
        self.view_combo = QComboBox()
        self.view_combo.addItems(["Image", "Spectrum"])
        self.view_combo.currentTextChanged.connect(self._on_view_mode_changed)
        top_row.addWidget(self.view_combo)
        
        top_row.addSpacing(15)
        
        top_row.addWidget(QLabel("Units:"))
        self.spec_unit_combo = QComboBox()
        self.spec_unit_combo.addItems(["Pixel", "Spectral Units"])
        self.spec_unit_combo.currentTextChanged.connect(self._on_unit_mode_changed)
        top_row.addWidget(self.spec_unit_combo)
        
        top_row.addSpacing(15)
        
        top_row.addWidget(QLabel("Data:"))
        self.data_type_combo = QComboBox()
        self.data_type_combo.addItems([
            "Raw Data", 
            "Background correction", 
            "Time Normalized", 
            "Background & Time Normalized"
        ])
        self.data_type_combo.currentTextChanged.connect(self._on_processing_mode_changed)
        top_row.addWidget(self.data_type_combo, stretch=1)
        
        global_layout.addLayout(top_row)
        
        # Thin divider
        div1 = QFrame()
        div1.setFrameShape(QFrame.Shape.HLine)
        div1.setFrameShadow(QFrame.Shadow.Sunken)
        global_layout.addWidget(div1)
        
        # Auto-scale and Axis Locks
        ctrl_row = QHBoxLayout()
        
        self.auto_all_btn = QPushButton("Auto Scale")
        self.auto_all_btn.setCheckable(True)
        self.auto_all_btn.setStyleSheet("""
            QPushButton { font-size: 10px; padding: 4px 10px; }
            QPushButton:checked { background-color: #27ae60; color: white; font-weight: bold; }
        """)
        self.auto_all_btn.toggled.connect(self._on_auto_scale_toggled)
        ctrl_row.addWidget(self.auto_all_btn)
        
        self.lock_x_check = QCheckBox("X Lock")
        self.lock_y_check = QCheckBox("Y Lock")
        self.lock_x_check.toggled.connect(self._on_axis_lock_changed)
        self.lock_y_check.toggled.connect(self._on_axis_lock_changed)
        ctrl_row.addWidget(self.lock_x_check)
        ctrl_row.addWidget(self.lock_y_check)
        
        ctrl_row.addSpacing(20)

        # Markers
        ctrl_row.addWidget(QLabel("Markers:"))
        self.marker_xy_btn = QPushButton("XY")
        self.marker_x_btn = QPushButton("X")
        self.marker_y_btn = QPushButton("Y")
        self.marker_clear_btn = QPushButton("Clear")
        for btn in [self.marker_xy_btn, self.marker_x_btn, self.marker_y_btn, self.marker_clear_btn]:
            btn.setStyleSheet("font-size: 10px; padding: 2px 8px;")
            ctrl_row.addWidget(btn)
        
        self.marker_xy_btn.clicked.connect(lambda: self._on_add_marker("xy"))
        self.marker_x_btn.clicked.connect(lambda: self._on_add_marker("x"))
        self.marker_y_btn.clicked.connect(lambda: self._on_add_marker("y"))
        self.marker_clear_btn.clicked.connect(self._on_clear_markers)
        
        ctrl_row.addStretch()
        global_layout.addLayout(ctrl_row)
        
        # Coords widget and colormaps on bottom row
        bottom_row = QHBoxLayout()
        self.coords_widget = CoordinateWidget()
        bottom_row.addWidget(self.coords_widget, stretch=1)
        
        # Colormaps
        cmap_layout = QHBoxLayout()
        cmap_layout.setSpacing(2)
        cmaps = [('grey', "#000", "#fff"), ('viridis', "#440154", "#addc30"), 
                 ('inferno', "#000", "#f57d15"), ('plasma', "#0d0887", "#fca636")]
        for name, c1, c2 in cmaps:
            btn = QPushButton()
            btn.setFixedSize(18, 18)
            btn.setStyleSheet(f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c1}, stop:1 {c2});")
            btn.clicked.connect(lambda checked, n=name: self.image_plot.set_colormap(n))
            cmap_layout.addWidget(btn)
        bottom_row.addLayout(cmap_layout)
        
        global_layout.addLayout(bottom_row)
        
        return container

    def rebuild_camera_strip(self):
        """Rebuild the camera strip from config."""
        # Clear layout
        while self.strip_container.count() > 0:
            item = self.strip_container.widgetAt(0)
            if item:
                self.strip_container.removeWidget(item)
                item.deleteLater()
        self.camera_panels.clear()
        
        cameras_cfg = self.hw.config.get('hardware', {}).get('cameras', [])
        for cam_cfg in cameras_cfg:
            if not cam_cfg.get('enabled', False):
                continue
            cam_id = cam_cfg['id']
            card = CameraCard(cam_id, cam_cfg)
            
            # Connect signals
            card.camera_selected.connect(self._on_camera_panel_selected)
            card.connect_requested.connect(self._on_cam_connect_clicked)
            card.apply_roi_requested.connect(self.apply_roi)
            card.readout_mode_changed.connect(lambda cid, text: self._on_readout_mode_changed(text, cid=cid))
            card.temp_changed_requested.connect(self._on_card_temp_changed)
            
            self.strip_container.addWidget(card)
            self.camera_panels[cam_id] = card
        
        # Auto-select first camera if active is gone or none selected
        if self.camera_panels:
            if self._active_camera_id not in self.camera_panels:
                self._on_camera_panel_selected(list(self.camera_panels.keys())[0])
            else:
                self._on_camera_panel_selected(self._active_camera_id)
        
        # Stretch handled by ReorderableVBoxContainer

    def _on_camera_order_changed(self):
        new_order = []
        for i in range(self.strip_container.count()):
            w = self.strip_container.widgetAt(i)
            if isinstance(w, CameraCard):
                new_order.append(w.camera_id)
                
        # Reorder cameras in hw config
        hw_cfg = self.hw.config.setdefault('hardware', {})
        cameras_cfg = hw_cfg.setdefault('cameras', [])
        
        ordered_cameras = []
        for cid in new_order:
            for cam in cameras_cfg:
                if cam.get('id') == cid:
                    ordered_cameras.append(cam)
                    break
                    
        for cam in cameras_cfg:
            if cam.get('id') not in new_order:
                ordered_cameras.append(cam)
                
        hw_cfg['cameras'] = ordered_cameras
        logger.info(f"Camera order updated in memory: {new_order}")

    def _on_camera_panel_selected(self, camera_id: str):
        """
        Handle camera selection from the sidebar.
        
        This method is critical for allowing multiple cameras (e.g., Visualisation vs Spectroscopy) 
        to share the same UI panels. When a user switches cameras:
        1. It saves the exact UI state (exposure, background frames, units) of the old camera.
        2. It loads the cached UI state of the new camera.
        3. It transparently disconnects and reconnects hardware polling hooks.
        """
        # 1. Store current state for the previous camera
        if self._active_camera_id:
            self._camera_states[self._active_camera_id] = {
                'frame': self.background_frame,
                'exposure_bg': self._background_exposure,
                'exposure': self.exposure_box.value(),
                'view': self.view_combo.currentText(),
                'units': self.spec_unit_combo.currentText(),
                'data_type': self.data_type_combo.currentText()
            }

        # 2. Switch to new camera
        if self._acquiring:
            logger.info("Stopping acquisition on current camera before switching")
            self.stop_live_view()
            
        self._active_camera_id = camera_id
        for cid, card in self.camera_panels.items():
            card.set_active(cid == camera_id)
        
        # Change current internal logic to match new camera
        cam = self.current_camera
        is_connected = cam.is_connected() if cam else False
        
        # Update layout states
        self._update_camera_controls_enabled(is_connected)
        
        # 3. Load and apply state for the new camera
        state = self._camera_states.get(camera_id, None)
        if state is None:
            state = self._get_default_state_for_camera(camera_id)
        
        # Block signals to prevent redundant updates while restoring
        self.view_combo.blockSignals(True)
        self.spec_unit_combo.blockSignals(True)
        self.data_type_combo.blockSignals(True)
        
        self.background_frame = state.get('frame')
        self._background_exposure = state.get('exposure_bg')
        self._background_camera_id = camera_id if self.background_frame is not None else None
        
        # Restore exposure (round to nearest ms)
        new_exposure = round(state.get('exposure', 100))
        self.exposure_box.setValue(new_exposure)
        self._last_exposure_ms = None # Force update
        self.update_exposure()
        
        logger.info(f"Restored state for {camera_id}: exposure={new_exposure}ms, view={state.get('view')}")
        
        self.view_combo.setCurrentText(state.get('view', "Image"))
        self.spec_unit_combo.setCurrentText(state.get('units', "Pixel"))
        self.data_type_combo.setCurrentText(state.get('data_type', "Raw Data"))

        self.view_combo.blockSignals(False)
        self.spec_unit_combo.blockSignals(False)
        self.data_type_combo.blockSignals(False)
        
        # Manually trigger updates that signals would have triggered
        self._on_view_mode_changed(self.view_combo.currentText())
        self._on_unit_mode_changed(self.spec_unit_combo.currentText())
        self._on_processing_mode_changed(self.data_type_combo.currentText())
            
        if is_connected:
            self._on_cam_connection_finished(camera_id)

    def _get_default_state_for_camera(self, camera_id: str) -> dict:
        """Calculate the initial UI state for a camera based on its role."""
        cam_cfg = self.hw.get_camera_config(camera_id)
        role = cam_cfg.get('role', 'general')
        exposure = cam_cfg.get('exposure_time', 0.1) * 1000.0 # s to ms
        
        # Check if mono is connected
        mono = self.hw.get_instrument('mono')
        is_mono_connected = mono.is_connected() if mono else False
        
        if role == 'spectroscopy':
            return {
                'exposure': exposure,
                'view': "Spectrum",
                'units': "Spectral Units" if is_mono_connected else "Pixel",
                'data_type': "Raw Data"
            }
        else:
            return {
                'exposure': exposure,
                'view': "Image",
                'units': "Pixel",
                'data_type': "Raw Data"
            }

    def _on_card_temp_changed(self, camera_id: str, temp: float):
        """Forward set temperature from card to hardware."""
        cam = cast(Optional[AndorCamera], self.hw.get_camera(camera_id))
        if cam and cam.is_connected():
            try:
                cam.set_temperature(temp)
            except Exception as e:
                logger.error(f"Failed to set temperature for {camera_id}: {e}")



    def _create_settings_group(self) -> QGroupBox:
        """Create acquisition settings controls."""
        group = QGroupBox("Acquisition")
        group.setStyleSheet("QGroupBox { font-weight: bold; }")
        layout = QHBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5) # Unified margins
        group.setLayout(layout)

        # --- Left Side: Camera Controls ---
        layout.addWidget(QLabel("Exposure (ms):"))
        self.exposure_box = QSpinBox()
        self.exposure_box.setRange(1, 1000000)
        self.exposure_box.setSingleStep(100)
        self.exposure_box.setValue(100)
        self._last_exposure_ms = 100
        self.exposure_box.editingFinished.connect(self.update_exposure)
        layout.addWidget(self.exposure_box)

        # Status Label
        self.bg_status_label = QLabel("RAW DATA")
        self.bg_status_label.setStyleSheet("color: gray; font-size: 10px; font-weight: bold;")
        layout.addWidget(self.bg_status_label)

        # Live Button
        self.live_btn = QPushButton("Live")
        self.live_btn.setCheckable(True)
        self.live_btn.setMinimumWidth(80)
        self.live_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                font-weight: bold;
                border-radius: 4px;
                padding: 4px;
            }
            QPushButton:hover {
                background-color: #218838;
            }
            QPushButton:checked {
                background-color: #dc3545;
            }
            QPushButton:checked:hover {
                background-color: #c82333;
            }
            QPushButton:disabled {
                background-color: #e9ecef;
                color: #6c757d;
                border: 1px solid #dee2e6;
            }
        """)
        self.live_btn.clicked.connect(self._on_live_toggled)
        layout.addWidget(self.live_btn)

        # Background Button
        self.background_btn = QPushButton("Take Background")
        self.background_btn.clicked.connect(self.take_background)
        layout.addWidget(self.background_btn)

        layout.addSpacing(10)

        # Pixel Deviation Offset
        layout.addWidget(QLabel("Pixel Deviation:"))
        self.pixel_dev_box = QDoubleSpinBox()
        self.pixel_dev_box.setRange(-500.0, 500.0)
        self.pixel_dev_box.setDecimals(1)
        self.pixel_dev_box.setFixedWidth(60)
        # Pull from manager (synchronized)
        self.pixel_dev_box.setValue(self.hw.pixel_deviation)
        self.pixel_dev_box.valueChanged.connect(self._on_pixel_dev_changed)
        layout.addWidget(self.pixel_dev_box)

        layout.addStretch()

        self.logs_btn = QPushButton("Show Logs")
        def show_logs():
            win = self.window()
            if win and hasattr(win, 'show_logs'):
                win.show_logs()
        self.logs_btn.clicked.connect(show_logs)
        layout.addWidget(self.logs_btn)

        return group


    def _on_add_marker(self, marker_type):
        """Add a marker to the active plot."""
        if self.view_combo.currentText() == "Spectrum":
            self.spectrum_plot.add_marker(marker_type)
        else:
            self.image_plot.add_marker(marker_type)

    def _on_clear_markers(self):
        """Clear all markers from both plots."""
        self.spectrum_plot.remove_markers()
        self.image_plot.remove_markers()

    def _get_filtered_metadata(self) -> dict:
        """Collect metadata from hardware and filter out inactive cameras."""
        meta = self.hw.collect_metadata()
        if 'Camera' in meta and self._active_camera_id:
            if self._active_camera_id in meta['Camera']:
                meta['Camera'] = {self._active_camera_id: meta['Camera'][self._active_camera_id]}
            else:
                meta['Camera'] = {}
        return meta

    def _get_safe_save_dir(self, base_dir: str, prefix: str) -> Optional[str]:
        """
        Check if base_dir is not empty. If it contains files, ask the user if they want
        to create a new timestamped subfolder or overwrite existing data.
        """
        if not os.path.exists(base_dir):
            return base_dir
            
        try:
            # Check if there are any files or directories inside base_dir
            has_files = any(os.scandir(base_dir))
        except Exception:
            has_files = False
            
        if has_files:
            reply = QMessageBox.question(
                self, "Directory Not Empty",
                f"The directory '{base_dir}' already contains files.\n\n"
                "Do you want to create a new timestamped subfolder to avoid overwriting your previous data?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes
            )
            
            if reply == QMessageBox.StandardButton.Cancel:
                return None
            elif reply == QMessageBox.StandardButton.Yes:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                new_dir = os.path.join(base_dir, f"{prefix}_{timestamp}")
                return new_dir
                
        return base_dir

    def _on_run_sequence_clicked(self):
        """Handle 'Run Heating Sequence' button click."""
        main_window = self.window()
        from .automation_panel import AutomationPanel, LaserHeatingWorker
        from .sequence_dialog import LaserHeatingSummaryDialog
        
        automation_panel = None
        if main_window:
            automation_panel = main_window.findChild(AutomationPanel)
            if not automation_panel and hasattr(main_window, 'automation_panel'):
                automation_panel = main_window.automation_panel
        
        if not automation_panel:
            QMessageBox.warning(self, "Error", "Could not find Automation Panel.")
            return

        steps = automation_panel.get_sequence_steps()
        if not steps:
            QMessageBox.warning(self, "Empty Sequence", "The sequence is empty.")
            return
            
        start_idx = automation_panel.start_step_spin.value()
        cooling_delay = automation_panel.get_cooling_delay()
        meas_power_w = automation_panel.get_measurement_power()
        dlg = LaserHeatingSummaryDialog(
            steps,
            cooling_delay=cooling_delay,
            start_index=start_idx,
            meas_power_w=meas_power_w,
            parent=self
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
            
        try:
            # 1. Collect Full Metadata
            meas_power_w = automation_panel.get_measurement_power()
            bg_meta = self._get_filtered_metadata()
            
            # Convert UI manual power to W for metadata consistency
            p_val = self.manual_power_spin.value()
            p_unit = self.power_unit_combo.currentText()
            manual_power_w = p_val * (1e-3 if p_unit == "mW" else 1e-6 if p_unit == "µW" else 1e-9)
            
            bg_meta['Laser'] = {
                'Wavelength (nm)': self.laser_wl_box.value(),
                'Mode': self.laser_mode_combo.currentText(),
                'Excitation Power (W)': manual_power_w,
                'Automation Measurement Power (W)': meas_power_w
            }
            bg_meta['Sample Temperature (K)'] = self.sample_temp_box.value()
            bg_meta['Objective'] = self.objective_box.currentText()
            
            save_dir = self.save_path_edit.text()
            save_dir = self._get_safe_save_dir(save_dir, "heating")
            if not save_dir:
                return
            processing_mode = self.hw.data_processing_mode

            # 2. Start Worker
            self._seq_worker = LaserHeatingWorker(
                self.hw, meas_power_w, steps, save_dir, 
                metadata=bg_meta,
                background=self.background_frame,
                background_exposure=self._background_exposure,
                processing_mode=processing_mode,
                cooling_delay=cooling_delay,
                skip_step_0=dlg.should_skip_step_0(),
                start_index=start_idx
            )
            self._seq_worker.progress.connect(self._on_seq_progress)
            self._seq_worker.measurement_ready.connect(self._on_seq_measurement)
            self._seq_worker.finished.connect(self._on_seq_finished)
            
            # Notify Monitor
            self.sequence_started.emit(steps, meas_power_w, start_idx)
            
            # UI State
            self.run_sequence_btn.setEnabled(False)
            self.run_sequence_btn.setText("Heating Running...")
            self.pause_resume_btn.setEnabled(True)
            self.pause_resume_btn.setIcon(self.icon_pause)
            self.pause_resume_btn.setToolTip("Pause Sequence")
            self.abort_sequence_btn.setEnabled(True)
            self.bg_status_label.setText("SEQUENCE RUNNING")
            self.bg_status_label.setStyleSheet("color: red; font-weight: bold;")
            
            self._seq_worker.start()
            
        except Exception as e:
            logger.error(f"Failed to start heating sequence: {e}")
            self.run_sequence_btn.setEnabled(True)
            self.run_sequence_btn.setText("Start Sequence")
            QMessageBox.critical(self, "Error", f"Failed to start sequence: {e}")

    def _on_run_power_series_clicked(self):
        """Handle 'Run Power Series' button click."""
        main_window = self.window()
        from .automation_panel import AutomationPanel, PowerSeriesWorker
        
        automation_panel = None
        if main_window:
            automation_panel = main_window.findChild(AutomationPanel)
            if not automation_panel and hasattr(main_window, 'automation_panel'):
                automation_panel = main_window.automation_panel
        
        if not automation_panel:
            QMessageBox.warning(self, "Error", "Could not find Automation Panel.")
            return

        powers = automation_panel.get_power_series_steps()
        if not powers:
            QMessageBox.warning(self, "Empty Sequence", "The power series is empty.")
            return

        from .sequence_dialog import PowerSeriesSummaryDialog
        stab_delay = automation_panel.get_ps_stabilization_delay()
        dlg = PowerSeriesSummaryDialog(powers, stabilization_delay=stab_delay, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        # Prepare Execution
        try:
            # 1. Collect Full Metadata
            bg_meta = self._get_filtered_metadata()
            
            # Convert UI manual power to W
            p_val = self.manual_power_spin.value()
            p_unit = self.power_unit_combo.currentText()
            manual_power_w = p_val * (1e-3 if p_unit == "mW" else 1e-6 if p_unit == "µW" else 1e-9)
            
            bg_meta['Laser'] = {
                'Wavelength (nm)': self.laser_wl_box.value(),
                'Mode': self.laser_mode_combo.currentText(),
                'Excitation Power (W)': manual_power_w
            }
            bg_meta['Sample Temperature (K)'] = self.sample_temp_box.value()
            bg_meta['Objective'] = self.objective_box.currentText()
            
            save_dir = self.save_path_edit.text()
            save_dir = self._get_safe_save_dir(save_dir, "power_series")
            if not save_dir:
                return
            processing_mode = self.hw.data_processing_mode
            stab_delay = automation_panel.get_ps_stabilization_delay()

            # 2. Start Worker
            self._seq_worker = PowerSeriesWorker(
                self.hw, powers, save_dir, metadata=bg_meta,
                background=self.background_frame,
                processing_mode=processing_mode,
                stabilization_delay=stab_delay
            )
            self._seq_worker.progress.connect(self._on_seq_progress)
            self._seq_worker.finished.connect(self._on_seq_finished)
            self._seq_worker.measurement_ready.connect(self._on_seq_measurement)
            
            # Notify monitor
            self.sequence_started.emit(powers, powers[0], 1)
            
            # UI State
            self.run_sequence_btn.setEnabled(False)
            self.run_sequence_btn.setText("Power Series Running...")
            self.pause_resume_btn.setEnabled(True)
            self.pause_resume_btn.setIcon(self.icon_pause)
            self.pause_resume_btn.setToolTip("Pause Sequence")
            self.abort_sequence_btn.setEnabled(True)
            self.bg_status_label.setText("SEQUENCE RUNNING")
            self.bg_status_label.setStyleSheet("color: red; font-weight: bold;")
            
            self._seq_worker.start()
            
        except Exception as e:
            logger.error(f"Failed to start power series: {e}")
            QMessageBox.critical(self, "Sequence Error", f"Could not start power series: {e}")
            self.run_sequence_btn.setEnabled(True)
            self.run_sequence_btn.setText("Start Sequence")

    def _on_run_mapping_clicked(self):
        """Handle 'Start XY Mapping' button click."""
        main_window = self.window()
        from .automation_panel import AutomationPanel, MappingWorker
        
        automation_panel = None
        if main_window:
            automation_panel = main_window.findChild(AutomationPanel)
            if not automation_panel and hasattr(main_window, 'automation_panel'):
                automation_panel = main_window.automation_panel
            
        if not automation_panel:
            QMessageBox.warning(self, "Error", "Could not find Automation Panel.")
            return

        if automation_panel.map_table.rowCount() == 0:
            automation_panel._on_generate_map()
        
        if automation_panel.map_table.rowCount() == 0:
            QMessageBox.warning(self, "Empty Map", "No valid coordinate points found.")
            return

        # Extract coordinates
        points = []
        for row in range(automation_panel.map_table.rowCount()):
            x_item = automation_panel.map_table.item(row, 1)
            y_item = automation_panel.map_table.item(row, 2)
            if x_item is not None and y_item is not None:
                try:
                    points.append((float(x_item.text()), float(y_item.text())))
                except ValueError:
                    pass

        if len(points) == 0:
            QMessageBox.warning(self, "Empty Map", "No valid coordinate points found.")
            return

        from .sequence_dialog import MappingSummaryDialog
        stab_delay = automation_panel.map_stab_spin.value()
        dlg = MappingSummaryDialog(points, stabilization_delay=stab_delay, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        # Prepare Execution
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            data_dir = os.path.join(self.hw.config.get('paths', {}).get('data_root', './data'), f"map_{timestamp}")
            
            bg_meta = self._get_filtered_metadata()
            
            p_val = self.manual_power_spin.value()
            p_unit = self.power_unit_combo.currentText()
            manual_power_w = p_val * (1e-3 if p_unit == "mW" else 1e-6 if p_unit == "µW" else 1e-9)
            
            bg_meta['Laser'] = {
                'Wavelength (nm)': self.laser_wl_box.value(),
                'Mode': self.laser_mode_combo.currentText(),
                'Excitation Power (W)': manual_power_w
            }
            bg_meta['Sample Temperature (K)'] = self.sample_temp_box.value()
            bg_meta['Objective'] = self.objective_box.currentText()
            
            processing_mode = self.hw.data_processing_mode
            stab_delay = automation_panel.map_stab_spin.value()

            self._seq_worker = MappingWorker(
                self.hw, points, data_dir, metadata=bg_meta,
                background=self.background_frame,
                processing_mode=processing_mode,
                stabilization_delay=stab_delay
            )
            self._seq_worker.progress.connect(self._on_seq_progress)
            self._seq_worker.finished.connect(self._on_seq_finished)
            self._seq_worker.measurement_ready.connect(self._on_seq_measurement)
            
            # Notify monitor
            self.sequence_started.emit(points, 0.0, 1)
            
            # UI State
            self.run_sequence_btn.setEnabled(False)
            self.run_sequence_btn.setText("Mapping Running...")
            self.pause_resume_btn.setEnabled(True)
            self.pause_resume_btn.setIcon(self.icon_pause)
            self.pause_resume_btn.setToolTip("Pause Sequence")
            self.abort_sequence_btn.setEnabled(True)
            self.bg_status_label.setText("SEQUENCE RUNNING")
            self.bg_status_label.setStyleSheet("color: red; font-weight: bold;")
            
            self._seq_worker.start()
            
        except Exception as e:
            logger.error(f"Failed to start mapping: {e}")
            QMessageBox.critical(self, "Sequence Error", f"Could not start mapping: {e}")
            self.run_sequence_btn.setEnabled(True)
            self.run_sequence_btn.setText("Start Sequence")

    def _on_run_custom_sequence_clicked(self):
        """Handle 'Run Custom Sequence' button click."""
        main_window = self.window()
        from .automation_panel import AutomationPanel, CustomSequenceWorker
        from .sequence_dialog import CustomSequenceSummaryDialog
        
        automation_panel = None
        if main_window:
            automation_panel = main_window.findChild(AutomationPanel)
            if not automation_panel and hasattr(main_window, 'automation_panel'):
                automation_panel = main_window.automation_panel
        
        if not automation_panel:
            QMessageBox.warning(self, "Error", "Could not find Automation Panel.")
            return

        steps = automation_panel.get_custom_sequence_steps()
        if not steps:
            QMessageBox.warning(self, "Empty Sequence", "The custom sequence is empty.")
            return

        dlg = CustomSequenceSummaryDialog(steps, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        # Prepare Execution
        try:
            # 1. Collect Full Metadata
            bg_meta = self._get_filtered_metadata()
            
            # Convert UI manual power to W for metadata consistency
            p_val = self.manual_power_spin.value()
            p_unit = self.power_unit_combo.currentText()
            manual_power_w = p_val * (1e-3 if p_unit == "mW" else 1e-6 if p_unit == "µW" else 1e-9)
            
            bg_meta['Laser'] = {
                'Wavelength (nm)': self.laser_wl_box.value(),
                'Mode': self.laser_mode_combo.currentText(),
                'Excitation Power (W)': manual_power_w,
            }
            bg_meta['Sample Temperature (K)'] = self.sample_temp_box.value()
            bg_meta['Objective'] = self.objective_box.currentText()
            
            save_dir = self.save_path_edit.text()
            save_dir = self._get_safe_save_dir(save_dir, "custom")
            if not save_dir:
                return
            processing_mode = self.hw.data_processing_mode

            # 2. Start Worker
            self._seq_worker = CustomSequenceWorker(
                self.hw, steps, save_dir, 
                metadata=bg_meta,
                background=self.background_frame,
                background_exposure=self._background_exposure,
                processing_mode=processing_mode
            )
            self._seq_worker.progress.connect(self._on_seq_progress)
            self._seq_worker.measurement_ready.connect(self._on_seq_measurement)
            self._seq_worker.finished.connect(self._on_seq_finished)
            
            # Notify Monitor
            self.sequence_started.emit(self._seq_worker.steps, 0.0, 1)
            
            # UI State
            self.run_sequence_btn.setEnabled(False)
            self.run_sequence_btn.setText("Custom Running...")
            self.pause_resume_btn.setEnabled(True)
            self.pause_resume_btn.setIcon(self.icon_pause)
            self.pause_resume_btn.setToolTip("Pause Sequence")
            self.abort_sequence_btn.setEnabled(True)
            self.bg_status_label.setText("SEQUENCE RUNNING")
            self.bg_status_label.setStyleSheet("color: red; font-weight: bold;")
            
            self._seq_worker.start()
            
        except Exception as e:
            logger.error(f"Failed to start custom sequence: {e}")
            self.run_sequence_btn.setEnabled(True)
            self.run_sequence_btn.setText("Start Sequence")
            QMessageBox.critical(self, "Error", f"Failed to start sequence: {e}")

    def _on_seq_progress(self, step_idx, status, percent):

        """Update UI with sequence progress."""
        logger.info(f"Sequence: {status}")
        # Forward to monitor
        self.step_progress.emit(step_idx, status, percent)

    def _on_seq_measurement(self, x, y, label):
        """Plot intermediate sequence result."""
        self.spectrum_plot.plot(x, y)
        # Forward to monitor
        self.measurement_ready.emit(x, y, label)

    def _on_pause_resume_clicked(self):
        if not hasattr(self, '_seq_worker') or self._seq_worker is None:
            return

        if self.pause_resume_btn.toolTip() == "Pause Sequence":
            if hasattr(self._seq_worker, 'pause'):
                getattr(self._seq_worker, 'pause')()
            self.pause_resume_btn.setIcon(self.icon_play)
            self.pause_resume_btn.setToolTip("Resume Sequence")
            self.bg_status_label.setText("SEQUENCE PAUSED")
            self.bg_status_label.setStyleSheet("color: orange; font-weight: bold;")
        else:
            if hasattr(self._seq_worker, 'resume'):
                getattr(self._seq_worker, 'resume')()
            self.pause_resume_btn.setIcon(self.icon_pause)
            self.pause_resume_btn.setToolTip("Pause Sequence")
            self.bg_status_label.setText("SEQUENCE RUNNING")
            self.bg_status_label.setStyleSheet("color: red; font-weight: bold;")

    def _on_abort_clicked(self):
        if not hasattr(self, '_seq_worker') or self._seq_worker is None:
            return
            
        if hasattr(self._seq_worker, 'stop'):
            getattr(self._seq_worker, 'stop')()
            
        QMessageBox.information(self, "Sequence Aborted", "The sequence has been aborted.")
        
        self.pause_resume_btn.setEnabled(False)
        self.abort_sequence_btn.setEnabled(False)

    def _on_seq_finished(self, success, message):
        """Handle sequence completion."""
        self.run_sequence_btn.setEnabled(True)
        self.run_sequence_btn.setText("Start Sequence")
        self.pause_resume_btn.setEnabled(False)
        self.pause_resume_btn.setIcon(self.icon_pause)
        self.pause_resume_btn.setToolTip("Pause Sequence")
        self.abort_sequence_btn.setEnabled(False)
        self.bg_status_label.setText("RAW DATA") # Reset
        self.bg_status_label.setStyleSheet("color: gray; font-size: 10px; font-weight: bold;")
        
        if success:
            QMessageBox.information(self, "Sequence Complete", message)
        else:
            QMessageBox.warning(self, "Sequence Aborted", message)
            
        # Forward to monitor
        self.sequence_finished.emit(success, message)

    def stop_sequence(self):
        """Public method to abort an active sequence."""
        if hasattr(self, '_seq_worker') and self._seq_worker and self._seq_worker.isRunning():
            if hasattr(self._seq_worker, 'stop'):
                getattr(self._seq_worker, 'stop')()

    def pause_sequence(self):
        """Public method to pause the active sequence (called from measurement panel)."""
        if hasattr(self, '_seq_worker') and self._seq_worker and self._seq_worker.isRunning():
            if hasattr(self._seq_worker, 'pause'):
                getattr(self._seq_worker, 'pause')()
            self.pause_resume_btn.setIcon(self.icon_play)
            self.pause_resume_btn.setToolTip("Resume Sequence")
            self.bg_status_label.setText("SEQUENCE PAUSED")
            self.bg_status_label.setStyleSheet("color: orange; font-weight: bold;")

    def resume_sequence(self):
        """Public method to resume a paused sequence (called from measurement panel)."""
        if hasattr(self, '_seq_worker') and self._seq_worker and self._seq_worker.isRunning():
            if hasattr(self._seq_worker, 'resume'):
                getattr(self._seq_worker, 'resume')()
            self.pause_resume_btn.setIcon(self.icon_pause)
            self.pause_resume_btn.setToolTip("Pause Sequence")
            self.bg_status_label.setText("SEQUENCE RUNNING")
            self.bg_status_label.setStyleSheet("color: red; font-weight: bold;")

    def _create_data_group(self) -> QGroupBox:
        """Create manual metadata and save settings group."""
        group = QGroupBox("Data Management")
        group.setStyleSheet("QGroupBox { font-weight: bold; }")
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(5, 5, 5, 5) # Unified margins
        group.setLayout(main_layout)

        # Left Columns: Inputs and Folder
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(5)
        main_layout.addLayout(left_layout, 1)

        # 1. Manual Metadata Row (All in one line)
        meta_row = QHBoxLayout()
        meta_row.setSpacing(0)

        # Laser
        meta_row.addWidget(QLabel("Laser (nm):"))
        meta_row.addSpacing(5)
        self.laser_wl_box = QDoubleSpinBox()
        self.laser_wl_box.setRange(0, 2000)
        self.laser_wl_box.setDecimals(1)
        self.laser_wl_box.setFixedWidth(55)
        default_wl = self.hw.config.get('hardware', {}).get('pm100', {}).get('wavelength', 750.0)
        self.laser_wl_box.setValue(float(default_wl))
        meta_row.addWidget(self.laser_wl_box)

        meta_row.addStretch()

        # Mode
        meta_row.addWidget(QLabel("Mode:"))
        meta_row.addSpacing(5)
        self.laser_mode_combo = QComboBox()
        self.laser_mode_combo.addItems(["CW", "Pulsed"])
        self.laser_mode_combo.setFixedWidth(65)
        meta_row.addWidget(self.laser_mode_combo)

        meta_row.addStretch()

        # Power
        meta_row.addWidget(QLabel("Power:"))
        meta_row.addSpacing(5)
        self.manual_power_spin = QDoubleSpinBox()
        self.manual_power_spin.setRange(0.0, 1000.0)
        self.manual_power_spin.setDecimals(3)
        self.manual_power_spin.setValue(1.0)
        self.manual_power_spin.setFixedWidth(65)
        
        self.power_unit_combo = QComboBox()
        self.power_unit_combo.addItems(["mW", "µW", "nW"])
        self.power_unit_combo.setCurrentText("µW")
        self.power_unit_combo.setFixedWidth(50)
        
        meta_row.addWidget(self.manual_power_spin)
        meta_row.addSpacing(5)
        meta_row.addWidget(self.power_unit_combo)

        meta_row.addStretch()

        # Objective
        meta_row.addWidget(QLabel("Objective:"))
        meta_row.addSpacing(5)
        self.objective_box = QComboBox()
        objectives = self.hw.config.get('acquisition', {}).get('objective_lenses', ["20x", "40x", "63x"])
        self.objective_box.addItems(objectives)
        self.objective_box.setCurrentIndex(1)
        self.objective_box.setEditable(True)
        self.objective_box.setFixedWidth(60)
        meta_row.addWidget(self.objective_box)

        meta_row.addStretch()

        # Temperature
        meta_row.addWidget(QLabel("Temperature (K):"))
        meta_row.addSpacing(5)
        self.sample_temp_box = QDoubleSpinBox()
        self.sample_temp_box.setRange(0, 500)
        self.sample_temp_box.setDecimals(1)
        self.sample_temp_box.setValue(5.0)
        self.sample_temp_box.setFixedWidth(50)
        meta_row.addWidget(self.sample_temp_box)
        
        left_layout.addLayout(meta_row)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(5)
        folder_row.addWidget(QLabel("Folder:"))
        
        # Default save path from config
        default_save_path = self.hw.config.get('paths', {}).get('data_root', str(Path.home() / "Desktop" / "MicroPL_Data"))
        self.save_path_edit = QLineEdit(default_save_path)
        folder_row.addWidget(self.save_path_edit)

        browse_btn = QPushButton("...")
        browse_btn.setFixedWidth(30)
        browse_btn.clicked.connect(self._on_browse_clicked)
        folder_row.addWidget(browse_btn)
        
        left_layout.addLayout(folder_row)

        # Vertical separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(line)

        # 3. Save Button
        self.save_btn = QPushButton("Save")
        self.save_btn.setMinimumWidth(60)
        self.save_btn.setStyleSheet("QPushButton { background-color: #007bff; color: white; border: 1px solid black; border-radius: 4px; padding: 4px; }")
        self.save_btn.clicked.connect(self.save_snapshot)
        main_layout.addWidget(self.save_btn)

        return group

    def _on_pixel_dev_changed(self, value):
        """Handle pixel deviation update."""
        self.hw.pixel_deviation = value
        # Trigger an immediate axis update if we're in wavelength/energy mode
        if self.hw.spectral_display_mode != "Pixel":
            self._update_plot_axis()

    def _on_browse_clicked(self):
        """Open a directory browser."""
        path = QFileDialog.getExistingDirectory(self, "Select Save Directory", self.save_path_edit.text())
        if path:
            self.save_path_edit.setText(path)

    def _on_cam_connect_clicked(self, camera_id: str):
        """Try to connect the specified camera."""
        card = self.camera_panels.get(camera_id)
        if not card:
            return

        logger.info(f"Attempting individual connection for {camera_id} camera")
        
        card.update_connection_state(connected=False, connecting=True)
        
        def _connect_thread():
            try:
                cam = cast(Optional[AndorCamera], self.hw.get_camera(camera_id))
                if not cam:
                    cam_cfg = self.hw.get_camera_config(camera_id)
                    self.hw.initialize_instrument(camera_id, cam_cfg.get('driver', 'andor_camera'), cam_cfg)
                    cam = cast(Optional[AndorCamera], self.hw.get_camera(camera_id))
                if cam:
                    cam.connect()
                    logger.info(f"{camera_id} camera connected successfully")
                else:
                    raise RuntimeError(f"Could not initialize camera {camera_id}")
            except Exception as e:
                logger.error(f"Failed to connect {camera_id} camera: {e}")
            finally:
                # Re-enable button and notify UI for cleanup
                if card:
                    QTimer.singleShot(0, lambda: card.connect_btn.setEnabled(True))
                self.sig_cam_connect_done.emit(camera_id)
        
        threading.Thread(target=_connect_thread, daemon=True).start()

    @pyqtSlot(str)
    def _on_cam_connection_finished(self, camera_id: str):
        """Update UI after camera connection attempt."""
        cam = cast(Optional[AndorCamera], self.hw.get_camera(camera_id))
        is_connected = cam.is_connected() if cam else False
        
        card = self.camera_panels.get(camera_id)
        if card:
            card.update_connection_state(is_connected, False)

        # If this is the active camera, update its specific controls
        if camera_id == getattr(self, '_active_camera_id', None):
            self._update_camera_controls_enabled(is_connected)
            
            if cam and is_connected:
                # Sync settings from hardware
                roi = cam.get_roi()
                actual_size = cam.get_detector_size()
                if card:
                    card.update_roi_limits(actual_size[0], actual_size[1])
                    card.sync_roi(roi)
                
                cam_role = self.hw.get_camera_config(camera_id).get('role', 'general')
                if cam_role == "spectroscopy":
                    # Force hardware sync of readout mode to ensure we aren't in slow Image mode
                    # ONLY for 2D sensors (iDus 420, etc). Linear arrays (1D) don't support mode switching.
                    if actual_size[1] > 1:
                        mode = "Single track"
                        if card: card.readout_combo.setCurrentText(mode)
                        self._on_readout_mode_changed(mode, cid=camera_id, trigger_hardware=True)
                    self.view_combo.setCurrentText("Spectrum")
                else:
                    if card: card.readout_combo.setCurrentText("Image")
                    self.view_combo.setCurrentText("Image")
                    if cam_role == 'visualisation':
                        if card: card.apply_preset("image_vis", trigger_hardware=True)
            
            self._on_view_mode_changed(self.view_combo.currentText())
    def _on_mono_status_changed(self, connected: bool):
        """Handle monochromator connection status changes."""
        # If the active camera is spectroscopy, switch units based on mono connection
        if self._active_camera_id:
            cam_cfg = self.hw.get_camera_config(self._active_camera_id)
            if cam_cfg.get('role', 'general') == 'spectroscopy':
                new_unit = "Spectral Units" if connected else "Pixel"
                if self.spec_unit_combo.currentText() != new_unit:
                    self.spec_unit_combo.setCurrentText(new_unit)
                    logger.info(f"Auto-switched units to {new_unit} due to monochromator status.")

    def _on_spectral_unit_changed(self, new_unit):
        """Handle unit changes (nm, meV, etc.) from other panels."""
        logger.debug(f"LiveView: Spectral units changed to {new_unit}")
        # Invalidate cache
        self._last_spectral_unit = None
        # Force a label update
        self._update_axis_labels()
        # Trigger frame refresh to update plot
        if not self._acquiring and self.current_camera and self.current_camera.is_connected():
             self._handle_new_frame(self.current_camera.read_newest_image())

    @pyqtSlot(str)
    def _on_spectral_mode_changed(self, new_mode):
        """Handle mode changes (Pixel vs Spectral Units) from other panels."""
        logger.debug(f"LiveView: Spectral mode changed to {new_mode}")
        if self.spec_unit_combo.currentText() != new_mode:
            self.spec_unit_combo.blockSignals(True)
            self.spec_unit_combo.setCurrentText(new_mode)
            self.spec_unit_combo.blockSignals(False)
            
        self._update_axis_labels()
        if not self._acquiring and self.current_camera and self.current_camera.is_connected():
             self._handle_new_frame(self.current_camera.read_newest_image())

    def _update_axis_labels(self):
        """Update spectral plot axis labels based on current settings with caching."""
        unit_mode = self.spec_unit_combo.currentText()
        spectral_unit = self.hw.spectral_unit
        mode = self.data_type_combo.currentText()
        
        if unit_mode != self._last_unit_mode or spectral_unit != self._last_spectral_unit or mode != self._last_data_mode:
            y_label = "Counts"
            if "Time Normalized" in mode:
                y_label = "Counts/s"

            if unit_mode == "Pixel":
                self.spectrum_plot.set_labels("Pixel", y_label)
            else:
                label = "Wavelength" if spectral_unit == "nm" else "Energy"
                self.spectrum_plot.set_labels(f"{label} ({spectral_unit})", y_label)
            
            self._last_unit_mode = unit_mode
            self._last_spectral_unit = spectral_unit
            self._last_data_mode = mode
            logger.debug(f"LiveView: Updated axis labels to {unit_mode}/{spectral_unit}/{y_label}")

    def _on_unit_mode_changed(self, mode):
        """Force a refresh of the plot labels and axis when unit mode changes."""
        logger.debug(f"Spectrometer unit mode changed to: {mode}")
        self.hw.spectral_display_mode = mode
        if self.hw.service:
            self.hw.service.spectral_display_mode_changed.emit(mode)
            
        if not self._acquiring and self.current_camera and self.current_camera.is_connected():
            # If not live, try to refresh from last reading if possible
            # For now, just trigger one frame update
            self._handle_new_frame(self.current_camera.read_newest_image())

    def _update_plot_axis(self):
        """Force a refresh of the plot axis by re-processing the latest data."""
        if self.current_camera and self.current_camera.is_connected():
            try:
                # If not currently acquiring, manually trigger a redraw with the newest frame
                if not self._acquiring:
                    frame = self.current_camera.read_newest_image()
                    if frame is not None:
                        self._handle_new_frame(frame)
            except Exception as e:
                logger.debug(f"Failed to refresh plot axis: {e}")

    def _update_camera_controls_enabled(self, enabled: bool):
        """Enable or disable all camera-specific hardware controls."""
        # Hardware Acquisition Controls
        self.exposure_box.setEnabled(enabled)
        self.live_btn.setEnabled(enabled)
        self.background_btn.setEnabled(enabled)
        
        # Stop live if it was running and we are disabling
        if not enabled and self.live_btn.isChecked():
            self.live_btn.setChecked(False)
            self.stop_live_view()
            
        self.pixel_dev_box.setEnabled(enabled)
        self.run_sequence_btn.setEnabled(enabled)
        
        # Snapshot button requires a camera
        self.save_btn.setEnabled(enabled)
        
        # NOTE: View Modes (view_combo), Units (spec_unit_combo), Data Type (data_type_combo),
        # and Plotting tools (Auto-Scale, Markers, Locks) remain ENABLED 
        # so the user can change visualization settings without a camera.

    def _on_auto_scale_toggled(self, checked: bool):
        """Handle continuous auto-scale toggle."""
        if checked:
            # Enable persistent auto-range in both plots
            self.image_plot.auto_scale_all()
            self.spectrum_plot.auto_scale_all()
        else:
            # Explicitly disable auto-scaling on the spectrum plot if unchecked manually
            self.spectrum_plot.disable_auto_scale()

    def _auto_scale_now(self):
        """Immediately trigger auto-scale on active plot."""
        if self.display_stack.currentIndex() == 0:
            self.image_plot.auto_scale_all()
        else:
            self.spectrum_plot.auto_scale_all()

    def _auto_scale_all(self):
        """Legacy handler or manual-trigger-only if needed."""
        self._auto_scale_now()

    def _on_axis_lock_changed(self):
        """Lock/Unlock mouse interaction for X and Y."""
        lock_x = self.lock_x_check.isChecked()
        lock_y = self.lock_y_check.isChecked()
        self.image_plot.set_mouse_enabled(not lock_x, not lock_y)
        self.spectrum_plot.set_mouse_enabled(not lock_x, not lock_y)


    def _on_plot_mouse_moved(self, x, y):
        """Update coordinates display."""
        self.coords_widget.set_coords(x, y)

    def _on_view_mode_changed(self, view_mode):
        """Switch between Image and Spectrum view."""
        if view_mode == "Spectrum":
            self.display_stack.setCurrentIndex(1)
        else:
            self.display_stack.setCurrentIndex(0)
        
        # Clear stale coordinates on switch
        self.coords_widget.clear()
        logger.info(f"View mode changed to {view_mode}")

    def _on_readout_mode_changed(self, mode, cid=None, trigger_hardware: bool = True):
        """Handle readout mode change with automatic ROI configuration."""
        logger.info(f"Readout mode changed to {mode} (trigger={trigger_hardware})")
        
        cam_id = cid or self._active_camera_id
        card = self.camera_panels.get(cam_id) if cam_id else None

        if mode == "FVB":
            if card: card.set_roi_enabled(False)
            
            # Auto-switch to Spectrum view
            self.view_combo.setCurrentText("Spectrum")
            
            # We do NOT call setValue or apply_roi here to preserve previous user ROI
            # the driver handles the FVB geometry internally via set_readout_mode
        elif mode == "Single track":
            if card: card.set_roi_enabled(True)
            
            # Auto-apply preset for spectroscopy cameras
            cam_role = self.hw.get_camera_config(cam_id).get('role', 'general') if cam_id else 'general'
            if cam_role == 'spectroscopy':
                # Only auto-apply if actually connected or if specifically requested
                if trigger_hardware or (self.current_camera and self.current_camera.is_connected()):
                    if card: card.apply_preset("center_spec", trigger_hardware=trigger_hardware)
                
                # Auto-switch to Spectrum view
                self.view_combo.setCurrentText("Spectrum")
        else:
            # Image mode
            if card: card.set_roi_enabled(True)
            
            # Auto-switch to Image view
            self.view_combo.setCurrentText("Image")

        # Update driver mode if connected
        if trigger_hardware and self.current_camera and self.current_camera.is_connected():
            try:
                self.current_camera.set_readout_mode(mode)
            except Exception as e:
                logger.error(f"Failed to set readout mode: {e}")

    def _on_live_toggled(self, checked):
        """Toggle live acquisition."""
        if checked:
            self.start_live_view()
        else:
            self.stop_live_view()

    def start_live_view(self):
        """Start live camera acquisition."""
        if not self.current_camera or not self.current_camera.is_connected():
            logger.warning("Cannot start live view: Camera not connected")
            return

        try:
            self.current_camera.start_acquisition()
            self._acquiring = True
            self.live_btn.setText("Abort")
            # Stylesheet is already handled by :checked state in CSS, but reinforcing for clarity
            logger.info("Live view started")
        except Exception as e:
            logger.error(f"Failed to start live view: {e}")
            self._acquiring = False
            self.live_btn.blockSignals(True)
            self.live_btn.setChecked(False)
            self.live_btn.setText("Live")
            self.live_btn.blockSignals(False)

    def stop_live_view(self):
        """Stop live camera acquisition."""
        if not self.current_camera:
            return

        try:
            self.current_camera.stop_acquisition()
        except:
            pass
            
        self._acquiring = False
        self.live_btn.blockSignals(True)
        self.live_btn.setChecked(False)
        self.live_btn.setText("Live")
        self.live_btn.blockSignals(False)
        logger.info("Live view stopped")

    def apply_roi(self, camera_id: Optional[str] = None):
        """Apply ROI settings to the current camera."""
        if not self.current_camera or not self.current_camera.is_connected():
            return
            
        cam_id = camera_id or self._active_camera_id
        if cam_id != self._active_camera_id:
            return

        try:
            card = self.camera_panels.get(cam_id)
            if not card: return
            x_start, x_end, y_start, y_end, x_bin, y_bin = card.get_roi()

            # Stop acquisition if running
            was_acquiring = self._acquiring
            if was_acquiring:
                self.stop_live_view()

            self.current_camera.set_roi(x_start, x_end, y_start, y_end, x_bin, y_bin)
            logger.info(f"ROI applied: x=[{x_start}:{x_end}], y=[{y_start}:{y_end}], bin=({x_bin},{y_bin})")

            if was_acquiring:
                self.start_live_view()
        except Exception as e:
            logger.error(f"Failed to apply ROI: {e}")

    def take_background(self):
        """Capture a background frame."""
        if not self.current_camera or not self.current_camera.is_connected():
            logger.error("Camera not connected")
            return

        logger.info("Taking background frame")
        try:
            # UI Feedback
            self.background_btn.setEnabled(False)
            self.background_btn.setText("Capturing...")
            self.background_btn.setStyleSheet("background-color: #ffc107; color: black;")
            QApplication.processEvents() # Ensure UI updates

            # Note: acquire_image (snap) now handles its own state (gapless if acquiring)
            # Capture multiple frames and average for a cleaner background
            frames = []
            
            # Note: acquire_image (snap) handles its own setup
            for i in range(5):
                try:
                    frame = self.current_camera.acquire_image()
                    if frame is not None:
                        frames.append(frame.astype(np.float32))
                except Exception as e:
                    logger.warning(f"Failed to capture background frame {i+1}: {e}")
                
                time.sleep(0.05)
                QApplication.processEvents()
            
            if frames:
                self.background_frame = np.mean(frames, axis=0)
                self._background_exposure = self.exposure_box.value()
                self._background_camera_id = self._active_camera_id
                
                # Store in dictionary for future camera switches
                if self._active_camera_id not in self._camera_states:
                    self._camera_states[self._active_camera_id] = {}
                
                self._camera_states[self._active_camera_id].update({
                    'frame': self.background_frame,
                    'exposure': self._background_exposure
                })
                
                logger.info(f"Background captured for {self._background_camera_id} at {self._background_exposure} ms")
                # Auto-switch to Background & Time Normalized if background is taken
                self.data_type_combo.setCurrentText("Background & Time Normalized")
            else:
                QMessageBox.warning(self, "Background Failed", "Could not capture background frames. Check camera connection.")
            
        except Exception as e:
            logger.error(f"Failed to take background: {e}")
        finally:
            # Reset UI
            self.background_btn.setEnabled(True)
            self.background_btn.setText("Take Background")
            self.background_btn.setStyleSheet("")
            QApplication.processEvents()

    def save_snapshot(self):
        """Capture current data and save with full metadata."""
        if not self.current_camera or not self.current_camera.is_connected():
            logger.error("Camera not connected")
            return

        logger.info("Saving data snapshot...")
        try:
            # 1. Collect full hardware metadata
            # Manual Power Input
            try:
                p_val = self.manual_power_spin.value()
                p_unit = self.power_unit_combo.currentText()
                if p_unit == "mW":
                    manual_power_w = p_val * 1e-3
                elif p_unit == "µW":
                    manual_power_w = p_val * 1e-6
                elif p_unit == "nW":
                    manual_power_w = p_val * 1e-9
                else:
                    manual_power_w = 0.0
            except:
                manual_power_w = None

            # 1. Collect metadata from hardware
            # 1. Collect metadata from hardware
            meta = self._get_filtered_metadata()
            
            # 2. Add manual metadata from UI
            meta['Laser'] = {
                'Wavelength (nm)': self.laser_wl_box.value(),
                'Mode': self.laser_mode_combo.currentText(),
                'Excitation Power (W)': manual_power_w
            }
            meta['Sample Temperature (K)'] = self.sample_temp_box.value()
            meta['Objective'] = self.objective_box.currentText()
            
            # 3. Capture image (fresh frame)
            image = self.current_camera.acquire_image()
            
            # 4. Prepare MeasurementResult
            
            # Calculate spectral x-axis if in Spectrum mode
            view_mode = "Image" if self.display_stack.currentIndex() == 0 else "Spectrum"
            
            result = MeasurementResult(
                timestamp=datetime.now(),
                integration_time=self.exposure_box.value() / 1000.0,
                background=self.background_frame,
                background_exposure=(self._background_exposure / 1000.0) if self._background_exposure else None,
                metadata=meta
            )
            
            # 5. Determine save path via Dialog
            folder = Path(self.save_path_edit.text())
            timestamp_str = result.timestamp.strftime("%Y%m%d_%H%M%S")
            
            if view_mode == "Spectrum":
                default_name = f"spectrum_{timestamp_str}.csv"
                filter_str = "CSV Files (*.csv)"
            else:
                default_name = f"image_{timestamp_str}.tif"
                filter_str = "TIFF Files (*.tif)"
                
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Snapshot", 
                str(folder / default_name),
                filter_str
            )
            if not path:
                return
            
            save_path = Path(path)
            
            # 6. Save based on mode
            dm = DataManager(data_root=str(save_path.parent))
            if view_mode == "Spectrum":
                # Prepare for processing
                if image.ndim == 2:
                    spectrum = np.sum(image, axis=0)
                else:
                    spectrum = image
                
                result.intensities = spectrum
                # Always save wavelengths in nm to MeasurementResult. 
                # DataManager will handle conversion based on metadata units.
                result.wavelengths = self._get_spectral_x(len(spectrum), force_nm=True)
                
                # 6. Apply selected processing
                result.process(self.hw.data_processing_mode)
                
                dm.save_spectrum(result, save_path)
                logger.info(f"Spectrum saved: {save_path.name} (Mode: {self.hw.data_processing_mode})")
            else:
                # Image mode
                result.image = image
                dm.save_image(result, save_path)
                logger.info(f"Image saved: {save_path.name}")


        except Exception as e:
            logger.error(f"Failed to save snapshot: {e}")
            # Ensure we try to resume even on error
                
            QMessageBox.critical(self, "Save Failed", f"Could not save data:\n{e}")

    def update_set_temperature(self, temp):
        """Update target temperature on the camera."""
        if self.current_camera and self.current_camera.is_connected():
            try:
                self.current_camera.set_temperature(temp)
                logger.info(f"Target temperature updated to {temp} °C")
            except Exception as e:
                logger.error(f"Failed to set temperature: {e}")

    def _get_spectral_x(self, n_pixels: int, force_nm: bool = False) -> np.ndarray:
        """Calculate spectral x-axis (nm, meV, cm-1) based on mono position with caching."""
        # Default pixel coordinates
        pixels = np.arange(n_pixels)
        
        # Only compute spectral axis for cameras with spectroscopy role
        cam_role = self.hw.get_camera_config(self._active_camera_id).get('role', 'general') if self._active_camera_id else 'general'
        if cam_role != 'spectroscopy':
            return pixels
            
        try:
            # 1. Cache Key Calculation
            unit_mode = self.spec_unit_combo.currentText()
            if unit_mode == "Pixel" and not force_nm:
                return pixels
                
            spectral_unit = self.hw.spectral_unit
            mono = self.hw.mono
            center_wl = mono._center_wavelength if (mono and mono.is_connected()) else 0.0
            
            # Include cached grating index in cache key to invalidate when grating changes
            grating_idx = getattr(self.hw, '_last_grating_idx', None)
            if grating_idx is None and mono and mono.is_connected():
                grating_idx = getattr(mono, '_grating_idx', None)

            cache_key = (n_pixels, center_wl, grating_idx, unit_mode, spectral_unit, self.hw.pixel_deviation, force_nm)
            
            if self._spectral_x_cache_key == cache_key and self._spectral_x_cache is not None:
                return self._spectral_x_cache

            # 2. Cache miss: Perform calculation
            # Use the physical model from HardwareManager
            x_nm = self.hw.get_wavelength_axis()
            
            if x_nm is None:
                return pixels
                
            # If the camera ROI is binned horizontally, x_nm will have length equal to ROI width.
            # We need to ensure it matches n_pixels.
            if len(x_nm) != n_pixels:
                indices = np.linspace(0, len(x_nm)-1, n_pixels)
                x_nm = np.interp(indices, np.arange(len(x_nm)), x_nm)

            if force_nm:
                # We don't cache force_nm requests as they are rare (usually only for save)
                return cast(np.ndarray, x_nm)

            # Convert to desired view unit
            final_x = x_nm
            safe_nm = np.where(x_nm == 0, 1e-9, x_nm)
            if spectral_unit == "meV":
                final_x = 1239841.93 / safe_nm
            elif spectral_unit == "cm⁻¹" or spectral_unit == "cm-1":
                final_x = 1e7 / safe_nm
            
            # Update cache
            self._spectral_x_cache = cast(np.ndarray, final_x)
            self._spectral_x_cache_key = cache_key
            
            return cast(np.ndarray, final_x)
            
        except Exception as e:
            logger.debug(f"Spectral sync failed: {e}")
            return pixels

    def _trigger_exposure_mismatch_warning(self, current_ms: int):
        """
        Notify the user of an exposure mismatch, reset data processing to Raw Data,
        and show a modal warning dialog.
        """
        if getattr(self, '_is_showing_mismatch_msg', False):
            return
            
        # Only trigger if the current camera matches the one used for the background
        bg_id = self._background_camera_id
        if self._active_camera_id != bg_id:
            return

        # Only trigger if we are currently in a mode that uses background subtraction
        if "Background" not in self.hw.data_processing_mode:
            return

        self._is_showing_mismatch_msg = True
        try:
            logger.warning(f"Exposure mismatch detected! Current: {current_ms} ms, BG: {self._background_exposure} ms.")
            
            # 1. Reset UI and Hardware Manager state
            self.data_type_combo.blockSignals(True)
            self.data_type_combo.setCurrentText("Raw Data")
            self.hw.data_processing_mode = "Raw Data"
            self.data_type_combo.blockSignals(False)
            
            # 2. Update status label for immediate feedback
            self.bg_status_label.setText("EXP MISMATCH")
            self.bg_status_label.setStyleSheet("color: #e74c3c; font-size: 10px; font-weight: bold;")

            # 3. Show modal popup to the user (deferred slightly to ensure clean rendering)
            msg = (f"The current exposure ({current_ms} ms) does not match the background exposure ({self._background_exposure} ms).\n\n"
                  "Data mode has been reset to Raw Data to avoid incorrect background subtraction.")
            
            QTimer.singleShot(100, lambda: QMessageBox.warning(self, "Exposure Mismatch", msg))
        finally:
            self._is_showing_mismatch_msg = False

    def update_exposure(self):
        """Update camera exposure time (input in ms)."""
        if self.current_camera and self.current_camera.is_connected():
            try:
                exposure_ms = self.exposure_box.value()
                
                # Guard: Only update hardware if the value actually changed
                if self._last_exposure_ms is not None and exposure_ms == self._last_exposure_ms:
                    return

                exposure_s = exposure_ms / 1000.0
                self.current_camera.set_exposure(exposure_s)
                self._last_exposure_ms = exposure_ms
                
                # Update persistent state immediately
                if self._active_camera_id:
                    if self._active_camera_id not in self._camera_states:
                        self._camera_states[self._active_camera_id] = self._get_default_state_for_camera(self._active_camera_id)
                    self._camera_states[self._active_camera_id]['exposure'] = exposure_ms

                logger.info(f"Exposure set to {exposure_ms} ms ({exposure_s} s)")
                
                # Check background compatibility and trigger warning if needed
                if self.background_frame is not None and self._background_exposure != exposure_ms:
                    self._trigger_exposure_mismatch_warning(exposure_ms)
            except Exception as e:
                logger.error(f"Failed to set exposure: {e}")

    @pyqtSlot(str, np.ndarray)
    def _on_camera_frame(self, camera_id: str, frame: np.ndarray):
        """Handle new frame from any camera — route to display if it's the active one."""
        if camera_id == self._get_current_camera_id() and self._acquiring:
            self._handle_new_frame(frame)

    @pyqtSlot(str, float, str)
    def _on_camera_temp(self, camera_id: str, temp: float, status: str):
        """Handle temperature update for any camera — update its card."""
        card = self.camera_panels.get(camera_id)
        if card:
            card.update_temperature(temp, status, self._acquiring)

    @pyqtSlot(str, bool)
    def _on_camera_status_changed(self, camera_id: str, is_connected: bool):
        """Handle dynamic camera connection/disconnection notifications."""
        card = self.camera_panels.get(camera_id)
        if card:
            card.update_connection_state(is_connected, False)
        if camera_id == getattr(self, '_active_camera_id', None):
            self._update_camera_controls_enabled(is_connected)

    def _on_processing_mode_changed(self, mode):
        """Sync processing mode to hardware manager."""
        self.hw.data_processing_mode = mode
        logger.debug(f"Data processing mode changed to: {mode}")

    def display_image(self, image: np.ndarray):
        """Display image on screen."""
        self.image_plot.imshow(image, auto_levels=self.auto_all_btn.isChecked())

    def _handle_new_frame(self, image):
        """Process and display a newly acquired frame."""
        if image is None:
            return
            
        try:
            # 1. Processing Logic (via MeasurementResult for consistency)
            
            # Temporary result for processing
            res = MeasurementResult(
                timestamp=datetime.now(), # Not used for display
                integration_time=self._last_exposure_ms / 1000.0 if self._last_exposure_ms else self.exposure_box.value() / 1000.0,
                intensities=image,
                background=self.background_frame,
                background_exposure=(self._background_exposure / 1000.0) if self._background_exposure else None
            )
            
            res.process(self.hw.data_processing_mode)
            image = res.intensities
            assert image is not None
            
            if "Exposure Mismatch" in res.metadata.get('Processing', ''):
                # Just update status label, don't trigger modal popups or restarts during live view
                status_text += " [BG Exposure Mismatch]"
                self.bg_status_label.setText("EXP MISMATCH")
                self.bg_status_label.setStyleSheet("color: #e74c3c; font-size: 10px; font-weight: bold;")
            elif "Background" in self.hw.data_processing_mode:
                if self.background_frame is not None:
                    # Shape check handled in res.process
                    if "Subtracted" in res.metadata.get('Processing', ''):
                        self.bg_status_label.setText("BG SUBTRACTED")
                        self.bg_status_label.setStyleSheet("color: #2ecc71; font-size: 10px; font-weight: bold;")
                    else:
                        self.bg_status_label.setText("SHAPE MISMATCH")
                        self.bg_status_label.setStyleSheet("color: #e74c3c; font-size: 10px; font-weight: bold;")
                else:
                    self.bg_status_label.setText("NO BG FRAME")
                    self.bg_status_label.setStyleSheet("color: #e67e22; font-size: 10px; font-weight: bold;")
            else:
                self.bg_status_label.setText("RAW DATA")
                self.bg_status_label.setStyleSheet("color: #95a5a6; font-size: 10px; font-weight: bold;")

            # 2. Reshaping for display
            if self.view_combo.currentText() == "Image":
                if image.ndim == 2:
                    self.display_image(image)
                else:
                    self.display_image(image.reshape(1, -1))
            else:
                # Spectrum View
                if image.ndim == 2:
                    spectrum = np.sum(image, axis=0)
                else:
                    spectrum = image
                
                x = self._get_spectral_x(len(spectrum))
                
                # Update labels if needed
                self._update_axis_labels()
                    
                self.spectrum_plot.update_plot(x, spectrum)
            # Perform continuous auto-scaling if enabled
            if self.auto_all_btn.isChecked():
                self._auto_scale_now()

            # 3. Unit Switching based on Monochromator connection
            mono = self.hw.mono
            is_mono_connected = mono is not None and mono.is_connected()
            if is_mono_connected != self._mono_connected_prev:
                self.spec_unit_combo.setCurrentText("Spectral Units" if is_mono_connected else "Pixel")
                self._mono_connected_prev = is_mono_connected

        except Exception as e:
            logger.error(f"Error handling frame: {e}")
