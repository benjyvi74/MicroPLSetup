import logging
from typing import Any, Dict, List, Tuple

from ..qt import (
    QCheckBox,
    QDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    Qt,
)

from .automation_panel import format_power_w

logger = logging.getLogger(__name__)

class LaserHeatingSummaryDialog(QDialog):
    """
    Dialog to review and confirm a laser heating sequence before execution.
    Allows toggling 'Skip Step 0'.
    """
    def __init__(self, steps: List[Dict[str, Any]], cooling_delay: float = 0.0, start_index: int = 1, meas_power_w: float = 0.0, parent=None):
        super().__init__(parent)
        self.steps = steps
        self.cooling_delay = cooling_delay
        self.start_index = start_index
        self.meas_power_w = meas_power_w
        self.setWindowTitle("Review Heating Sequence")
        self.resize(500, 450)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Header
        layout.addWidget(QLabel("<b>Sequence Summary</b>"))
        
        # Summary Table
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Step #", "Heat Power", "Duration"])
        h_header = self.table.horizontalHeader()
        if h_header is not None:
            h_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v_header = self.table.verticalHeader()
        if v_header is not None:
            v_header.setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        # Populate table
        # Step 0 explicit row
        self.table.insertRow(0)
        self.table.setItem(0, 0, QTableWidgetItem("0 (Initial)"))
        self.table.setItem(0, 1, QTableWidgetItem("-"))
        self.table.setItem(0, 2, QTableWidgetItem("-"))
        
        # Dim Step 0 if we are starting from a later index
        if self.start_index > 0:
            for c in range(3):
                item = self.table.item(0, c)
                if item is not None:
                    item.setText(item.text() + " (Skipped)")
                    item.setForeground(Qt.GlobalColor.gray)

        # Labels match AutomationPanel re-indexing logic
        offset = self.start_index if self.start_index > 0 else 1
        
        for i, step in enumerate(self.steps):
            row = i + 1
            self.table.insertRow(row)
            step_num = i + offset
            self.table.setItem(row, 0, QTableWidgetItem(str(step_num)))
            
            p_val = step.get('target_w', 0.0)
            p_str = format_power_w(p_val)
            self.table.setItem(row, 1, QTableWidgetItem(p_str))
            
            d_val = step.get('duration', 0.0)
            self.table.setItem(row, 2, QTableWidgetItem(f"{d_val} s"))

        layout.addWidget(self.table)

        # Options
        self.skip_checkbox = QCheckBox("Skip Step 0 (Initial Measurement)")
        # If start_index > 1, we MUST skip step 0 (already done in previous run), so disable toggle
        if self.start_index > 1:
            self.skip_checkbox.setChecked(True)
            self.skip_checkbox.setEnabled(False)
        else:
            # For a fresh run (start index 1), don't skip by default
            self.skip_checkbox.setChecked(False)
            self.skip_checkbox.setEnabled(True)
        
        self.skip_checkbox.setToolTip("If checked, the sequence will start directly with Heating Step 1.")
        layout.addWidget(self.skip_checkbox)

        # Info
        info_layout = QVBoxLayout()
        
        delay_lbl = QLabel(f"<b>Cooling Delay: {self.cooling_delay} s</b>")
        delay_lbl.setStyleSheet("color: #d35400;")
        info_layout.addWidget(delay_lbl)
        
        # Estimated time label
        self.est_time_lbl = QLabel()
        self.est_time_lbl.setStyleSheet("color: #2980b9; font-weight: bold;")
        info_layout.addWidget(self.est_time_lbl)
        
        info_lbl = QLabel("Note: Data will be saved to the folder/prefix defined in the main window.\n"
                         "Background correction and Time Normalization will be applied.")
        info_lbl.setStyleSheet("color: gray; font-style: italic;")
        info_lbl.setWordWrap(True)
        info_layout.addWidget(info_lbl)
        
        layout.addLayout(info_layout)

        # Connect skip checkbox state change to dynamically update estimate
        self.skip_checkbox.stateChanged.connect(self._update_time_estimate)
        self._update_time_estimate()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        run_btn = QPushButton("Run Sequence")
        run_btn.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold;")
        run_btn.clicked.connect(self.accept)
        btn_layout.addWidget(run_btn)
        
        layout.addLayout(btn_layout)

    def should_skip_step_0(self) -> bool:
        return self.skip_checkbox.isChecked()  # type: ignore[no-any-return]

    def calculate_estimated_duration(self) -> float:
        """
        Calculate the total estimated duration of the sequence in seconds.
        Includes heating durations, cooling delays, exposure times,
        stabilization delays, and estimated polarizer movement times.
        """
        exposure_s = 1.0
        v_c = 25.0
        a = 25.0
        cal = None
        polarizer = None
        
        # Try to retrieve hardware config from parent (LiveView)
        parent = self.parent()
        if parent and hasattr(parent, 'hw') and parent.hw:
            hw = parent.hw
            cam = hw.get_spectroscopy_camera()
            if cam:
                try:
                    exposure_s = cam.get_exposure()
                except Exception:
                    pass
            pol_config = hw.get_accessory_config('polarizer') or {}
            v_c = pol_config.get('velocity', 25.0)
            a = pol_config.get('acceleration', 25.0)
            cal = hw.polarizer_calibration
            polarizer = hw.polarizer
            
        # Get start/end angles if calibration is available
        base_angle = 0.0
        if cal:
            base_angle = cal.get_angle_for_power(self.meas_power_w) or 0.0
            
        # Helper for polarizer move time estimation
        def get_move_time(from_angle, to_angle):
            if cal is None:
                return 3.0  # default estimate if calibration is unavailable
            delta = abs(from_angle - to_angle)
            if delta < 1e-3:
                return 0.0
            theta_crit = (v_c**2) / a
            if delta > theta_crit:
                return v_c / a + delta / v_c
            else:
                return 2 * (delta / a)**0.5

        total_s = 0.0
        current_angle = base_angle
        if polarizer:
            try:
                current_angle = polarizer.get_position()
            except Exception:
                pass

        # 1. Step 0 (Initial Measurement)
        if not self.should_skip_step_0() and self.start_index <= 1:
            total_s += get_move_time(current_angle, base_angle)
            total_s += 1.0  # stabilization delay after move
            total_s += max(3.0, exposure_s)  # shutter stabilization
            total_s += exposure_s  # camera exposure
            total_s += 0.5  # software/file saving overhead
            current_angle = base_angle

        # 2. Heating & Measurement Loop
        offset = self.start_index if self.start_index > 0 else 1
        for i, step in enumerate(self.steps):
            step_idx = i + offset
            h_power = step.get('target_w', 0.0)
            h_duration = step.get('duration', 0.0)
            
            h_angle = base_angle
            if cal:
                h_angle = cal.get_angle_for_power(h_power) or base_angle
                
            # Phase 1: Move to Heating Power + Heat
            total_s += get_move_time(current_angle, h_angle)
            total_s += 1.0  # stabilization delay after move
            total_s += h_duration  # heating duration
            
            # Phase 2: Move back to Baseline + Cool + Measure
            total_s += get_move_time(h_angle, base_angle)
            total_s += 1.0  # stabilization delay after move
            total_s += self.cooling_delay
            
            # Dynamic background capture every 10 steps
            if step_idx > 0 and step_idx % 10 == 0:
                total_s += 0.5 + exposure_s
                
            total_s += max(3.0, exposure_s)  # shutter stabilization
            total_s += exposure_s  # camera exposure
            total_s += 0.5  # software/file saving overhead
            
            current_angle = base_angle
            
        return total_s

    def _update_time_estimate(self):
        """Calculate and display the new estimated sequence duration."""
        total_seconds = self.calculate_estimated_duration()
        mins = int(total_seconds // 60)
        secs = int(total_seconds % 60)
        if mins > 0:
            time_str = f"{mins}m {secs}s"
        else:
            time_str = f"{secs}s"
        self.est_time_lbl.setText(f"Estimated Total Duration: {time_str}")


class PowerSeriesSummaryDialog(QDialog):
    """
    Dialog to review and confirm a power series sequence before execution.
    """
    def __init__(self, powers_w: List[float], stabilization_delay: float = 2.0, parent=None):
        super().__init__(parent)
        self.powers_w = powers_w
        self.stabilization_delay = stabilization_delay
        self.setWindowTitle("Review Power Series")
        self.resize(500, 450)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Header
        layout.addWidget(QLabel("<b>Power Series Steps</b>"))
        
        # Summary Table
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Step #", "Target Power"])
        h_header = self.table.horizontalHeader()
        if h_header is not None:
            h_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v_header = self.table.verticalHeader()
        if v_header is not None:
            v_header.setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        # Populate table
        for i, target_w in enumerate(self.powers_w):
            row = i
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(i + 1)))
            p_str = format_power_w(target_w)
            self.table.setItem(row, 1, QTableWidgetItem(p_str))

        layout.addWidget(self.table)

        # Info
        info_layout = QVBoxLayout()
        
        # Stabilization Delay Label
        delay_lbl = QLabel(f"<b>Stabilization Delay: {self.stabilization_delay} s</b>")
        delay_lbl.setStyleSheet("color: #d35400;")
        info_layout.addWidget(delay_lbl)
        
        # Estimated time label
        self.est_time_lbl = QLabel()
        self.est_time_lbl.setStyleSheet("color: #2980b9; font-weight: bold;")
        info_layout.addWidget(self.est_time_lbl)
        
        info_lbl = QLabel("Note: Data will be saved to the folder/prefix defined in the main window.\n"
                         "Ensure polarizer calibration is accurate for power target positioning.")
        info_lbl.setStyleSheet("color: gray; font-style: italic;")
        info_lbl.setWordWrap(True)
        info_layout.addWidget(info_lbl)
        
        layout.addLayout(info_layout)

        self._update_time_estimate()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        run_btn = QPushButton("Run Sequence")
        run_btn.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold;")
        run_btn.clicked.connect(self.accept)
        btn_layout.addWidget(run_btn)
        
        layout.addLayout(btn_layout)

    def calculate_estimated_duration(self) -> float:
        """Calculate estimated total duration of power sweep."""
        exposure_s = 1.0
        v_c = 25.0
        a = 25.0
        cal = None
        polarizer = None
        
        parent = self.parent()
        if parent and hasattr(parent, 'hw') and parent.hw:
            hw = parent.hw
            cam = hw.get_spectroscopy_camera()
            if cam:
                try:
                    exposure_s = cam.get_exposure()
                except Exception:
                    pass
            pol_config = hw.get_accessory_config('polarizer') or {}
            v_c = pol_config.get('velocity', 25.0)
            a = pol_config.get('acceleration', 25.0)
            cal = hw.polarizer_calibration
            polarizer = hw.polarizer

        base_angle = 0.0
        current_angle = base_angle
        if polarizer:
            try:
                current_angle = polarizer.get_position()
            except Exception:
                pass

        def get_move_time(from_angle, to_angle):
            if cal is None:
                return 3.0
            delta = abs(from_angle - to_angle)
            if delta < 1e-3:
                return 0.0
            theta_crit = (v_c**2) / a
            if delta > theta_crit:
                return v_c / a + delta / v_c
            else:
                return 2 * (delta / a)**0.5

        total_s = 0.0
        for target_w in self.powers_w:
            target_angle = base_angle
            if cal:
                target_angle = cal.get_angle_for_power(target_w) or base_angle
                
            # Polarizer movement to target power
            total_s += get_move_time(current_angle, target_angle)
            # Stabilization delay
            total_s += self.stabilization_delay
            # Measurement acquisition (shutter open/close + exposure)
            total_s += max(3.0, exposure_s) + exposure_s + 0.5
            
            current_angle = target_angle
            
        return total_s

    def _update_time_estimate(self):
        total_seconds = self.calculate_estimated_duration()
        mins = int(total_seconds // 60)
        secs = int(total_seconds % 60)
        if mins > 0:
            time_str = f"{mins}m {secs}s"
        else:
            time_str = f"{secs}s"
        self.est_time_lbl.setText(f"Estimated Total Duration: {time_str}")


class MappingSummaryDialog(QDialog):
    """
    Dialog to review and confirm an XY Stage Mapping grid before execution.
    """
    def __init__(self, points: List[Tuple[float, float]], stabilization_delay: float = 0.5, parent=None):
        super().__init__(parent)
        self.points = points
        self.stabilization_delay = stabilization_delay
        self.setWindowTitle("Review XY Mapping")
        self.resize(550, 450)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Header
        layout.addWidget(QLabel("<b>XY Mapping Grid Points</b>"))
        
        # Summary Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Point #", "X (mm)", "Y (mm)", "Est. Distance (mm)"])
        h_header = self.table.horizontalHeader()
        if h_header is not None:
            h_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v_header = self.table.verticalHeader()
        if v_header is not None:
            v_header.setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        # Populate table and estimate distance
        last_x, last_y = 0.0, 0.0
        parent = self.parent()
        if parent and hasattr(parent, 'hw') and parent.hw:
            sx = parent.hw.stage_x
            sy = parent.hw.stage_y
            if sx and sx.is_connected() and sy and sy.is_connected():
                try:
                    last_x = sx.get_position()
                    last_y = sy.get_position()
                except Exception:
                    pass

        for i, (x, y) in enumerate(self.points):
            row = i
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(i + 1)))
            self.table.setItem(row, 1, QTableWidgetItem(f"{x:.3f}"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{y:.3f}"))
            
            dist = ((x - last_x)**2 + (y - last_y)**2)**0.5
            dist_str = f"{dist:.3f}" if i > 0 or last_x != 0.0 or last_y != 0.0 else "-"
            self.table.setItem(row, 3, QTableWidgetItem(dist_str))
            last_x, last_y = x, y

        layout.addWidget(self.table)

        # Info
        info_layout = QVBoxLayout()
        
        # Estimated time label
        self.est_time_lbl = QLabel()
        self.est_time_lbl.setStyleSheet("color: #2980b9; font-weight: bold;")
        info_layout.addWidget(self.est_time_lbl)
        
        info_lbl = QLabel("Note: Data will be saved to a subfolder named map_YYYYMMDD_HHMMSS.\n"
                         "For each point, both signal and background frames will be captured.")
        info_lbl.setStyleSheet("color: gray; font-style: italic;")
        info_lbl.setWordWrap(True)
        info_layout.addWidget(info_lbl)
        
        layout.addLayout(info_layout)

        self._update_time_estimate()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        run_btn = QPushButton("Run Mapping")
        run_btn.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold;")
        run_btn.clicked.connect(self.accept)
        btn_layout.addWidget(run_btn)
        
        layout.addLayout(btn_layout)

    def calculate_estimated_duration(self) -> float:
        """Calculate estimated total duration of stage mapping."""
        exposure_s = 1.0
        v_c = 2.4
        a = 4.5
        parent = self.parent()
        
        last_x, last_y = 0.0, 0.0
        if parent and hasattr(parent, 'hw') and parent.hw:
            hw = parent.hw
            cam = hw.get_spectroscopy_camera()
            if cam:
                try:
                    exposure_s = cam.get_exposure()
                except Exception:
                    pass
            cfg_x = hw.get_accessory_config('stage_x') or {}
            v_c = cfg_x.get('velocity', 2.4)
            a = cfg_x.get('acceleration', 4.5)
            
            sx = hw.stage_x
            sy = hw.stage_y
            if sx and sx.is_connected() and sy and sy.is_connected():
                try:
                    last_x = sx.get_position()
                    last_y = sy.get_position()
                except Exception:
                    pass

        def get_move_time(dist):
            if dist < 1e-4:
                return 0.0
            theta_crit = (v_c**2) / a
            if dist > theta_crit:
                return v_c / a + dist / v_c
            else:
                return 2 * (dist / a)**0.5

        total_s = 0.0
        for x, y in self.points:
            dist = ((x - last_x)**2 + (y - last_y)**2)**0.5
            total_s += get_move_time(dist)
            total_s += self.stabilization_delay
            # Background acquisition (shutter closed + exposure)
            total_s += 0.5 + exposure_s
            # Signal acquisition (shutter open + stabilization + exposure)
            total_s += 0.5 + exposure_s
            total_s += 0.5  # overhead
            last_x, last_y = x, y
            
        return total_s

    def _update_time_estimate(self):
        total_seconds = self.calculate_estimated_duration()
        mins = int(total_seconds // 60)
        secs = int(total_seconds % 60)
        if mins > 0:
            time_str = f"{mins}m {secs}s"
        else:
            time_str = f"{secs}s"
        self.est_time_lbl.setText(f"Estimated Total Duration: {time_str}")


class CustomSequenceSummaryDialog(QDialog):
    """
    Dialog to review and confirm a generic custom sequence before execution.
    """
    def __init__(self, steps: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.steps = steps
        self.setWindowTitle("Review Custom Sequence")
        self.resize(600, 500)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Header
        layout.addWidget(QLabel("<b>Custom Sequence Steps</b>"))
        
        # Summary Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Step #", "Action", "Parameters", "Label/Comment"])
        h_header = self.table.horizontalHeader()
        if h_header is not None:
            h_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v_header = self.table.verticalHeader()
        if v_header is not None:
            v_header.setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        # Populate table
        for i, step in enumerate(self.steps):
            row = i
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(i + 1)))
            self.table.setItem(row, 1, QTableWidgetItem(step.get('action', '')))
            self.table.setItem(row, 2, QTableWidgetItem(step.get('params_desc', '')))
            self.table.setItem(row, 3, QTableWidgetItem(step.get('comment', '')))

        layout.addWidget(self.table)

        # Info & Estimated time
        info_layout = QVBoxLayout()
        
        # Estimated time label
        self.est_time_lbl = QLabel()
        self.est_time_lbl.setStyleSheet("color: #2980b9; font-weight: bold;")
        info_layout.addWidget(self.est_time_lbl)
        
        info_lbl = QLabel("Note: Data will be saved to the folder/prefix defined in the main window.\n"
                          "Ensure relevant hardware devices are connected and calibrated if needed.")
        info_lbl.setStyleSheet("color: gray; font-style: italic;")
        info_lbl.setWordWrap(True)
        info_layout.addWidget(info_lbl)
        
        layout.addLayout(info_layout)

        self._update_time_estimate()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        run_btn = QPushButton("Run Sequence")
        run_btn.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold;")
        run_btn.clicked.connect(self.accept)
        btn_layout.addWidget(run_btn)
        
        layout.addLayout(btn_layout)

    def calculate_estimated_duration(self) -> float:
        """Calculate estimated total duration of the custom sequence."""
        exposure_s = 1.0
        v_pol_c = 25.0
        a_pol = 25.0
        v_stage_c = 2.4
        a_stage = 4.5
        cal = None
        
        parent = self.parent()
        if parent and hasattr(parent, 'hw') and parent.hw:
            hw = parent.hw
            cam = hw.get_spectroscopy_camera()
            if cam:
                try:
                    exposure_s = cam.get_exposure()
                except Exception:
                    pass
            # Polarizer
            cfg_pol = hw.get_accessory_config('polarizer') or {}
            v_pol_c = cfg_pol.get('velocity', 25.0)
            a_pol = cfg_pol.get('acceleration', 25.0)
            cal = hw.polarizer_calibration
            
            # Stages
            cfg_stage = hw.get_accessory_config('stage_x') or {}
            v_stage_c = cfg_stage.get('velocity', 2.4)
            a_stage = cfg_stage.get('acceleration', 4.5)

        # Setup baseline states
        curr_pol_angle = 0.0
        curr_stage_x = 0.0
        curr_stage_y = 0.0
        
        # Try to read starting positions
        if parent and hasattr(parent, 'hw') and parent.hw:
            hw = parent.hw
            if hw.polarizer:
                try:
                    curr_pol_angle = hw.polarizer.get_position()
                except Exception:
                    pass
            if hw.stage_x and hw.stage_x.is_connected():
                try:
                    curr_stage_x = hw.stage_x.get_position()
                except Exception:
                    pass
            if hw.stage_y and hw.stage_y.is_connected():
                try:
                    curr_stage_y = hw.stage_y.get_position()
                except Exception:
                    pass

        def get_pol_move_time(from_a, to_a):
            delta = abs(from_a - to_a)
            if delta < 1e-3:
                return 0.0
            theta_c = (v_pol_c**2) / a_pol
            return v_pol_c / a_pol + delta / v_pol_c if delta > theta_c else 2 * (delta / a_pol)**0.5

        def get_stage_move_time(dist):
            if dist < 1e-4:
                return 0.0
            theta_c = (v_stage_c**2) / a_stage
            return v_stage_c / a_stage + dist / v_stage_c if dist > theta_c else 2 * (dist / a_stage)**0.5

        total_s = 0.0
        for step in self.steps:
            action = step.get('action', '')
            params = step.get('params', {})
            
            if action == "Wait / Stabilize":
                total_s += params.get('duration', 0.0)
                
            elif action == "Shutter (linked)":
                total_s += 0.5  # small delay
                
            elif action == "Polarizer Angle":
                target_a = params.get('angle', curr_pol_angle)
                total_s += get_pol_move_time(curr_pol_angle, target_a) + 0.5
                curr_pol_angle = target_a
                
            elif action == "Polarizer Power (calibrated)":
                p_w = params.get('power_w', 0.0)
                target_a = curr_pol_angle
                if cal:
                    target_a = cal.get_angle_for_power(p_w) or curr_pol_angle
                total_s += get_pol_move_time(curr_pol_angle, target_a) + 0.5
                curr_pol_angle = target_a
                
            elif action == "Move Stage X":
                target_x = params.get('position', curr_stage_x)
                dist = abs(target_x - curr_stage_x)
                total_s += get_stage_move_time(dist)
                curr_stage_x = target_x
                
            elif action == "Move Stage Y":
                target_y = params.get('position', curr_stage_y)
                dist = abs(target_y - curr_stage_y)
                total_s += get_stage_move_time(dist)
                curr_stage_y = target_y
                
            elif action == "Collect Spectrum":
                total_s += max(3.0, exposure_s) + exposure_s + 0.5
                
        return total_s

    def _update_time_estimate(self):
        total_seconds = self.calculate_estimated_duration()
        mins = int(total_seconds // 60)
        secs = int(total_seconds % 60)
        if mins > 0:
            time_str = f"{mins}m {secs}s"
        else:
            time_str = f"{secs}s"
        self.est_time_lbl.setText(f"Estimated Total Duration: {time_str}")