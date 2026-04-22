"""
Live view panel for real-time camera display.
"""

import time
import logging
from pathlib import Path
import numpy as np
from ..qt import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGroupBox, QDoubleSpinBox, QComboBox,
    QSpinBox, QGridLayout, Qt, QTimer, QImage, QPixmap,
    QLineEdit, QFrame, QMenu, QStackedWidget, QApplication,
    QCheckBox, QMessageBox, QFileDialog, QDialog, QTableWidget,
    QTableWidgetItem, QHeaderView, pyqtSignal, pyqtSlot, QtGui
)
import threading

from .plot import PlotWidget, ImagePlotWidget, CoordinateWidget

logger = logging.getLogger(__name__)


from ..hardware.manager import HardwareManager

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
        self.current_camera = None
        self.background_frame = None
        self._acquiring = False
        
        # Connect to Hardware Service signals
        service = self.hw.service
        service.camera_frame_ready.connect(self._on_camera_frame)
        service.camera_temp_changed.connect(self._on_camera_temp)
        service.spectral_unit_changed.connect(self._on_spectral_unit_changed)
        service.spectral_display_mode_changed.connect(self._on_spectral_mode_changed)
        
        self._background_exposure = None # Store exposure time of captured background
        self._background_camera_name = None # Store which camera took the background
        self._mono_connected_prev = False # Track monochromator connection for auto-units
        self._spec_connecting = False
        self._vis_connecting = False
        self._last_unit_mode = None
        self._last_spectral_unit = None
        self._last_data_mode = None
        self._is_showing_mismatch_msg = False # Guard to prevent multiple modal popups
        self._last_exposure_ms = None # Track last set value to avoid direct-type updates
        
        self._init_ui()
        
        # Internal signal for thread-safe connection finalization
        self.sig_cam_connect_done.connect(self._on_cam_connection_finished)
        
        logger.info("Live view initialized (Signal-driven)")

    def _get_current_camera_id(self) -> str:
        """Return the camera ID that corresponds to the current combo selection."""
        camera_name = self.camera_combo.currentText()
        cameras_cfg = self.hw.config.get('hardware', {}).get('cameras', [])
        for cam_cfg in cameras_cfg:
            if cam_cfg.get('name') == camera_name and cam_cfg.get('enabled', False):
                return cam_cfg['id']
        return None

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
        
        # Finally, populate camera combo from config
        cameras_cfg = self.hw.config.get('hardware', {}).get('cameras', [])
        camera_names = [c['name'] for c in cameras_cfg if c.get('enabled', False)]
        self.camera_combo.addItems(camera_names)

    def _create_main_control_group(self) -> QGroupBox:
        """Create the consolidated camera control group."""
        group = QGroupBox("Camera Selection Mode")
        group.setStyleSheet("QGroupBox { font-weight: bold; }")
        layout = QHBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5) # Unified margins
        layout.setSpacing(10) # Reduced spacing
        group.setLayout(layout)

        # 1. Left Section: Selection
        selection_layout = QGridLayout()
        selection_layout.setSpacing(5)
        
        # Camera connection and status
        cam_conn_layout = QHBoxLayout()
        cam_conn_layout.setSpacing(5)
        
        self.cam_connect_btn = QPushButton("Connect")
        self.cam_connect_btn.setFixedHeight(18)
        self.cam_connect_btn.setStyleSheet("font-size: 10px; padding: 0px;")
        self.cam_connect_btn.clicked.connect(self._on_cam_connect_clicked)
        cam_conn_layout.addWidget(self.cam_connect_btn)
        
        self.cam_status_label = QLabel("Disconnected")
        self.cam_status_label.setStyleSheet("color: red; font-size: 10px;")
        cam_conn_layout.addWidget(self.cam_status_label)
        
        # Position at row 0, spanning 2 columns
        selection_layout.addLayout(cam_conn_layout, 0, 0, 1, 2)

        selection_layout.addWidget(QLabel("Camera:"), 1, 0)
        self.camera_combo = QComboBox()
        self.camera_combo.setStyleSheet("QComboBox { background-color: orange; color: black; }")
        self.camera_combo.setFixedWidth(120)
        self.camera_combo.currentTextChanged.connect(self._on_camera_changed)
        selection_layout.addWidget(self.camera_combo, 1, 1)

        selection_layout.addWidget(QLabel("Readout:"), 2, 0)
        self.readout_combo = QComboBox()
        self.readout_combo.setFixedWidth(120) # Constrain width
        self.readout_combo.currentTextChanged.connect(self._on_readout_mode_changed)
        selection_layout.addWidget(self.readout_combo, 2, 1)
        
        layout.addLayout(selection_layout)

        # Vertical line separator
        line_view = QFrame()
        line_view.setFrameShape(QFrame.Shape.VLine)
        line_view.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line_view)

        # View Mode / Units / Data
        view_layout = QGridLayout()
        view_layout.setSpacing(5)
        
        view_layout.addWidget(QLabel("View:"), 0, 0)
        self.view_combo = QComboBox()
        self.view_combo.addItems(["Image", "Spectrum"])
        self.view_combo.currentTextChanged.connect(self._on_view_mode_changed)
        view_layout.addWidget(self.view_combo, 0, 1)
        
        view_layout.addWidget(QLabel("Units:"), 0, 2)
        self.spec_unit_combo = QComboBox()
        self.spec_unit_combo.addItems(["Pixel", "Spectral Units"])
        self.spec_unit_combo.currentTextChanged.connect(self._on_unit_mode_changed)
        view_layout.addWidget(self.spec_unit_combo, 0, 3)
        
        view_layout.addWidget(QLabel("Data:"), 1, 0)
        self.data_type_combo = QComboBox()
        self.data_type_combo.addItems([
            "Raw Data", 
            "Background correction", 
            "Time Normalized", 
            "Background & Time Normalized"
        ])
        self.data_type_combo.currentTextChanged.connect(self._on_processing_mode_changed)
        view_layout.addWidget(self.data_type_combo, 1, 1, 1, 3) 
        
        layout.addLayout(view_layout)

        # Vertical line separator
        line1 = QFrame()
        line1.setFrameShape(QFrame.Shape.VLine)
        line1.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line1)

        # 2. Middle Section: ROI/Binning Table
        roi_layout = QGridLayout()
        roi_layout.setSpacing(4)
        
        # Headers
        roi_layout.addWidget(QLabel(""), 0, 0)
        roi_layout.addWidget(QLabel("Start"), 0, 1)
        roi_layout.addWidget(QLabel("End"), 0, 2)
        roi_layout.addWidget(QLabel("Bin"), 0, 3)

        # X row
        roi_layout.addWidget(QLabel("X:"), 1, 0)
        self.x_start_box = QSpinBox()
        self.x_start_box.setRange(0, 4096)
        self.x_start_box.setFixedWidth(55)
        roi_layout.addWidget(self.x_start_box, 1, 1)
        
        self.x_end_box = QSpinBox()
        self.x_end_box.setRange(1, 4096)
        self.x_end_box.setFixedWidth(55)
        roi_layout.addWidget(self.x_end_box, 1, 2)
        
        self.x_bin_box = QSpinBox()
        self.x_bin_box.setRange(1, 1024)
        self.x_bin_box.setFixedWidth(45)
        roi_layout.addWidget(self.x_bin_box, 1, 3)

        # Y row
        roi_layout.addWidget(QLabel("Y:"), 2, 0)
        self.y_start_box = QSpinBox()
        self.y_start_box.setRange(0, 4096)
        self.y_start_box.setFixedWidth(55)
        roi_layout.addWidget(self.y_start_box, 2, 1)
        
        self.y_end_box = QSpinBox()
        self.y_end_box.setRange(1, 4096)
        self.y_end_box.setFixedWidth(55)
        roi_layout.addWidget(self.y_end_box, 2, 2)
        
        self.y_bin_box = QSpinBox()
        self.y_bin_box.setRange(1, 1024)
        self.y_bin_box.setFixedWidth(45)
        roi_layout.addWidget(self.y_bin_box, 2, 3)

        # Buttons (compact)
        self.apply_roi_btn = QPushButton("Apply")
        self.apply_roi_btn.setFixedWidth(55)
        self.apply_roi_btn.clicked.connect(self.apply_roi)
        roi_layout.addWidget(self.apply_roi_btn, 1, 4)
        
        self.presets_btn = QPushButton("Presets")
        self.presets_btn.setFixedWidth(70)
        self._setup_presets_menu()
        roi_layout.addWidget(self.presets_btn, 2, 4)
        
        layout.addLayout(roi_layout)

        # Vertical line separator
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.VLine)
        line2.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line2)

        # 3. Right Section: Temperature
        temp_layout = QGridLayout()
        temp_layout.setSpacing(5)
        
        temp_layout.addWidget(QLabel("Set:"), 0, 0)
        self.set_temp_box = QDoubleSpinBox()
        self.set_temp_box.setRange(-100, 20)
        self.set_temp_box.setSuffix(" °C")
        self.set_temp_box.setFixedWidth(100)
        self.set_temp_box.valueChanged.connect(self.update_set_temperature)
        temp_layout.addWidget(self.set_temp_box, 0, 1)

        temp_layout.addWidget(QLabel("Real:"), 1, 0)
        self.real_temp_box = QLineEdit()
        self.real_temp_box.setReadOnly(True)
        self.real_temp_box.setFixedWidth(100)
        self.real_temp_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.real_temp_box.setText("N/A")
        self.real_temp_box.setToolTip("Current sensor temperature. Shows (Hold) during acquisition.")
        temp_layout.addWidget(self.real_temp_box, 1, 1)
        
        layout.addLayout(temp_layout)

        # Vertical line separator
        line3 = QFrame()
        line3.setFrameShape(QFrame.Shape.VLine)
        line3.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line3)

        # 4. Far Right Section: Graph Analysis
        analysis_layout = QGridLayout()
        analysis_layout.setSpacing(5)

        self.auto_all_btn = QPushButton("Auto Scale")
        self.auto_all_btn.setCheckable(True)
        self.auto_all_btn.setToolTip("Toggle continuous auto-scaling. Manually zooming disables this.")
        self.auto_all_btn.setStyleSheet("""
            QPushButton { font-size: 10px; padding: 2px; }
            QPushButton:checked { background-color: #27ae60; color: white; font-weight: bold; }
        """)
        self.auto_all_btn.setFixedHeight(22)
        self.auto_all_btn.toggled.connect(self._on_auto_scale_toggled)
        analysis_layout.addWidget(self.auto_all_btn, 0, 0)

        self.lock_x_check = QCheckBox("X Lock")
        self.lock_y_check = QCheckBox("Y Lock")
        self.lock_x_check.setStyleSheet("font-size: 10px;")
        self.lock_y_check.setStyleSheet("font-size: 10px;")
        self.lock_x_check.toggled.connect(self._on_axis_lock_changed)
        self.lock_y_check.toggled.connect(self._on_axis_lock_changed)
        analysis_layout.addWidget(self.lock_x_check, 0, 1)
        analysis_layout.addWidget(self.lock_y_check, 0, 2)

        # 1. Create the Table
        self.coords_widget = CoordinateWidget()
        
        # Markers row
        marker_layout = QHBoxLayout()
        marker_layout.setSpacing(2)
        marker_layout.addWidget(QLabel("Markers:"))
        
        self.marker_xy_btn = QPushButton("XY")
        self.marker_x_btn = QPushButton("X")
        self.marker_y_btn = QPushButton("Y")
        self.marker_clear_btn = QPushButton("Clear")
        
        for btn, label in [(self.marker_xy_btn, "XY"), (self.marker_x_btn, "X"), 
                          (self.marker_y_btn, "Y"), (self.marker_clear_btn, "Clear")]:
            btn.setToolTip(f"Add {label} marker")
            btn.setFixedWidth(32 if label == "Clear" else 22)
            btn.setStyleSheet("font-size: 9px; padding: 1px;")
            marker_layout.addWidget(btn)
        
        self.marker_xy_btn.clicked.connect(lambda: self._on_add_marker("xy"))
        self.marker_x_btn.clicked.connect(lambda: self._on_add_marker("x"))
        self.marker_y_btn.clicked.connect(lambda: self._on_add_marker("y"))
        self.marker_clear_btn.clicked.connect(self._on_clear_markers)
        
        analysis_layout.addLayout(marker_layout, 1, 0, 1, 3)
        analysis_layout.addWidget(self.coords_widget, 2, 0, 1, 3)
        
        # 5. Colormap shortcuts (Split triangles)
        cmap_layout = QVBoxLayout()
        cmap_layout.setSpacing(2)
        cmap_layout.setContentsMargins(2, 0, 0, 0)
        
        cmaps = [
            ('grey', "#000", "#fff"),
            ('viridis', "#440154", "#addc30"),
            ('inferno', "#000", "#f57d15"),
            ('plasma', "#0d0887", "#fca636")
        ]
        
        for name, c1, c2 in cmaps:
            btn = QPushButton()
            btn.setFixedSize(18, 18)
            btn.setToolTip(f"Colormap: {name.capitalize()}")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0.49 {c1}, stop:0.5 {c2});
                    border: 1px solid #999;
                    border-radius: 2px;
                }}
                QPushButton:hover {{ border: 1px solid #333; }}
            """)
            btn.clicked.connect(lambda checked, n=name: self.image_plot.set_colormap(n))
            cmap_layout.addWidget(btn)
            
        analysis_layout.addLayout(cmap_layout, 0, 3, 3, 1)
        
        layout.addLayout(analysis_layout)
        
        # Add stretch to push everything to the left and prevent "expanding" 
        layout.addStretch(1)

        return group

    def _setup_presets_menu(self):
        """Setup the ROI presets menu."""
        menu = QMenu(self)
        
        img_action = menu.addAction("Image Visualisation")
        img_action.triggered.connect(lambda: self._apply_preset("image_vis"))
        
        spec_action = menu.addAction("Center Spectrometer")
        spec_action.triggered.connect(lambda: self._apply_preset("center_spec"))
        
        slit_action = menu.addAction("Slit Image")
        slit_action.triggered.connect(lambda: self._apply_preset("slit_image"))
        
        self.presets_btn.setMenu(menu)

    def _apply_preset(self, preset_type, trigger_hardware: bool = True):
        """Apply a predefined ROI preset."""
        # Block signals to update multiple values without triggering intermediate hardware calls
        self.x_start_box.blockSignals(True)
        self.x_end_box.blockSignals(True)
        self.y_start_box.blockSignals(True)
        self.y_end_box.blockSignals(True)
        self.x_bin_box.blockSignals(True)
        self.y_bin_box.blockSignals(True)

        # Determine dynamic limits for presets
        cam_cfg = self.hw.get_camera_config(self._get_current_camera_id())
        conf = cam_cfg if cam_cfg else {}
        width, height = conf.get('detector_size', [1024, 256])

        if preset_type == "image_vis":
            self.x_start_box.setValue(253)
            self.x_end_box.setValue(752)
            self.y_start_box.setValue(252)
            self.y_end_box.setValue(753)
            self.x_bin_box.setValue(1)
            self.y_bin_box.setValue(1)
        elif preset_type == "center_spec":
            self.x_start_box.setValue(1)
            self.x_end_box.setValue(width)
            # Centered track (e.g. for 256 height, centered 30px)
            track_height = 30
            y_start = (height - track_height) // 2
            self.y_start_box.setValue(y_start)
            self.y_end_box.setValue(y_start + track_height)
            self.x_bin_box.setValue(1)
            self.y_bin_box.setValue(track_height)
        elif preset_type == "slit_image":
            self.x_start_box.setValue(1)
            self.x_end_box.setValue(width)
            self.y_start_box.setValue(1)
            self.y_end_box.setValue(height)
            self.x_bin_box.setValue(1)
            self.y_bin_box.setValue(8)
        
        self.x_start_box.blockSignals(False)
        self.x_end_box.blockSignals(False)
        self.y_start_box.blockSignals(False)
        self.y_end_box.blockSignals(False)
        self.x_bin_box.blockSignals(False)
        self.y_bin_box.blockSignals(False)
            
        if trigger_hardware:
            self.apply_roi()

    def _reset_to_full_sensor(self, width: int, height: int):
        """Reset ROI controls to full sensor dimensions (No hardware call)."""
        self.x_start_box.setValue(0)
        self.x_end_box.setValue(width)
        self.y_start_box.setValue(0)
        self.y_end_box.setValue(height)
        self.x_bin_box.setValue(1)
        self.y_bin_box.setValue(1)


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

        # --- Middle: Spacer ---
        layout.addStretch()

        # --- Right Side: Automation & Logs ---
        self.run_seq_btn = QPushButton("Run Heating Sequence")
        self.run_seq_btn.clicked.connect(self._on_run_sequence_clicked)
        layout.addWidget(self.run_seq_btn)

        self.logs_btn = QPushButton("Show Logs")
        self.logs_btn.clicked.connect(lambda: self.window().show_logs())
        layout.addWidget(self.logs_btn)

        return group

    # ... [existing methods] ...

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

    def _on_run_sequence_clicked(self):
        """Handle 'Run Heating Sequence' button click."""
        # 1. Get steps from Automation Panel
        # We need to find the AutomationPanel instance.
        # It's likely in the parent Main window's tabs.
        main_window = self.window()
        automation_panel = None
        
        # Try to find it by type or object name
        from .automation_panel import AutomationPanel, LaserHeatingWorker
        from .sequence_dialog import SequenceSummaryDialog
        
        # Iterate over all widgets to find AutomationPanel? 
        # Or better: Assume it's passed/linked. 
        # For now, let's try finding it via the main window tabs if accessible, 
        # or require it to be injected.
        # Fallback: Search children of main window
        automation_panel = main_window.findChild(AutomationPanel)
        
        if not automation_panel:
            # Fallback for when running standalone or dev mode
            logger.warning("AutomationPanel not found via findChild. Checking attributes.")
            if hasattr(main_window, 'automation_panel'):
                automation_panel = main_window.automation_panel
        
        if not automation_panel:
            QMessageBox.warning(self, "Error", "Could not find Automation Panel to retrieve sequence.")
            return

        steps = automation_panel.get_sequence_steps()
        if not steps:
            QMessageBox.warning(self, "Empty Sequence", "The sequence is empty. Please add steps in the Automation panel.")
            return
            
        # 2. Show Summary Dialog
        start_idx = automation_panel.start_step_spin.value()
        cooling_delay = automation_panel.get_cooling_delay()
        dlg = SequenceSummaryDialog(steps, cooling_delay=cooling_delay, start_index=start_idx, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
            
        skip_step_0 = dlg.should_skip_step_0()
        
        # Check for background correction safety
        processing_mode = self.hw.data_processing_mode
        if "Background" in processing_mode and self.background_frame is None:
            ret = QMessageBox.question(self, "No Background", 
                                     "Background correction is ENABLED, but no background frame has been captured.\n\n"
                                     "Continue anyway (using Raw Data)?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ret == QMessageBox.StandardButton.No:
                return
            # If Yes, we proceed but the worker will handle the missing background gracefully (skipping subtraction)
        
        # 3. Prepare Execution
        # Metadata
        try:
            # Get manual power (converted to W) for the *measurement* phase
            # AutomationPanel has its own measurement power setting
            meas_power_w = automation_panel.get_measurement_power()
            
            # Base metadata plus manual fields
            bg_meta = self.hw.collect_metadata()
            
            # Calculate manual power first (converted to W)
            try:
                p_val = self.manual_power_spin.value()
                p_unit = self.power_unit_combo.currentText()
                if p_unit == "mW": manual_power_w = p_val * 1e-3
                elif p_unit == "µW": manual_power_w = p_val * 1e-6
                elif p_unit == "nW": manual_power_w = p_val * 1e-9
                else: manual_power_w = 0.0
            except:
                manual_power_w = 0.0
            
            # Add manual metadata from UI (matching save_snapshot)
            bg_meta['laser'] = {
                'Wavelength (nm)': self.laser_wl_box.value(),
                'Mode': self.laser_mode_combo.currentText(),
                'Excitation Power (W)': manual_power_w
            }
            bg_meta['Sample Temperature (K)'] = self.sample_temp_box.value()
            bg_meta['Objective'] = self.objective_box.currentText()
            
            # Folder
            save_dir = self.save_path_edit.text()
            
            # Background
            bg_frame = None
            if self.background_frame is not None:
                bg_frame = self.background_frame
                
            # 4. Start Worker
            start_idx = automation_panel.start_step_spin.value()
            cooling_delay = automation_panel.get_cooling_delay()
            processing_mode = self.hw.data_processing_mode
            
            self._seq_worker = LaserHeatingWorker(
                self.hw, 
                meas_power_w=meas_power_w,
                steps=steps,
                data_dir=save_dir,
                metadata=bg_meta,
                skip_step_0=skip_step_0,
                background=bg_frame,
                background_exposure=self._background_exposure,
                processing_mode=processing_mode,
                cooling_delay=cooling_delay,
                start_index=start_idx
            )
            
            self._seq_worker.progress.connect(self._on_seq_progress)
            self._seq_worker.measurement_ready.connect(self._on_seq_measurement)
            self._seq_worker.finished.connect(self._on_seq_finished)
            
            # Coordination: Notify Monitor that sequence has started
            self.sequence_started.emit(steps, meas_power_w, start_idx)
            
            # UI Updates
            self.run_seq_btn.setEnabled(False)
            self.run_seq_btn.setText("Running...")
            self.bg_status_label.setText("SEQUENCE RUNNING")
            self.bg_status_label.setStyleSheet("color: red; font-weight: bold;")
            
            self._seq_worker.start()
            
        except Exception as e:
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

    def _on_seq_finished(self, success, message):
        """Handle sequence completion."""
        self.run_seq_btn.setEnabled(True)
        self.run_seq_btn.setText("Run Heating Sequence")
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
            self._seq_worker.stop()
            self.run_seq_btn.setText("STOPPING...")
            self.run_seq_btn.setEnabled(False)

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
        from ..qt import QFileDialog
        path = QFileDialog.getExistingDirectory(self, "Select Save Directory", self.save_path_edit.text())
        if path:
            self.save_path_edit.setText(path)

    def _on_camera_changed(self, camera_name):
        """Handle camera selection change."""
        self.stop_live_view()
        
        # Reset temperature display immediately to avoid stale data
        self.real_temp_box.setText("--- °C")
        self.real_temp_box.setStyleSheet("background-color: transparent; border: 1px solid #ced4da; color: gray;")
        self.real_temp_box.setToolTip("Waiting for hardware...")
        
        camera_id = self._get_current_camera_id()
        self.current_camera = self.hw.get_camera(camera_id) if camera_id else None
        
        # Determine readout modes based on camera role
        cam_role = self.hw.get_camera_config(camera_id).get('role', 'general') if camera_id else 'general'
        if cam_role == 'spectroscopy':
            modes = ["Image", "FVB", "Single track"]
        else:
            modes = ["Image"]

        # Refresh readout modes
        self.readout_combo.blockSignals(True)
        self.readout_combo.clear()
        self.readout_combo.addItems(modes)
        
        # Set default readout mode based on camera
        default_mode = "Single track" if camera_name == "Spectrometer" else "Image"
        self.readout_combo.setCurrentText(default_mode)
        self.readout_combo.blockSignals(False)
        
        # No longer trigger mode changed here - we do it atomically at the end
        # self._on_readout_mode_changed(default_mode)
            
        if self.current_camera and self.current_camera.is_connected():
            # If spectrometer camera connected, sync physical calibration parameters
            if camera_name == "Spectrometer":
                self.hw.sync_calibration_with_hardware()
                
            info = self.current_camera.get_info()
            
            # Update set temperature box
            self.set_temp_box.blockSignals(True)
            self.set_temp_box.setValue(info.get('target_temperature', -20))
            self.set_temp_box.blockSignals(False)
            
            # Update exposure in UI (converting back to integer ms)
            self.exposure_box.blockSignals(True)
            new_exp = int(info.get('exposure_time', 0.1) * 1000)
            self.exposure_box.setValue(new_exp)
            self._last_exposure_ms = new_exp
            self.exposure_box.blockSignals(False)

            # Update ROI limits based on detector size
            detector_size = info.get('detector_size', (2048, 512))
            width, height = detector_size
            self.x_start_box.setRange(0, width - 1)
            self.x_end_box.setRange(1, width)
            self.y_start_box.setRange(0, height - 1)
            self.y_end_box.setRange(1, height)
        else:
            logger.warning(f"Camera {camera_name} not connected")
            # Sync set temperature box with last known/intended target
            self.set_temp_box.blockSignals(True)
            # Default to -70 for spectrometer, -20 for vis as a sensible visual hint
            hint_temp = -70 if camera_name == "Spectrometer" else -20
            self.set_temp_box.setValue(hint_temp)
            self.set_temp_box.blockSignals(False)

            # Set limits based on config for UI safety
            cam_cfg = self.hw.get_camera_config(self._get_current_camera_id())
            detector_size = cam_cfg.get('detector_size', [1024, 1024])
            width, height = detector_size
            
            self.x_start_box.setRange(0, width - 1)
            self.x_end_box.setRange(1, width)
            self.y_start_box.setRange(0, height - 1)
            self.y_end_box.setRange(1, height)

        # Reset poll count for "..." logic
        self._spec_poll_count = 0

        # --- CONNECTION-AWARE UI STATE ---
        is_connected = bool(self.current_camera and self.current_camera.is_connected())
        
        # Check if this specific camera is currently in the middle of a connection attempt
        is_connecting = (camera_name == "Visualisation" and self._vis_connecting) or \
                        (camera_name == "Spectrometer" and self._spec_connecting)

        self.cam_connect_btn.setEnabled(not is_connected and not is_connecting)
        
        if is_connected:
            self.cam_status_label.setText("Connected")
            self.cam_status_label.setStyleSheet("color: green; font-size: 10px;")
        elif is_connecting:
            self.cam_status_label.setText("Connecting...")
            self.cam_status_label.setStyleSheet("color: orange; font-size: 10px;")
        else:
            self.cam_status_label.setText("Disconnected")
            self.cam_status_label.setStyleSheet("color: red; font-size: 10px;")

        # --- ATOMIC UI SYNCHRONIZATION ---
        # Block everything during the entire setup to prevent race conditions
        self.readout_combo.blockSignals(True)
        self.view_combo.blockSignals(True)
        self.x_start_box.blockSignals(True)
        self.x_end_box.blockSignals(True)
        self.y_start_box.blockSignals(True)
        self.y_end_box.blockSignals(True)
        self.x_bin_box.blockSignals(True)
        self.y_bin_box.blockSignals(True)

        try:
            cam_role = self.hw.get_camera_config(self._get_current_camera_id()).get('role', 'general')
            if cam_role == 'spectroscopy':
                self.readout_combo.setCurrentText("Single track")
                self.view_combo.setCurrentText("Spectrum")
                if is_connected:
                    roi = self.current_camera.get_roi()
                    if roi[2] == 0 and roi[3] == height:
                        self._apply_preset("center_spec", trigger_hardware=False)
                    else:
                        self.x_start_box.setValue(roi[0])
                        self.x_end_box.setValue(roi[1])
                        self.y_start_box.setValue(roi[2])
                        self.y_end_box.setValue(roi[3])
                        self.x_bin_box.setValue(roi[4])
                        self.y_bin_box.setValue(roi[5])
                else:
                    self._reset_to_full_sensor(width, height)
            else:
                self.readout_combo.setCurrentText("Image")
                self.view_combo.setCurrentText("Image")
                if is_connected:
                    roi = self.current_camera.get_roi()
                    self.x_start_box.setValue(roi[0])
                    self.x_end_box.setValue(roi[1])
                    self.y_start_box.setValue(roi[2])
                    self.y_end_box.setValue(roi[3])
                    self.x_bin_box.setValue(roi[4])
                    self.y_bin_box.setValue(roi[5])
                else:
                    self._reset_to_full_sensor(width, height)
            
            # Trigger layout update for the new mode (updates enabled states)
            # Use trigger_hardware=False to avoid unwanted auto-presets during switch
            self._on_readout_mode_changed(self.readout_combo.currentText(), trigger_hardware=False)

        finally:
            self.readout_combo.blockSignals(False)
            self.view_combo.blockSignals(False)
            self.x_start_box.blockSignals(False)
            self.x_end_box.blockSignals(False)
            self.y_start_box.blockSignals(False)
            self.y_end_box.blockSignals(False)
            self.x_bin_box.blockSignals(False)
            self.y_bin_box.blockSignals(False)

        # APPLY TO HARDWARE ONCE AT THE VERY END (Only if connected)
        if is_connected:
            logger.debug(f"Atomic Init: Applying configuration to {camera_name}")
            self.apply_roi()
            
        # FORCE VIEW REFRESH: Signal blocking silenced the auto-switch, so we nudge it here
        self._on_view_mode_changed(self.view_combo.currentText())
        
        # --- UPDATE ENABLED STATE ---
        self._update_camera_controls_enabled(is_connected)

    def _on_cam_connect_clicked(self):
        """Try to connect the currently selected camera."""
        from ..qt import QMessageBox
        
        selected = self.camera_combo.currentText()
        logger.info(f"Attempting individual connection for {selected} camera")
        
        self.cam_connect_btn.setEnabled(False)
        self.cam_status_label.setText("Connecting...")
        self.cam_status_label.setStyleSheet("color: orange; font-size: 10px;")
        
        def _connect_thread():
            try:
                camera_id = self._get_current_camera_id()
                if camera_id:
                    if not self.hw.get_camera(camera_id):
                        cam_cfg = self.hw.get_camera_config(camera_id)
                        self.hw.initialize_instrument(camera_id, cam_cfg.get('driver', 'andor_camera'), cam_cfg)
                    self.hw.get_camera(camera_id).connect()
                logger.info(f"{selected} camera connected successfully")
            except Exception as e:
                logger.error(f"Failed to connect {selected} camera: {e}")
            finally:
                self.sig_cam_connect_done.emit(selected)

        threading.Thread(target=_connect_thread, daemon=True).start()

    @pyqtSlot(str)
    def _on_cam_connection_finished(self, selected):
        """Finalize UI after camera connection (CALLED ON UI THREAD)."""
        # If the camera that just finished is the one we are currently looking at, refresh the UI
        if selected == self.camera_combo.currentText():
            self.cam_connect_btn.setEnabled(True)
            self.cam_connect_btn.setText("Connect")
            self._on_camera_changed(selected)
        else:
            logger.info(f"Background connection for {selected} finished, but current view is {self.camera_combo.currentText()}")

    @pyqtSlot(str)
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
        """Enable or disable all camera-specific controls."""
        # Acquisition
        self.exposure_box.setEnabled(enabled)
        self.live_btn.setEnabled(enabled)
        self.background_btn.setEnabled(enabled)
        
        # Stop live if it was running and we are disabling
        if not enabled and self.live_btn.isChecked():
            self.live_btn.setChecked(False)
            self.stop_live_view()
            
        self.pixel_dev_box.setEnabled(enabled)
        self.run_seq_btn.setEnabled(enabled)
        
        # Readout / View Modes
        self.readout_combo.setEnabled(enabled)
        self.view_combo.setEnabled(enabled)
        self.spec_unit_combo.setEnabled(enabled)
        self.data_type_combo.setEnabled(enabled)
        
        # ROI / Binning
        self.x_start_box.setEnabled(enabled)
        self.x_end_box.setEnabled(enabled)
        self.x_bin_box.setEnabled(enabled)
        self.y_start_box.setEnabled(enabled)
        self.y_end_box.setEnabled(enabled)
        self.y_bin_box.setEnabled(enabled)
        self.apply_roi_btn.setEnabled(enabled)
        self.presets_btn.setEnabled(enabled)
        
        # Temperature
        self.set_temp_box.setEnabled(enabled)
        
        # Data Management
        self.save_btn.setEnabled(enabled)

    def _on_auto_scale_toggled(self, checked: bool):
        """Handle continuous auto-scale toggle."""
        if checked:
            # Enable persistent auto-range in both plots
            self.image_plot.auto_scale_all()
            self.spectrum_plot.auto_scale_all()
        else:
            # Note: We don't explicitly disable it here because the user's zoom 
            # will naturally disable it, which triggers the signal to uncheck this.
            # But if they uncheck it manually, we can just leave the current range as is.
            pass

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

    def _on_readout_mode_changed(self, mode, trigger_hardware: bool = True):
        """Handle readout mode change with automatic ROI configuration."""
        logger.info(f"Readout mode changed to {mode} (trigger={trigger_hardware})")
        
        # Get detector size (use defaults if disconnected)
        width, height = 2048, 512
        if self.current_camera and self.current_camera.is_connected():
            info = self.current_camera.get_info()
            detector_size = info.get('detector_size', (2048, 512))
            width, height = detector_size

        if mode == "FVB":
            # Gray out everything in ROI section
            for box in [self.x_start_box, self.x_end_box, self.x_bin_box,
                        self.y_start_box, self.y_end_box, self.y_bin_box]:
                box.setEnabled(False)
            self.apply_roi_btn.setEnabled(False)
            self.presets_btn.setEnabled(False)
            
            # Auto-switch to Spectrum view
            self.view_combo.setCurrentText("Spectrum")
            
            # We do NOT call setValue or apply_roi here to preserve previous user ROI
            # the driver handles the FVB geometry internally via set_readout_mode
        elif mode == "Single track":
            # Enable all because user can still tweak single track ROI
            for box in [self.x_start_box, self.x_end_box, self.x_bin_box,
                        self.y_start_box, self.y_end_box, self.y_bin_box]:
                box.setEnabled(True)
            self.apply_roi_btn.setEnabled(True)
            self.presets_btn.setEnabled(True)
            
            # Auto-apply preset for spectroscopy cameras
            cam_role = self.hw.get_camera_config(self._get_current_camera_id()).get('role', 'general')
            if cam_role == 'spectroscopy':
                # Only auto-apply if actually connected or if specifically requested
                if trigger_hardware or (self.current_camera and self.current_camera.is_connected()):
                    self._apply_preset("center_spec", trigger_hardware=trigger_hardware)
                
                # Auto-switch to Spectrum view
                self.view_combo.setCurrentText("Spectrum")
        else:
            # Image mode
            for box in [self.x_start_box, self.x_end_box, self.x_bin_box,
                        self.y_start_box, self.y_end_box, self.y_bin_box]:
                box.setEnabled(True)
            self.apply_roi_btn.setEnabled(True)
            self.presets_btn.setEnabled(True)
            
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

    def stop_live_view(self):
        """Stop live camera acquisition."""
        if not self.current_camera:
            return

        try:
            self.current_camera.stop_acquisition()
        except:
            pass
            
        self._acquiring = False
        self.live_btn.setChecked(False)
        self.live_btn.setText("Live")
        logger.info("Live view stopped")

    def apply_roi(self):
        """Apply ROI settings to the current camera."""
        if not self.current_camera or not self.current_camera.is_connected():
            return

        try:
            x_start = self.x_start_box.value()
            x_end = self.x_end_box.value()
            x_bin = self.x_bin_box.value()
            y_start = self.y_start_box.value()
            y_end = self.y_end_box.value()
            y_bin = self.y_bin_box.value()

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
                self._background_camera_name = self.camera_combo.currentText()
                logger.info(f"Background captured for {self._background_camera_name} at {self._background_exposure} ms")
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
            meta = self.hw.collect_metadata()
            
            # 2. Add manual metadata from UI
            meta['laser'] = {
                'Wavelength (nm)': self.laser_wl_box.value(),
                'Mode': self.laser_mode_combo.currentText(),
                'Excitation Power (W)': manual_power_w
            }
            meta['Sample Temperature (K)'] = self.sample_temp_box.value()
            meta['Objective'] = self.objective_box.currentText()
            
            # 3. Capture image (fresh frame)
            image = self.current_camera.acquire_image()
            
            # 4. Prepare MeasurementResult
            from ..core.measurement import MeasurementResult
            from datetime import datetime
            
            # Calculate spectral x-axis if in Spectrum mode
            view_mode = "Image" if self.display_stack.currentIndex() == 0 else "Spectrum"
            
            result = MeasurementResult(
                timestamp=datetime.now(),
                integration_time=self.exposure_box.value() / 1000.0,
                metadata=meta
            )
            
            # 5. Determine save path via Dialog
            from ..qt import QFileDialog
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
            from ..core.data_manager import DataManager
            dm = DataManager(data_root=str(save_path.parent))
            if view_mode == "Spectrum":
                # Prepare for processing
                if image.ndim == 2:
                    spectrum = np.sum(image, axis=0)
                else:
                    spectrum = image
                
                result.intensities = spectrum
                result.background = self.background_frame # MeasurementResult handles 2D vs 1D bg
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
                
            from ..qt import QMessageBox
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
        """Calculate spectral x-axis (nm, meV, cm-1) based on mono position."""
        # Default pixel coordinates
        pixels = np.arange(n_pixels)
        
        # Only compute spectral axis for cameras with spectroscopy role
        cam_role = self.hw.get_camera_config(self._get_current_camera_id()).get('role', 'general') if self._get_current_camera_id() else 'general'
        if cam_role != 'spectroscopy':
            return pixels
            
        try:
            # Use the physical model from HardwareManager
            x_nm = self.hw.get_wavelength_axis()
            
            if x_nm is None:
                return pixels
                
            # If the camera ROI is binned horizontally, x_nm will have length equal to ROI width.
            # We need to ensure it matches n_pixels. (Usually it will, as n_pixels comes from the frame).
            if len(x_nm) != n_pixels:
                logger.debug(f"Axis length mismatch: {len(x_nm)} vs {n_pixels}. Resampling.")
                indices = np.linspace(0, len(x_nm)-1, n_pixels)
                x_nm = np.interp(indices, np.arange(len(x_nm)), x_nm)

            if force_nm:
                return x_nm

            # Convert to desired view unit
            unit_mode = self.spec_unit_combo.currentText()
            if unit_mode == "Pixel":
                return pixels
                
            # Use the global unit synchronized with the Monochromator Panel
            unit = self.hw.spectral_unit
            if unit == "nm":
                return x_nm
            elif unit == "meV":
                # Avoid division by zero
                x_nm = np.where(x_nm == 0, 1e-9, x_nm)
                return 1239841.93 / x_nm
            elif unit == "cm⁻¹" or unit == "cm-1":
                x_nm = np.where(x_nm == 0, 1e-9, x_nm)
                return 1e7 / x_nm
            else:
                return x_nm
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
        if self.camera_combo.currentText() != self._background_camera_name:
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
            from ..qt import QTimer
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
        """Handle temperature update for any camera — route if it's the active one."""
        if camera_id == self._get_current_camera_id():
            self._update_temperature_display(temp, status)

    def _on_processing_mode_changed(self, mode):
        """Sync processing mode to hardware manager."""
        self.hw.data_processing_mode = mode
        logger.debug(f"Data processing mode changed to: {mode}")

    def display_image(self, image: np.ndarray):
        """Display image on screen."""
        self.image_plot.imshow(image)

    def _handle_new_frame(self, image):
        """Process and display a newly acquired frame."""
        if image is None:
            return
            
        try:
            # 1. Processing Logic (via MeasurementResult for consistency)
            from ..core.measurement import MeasurementResult
            
            # Temporary result for processing
            res = MeasurementResult(
                timestamp=time.time(), # Not used for display
                integration_time=self._last_exposure_ms / 1000.0 if self._last_exposure_ms else self.exposure_box.value() / 1000.0,
                intensities=image,
                background=self.background_frame,
                background_exposure=(self._background_exposure / 1000.0) if self._background_exposure else None
            )
            
            res.process(self.hw.data_processing_mode)
            image = res.intensities
            
            # Exposure Mismatch Auto-Switch
            # IMPORTANT: Only trigger if the user isn't currently typing (doesn't have focus)
            # to avoid focus-steals that interrupt input half-way.
            if "Exposure Mismatch" in res.metadata.get('Processing', '') and not self.exposure_box.hasFocus():
                self._trigger_exposure_mismatch_warning(self.exposure_box.value())
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
                
            # Perform continuous auto-scaling is now handled natively by PyQtGraph
            # we no longer need to call _auto_scale_now() every frame, which avoids
            # the race condition where hardware updates override manual zoom.

        except Exception as e:
            logger.error(f"Error handling frame: {e}")

    def _update_temperature_display(self, real_temp, status):
        """Update temperature display with dynamic styling."""
        try:
            camera_id = self._get_current_camera_id()
            cam_cfg = self.hw.get_camera_config(camera_id) if camera_id else {}
            target = cam_cfg.get('temperature', -20)
            
            # Apply display logic
            if self._acquiring:
                display_text = f"{real_temp:.1f} °C (Busy)"
                style_mode = "cached"
                status_tooltip = f"Hardware Status: Acquiring..."
            else:
                display_text = f"{real_temp:.1f} °C (Live)"
                style_mode = "stable"
                status_tooltip = f"Hardware Status: {status}"
            
            self.real_temp_box.setText(display_text)
            self.real_temp_box.setToolTip(status_tooltip)
            
            # Styles
            if style_mode == "stable":
                set_temp = self.set_temp_box.value()
                diff = abs(real_temp - set_temp)
                if diff < 1.0:
                    self.real_temp_box.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold; border: 1px solid #1976D2; border-radius: 4px;")
                else:
                    self.real_temp_box.setStyleSheet("background-color: #F44336; color: white; font-weight: bold; border: 1px solid #D32F2F; border-radius: 4px;")
            elif style_mode == "cached":
                self.real_temp_box.setStyleSheet("background-color: #FFC107; color: black; font-weight: bold; border: 1px solid #FFA000; border-radius: 4px;")
            else:
                self.real_temp_box.setStyleSheet("background-color: transparent; border: 1px solid #ced4da; color: gray;")
                
            # Auto-Unit Switching logic (simplified for now as it used to be in temp loop)
            mono = self.hw.mono
            is_mono_connected = mono is not None and mono.is_connected()
            if is_mono_connected != self._mono_connected_prev:
                self.spec_unit_combo.setCurrentText("Spectral Units" if is_mono_connected else "Pixel")
                self._mono_connected_prev = is_mono_connected
                
        except Exception as e:
            logger.error(f"Error updating temp display: {e}")
