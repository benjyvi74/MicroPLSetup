import logging
import time
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from ..qt import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QProgressBar, QGroupBox, QTextEdit,
    Qt, QTimer, QListWidget, QListWidgetItem, QCheckBox,
    QSplitter, QFrame, QTabWidget, QGridLayout, QTableWidget,
    QTableWidgetItem, QHeaderView, QSizePolicy, pyqtSlot, pyqtSignal, QtGui,
    QIcon, QSize, QComboBox, QDoubleSpinBox
)

from .plot import PlotWidget, ImagePlotWidget, CoordinateWidget, SpatialMapWidget
from typing import Tuple, List, Optional
from ..hardware.manager import HardwareManager

logger = logging.getLogger(__name__)


class HistoryList(QListWidget):
    """QListWidget with keyboard deletion support."""
    delete_pressed = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() in [Qt.Key.Key_Delete, Qt.Key.Key_Backspace]:
            self.delete_pressed.emit()
        else:
            super().keyPressEvent(event)


class MeasurementPanel(QWidget):
    """
    Dedicated Monitor and Control Center for automated sequences.
    Displays real-time spectral acquisition and the evolution of the experimental stack.
    """

    stop_requested = pyqtSignal()
    pause_requested = pyqtSignal()
    resume_requested = pyqtSignal()
    abort_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.hw = HardwareManager()
        
        # Data storage for history and heatmap
        self._history_data = [] # List of (x, y, label)
        self._heatmap_matrix = None
        self._wavelength_axis = None
        self._start_time = None
        self._first_step_idx = None # Starting offset for heatmap alignment
        self._total_steps = 0
        self._current_unit = self.hw.spectral_unit
        self._current_mode = self.hw.spectral_display_mode
        
        self._spatial_map_data = []
        self._selected_spatial_idx = -1
        self._active_colormap = "inferno"

        self._init_ui()
        
        if self.hw.service:
            self.hw.service.spectral_unit_changed.connect(self._on_spectral_unit_changed)
            self.hw.service.spectral_display_mode_changed.connect(self._on_spectral_mode_changed)
            
        # Ensure initial units match global state
        self._refresh_plots()
        
        # Auto-range synchronization
        self.live_plot.sigAutoRangeDisabled.connect(lambda: self.auto_all_btn.setChecked(False))
        self.heatmap.sigAutoRangeDisabled.connect(lambda: self.auto_all_btn.setChecked(False))
        
        logger.info("Measurement Monitor initialized")

    def _init_ui(self):
        """Build the dashboard layout."""
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(10)
        self.setLayout(main_layout)

        # --- LEFT SIDE: Left Column ---
        left_column = QVBoxLayout()
        left_column.setContentsMargins(0, 0, 0, 0)
        left_column.setSpacing(5)
        
        # 1. Sequence History
        history_group = QGroupBox("Sequence History")
        history_layout = QVBoxLayout()
        history_layout.setContentsMargins(5, 5, 5, 5)
        history_group.setLayout(history_layout)
        # history_group.setFixedWidth(250) # Move width constraint to the column or use a widget

        self.history_list = HistoryList()
        self.history_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.history_list.itemSelectionChanged.connect(self._on_history_selection_changed)
        self.history_list.delete_pressed.connect(self._on_delete_selected)
        history_layout.addWidget(self.history_list)

        # Plot Controls
        controls_layout = QVBoxLayout()
        controls_layout.setSpacing(2)
        
        self.norm_check = QCheckBox("Normalize")
        self.norm_check.setToolTip("Scale all spectra to [0, 1] for comparison")
        self.norm_check.stateChanged.connect(self._on_history_selection_changed)
        
        self.legend_check = QCheckBox("Legend")
        self.legend_check.setToolTip("Show color-coded legend (Step X)")
        self.legend_check.setChecked(True)
        self.legend_check.stateChanged.connect(self._on_history_selection_changed)

        self.auto_clear_check = QCheckBox("Auto-clear")
        self.auto_clear_check.setToolTip("Clear history when a new sequence starts")
        self.auto_clear_check.setChecked(False)
        
        controls_layout.addWidget(self.norm_check)
        controls_layout.addWidget(self.legend_check)
        controls_layout.addWidget(self.auto_clear_check)
        history_layout.addLayout(controls_layout)
        history_layout.addSpacing(5)
        
        clear_btn = QPushButton("Clear Monitor")
        clear_btn.clicked.connect(self.reset_monitor)
        history_layout.addWidget(clear_btn)

        import_btn = QPushButton("Import Spectra")
        import_btn.setToolTip("Import existing CSV spectra into history")
        import_btn.clicked.connect(self._on_import_spectra)
        history_layout.addWidget(import_btn)

        left_column.addWidget(history_group)

        # 2. Graph Analysis (Graph interaction)
        analysis_group = QGroupBox("Graph Analysis")
        # Use a grid layout for compact buttons
        analysis_layout = QGridLayout()
        analysis_layout.setContentsMargins(5, 5, 5, 5)
        analysis_layout.setSpacing(5)
        analysis_group.setLayout(analysis_layout)

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

        # Markers row
        marker_row = QHBoxLayout()
        marker_row.setSpacing(2)
        marker_label = QLabel("Markers:")
        marker_label.setStyleSheet("font-size: 10px;")
        marker_row.addWidget(marker_label)
        
        self.marker_xy_btn = QPushButton("XY")
        self.marker_x_btn = QPushButton("X")
        self.marker_y_btn = QPushButton("Y")
        self.marker_clear_btn = QPushButton("Clear")
        
        for btn, label in [(self.marker_xy_btn, "XY"), (self.marker_x_btn, "X"), 
                          (self.marker_y_btn, "Y"), (self.marker_clear_btn, "Clear")]:
            btn.setToolTip(f"Add {label} marker")
            btn.setFixedWidth(32 if label == "Clear" else 22)
            btn.setStyleSheet("font-size: 9px; padding: 1px;")
            marker_row.addWidget(btn)
        
        self.marker_xy_btn.clicked.connect(lambda: self._on_add_marker("xy"))
        self.marker_x_btn.clicked.connect(lambda: self._on_add_marker("x"))
        self.marker_y_btn.clicked.connect(lambda: self._on_add_marker("y"))
        self.marker_clear_btn.clicked.connect(self._on_clear_markers)
        
        analysis_layout.addLayout(marker_row, 1, 0, 1, 3)

        # 1. Create the Table
        self.coords_widget = CoordinateWidget()
        analysis_layout.addWidget(self.coords_widget, 2, 0, 1, 3)
        
        # 3. Colormap shortcuts (Horizontal layout to match LiveView)
        cmap_layout = QHBoxLayout()
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
            btn.setStyleSheet(f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c1}, stop:1 {c2});")
            btn.clicked.connect(lambda checked, n=name: self._on_colormap_changed(n))
            cmap_layout.addWidget(btn)
            
        analysis_layout.addLayout(cmap_layout, 3, 0, 1, 3)

        # Force the group to stay compact vertically
        analysis_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        left_column.addWidget(analysis_group)
        left_column.addStretch() # Push everything up

        left_widget = QWidget()
        left_widget.setLayout(left_column)
        left_widget.setFixedWidth(250)
        main_layout.addWidget(left_widget)

        # --- RIGHT SIDE: Dashboard & Plots ---
        right_panel = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_panel.setLayout(right_layout)
        main_layout.addWidget(right_panel, stretch=1)

        # 1. Progress Dashboard
        dash_group = QGroupBox("Sequence Progress")
        dash_layout = QVBoxLayout()
        dash_layout.setContentsMargins(5, 5, 5, 5) # Unified margins
        dash_layout.setSpacing(5) # Reduced spacing
        dash_group.setLayout(dash_layout)
        dash_group.setFixedHeight(130) # Reduced height

        # Status & Step Labels
        labels_layout = QHBoxLayout()
        self.status_label = QLabel("Status: Idle")
        self.status_label.setStyleSheet("font-weight: bold; color: #555;")
        
        self.step_label = QLabel("Step: --- / ---")
        self.step_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        
        self.steps_left_label = QLabel("Steps Left: ---")
        self.steps_left_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #16a085;")
        
        labels_layout.addWidget(self.status_label)
        labels_layout.addStretch()
        labels_layout.addWidget(self.steps_left_label)
        labels_layout.addSpacing(20)
        labels_layout.addWidget(self.step_label)
        dash_layout.addLayout(labels_layout)

        # Progress Bar & Stop Button
        progress_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(25)
        self.progress_bar.setStyleSheet("""
            QProgressBar { border: 1px solid #bbb; border-radius: 5px; text-align: center; }
            QProgressBar::chunk { background-color: #4caf50; }
        """)
        progress_layout.addWidget(self.progress_bar, stretch=10)

        import os
        assets_dir = os.path.join(os.path.dirname(__file__), "assets")
        self._icon_pause_mon = QIcon(os.path.join(assets_dir, "pause_button.png"))
        self._icon_play_mon = QIcon(os.path.join(assets_dir, "play_button.png"))
        self._icon_stop_mon = QIcon(os.path.join(assets_dir, "stop_button.png"))

        self.pause_resume_btn = QPushButton()
        self.pause_resume_btn.setIcon(self._icon_pause_mon)
        self.pause_resume_btn.setIconSize(QSize(18, 18))
        self.pause_resume_btn.setFixedSize(25, 25)
        self.pause_resume_btn.setToolTip("Pause Sequence")
        self.pause_resume_btn.setEnabled(False)
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
        self.pause_resume_btn.clicked.connect(self._on_pause_resume_clicked)
        progress_layout.addWidget(self.pause_resume_btn)

        self.abort_btn = QPushButton()
        self.abort_btn.setIcon(self._icon_stop_mon)
        self.abort_btn.setIconSize(QSize(18, 18))
        self.abort_btn.setFixedSize(25, 25)
        self.abort_btn.setToolTip("Abort Sequence")
        self.abort_btn.setEnabled(False)
        self.abort_btn.setStyleSheet("""
            QPushButton { 
                background-color: #e74c3c; border-radius: 4px;
                padding: 0px;
            }
            QPushButton:hover { background-color: #c0392b; }
            QPushButton:disabled { background-color: #888; }
        """)
        self.abort_btn.clicked.connect(self._on_abort_clicked)
        progress_layout.addWidget(self.abort_btn)
        
        dash_layout.addLayout(progress_layout)

        # ETR and Details
        metrics_layout = QHBoxLayout()
        self.etr_label = QLabel("ETR: --:--:--")
        self.etr_label.setStyleSheet("font-family: 'Courier New'; color: #2c3e50;")
        
        self.action_label = QLabel("---")
        self.action_label.setStyleSheet("font-style: italic; color: #7f8c8d;")

        metrics_layout.addWidget(self.etr_label)
        metrics_layout.addStretch()
        metrics_layout.addWidget(self.action_label)
        dash_layout.addLayout(metrics_layout)

        right_layout.addWidget(dash_group)

        # 2. Visualisation Monitor (Tabs)
        self.monitor_tabs = QTabWidget()
        
        # Tab 1: Spectrum
        spectrum_tab = QWidget()
        spectrum_layout = QVBoxLayout()
        spectrum_layout.setContentsMargins(0, 0, 0, 0) # No double padding in tabs
        spectrum_tab.setLayout(spectrum_layout)
        
        self.live_plot_group = QGroupBox("")
        self.live_plot_layout = QVBoxLayout()
        self.live_plot_layout.setContentsMargins(5, 5, 5, 5) # Unified margins
        self.live_plot_group.setLayout(self.live_plot_layout)
        self.live_plot = PlotWidget()
        self.live_plot.set_labels("Wavelength (nm)", "Intensity (a.u.)")
        self.live_plot_layout.addWidget(self.live_plot)
        spectrum_layout.addWidget(self.live_plot_group)
        
        self.monitor_tabs.addTab(spectrum_tab, "Spectrum")

        # Tab 2: Heatmap
        heatmap_tab = QWidget()
        heatmap_layout = QVBoxLayout()
        heatmap_layout.setContentsMargins(0, 0, 0, 0) # No double padding in tabs
        heatmap_tab.setLayout(heatmap_layout)

        self.heatmap_group = QGroupBox("")
        self.heatmap_layout = QVBoxLayout()
        self.heatmap_layout.setContentsMargins(5, 5, 5, 5) # Unified margins
        self.heatmap_group.setLayout(self.heatmap_layout)
        self.heatmap = ImagePlotWidget()
        self.heatmap.set_aspect_locked(False) # Heatmap can stretch to fill space
        self.heatmap_layout.addWidget(self.heatmap)
        heatmap_layout.addWidget(self.heatmap_group)
        
        self.monitor_tabs.addTab(heatmap_tab, "Evolution Map")

        # Tab 3: Spatial Heatmap
        spatial_tab = QWidget()
        spatial_layout = QVBoxLayout()
        spatial_layout.setContentsMargins(0, 0, 0, 0)
        spatial_tab.setLayout(spatial_layout)

        self.spatial_group = QGroupBox("")
        self.spatial_group_layout = QVBoxLayout()
        self.spatial_group_layout.setContentsMargins(5, 5, 5, 5)
        self.spatial_group.setLayout(self.spatial_group_layout)

        # Control row for Spatial Map (includes Colormap value selection and all scaling controls)
        spatial_ctrl = QHBoxLayout()
        spatial_ctrl.addWidget(QLabel("Color Map Value:"))
        self.spatial_metric_combo = QComboBox()
        self.spatial_metric_combo.addItems([
            "Peak Wavelength", 
            "Peak Intensity", 
            "Integrated Intensity"
        ])
        self.spatial_metric_combo.currentTextChanged.connect(self._on_spatial_metric_changed)
        spatial_ctrl.addWidget(self.spatial_metric_combo)
        
        spatial_ctrl.addSpacing(20)
        
        self.spatial_autoscale_chk = QCheckBox("Auto-scale")
        self.spatial_autoscale_chk.setChecked(True)
        self.spatial_autoscale_chk.toggled.connect(self._on_spatial_autoscale_toggled)
        spatial_ctrl.addWidget(self.spatial_autoscale_chk)
        
        spatial_ctrl.addSpacing(10)
        
        self.spatial_scale_mode_combo = QComboBox()
        self.spatial_scale_mode_combo.addItems(["Min / Max", "Center / Range"])
        self.spatial_scale_mode_combo.currentTextChanged.connect(self._on_spatial_scale_mode_changed)
        spatial_ctrl.addWidget(self.spatial_scale_mode_combo)
        
        spatial_ctrl.addSpacing(10)
        
        # Container for Min / Max controls
        self.spatial_min_max_widget = QWidget()
        min_max_layout = QHBoxLayout(self.spatial_min_max_widget)
        min_max_layout.setContentsMargins(0, 0, 0, 0)
        min_max_layout.setSpacing(5)
        
        min_max_layout.addWidget(QLabel("Min:"))
        self.spatial_min_spin = QDoubleSpinBox()
        self.spatial_min_spin.setRange(-1e9, 1e9)
        self.spatial_min_spin.setDecimals(3)
        self.spatial_min_spin.setValue(0.0)
        self.spatial_min_spin.setFixedWidth(80)
        self.spatial_min_spin.valueChanged.connect(self._on_spatial_limits_changed)
        min_max_layout.addWidget(self.spatial_min_spin)
        
        min_max_layout.addWidget(QLabel("Max:"))
        self.spatial_max_spin = QDoubleSpinBox()
        self.spatial_max_spin.setRange(-1e9, 1e9)
        self.spatial_max_spin.setDecimals(3)
        self.spatial_max_spin.setValue(1.0)
        self.spatial_max_spin.setFixedWidth(80)
        self.spatial_max_spin.valueChanged.connect(self._on_spatial_limits_changed)
        min_max_layout.addWidget(self.spatial_max_spin)
        
        spatial_ctrl.addWidget(self.spatial_min_max_widget)
        
        # Container for Center / Range controls
        self.spatial_center_range_widget = QWidget()
        center_range_layout = QHBoxLayout(self.spatial_center_range_widget)
        center_range_layout.setContentsMargins(0, 0, 0, 0)
        center_range_layout.setSpacing(5)
        
        center_range_layout.addWidget(QLabel("Center:"))
        self.spatial_center_spin = QDoubleSpinBox()
        self.spatial_center_spin.setRange(-1e9, 1e9)
        self.spatial_center_spin.setDecimals(3)
        self.spatial_center_spin.setValue(0.5)
        self.spatial_center_spin.setFixedWidth(80)
        self.spatial_center_spin.valueChanged.connect(self._on_spatial_limits_changed)
        center_range_layout.addWidget(self.spatial_center_spin)
        
        center_range_layout.addWidget(QLabel("Range (+/-):"))
        self.spatial_range_spin = QDoubleSpinBox()
        self.spatial_range_spin.setRange(0.001, 1e9)
        self.spatial_range_spin.setDecimals(3)
        self.spatial_range_spin.setValue(0.5)
        self.spatial_range_spin.setFixedWidth(80)
        self.spatial_range_spin.valueChanged.connect(self._on_spatial_limits_changed)
        center_range_layout.addWidget(self.spatial_range_spin)
        
        spatial_ctrl.addWidget(self.spatial_center_range_widget)
        self.spatial_center_range_widget.hide() # Hidden initially
        
        spatial_ctrl.addStretch()
        self.spatial_group_layout.addLayout(spatial_ctrl)
        
        # Initially disable manual controls as auto-scale is checked by default
        self.spatial_scale_mode_combo.setEnabled(False)
        self.spatial_min_spin.setEnabled(False)
        self.spatial_max_spin.setEnabled(False)
        self.spatial_center_spin.setEnabled(False)
        self.spatial_range_spin.setEnabled(False)

        # Spatial Map Widget
        self.spatial_map = SpatialMapWidget()
        self.spatial_group_layout.addWidget(self.spatial_map)
        
        spatial_layout.addWidget(self.spatial_group)
        self.monitor_tabs.addTab(spatial_tab, "Spatial Map")

        right_layout.addWidget(self.monitor_tabs)

        # Connect mouse movement signals for coordinate display
        self.live_plot.sigMouseMoved.connect(self._on_plot_mouse_moved)
        self.heatmap.sigMouseMoved.connect(self._on_plot_mouse_moved)
        self.spatial_map.sigPointHovered.connect(self._on_spatial_point_hovered)
        self.spatial_map.sigPointClicked.connect(self._on_spatial_point_clicked)
        
        # Clear coordinates when switching tabs
        self.monitor_tabs.currentChanged.connect(self.coords_widget.clear)

    # --- SLOTS FOR PROXY SIGNALS ---

    def on_sequence_started(self, steps: list, meas_power: float, start_index: int = 1):
        """Initialize monitor for a new run."""
        if self.auto_clear_check.isChecked():
            self.reset_monitor()
        else:
            # Partial reset: Only progress and current sequence data
            self._reset_progress()
            self._spatial_map_data = []
            self._selected_spatial_idx = -1
            self.spatial_map.clear()
            
        self._start_index = start_index
        
        is_mapping = len(steps) > 0 and isinstance(steps[0], (tuple, list)) and len(steps[0]) == 2
        if is_mapping:
            main_win = self.window()
            from .automation_panel import AutomationPanel
            ap = main_win.findChild(AutomationPanel)
            if not ap and hasattr(main_win, 'automation_panel'):
                ap = main_win.automation_panel
            if ap:
                is_circle = ap.map_shape_combo.currentText() == "Circle (Circular Window)"
                shape = "circle" if is_circle else "rectangle"
                diameter = ap.map_diameter_spin.value()
                x_start = ap.map_x_start.value()
                x_end = ap.map_x_end.value()
                y_start = ap.map_y_start.value()
                y_end = ap.map_y_end.value()
                
                self.spatial_map.draw_background_shape(shape, x_start, x_end, y_start, y_end, diameter)
                
            # Automatically switch to the "Spatial Map" tab
            for i in range(self.monitor_tabs.count()):
                if self.monitor_tabs.tabText(i) == "Spatial Map":
                    self.monitor_tabs.setCurrentIndex(i)
                    break
        self._num_steps = len(steps)
        self._max_step = start_index + self._num_steps - (1 if start_index > 0 else 0)
        # If start_index is 0 (baseline included), max step is num_steps. 
        # If start_index is 1, max step is 1 + 20 - 1 = 20.
        # Actually, let's look at how LaserHeatingWorker calculates it.
        # step_idx = i + offset where offset is start_index or 1.
        # If start_index is 56, steps=20 -> step_idx=56..75. Max is 75.
        # offset = start_index if start_index > 0 else 1
        # max = (num_steps - 1) + offset
        offset = start_index if start_index > 0 else 1
        self._max_step = (self._num_steps - 1) + offset
        
        self._start_time = time.time()
        
        self.status_label.setText("Status: RUNNING")
        self.status_label.setStyleSheet("font-weight: bold; color: #27ae60;")
        self.step_label.setText(f"Step: {offset-1} / {self._max_step}")
        self.steps_left_label.setText(f"Steps Left: {self._num_steps}")
        self.progress_bar.setValue(0)
        
        self.pause_resume_btn.setEnabled(True)
        self.pause_resume_btn.setIcon(self._icon_pause_mon)
        self.pause_resume_btn.setToolTip("Pause Sequence")
        self.abort_btn.setEnabled(True)
        
        logger.debug(f"Monitor: Sequence started with {self._num_steps} steps, starting at {offset}")

    def on_step_progress(self, step_idx: int, action_text: str, progress_percent: int):
        """Update progress dashboard."""
        if step_idx >= 0:
            # step_idx is the absolute index (e.g. 56)
            self.step_label.setText(f"Step: {step_idx} / {self._max_step}")
            self.progress_bar.setValue(progress_percent)
            
            # Calculate steps remaining
            # If we are at step_idx, and we started at offset, and have num_steps...
            # The current step number in this sequence is (step_idx - offset + 1)
            offset = self._start_index if self._start_index > 0 else 1
            current_step_in_seq = step_idx - offset + 1
            remaining = max(0, self._num_steps - current_step_in_seq)
            self.steps_left_label.setText(f"Steps Left: {remaining}")
            
        self.action_label.setText(action_text)
        
        # Highlight cooling status
        if "Cooling" in action_text:
            self.action_label.setStyleSheet("font-weight: bold; color: #d35400;") # Orange/rust color
        else:
            self.action_label.setStyleSheet("font-style: italic; color: #7f8c8d;")
        
        # Update ETR
        if self._start_time and progress_percent > 0:
            elapsed = time.time() - self._start_time
            total_est = elapsed / (progress_percent / 100.0)
            remaining = total_est - elapsed
            
            etr_str = str(timedelta(seconds=int(remaining)))
            self.etr_label.setText(f"ETR: {etr_str}")

    def _convert_x_axis(self, x_nm: np.ndarray, target_unit: str) -> np.ndarray:
        """Convert wavelength array to target units based on mode."""
        if self._current_mode == "Pixel":
            return np.arange(len(x_nm))
            
        if target_unit == "nm":
            return x_nm
        elif target_unit == "meV":
            # Avoid division by zero
            safe_nm = np.where(x_nm == 0, 1e-9, x_nm)
            return 1239841.93 / safe_nm
        elif target_unit in ["cm⁻¹", "cm-1"]:
            safe_nm = np.where(x_nm == 0, 1e-9, x_nm)
            return 1e7 / safe_nm
        return x_nm

    @pyqtSlot(str)
    def _on_spectral_mode_changed(self, new_mode: str):
        """Handle display mode changes (Pixel vs Spectral Units)."""
        logger.debug(f"Monitor: Spectral mode changed to {new_mode}")
        self._current_mode = new_mode
        self._refresh_plots()

    @pyqtSlot(str)
    def _on_spectral_unit_changed(self, new_unit: str):
        """Handle unit changes (nm, meV, etc.) from other panels."""
        logger.debug(f"Monitor: Spectral units changed to {new_unit}")
        self._current_unit = new_unit
        self._refresh_plots()

    def _refresh_plots(self):
        """Force update of labels and data in both plots."""
        # Update Labels
        if self._current_mode == "Pixel":
            x_label = "Pixel"
        else:
            x_label = "Wavelength (nm)" if self._current_unit == "nm" else f"Energy ({self._current_unit})"
        
        self.live_plot.set_labels(x_label, "Intensity (a.u.)")
        self.heatmap.set_labels("Step Index", x_label)
        
        # Refresh Heatmap
        if self._heatmap_matrix is not None and self._wavelength_axis is not None:
            # Interpolate for non-linear axes and fix half-pixel shift
            display_matrix, x_linear = self._get_display_heatmap(
                self._heatmap_matrix, self._wavelength_axis, self._current_unit
            )
            
            # Use start index offset for alignment
            s_start = self._first_step_idx if self._first_step_idx is not None else 0
            s_end = s_start + self._heatmap_matrix.shape[0]
            
            # Calculate extent mapping to pixel edges (not centers)
            # dx is spectral delta, ds is step delta (always 1.0)
            dx = (x_linear[-1] - x_linear[0]) / (len(x_linear) - 1) if len(x_linear) > 1 else 1.0
            
            # SWAP: Horizontal = Step Index, Vertical = Spectral Axis
            extent = [s_start, s_end, x_linear[0] - 0.5*dx, x_linear[-1] + 0.5*dx]
            
            self.heatmap.imshow(display_matrix.T, extent=extent)
            
        # Refresh current review plot
        if self.history_list.currentItem():
            self._on_history_item_clicked(self.history_list.currentItem())

    def _get_display_heatmap(self, matrix: np.ndarray, x_nm: np.ndarray, unit: str):
        """
        Interpolate heatmap matrix onto a linear grid for the target units.
        This ensures that peaks align perfectly even in non-linear units like meV.
        """
        # 1. Convert actual x-axis to target units
        x_actual = self._convert_x_axis(x_nm, unit)
        
        # 2. Handle Pixel mode (already linear, no interpolation needed but we return linear grid)
        if self._current_mode == "Pixel":
            x_linear = np.arange(len(x_nm))
            return matrix, x_linear
            
        # 3. Create a perfectly linear grid for display
        # We always interpolate to ensure "extent" mapping to edges is perfectly centered.
        x_linear = np.linspace(x_actual[0], x_actual[-1], len(x_actual))
        
        # 4. Perform row-by-row interpolation
        # np.interp requires increasing x_actual.
        is_decreasing = x_actual[0] > x_actual[-1]
        if is_decreasing:
            x_actual_sorted = x_actual[::-1]
            x_linear_sorted = x_linear[::-1]
            matrix_sorted = matrix[:, ::-1]
            
            display_matrix = np.zeros_like(matrix)
            for i in range(matrix.shape[0]):
                display_matrix[i, :] = np.interp(x_linear_sorted, x_actual_sorted, matrix_sorted[i, :])[::-1]
        else:
            display_matrix = np.zeros_like(matrix)
            for i in range(matrix.shape[0]):
                display_matrix[i, :] = np.interp(x_linear, x_actual, matrix[i, :])
                
        return display_matrix, x_linear

    def on_measurement_ready(self, x_axis_nm: np.ndarray, y_axis: np.ndarray, label: str):
        """Archived a new spectrum. Update live plot and heatmap."""
        # 1. Update Live Plot
        self.live_plot_group.setTitle(label)
        
        # Convert X-axis for display
        x_axis_display = self._convert_x_axis(x_axis_nm, self._current_unit)
        x_label = "Wavelength (nm)" if self._current_unit == "nm" else f"Energy ({self._current_unit})"
        self.live_plot.set_labels(x_label, "Intensity (a.u.)")
        self.heatmap.set_labels("Step Index", x_label)
        
        self.live_plot.update_plot(x_axis_display, y_axis)
        
        # 2. Add to History
        item = QListWidgetItem(label)
        self.history_list.addItem(item)
        self.history_list.scrollToBottom()
        
        self._history_data.append((x_axis_nm, y_axis, label))
        
        # 3. Update Heatmap
        if self._heatmap_matrix is None:
            # First row defines dimensions
            self._heatmap_matrix = y_axis.reshape(1, -1)
            self._wavelength_axis = x_axis_nm
            
            # Parse start index from label (e.g. step_005_...)
            if "step_" in label.lower():
                try:
                    parts = label.split('_')
                    self._first_step_idx = int(parts[1])
                except:
                    self._first_step_idx = 0
            else:
                self._first_step_idx = 0
        else:
            # Append new row if shapes match
            if y_axis.shape == self._heatmap_matrix[0].shape:
                self._heatmap_matrix = np.vstack([self._heatmap_matrix, y_axis])
            else:
                logger.warning(f"Spectrum shape mismatch: {y_axis.shape} vs {self._heatmap_matrix[0].shape}. Skipping heatmap update.")
                return 
            
        # Display heatmap (Step index on X, Axis on Y)
        display_matrix, x_linear = self._get_display_heatmap(
            self._heatmap_matrix, self._wavelength_axis, self._current_unit
        )
        
        s_start = self._first_step_idx if self._first_step_idx is not None else 0
        s_end = s_start + self._heatmap_matrix.shape[0]
        
        # Calculate extent mapping to pixel edges (not centers)
        dx = (x_linear[-1] - x_linear[0]) / (len(x_linear) - 1) if len(x_linear) > 1 else 1.0
        extent = [s_start, s_end, x_linear[0] - 0.5*dx, x_linear[-1] + 0.5*dx]
        
        self.heatmap.imshow(display_matrix.T, extent=extent)

        # Continuous auto-scale 
        if self.auto_all_btn.isChecked():
            self._auto_scale_now()
            
        # 4. Update Spatial Map (if mapping coordinates are present)
        coords = self.parse_map_coords(label)
        if coords is not None:
            x, y = coords
            # Calculate spectral features
            peak_idx = np.argmax(y_axis)
            peak_wl = x_axis_nm[peak_idx]
            peak_int = y_axis[peak_idx]
            int_int = np.sum(y_axis)
            
            self._spatial_map_data.append({
                'index': len(self._spatial_map_data),
                'x': x,
                'y': y,
                'spectrum_x': x_axis_nm,
                'spectrum_y': y_axis,
                'label': label,
                'peak_wavelength': peak_wl,
                'peak_intensity': peak_int,
                'integrated_intensity': int_int
            })
            self._update_spatial_map()

    def on_sequence_finished(self, success: bool, message: str):
        """Cleanup after run."""
        self._start_time = None
        self.status_label.setText("Status: FINISHED" if success else "Status: ABORTED")
        self.status_label.setStyleSheet(f"font-weight: bold; color: {'#2980b9' if success else '#c0392b'};")
        self.etr_label.setText("ETR: 00:00:00")
        self.progress_bar.setValue(100 if success else self.progress_bar.value())
        self.steps_left_label.setText("Steps Left: 0" if success else "Steps Left: ---")
        
        self.pause_resume_btn.setEnabled(False)
        self.pause_resume_btn.setIcon(self._icon_pause_mon)
        self.pause_resume_btn.setToolTip("Pause Sequence")
        self.abort_btn.setEnabled(False)

    # --- ACTIONS ---

    def _on_pause_resume_clicked(self):
        if self.pause_resume_btn.toolTip() == "Pause Sequence":
            self.pause_requested.emit()
            self.pause_resume_btn.setIcon(self._icon_play_mon)
            self.pause_resume_btn.setToolTip("Resume Sequence")
            self.status_label.setText("Status: PAUSED")
            self.status_label.setStyleSheet("font-weight: bold; color: #e67e22;")
        else:
            self.resume_requested.emit()
            self.pause_resume_btn.setIcon(self._icon_pause_mon)
            self.pause_resume_btn.setToolTip("Pause Sequence")
            self.status_label.setText("Status: RUNNING")
            self.status_label.setStyleSheet("font-weight: bold; color: #27ae60;")

    def _on_abort_clicked(self):
        self.abort_requested.emit()
        self.pause_resume_btn.setEnabled(False)
        self.abort_btn.setEnabled(False)
        self.status_label.setText("Status: ABORTING...")
        self.status_label.setStyleSheet("font-weight: bold; color: #c0392b;")

    def _on_history_selection_changed(self):
        """Show selected historical results in top plot."""
        items = self.history_list.selectedItems()
        if not items:
            return
            
        # Update legend visibility
        self.live_plot.show_legend(self.legend_check.isChecked())
            
        # Clear and prepare series for multi-plot
        series = []
        for item in items:
            index = self.history_list.row(item)
            if 0 <= index < len(self._history_data):
                x_nm, y, label = self._history_data[index]
                
                # Apply normalization if requested
                if self.norm_check.isChecked():
                    y_max = np.max(y)
                    y_plot = y / y_max if y_max > 0 else y
                else:
                    y_plot = y
                
                # Simplify legend label if requested
                if self.legend_check.isChecked():
                    # Extract step number if possible, else use original label
                    display_label = label
                    if "step_" in label.lower():
                        try:
                            # format is usually step_001_...
                            parts = label.split('_')
                            idx = int(parts[1])
                            display_label = f"Step {idx}"
                        except:
                            pass
                else:
                    display_label = label

                x_display = self._convert_x_axis(x_nm, self._current_unit)
                series.append((x_display, y_plot, display_label))
        
        if len(series) == 1:
            self.monitor_tabs.setCurrentIndex(0)
            self.live_plot_group.setTitle(f"Review: {series[0][2]}")
            self.live_plot.plot(series[0][0], series[0][1], label=series[0][2])
        elif len(series) > 1:
            self.monitor_tabs.setCurrentIndex(0)
            self.live_plot_group.setTitle(f"Review: Multiple ({len(series)})")
            self.live_plot.plot_multiple(series)

    def _on_history_item_clicked(self, item):
        # Kept for compatibility if called directly, but now handled by selection change
        self._on_history_selection_changed()

    def _on_colormap_changed(self, name):
        self._active_colormap = name
        self.heatmap.set_colormap(name)
        self._update_spatial_map()

    def parse_map_coords(self, label: str) -> Optional[Tuple[float, float]]:
        if "map_idx_" in label and "_X_" in label and "_Y_" in label:
            try:
                parts_x = label.split("_X_")[1].split("_Y_")
                x_part = parts_x[0]
                y_part = parts_x[1]
                
                if "_" in x_part:
                    r_idx = x_part.rfind("_")
                    x_val = float(x_part[:r_idx] + "." + x_part[r_idx+1:])
                else:
                    x_val = float(x_part)
                    
                if "_" in y_part:
                    r_idx = y_part.rfind("_")
                    y_val = float(y_part[:r_idx] + "." + y_part[r_idx+1:])
                else:
                    y_val = float(y_part)
                    
                return x_val, y_val
            except Exception as e:
                logger.error(f"Error parsing map coordinates from {label}: {e}")
        return None

    def _on_spatial_metric_changed(self, text):
        self._update_spatial_map()

    def _on_spatial_autoscale_toggled(self, checked):
        # Disable manual mode selection and spinboxes if auto-scale is checked
        self.spatial_scale_mode_combo.setEnabled(not checked)
        self.spatial_min_spin.setEnabled(not checked)
        self.spatial_max_spin.setEnabled(not checked)
        self.spatial_center_spin.setEnabled(not checked)
        self.spatial_range_spin.setEnabled(not checked)
        self._update_spatial_map()

    def _on_spatial_scale_mode_changed(self, mode):
        if mode == "Min / Max":
            self.spatial_min_max_widget.show()
            self.spatial_center_range_widget.hide()
        else:
            self.spatial_min_max_widget.hide()
            self.spatial_center_range_widget.show()
        self._update_spatial_map()

    def _on_spatial_limits_changed(self, val):
        self._update_spatial_map()

    def _on_spatial_point_hovered(self, data: dict):
        if data:
            x, y = data['x'], data['y']
            self.coords_widget.set_coords(x, y)
        else:
            self.coords_widget.clear()

    def _on_spatial_point_clicked(self, data: dict):
        if data:
            self._selected_spatial_idx = data['index']
            
            # Update Live Plot to show this spectrum
            x_axis_display = self._convert_x_axis(data['spectrum_x'], self._current_unit)
            x_label = "Wavelength (nm)" if self._current_unit == "nm" else f"Energy ({self._current_unit})"
            self.live_plot.set_labels(x_label, "Intensity (a.u.)")
            self.live_plot_group.setTitle(f"Spectrum (Selected from Map: X={data['x']:.3f}, Y={data['y']:.3f})")
            self.live_plot.update_plot(x_axis_display, data['spectrum_y'])
            
            # Re-draw the highlight on the spatial map to make sure the selected outline updates
            self._update_spatial_map()
            
            for i in range(self.monitor_tabs.count()):
                if self.monitor_tabs.tabText(i) == "Spectrum":
                    self.monitor_tabs.setCurrentIndex(i)
                    break

    def _update_spatial_map(self):
        if not self._spatial_map_data:
            self.spatial_map.clear()
            return
            
        metric_sel = self.spatial_metric_combo.currentText()
        if metric_sel == "Peak Wavelength":
            metric = 'peak_wavelength'
        elif metric_sel == "Peak Intensity":
            metric = 'peak_intensity'
        else:
            metric = 'integrated_intensity'

        # Get active values for the metric
        values = np.array([p[metric] for p in self._spatial_map_data])
        
        auto_scale = self.spatial_autoscale_chk.isChecked()
        mode = self.spatial_scale_mode_combo.currentText()
        
        if auto_scale:
            min_val = np.min(values) if len(values) > 0 else 0.0
            max_val = np.max(values) if len(values) > 0 else 1.0
            
            # Update spinboxes without triggering signals
            self.spatial_min_spin.blockSignals(True)
            self.spatial_max_spin.blockSignals(True)
            self.spatial_center_spin.blockSignals(True)
            self.spatial_range_spin.blockSignals(True)
            
            self.spatial_min_spin.setValue(min_val)
            self.spatial_max_spin.setValue(max_val)
            self.spatial_center_spin.setValue((max_val + min_val) / 2.0)
            self.spatial_range_spin.setValue(max((max_val - min_val) / 2.0, 0.001))
            
            self.spatial_min_spin.blockSignals(False)
            self.spatial_max_spin.blockSignals(False)
            self.spatial_center_spin.blockSignals(False)
            self.spatial_range_spin.blockSignals(False)
        else:
            if mode == "Min / Max":
                min_val = self.spatial_min_spin.value()
                max_val = self.spatial_max_spin.value()
            else:
                center = self.spatial_center_spin.value()
                span = self.spatial_range_spin.value()
                min_val = center - span
                max_val = center + span
            
        self.spatial_map.update_points(
            self._spatial_map_data, 
            self._selected_spatial_idx, 
            metric, 
            self._active_colormap,
            auto_scale=auto_scale,
            min_val=min_val,
            max_val=max_val
        )

    def reset_monitor(self):
        """Clear all previous results from the view."""
        self.history_list.clear()
        self._history_data = []
        self.live_plot.clear()
        self.live_plot_group.setTitle("")
        self._reset_progress()
        self._spatial_map_data = []
        self._selected_spatial_idx = -1
        self.spatial_map.clear()

    def _reset_progress(self):
        """Clear progress indicators and current evolution map."""
        self.heatmap.clear()
        self._heatmap_matrix = None
        self._wavelength_axis = None
        self._start_time = None
        self._first_step_idx = None
        self.progress_bar.setValue(0)
        self.etr_label.setText("ETR: --:--:--")
        self.step_label.setText("Step: --- / ---")
        self.steps_left_label.setText("Steps Left: ---")

    def _on_import_spectra(self):
        """Load spectra from file system and add to history."""
        from ..qt import QFileDialog
        from ..core.data_manager import DataManager
        
        files, _ = QFileDialog.getOpenFileNames(
            self, "Import Spectra", "", "CSV Files (*.csv);;All Files (*)"
        )
        
        if not files:
            return
            
        # Sort files by step index to ensure correctly ordered heatmap
        def extract_index(filename):
            if "step_" in filename.lower():
                try:
                    return int(filename.split('_')[1])
                except:
                    pass
            return 0

        files.sort(key=lambda f: extract_index(Path(f).stem))

        data_root = self.hw.config.get('paths', {}).get('data_root', '.')
        dm = DataManager(data_root=data_root)
        count = 0
        
        for f in files:
            try:
                res = dm.load_spectrum(f)
                if res.has_spectrum():
                    # Determine units from metadata for conversion if needed
                    unit = res.metadata.get('_units', res.metadata.get('units', 'nm'))
                    x_nm = res.wavelengths
                    
                    # If imported in non-nm units, convert back to nm for internal storage
                    if unit == 'meV':
                        x_nm = 1239841.93 / np.where(res.wavelengths == 0, 1e-9, res.wavelengths)
                    elif unit in ['cm-1', 'cm⁻¹']:
                        x_nm = 1e7 / np.where(res.wavelengths == 0, 1e-9, res.wavelengths)
                    
                    # Add to history (reuses local plot update logic)
                    self.on_measurement_ready(x_nm, res.intensities, Path(f).stem)
                    count += 1
            except Exception as e:
                logger.error(f"Failed to import {f}: {e}")

        if count > 0:
            logger.info(f"Imported {count} spectra.")

    def _on_delete_selected(self):
        """Remove selected items from history and heatmap."""
        items = self.history_list.selectedItems()
        if not items:
            return
            
        # Get indices and sort in descending order for safe deletion
        indices = sorted([self.history_list.row(item) for item in items], reverse=True)
        
        for idx in indices:
            # 1. Remove from UI list
            self.history_list.takeItem(idx)
            
            # 2. Remove from internal history
            if 0 <= idx < len(self._history_data):
                self._history_data.pop(idx)
            
            # 3. Remove from heatmap matrix
            if self._heatmap_matrix is not None:
                if 0 <= idx < self._heatmap_matrix.shape[0]:
                    self._heatmap_matrix = np.delete(self._heatmap_matrix, idx, axis=0)
                    
                    if self._heatmap_matrix.shape[0] == 0:
                        self._heatmap_matrix = None
                        self._wavelength_axis = None
        
        # 4. Refresh plots
        self.live_plot.clear()
        self.live_plot_group.setTitle("")
        
        if self._heatmap_matrix is None:
            self.heatmap.clear()
        else:
            self._refresh_plots()
            
        logger.info(f"Deleted {len(indices)} spectra from history.")

    def _on_auto_scale_toggled(self, checked: bool):
        """Handle continuous auto-scale toggle."""
        if checked:
            self._auto_scale_now()

    def _auto_scale_now(self):
        """Immediately trigger auto-scale on active plot."""
        if self.monitor_tabs.currentIndex() == 0:
            self.live_plot.auto_scale_all()
        else:
            self.heatmap.auto_scale_all()

    def _auto_scale_all(self):
        """Legacy handler or manual-trigger-only if needed."""
        self._auto_scale_now()

    def _on_axis_lock_changed(self):
        """Lock/Unlock mouse interaction for X and Y on both plots."""
        lock_x = self.lock_x_check.isChecked()
        lock_y = self.lock_y_check.isChecked()
        self.live_plot.set_mouse_enabled(not lock_x, not lock_y)
        self.heatmap.set_mouse_enabled(not lock_x, not lock_y)

    def _on_add_marker(self, marker_type):
        """Add a marker to the active plot."""
        if self.monitor_tabs.currentIndex() == 0:
            self.live_plot.add_marker(marker_type)
        else:
            # For heatmap, image plot also has add_marker now
            self.heatmap.add_marker(marker_type)

    def _on_clear_markers(self):
        """Clear all markers from both plots."""
        self.live_plot.remove_markers()
        self.heatmap.remove_markers()

    def _on_plot_mouse_moved(self, x, y):
        """Update coordinates display."""
        # Note: CoordinateWidget handles NaN/Reset internally via set_coords(np.nan, np.nan)
        # However, for the specifically formatted strings in the Heatmap vs Spectrum,
        # we might want to keep some of that logic or move it to CoordinateWidget.
        # For simplicity and unification, we'll use standard formatting for now.
        
        # Detect unit dynamically and handle Heatmap swap
        is_heatmap = self.sender() == self.heatmap
        
        if np.isnan(x) or np.isnan(y):
             self.coords_widget.clear()
             return

        if is_heatmap:
            # For heatmap, we show step index and spectral unit
            self.coords_widget.set_coords(x, y, x_fmt=".1f", y_fmt=".2f")
        else:
            # Standard Plot: X is spectral, Y is intensity
            self.coords_widget.set_coords(x, y)

