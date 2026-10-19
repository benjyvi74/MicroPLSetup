import logging
import time
import threading
import os
import csv
from datetime import datetime
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from ..qt import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QSpinBox, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, Qt, QComboBox,
    QHeaderView, QThread, pyqtSignal, QFileDialog,
    QMessageBox, QTabWidget, QCheckBox, QSplitter, QSizePolicy,
    QtGui, QtCore, QFrame, QTimer, QDialog, QGridLayout, QLineEdit
)

from ..hardware.manager import HardwareManager
from ..core.measurement import MeasurementResult
from ..core.data_manager import DataManager

logger = logging.getLogger(__name__)


def format_power_w(p_w: float) -> str:
    """Format power in Watts to a human-readable string with units and precision."""
    abs_p = abs(p_w)
    if abs_p < 1e-9: # < 1nW
        return f"{p_w*1e12:.2f} pW"
    elif abs_p < 1e-6: # < 1µW
        return f"{p_w*1e9:.2f} nW"
    elif abs_p < 1e-3: # < 1mW
        return f"{p_w*1e6:.2f} µW"
    elif abs_p < 1: # < 1W
        return f"{p_w*1e3:.2f} mW"
    else:
        return f"{p_w:.3f} W"


class LoopParamWidget(QWidget):
    """
    Compact widget to configure loop parameters in the sequence table:
    From step N to step M, repeating X times (total executions).
    """
    valueChanged = pyqtSignal()

    def __init__(self, from_step: int = 1, to_step: int = 1, count: int = 2, max_steps: int = 999, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 1, 4, 1)
        layout.setSpacing(4)

        layout.addWidget(QLabel("From:"))
        self.from_spin = QSpinBox()
        self.from_spin.setRange(1, max(1, max_steps))
        self.from_spin.setValue(max(1, from_step))
        self.from_spin.setToolTip("Starting step number of the loop")
        layout.addWidget(self.from_spin)

        layout.addWidget(QLabel("To:"))
        self.to_spin = QSpinBox()
        self.to_spin.setRange(1, max(1, max_steps))
        self.to_spin.setValue(max(1, to_step))
        self.to_spin.setToolTip("Ending step number of the loop")
        layout.addWidget(self.to_spin)

        layout.addWidget(QLabel("Count:"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 9999)
        self.count_spin.setValue(max(1, count))
        self.count_spin.setSuffix("x")
        self.count_spin.setToolTip("Total number of times these steps will be executed")
        layout.addWidget(self.count_spin)

        self.from_spin.valueChanged.connect(self._on_change)
        self.to_spin.valueChanged.connect(self._on_change)
        self.count_spin.valueChanged.connect(self._on_change)

    def _on_change(self):
        self.valueChanged.emit()

    def get_values(self) -> Tuple[int, int, int]:
        return self.from_spin.value(), self.to_spin.value(), self.count_spin.value()

    def set_values(self, from_step: int, to_step: int, count: int):
        self.from_spin.blockSignals(True)
        self.to_spin.blockSignals(True)
        self.count_spin.blockSignals(True)
        self.from_spin.setValue(max(1, from_step))
        self.to_spin.setValue(max(1, to_step))
        self.count_spin.setValue(max(1, count))
        self.from_spin.blockSignals(False)
        self.to_spin.blockSignals(False)
        self.count_spin.blockSignals(False)

    def set_max_steps(self, max_steps: int):
        m = max(1, max_steps)
        self.from_spin.setMaximum(m)
        self.to_spin.setMaximum(m)


def unroll_custom_sequence(steps: List[Dict[str, Any]], max_total_steps: int = 10000) -> List[Dict[str, Any]]:
    """
    Unroll / expand a custom sequence containing 'Repeat / Loop' steps into a
    flat list of executable steps.
    
    Each step in the unrolled list contains:
      - 'action': action string
      - 'params': action parameters dict
      - 'params_desc': formatted description
      - 'comment': label/comment
      - 'orig_step_num': 1-based original index from the table
      - 'loop_iteration': 1-based loop iteration number for this step
      - 'total_iterations': total executions configured for the loop (1 if not in a loop)
    """
    import copy
    if not steps:
        return []

    # Map step_num (1-based) to its total iterations across all loops that include it
    step_total_iters: Dict[int, int] = {i + 1: 1 for i in range(len(steps))}
    for idx, s in enumerate(steps):
        if s.get('action') == "Repeat / Loop":
            params = s.get('params', {})
            cnt = max(1, int(params.get('count', 1)))
            f_s = min(int(params.get('from_step', 1)), int(params.get('to_step', 1)))
            t_s = max(int(params.get('from_step', 1)), int(params.get('to_step', 1)))
            f_s = max(1, min(f_s, len(steps)))
            t_s = max(f_s, min(t_s, idx + 1))
            for st in range(f_s, t_s + 1):
                step_total_iters[st] = max(step_total_iters.get(st, 1), cnt)

    unrolled: List[Dict[str, Any]] = []
    current_iter: Dict[int, int] = {i + 1: 1 for i in range(len(steps))}
    loop_triggered: Dict[int, int] = {i + 1: 0 for i in range(len(steps))}

    pc = 0
    total_executed = 0

    while pc < len(steps) and total_executed < max_total_steps:
        s = steps[pc]
        step_num = pc + 1
        action = s.get('action', '')

        if action == "Repeat / Loop":
            params = s.get('params', {})
            target_count = max(1, int(params.get('count', 1)))
            f_s = min(int(params.get('from_step', 1)), int(params.get('to_step', 1)))
            t_s = max(int(params.get('from_step', 1)), int(params.get('to_step', 1)))
            f_s = max(1, min(f_s, len(steps)))
            t_s = max(f_s, min(t_s, step_num))

            # Initial pass was 1. Additional passes triggered by this loop = loop_triggered[step_num].
            if loop_triggered[step_num] < (target_count - 1):
                loop_triggered[step_num] += 1
                # Reset inner loop triggers if any inside [f_s, t_s]
                for inner_idx in range(f_s, t_s + 1):
                    if steps[inner_idx - 1].get('action') == "Repeat / Loop" and inner_idx != step_num:
                        loop_triggered[inner_idx] = 0
                # Jump back to start of loop block
                pc = f_s - 1
                continue
            else:
                # Loop completed, proceed forward
                pc += 1
                continue
        else:
            iter_num = current_iter[step_num]
            total_iters = step_total_iters.get(step_num, 1)
            
            step_copy = copy.deepcopy(s)
            step_copy['orig_step_num'] = step_num
            step_copy['loop_iteration'] = iter_num
            step_copy['total_iterations'] = total_iters

            unrolled.append(step_copy)
            current_iter[step_num] += 1
            total_executed += 1
            pc += 1

    return unrolled


class NumericTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem that sorts numerically instead of alphabetically when possible."""
    def __lt__(self, other: QTableWidgetItem) -> bool:
        try:
            return float(self.text()) < float(other.text())
        except ValueError:
            return super().__lt__(other)


class ReorderableTableWidget(QTableWidget):
    """
    A QTableWidget subclass that supports drag-and-drop row reordering,
    preserving custom cell widgets.
    """
    order_changed = pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        vp = self.viewport()
        if vp is not None:
            vp.setAcceptDrops(True)
        self.setDragDropOverwriteMode(False)
        self.setDragDropMode(QTableWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)

    def showEvent(self, event):
        super().showEvent(event)
        vp = self.viewport()
        if vp is not None:
            vp.setAcceptDrops(True)

    def dropEvent(self, event):
        if event.source() != self:
            event.ignore()
            return
            
        selected_rows = sorted(list(set(index.row() for index in self.selectedIndexes())))
        if not selected_rows:
            event.ignore()
            return
            
        pos = event.position()
        target_row = self.rowAt(int(pos.y()))
        
        if target_row == -1:
            target_row = self.rowCount()
        else:
            # If dropped on the bottom half of the row, insert after it
            row_y = self.rowViewportPosition(target_row)
            row_height = self.rowHeight(target_row)
            if pos.y() > row_y + row_height / 2:
                target_row += 1
            
        event.setDropAction(Qt.DropAction.IgnoreAction)
        event.accept()
        
        # Defer move_rows to prevent crashes from modifying the table
        # while the drag-and-drop operation is still active.
        QTimer.singleShot(0, lambda: self.move_rows(selected_rows, target_row))

    def move_rows(self, source_rows: List[int], target_row: int):
        was_sorting = self.isSortingEnabled()
        self.setSortingEnabled(False)
        self.blockSignals(True)
        
        source_rows = sorted(list(set(source_rows)))
        if not source_rows:
            self.blockSignals(False)
            self.setSortingEnabled(was_sorting)
            return

        # 1. Store the items and clone widgets of the rows to be moved
        moved_data = []
        for r in source_rows:
            row_cols = []
            for c in range(self.columnCount()):
                item = self.item(r, c)
                cloned_item = QTableWidgetItem(item) if item is not None else None
                
                widget = self.cellWidget(r, c)
                cloned_widget = None
                if widget is not None:
                    if isinstance(widget, QComboBox):
                        cloned_widget = QComboBox()
                        for i in range(widget.count()):
                            cloned_widget.addItem(widget.itemText(i), widget.itemData(i))
                        cloned_widget.setCurrentIndex(widget.currentIndex())
                        # Reconnect signal if it is custom_seq_table column 1
                        if self == getattr(self.parent(), 'custom_seq_table', None) and c == 1:
                            panel = self.parent()
                            if hasattr(panel, '_on_custom_action_changed'):
                                cloned_widget.currentIndexChanged.connect(panel._on_custom_action_changed)
                    elif isinstance(widget, QDoubleSpinBox):
                        cloned_widget = QDoubleSpinBox()
                        cloned_widget.setRange(widget.minimum(), widget.maximum())
                        cloned_widget.setValue(widget.value())
                        cloned_widget.setSuffix(widget.suffix())
                        cloned_widget.setDecimals(widget.decimals())
                        cloned_widget.setSingleStep(widget.singleStep())
                    elif isinstance(widget, QSpinBox):
                        cloned_widget = QSpinBox()
                        cloned_widget.setRange(widget.minimum(), widget.maximum())
                        cloned_widget.setValue(widget.value())
                        cloned_widget.setSuffix(widget.suffix())
                        cloned_widget.setSingleStep(widget.singleStep())
                    elif isinstance(widget, QLabel):
                        cloned_widget = QLabel(widget.text())
                        cloned_widget.setStyleSheet(widget.styleSheet())
                    elif isinstance(widget, QLineEdit):
                        cloned_widget = QLineEdit(widget.text())
                        cloned_widget.setPlaceholderText(widget.placeholderText())
                    elif isinstance(widget, LoopParamWidget):
                        from_s, to_s, cnt = widget.get_values()
                        cloned_widget = LoopParamWidget(from_s, to_s, cnt, max_steps=widget.to_spin.maximum())
                        
                row_cols.append((cloned_item, cloned_widget))
            moved_data.append(row_cols)

        # 2. Remove the source rows from the table in reverse order
        for r in reversed(source_rows):
            self.removeRow(r)

        # 3. Calculate the new target row index in the updated table
        num_removed_before_target = sum(1 for r in source_rows if r < target_row)
        new_target = target_row - num_removed_before_target
        new_target = max(0, min(new_target, self.rowCount()))

        # 4. Insert new rows at the new target and restore items/widgets
        for i, row_cols in enumerate(moved_data):
            insert_idx = new_target + i
            self.insertRow(insert_idx)
            for c, (item, widget) in enumerate(row_cols):
                if item is not None:
                    self.setItem(insert_idx, c, item)
                if widget is not None:
                    self.setCellWidget(insert_idx, c, widget)

        self.blockSignals(False)
        self.order_changed.emit()
        self.setSortingEnabled(was_sorting)



def acquire_spectrum_synchronized(cam, hw) -> np.ndarray:

    """
    Acquire a spectrum from the camera. If Live View is active, synchronize
    with the background service to fetch a live frame instead of calling
    acquire_spectrum directly (which would fail/conflict).
    """
    exposure_time = cam.get_exposure()
    spec_cam_id = hw.get_spectroscopy_camera_id()
    if cam.is_acquiring() and hasattr(hw, 'service') and hw.service and spec_cam_id:
        frame_ready_event = threading.Event()
        captured_frame: Optional[np.ndarray] = None

        def on_frame(camera_id, data):
            if camera_id == spec_cam_id:
                nonlocal captured_frame
                captured_frame = data
                frame_ready_event.set()

        # Connect temporarily to the service signal
        # Use DirectConnection because on_frame is thread-safe (just sets event)
        hw.service.camera_frame_ready.connect(on_frame, Qt.ConnectionType.DirectConnection)
        
        try:
            # Synchronization with Live View
            # Wait long enough for exposure + overhead
            timeout = (exposure_time * 3.0) + 2.0 
            
            # Wait for 1-2 frames to ensure the new state (shutter open/closed) is captured
            # (First frame might have started BEFORE shutter state was changed)
            if frame_ready_event.wait(timeout):
                frame_ready_event.clear()
                if frame_ready_event.wait(timeout):
                    assert captured_frame is not None
                    return captured_frame
                else:
                    logger.warning(f"Live capture (2nd frame) timed out after {timeout}s")
            else:
                logger.warning(f"Live capture (1st frame) timed out after {timeout}s")
        finally:
            hw.service.camera_frame_ready.disconnect(on_frame)
            
    # Fallback to direct acquisition
    return cam.acquire_spectrum()


class CalibrationSweepWorker(QThread):
    """
    Background worker to sequentially calibrate multiple power target points.
    """
    # row_index, success, angle, power, message
    point_finished = pyqtSignal(int, bool, float, float, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, hardware_manager, points_to_calibrate: list):
        super().__init__()
        self.hw = hardware_manager
        self.points = points_to_calibrate # List of (index, target_w)
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        polarizer = self.hw.polarizer
        pm = self.hw.get_instrument('pm100')

        if not polarizer or not polarizer.is_connected():
            self.finished.emit(False, "Polarizer not connected")
            return
        if not pm or not pm.is_connected():
            self.finished.emit(False, "Power meter not connected")
            return

        logger.info(f"Starting polarizer calibration sweep for {len(self.points)} points")

        for idx, target_w in self.points:
            if not self._running:
                break

            try:
                # Reuse the seeker logic here
                success, angle, measured_p = self._seek_single(target_w)
                self.point_finished.emit(idx, success, angle, measured_p, "" if success else "Failed")
            except Exception as e:
                logger.error(f"Error calibrating point {idx}: {e}")
                self.point_finished.emit(idx, False, 0, 0, str(e))

        if not self._running:
            self.finished.emit(False, "Calibration stopped by user")
        else:
            self.finished.emit(True, "Calibration sweep complete")

    def _seek_single(self, target_w):
        """Internal seek logic similar to PowerSeeker."""
        polarizer = self.hw.polarizer
        pm = self.hw.get_instrument('pm100')
        
        tolerance = 0.015 # Slightly wider tolerance for auto-sweep
        min_step = 0.05
        
        current_p = pm.read_power()
        error = abs(current_p - target_w)
        direction = 1
        step_size = 3.0 # Slightly larger initial step for faster sweep
        
        # Limit total iterations per point to avoid infinite loops
        max_iters = 50
        iters = 0
        
        while self._running and error > (target_w * tolerance) and iters < max_iters:
            iters += 1
            polarizer.move_by(direction * step_size)
            
            time.sleep(0.3)
            while polarizer.is_moving() and self._running:
                time.sleep(0.1)
                
            new_p = pm.read_power()
            new_error = abs(new_p - target_w)
            
            if new_error > error:
                direction *= -1
                step_size *= 0.6
            
            error = new_error
            if step_size < min_step:
                break
                
        return True, polarizer.get_position(), pm.read_power()



class LaserHeatingWorker(QThread):
    """
    Background worker to execute a laser heating sequence.
    Alternates between heating steps and PL measurements.
    """
    # step_index, status_text, progress_percent
    progress = pyqtSignal(int, str, int)
    # x_axis, y_axis, label (for plotting and history)
    measurement_ready = pyqtSignal(np.ndarray, np.ndarray, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, hardware_manager, meas_power_w: float, steps: List[Dict[str, Any]], 
                 data_dir: str, metadata: Dict[str, Any], 
                 skip_step_0: bool = False, background: Optional[np.ndarray] = None,
                 background_exposure: Optional[float] = None,
                 processing_mode: str = "Raw Data",
                 cooling_delay: float = 1.0,
                 start_index: int = 1):
        """
        Worker thread for executing automated laser heating sequences.
        
        Args:
            meas_power_w: Power used for the PL measurement phase (reference power).
            steps: List of dictionaries containing 'target_w' (heating power) and 'duration'.
            data_dir: Root directory for saving measurement files.
            skip_step_0: If True, skips the initial baseline measurement.
            cooling_delay: Time to wait after heating before starting the PL acquisition.
        """
        super().__init__()
        self.hw = hardware_manager
        self.meas_power_w = meas_power_w
        self.steps = steps
        self.data_dir = data_dir
        self.metadata = metadata
        self.skip_step_0 = skip_step_0
        self.background = background
        self.background_exposure = background_exposure # In ms from UI
        self.processing_mode = processing_mode
        self.cooling_delay = cooling_delay
        self.start_index = start_index 
        self._running = True
        self._pause_event = threading.Event()
        self._pause_event.set()
        logger.info(f"Worker initialized with cooling_delay={self.cooling_delay}s")

    def _calculate_move_time(self, delta_theta: float, v_c: float = 25.0, a: float = 25.0) -> float:
        """
        Calculate polarizer move time using a trapezoidal/triangular motion kinematics model.
        
        This is used to accurately estimate the remaining time of complex heating sequences
        without actually executing hardware moves.
        
        Args:
            delta_theta: Angular distance to move in degrees.
            v_c: Cruise velocity (max velocity) in deg/s.
            a: Acceleration in deg/s^2.
        """
        delta_theta = abs(delta_theta)
        if delta_theta < 1e-3:
            return 0.0
            
        theta_crit = (v_c**2) / a
        
        if delta_theta > theta_crit:
            # Regime 1: Trapezoidal (Acc + Cruise + Dec)
            return v_c / a + delta_theta / v_c
        else:
            # Regime 2: Triangular (Acc + Dec)
            return 2 * np.sqrt(delta_theta / a)

    def _estimate_remaining_time(self, current_step_idx: int, phase: str, start_time: float) -> str:
        """Estimate time remaining in the sequence."""
        polarizer = self.hw.polarizer
        cal = self.hw.polarizer_calibration
        
        # Get velocity and acceleration for move time estimation
        pol_config = self.hw.get_accessory_config('polarizer') or {}
        v_c = pol_config.get('velocity', 25.0)
        a = pol_config.get('acceleration', 25.0)
        
        # 1. Total remaining scheduled durations
        total_remaining = 0.0
        
        # Determine remaining steps (from current_step_idx to end)
        remaining_steps = []
        if current_step_idx == 0 and not self.skip_step_0:
            remaining_steps = [(-1, self.meas_power_w, 0.0)] + [(i, s['target_w'], s['duration']) for i, s in enumerate(self.steps)]
        else:
            # offset of starting steps
            offset = self.start_index if self.start_index > 0 else 1
            idx_in_list = current_step_idx - offset
            if idx_in_list < 0: idx_in_list = 0
            remaining_steps = [(i, s['target_w'], s['duration']) for i, s in enumerate(self.steps[idx_in_list:])]

        # Exposure time and stabilization
        cam = self.hw.get_spectroscopy_camera()
        exposure_s = cam.get_exposure() if cam else 1.0
        stab_delay = max(3.0, exposure_s)
        
        # Baseline angle
        base_angle = cal.get_angle_for_power(self.meas_power_w) or 0.0
        current_angle = polarizer.get_position() if polarizer else base_angle
        
        for i, h_power, h_dur in remaining_steps:
            h_angle = cal.get_angle_for_power(h_power) or base_angle
            
            # Phase 1: Move to Heating Power + Heat
            if i == -1: # Step 0
                dt_h = abs(base_angle - current_angle) if i == 0 else 0 
                total_remaining += self._calculate_move_time(dt_h, v_c, a) + 1.0 # set_power stabilization
            else:
                dt_h = abs(h_angle - base_angle)
                total_remaining += self._calculate_move_time(dt_h, v_c, a) + 1.0 + h_dur 
            
            # Phase 2: Move to Base + Cool + Meas
            dt_m = abs(base_angle - h_angle)
            total_remaining += self._calculate_move_time(dt_m, v_c, a) + 1.0 + self.cooling_delay + stab_delay + exposure_s + 0.5 # overhead

        # 2. Subtract elapsed time in current phase if applicable
        # (Simplified: just show total remaining from current state)
        elapsed = time.time() - start_time
        etr_s = max(0, total_remaining - elapsed)
        
        mins = int(etr_s // 60)
        secs = int(etr_s % 60)
        return f"{mins:02d}:{secs:02d}"

    def stop(self):
        self._running = False
        self._pause_event.set()

    def pause(self):
        self._pause_event.clear()

    def resume(self):
        self._pause_event.set()

    def run(self):
        try:
            self._execute_sequence()
        except Exception as e:
            logger.error(f"Sequence execution failed: {e}")
            self.finished.emit(False, str(e))

    def _execute_sequence(self):
        """
        Core orchestration logic for the heating + PL measurement loop.
        
        Workflow for each step:
        1. Heating Phase: Move polarizer to achieve 'h_power', open shutter for 'h_duration'.
        2. Move to Baseline: Move polarizer back to 'meas_power_w' and close shutter.
        3. Cooling/Thermalization: Wait for 'cooling_delay' to let the sample stabilize.
        4. Acquisition: Open shutter, acquire spectrum from Andor, close shutter.
        5. Data Processing: Apply background subtraction and wavelength calibration.
        6. Persistence: Save to CSV and emit signal to the GUI for real-time plotting.
        """
        polarizer = self.hw.polarizer
        shutter = self.hw.shutter
        cam = self.hw.get_spectroscopy_camera()
        cal = self.hw.polarizer_calibration

        # 1. Validation
        if not polarizer or not polarizer.is_connected():
            raise RuntimeError("Polarizer (KDC101) not connected")
        if not cam or not cam.is_connected():
            raise RuntimeError("Spectrometer camera not connected")
        if not cal.points:
            raise RuntimeError("Polarizer calibration is empty. Please calibrate or load one first.")

        # 2. Preparation
        os.makedirs(self.data_dir, exist_ok=True)
        # Total phases depends on whether we skip step 0
        total_steps = len(self.steps) + (0 if self.skip_step_0 else 1)
        total_phases = total_steps * 2 # Heat + Meas (Step 0 "heats" to baseline)
        current_phase = 0

        # Helper to set power via polarizer
        def set_power(target_w, label, step_idx):
            angle = cal.get_angle_for_power(target_w)
            if angle is None:
                p_str = format_power_w(target_w)
                raise ValueError(f"Target power {p_str} outside calibration range")
            
            p_str = format_power_w(target_w)
            status = f"Moving for {label} to {p_str} ({angle:.2f}°)" if label else "Moving"
            self.progress.emit(-1, status, 0)
            
            if shutter: shutter.set_shutter(False, channel=self.hw.shutter_channel) # Safety first
            polarizer.move_to(angle)
            while polarizer.is_moving() and self._running:
                self._pause_event.wait()
                time.sleep(0.1)
            if not self._running: return False
            self._pause_event.wait()
            time.sleep(1.0) # Stabilization
            return True

        # Helper to acquire and save data for a single step
        def measure(step_name, step_meta, step_idx):
            self.progress.emit(-1, "Measuring spectrum", 0)
            if shutter: shutter.set_shutter(True, channel=self.hw.shutter_channel)
            
            # 1. ACQUISITION
            # Get the exposure time from the camera to determine wait duration
            exposure_time = cam.get_exposure()
            
            # Wait for the shutter to open and sensor to initialize
            # We wait for 3s or the exposure time, whichever is longer, to be safe
            stab_delay = max(3.0, exposure_time)
            time.sleep(stab_delay) 
            
            # Determine the spectral axis (Wavelengths or Pixels)
            x_axis = self.hw.get_wavelength_axis()
            if x_axis is None:
                det_size = cam.get_info().get('detector_size', (1024, 256))
                x_axis = np.arange(det_size[0])
            
            # Acquire spectrum, synchronizing with Live View if active
            raw_data = acquire_spectrum_synchronized(cam, self.hw)
            
            # Ensure data is 1D for spectrum saving
            if raw_data.ndim == 2:
                logger.debug(f"Collapsing 2D frame {raw_data.shape} to 1D spectrum")
                raw_data = np.sum(raw_data, axis=0)
            
            if shutter: shutter.set_shutter(False, channel=self.hw.shutter_channel)
            
            # 2. Process Data (Background Correction + Time Normalization)
            # Use the unified processing logic from HardwareManager
            
            # Create a full MeasurementResult to leverage centralized processing and DataManager
            result = MeasurementResult(
                timestamp=datetime.now(),
                integration_time=exposure_time,
                metadata=step_meta, # step_meta will be merged below
                wavelengths=x_axis,
                intensities=raw_data,
                background=self.background,
                background_exposure=(self.background_exposure / 1000.0) if self.background_exposure else None
            )
            
            # Apply selected processing (synced via HardwareManager)
            result.process(self.processing_mode)
            
            processed_data = result.intensities
            
            # 3. Save
            # Combine base metadata with step-specific metadata
            full_meta = self.metadata.copy()
            
            # Ensure step-specific metadata (like laser power if changed) 
            # is merged into the 'Laser' group if it belongs there
            if 'Laser' in step_meta:
                 if 'Laser' not in full_meta:
                     full_meta['Laser'] = {}
                 full_meta['Laser'].update(step_meta['Laser'])
            elif 'laser' in step_meta:
                 if 'Laser' not in full_meta:
                     full_meta['Laser'] = {}
                 full_meta['Laser'].update(step_meta['laser'])
            else:
                 # Check for flat keys that should be in Laser
                 laser_keys = ['Excitation Power (W)', 'Wavelength (nm)', 'Mode']
                 for k in laser_keys:
                     if k in step_meta:
                          if 'Laser' not in full_meta:
                              full_meta['Laser'] = {}
                          full_meta['Laser'][k] = step_meta[k]
                  
            # Merge remaining step_meta
            for k, v in step_meta.items():
                if k not in ['Laser', 'laser'] and k not in ['Excitation Power (W)', 'Wavelength (nm)', 'Mode']:
                    full_meta[k] = v
            
            # Add processing info to metadata
            full_meta['Processing'] = result.metadata.get('Processing', 'Raw')
            result.metadata = full_meta # Finalize metadata in result object
            
            # Use DataManager for the unified format
            dm = DataManager(data_root=self.data_dir)
            fname = f"{step_name}.csv"
            save_path = os.path.join(self.data_dir, fname)
            
            dm.save_spectrum(result, save_path)
            
            # Emit for GUI plotting
            self.measurement_ready.emit(x_axis, processed_data, step_name)
            return True

        # --- STEP 0: INITIAL MEASUREMENT ---
        if not self.skip_step_0 and self.start_index <= 0:
            self.progress.emit(0, "Measuring initial baseline", 0)
            if not set_power(self.meas_power_w, "Step 0 (Initial)", 0): return
            
            meta_0 = {
                'Step': {
                    'Step Type': 'Baseline',
                    'Sequence Step Number': 0
                },
                'Laser': {
                    'Excitation Power (W)': self.meas_power_w
                }
            }
            # Step 0 filename matching the pattern: P=0mW (heating power), t=0s
            if not measure("step_000_P_0,0mW_t_0s", meta_0, 0): return
            current_phase += 2
        
        # --- LOOP STEPS ---
        offset = self.start_index if self.start_index > 0 else 1
        for i, step in enumerate(self.steps):
            self._pause_event.wait()
            if not self._running: break
            
            step_idx = i + offset
            h_power = step['target_w']
            h_duration = step['duration']
            
            # 1. Heating Phase
            percent = int((current_phase / total_phases) * 100)
            if not set_power(h_power, f"Heating {step_idx}", step_idx): break
            
            p_str = format_power_w(h_power)
            self.progress.emit(step_idx, f"Heating at {p_str} for {h_duration}s", percent)
            
            if shutter: shutter.set_shutter(True, channel=self.hw.shutter_channel)
            # Timed sleep
            end_time = time.time() + h_duration
            while time.time() < end_time and self._running:
                self._pause_event.wait()
                time.sleep(0.1)
            if shutter: shutter.set_shutter(False, channel=self.hw.shutter_channel)
            current_phase += 1
            if not self._running: break

            # 2. Measurement Phase
            percent = int((current_phase / total_phases) * 100)
            # set_power will emit its own "Moving for Measure X..." status
            if not set_power(self.meas_power_w, f"Measure {step_idx}", step_idx): break
            
            # Every 10 steps, capture a new background with shutter closed
            if step_idx > 0 and step_idx % 10 == 0:
                self.progress.emit(step_idx, f"Updating Background (Step {step_idx})", percent)
                if shutter and shutter.is_connected():
                    shutter.set_shutter(False, channel=self.hw.shutter_channel)
                    time.sleep(0.5) # Wait for shutter to close / stabilize
                
                exposure_time = cam.get_exposure()
                bg_data = acquire_spectrum_synchronized(cam, self.hw)
                if bg_data.ndim == 2:
                    bg_data = np.sum(bg_data, axis=0)
                
                self.background = bg_data
                self.background_exposure = exposure_time * 1000.0 # in ms
                logger.info(f"Background dynamically updated at step {step_idx} with exposure {exposure_time}s")
            
            # Open shutter for Live View observation during cooling
            if shutter: shutter.set_shutter(True, channel=self.hw.shutter_channel)

            # --- THERMALIZATION / COOLING DELAY ---
            if self.cooling_delay > 0:
                self.progress.emit(step_idx, f"Cooling for {self.cooling_delay}s", percent)
                end_cooling = time.time() + self.cooling_delay
                while time.time() < end_cooling and self._running:
                    self._pause_event.wait()
                    time.sleep(0.5)
                if not self._running: break

            p_str = format_power_w(h_power)
            meta_step = {
                'Step': {
                    'Step Type': 'Laser Heating Cycle',
                    'Sequence Step Number': step_idx,
                    'Heating Power (W)': h_power,
                    'Heating Duration (s)': h_duration
                },
                'Laser': {
                    'Excitation Power (W)': self.meas_power_w
                }
            }
            # Filename-friendly power string (no spaces, units: mW, µW, nW, comma decimal)
            if h_power < 1e-6: # < 1µW
                p_file = f"{h_power*1e9:.1f}nW".replace(".", ",")
            elif h_power < 1e-3: # < 1mW
                p_file = f"{h_power*1e6:.1f}uW".replace(".", ",")
            else:
                p_file = f"{h_power*1e3:.2f}mW".replace(".", ",")
            
            # Format duration with comma if it's float
            dur_str = f"{h_duration}".replace(".", ",")
            step_name = f"step_{step_idx:03d}_P_{p_file}_t_{dur_str}s"
            
            if not measure(step_name, meta_step, step_idx): break
            current_phase += 1

        if not self._running:
            if shutter: shutter.set_shutter(False, channel=self.hw.shutter_channel)
            self.finished.emit(False, "Sequence aborted by user")
        else:
            # Leave shutter OPEN after successful completion as requested
            if shutter: shutter.set_shutter(True, channel=self.hw.shutter_channel)
            
            # Emit the correct final absolute step index
            offset = self.start_index if self.start_index > 0 else 1
            last_idx = (len(self.steps) - 1) + offset if len(self.steps) > 0 else 0
            
            self.progress.emit(last_idx, "Status: Complete", 100)
            self.finished.emit(True, f"Successfully completed sequence. Data saved to {self.data_dir}")



class MappingWorker(QThread):
    """
    Background worker for XY Stage Mapping.
    Iterates through a list of points, moves stage, and acquires spectra.
    """
    # step_idx, status_text, progress_percent
    progress = pyqtSignal(int, str, int)
    # x_axis, y_axis, label
    measurement_ready = pyqtSignal(np.ndarray, np.ndarray, str)
    # success, message
    finished = pyqtSignal(bool, str)

    def __init__(self, hardware_manager, 
                 points: List[Tuple[float, float]],
                 data_dir, metadata: Dict[str, Any],
                 background: Optional[np.ndarray] = None,
                 background_exposure: Optional[float] = None,
                 processing_mode: str = "Raw Data",
                 stabilization_delay: float = 0.5):
        super().__init__()
        self.hw = hardware_manager
        self.points = points
        self.data_dir = data_dir
        self.metadata = metadata
        self.background = background
        self.background_exposure = background_exposure
        self.processing_mode = processing_mode
        self.stabilization_delay = stabilization_delay
        self._running = True
        self._pause_event = threading.Event()
        self._pause_event.set()

    def stop(self):
        self._running = False
        self._pause_event.set()

    def pause(self):
        self._pause_event.clear()

    def resume(self):
        self._pause_event.set()

    def run(self):
        try:
            self._execute_mapping()
        except Exception as e:
            logger.error(f"Mapping failed: {e}")
            self.finished.emit(False, str(e))

    def _execute_mapping(self):
        sx = self.hw.stage_x
        sy = self.hw.stage_y
        cam = self.hw.get_spectroscopy_camera()
        shutter = self.hw.shutter

        if not sx or not sx.is_connected(): raise RuntimeError("Stage X not connected")
        if not sy or not sy.is_connected(): raise RuntimeError("Stage Y not connected")
        if not cam or not cam.is_connected(): raise RuntimeError("Camera not connected")

        os.makedirs(self.data_dir, exist_ok=True)
        total_points = len(self.points)
        current_point = 0

        for x, y in self.points:
            self._pause_event.wait()
            if not self._running: break
            current_point += 1
            percent = int((current_point / total_points) * 100)
            
            status = f"Moving to ({x:.3f}, {y:.3f})"
            self.progress.emit(current_point, status, percent)
            
            # 1. Move axes
            sx.move_to(x)
            sy.move_to(y)
            while (sx.is_moving() or sy.is_moving()) and self._running:
                self._pause_event.wait()
                time.sleep(0.05)
            
            if not self._running: break
            self._pause_event.wait()
            time.sleep(self.stabilization_delay)
            
            # 2. Acquire Background
            self.progress.emit(current_point, f"BG ({x:.3f}, {y:.3f})", percent)
            if shutter and shutter.is_connected():
                shutter.set_shutter(False, channel=self.hw.shutter_channel)
                time.sleep(0.5) # Wait for shutter
            
            exposure_time = cam.get_exposure()
            x_axis = self.hw.get_wavelength_axis()
            if x_axis is None:
                det_size = cam.get_info().get('detector_size', (1024, 256))
                x_axis = np.arange(det_size[0])
            
            bg_data = acquire_spectrum_synchronized(cam, self.hw)
            if bg_data.ndim == 2:
                bg_data = np.sum(bg_data, axis=0)
            
            # 3. Acquire Signal
            self.progress.emit(current_point, f"Signal ({x:.3f}, {y:.3f})", percent)
            if shutter and shutter.is_connected():
                shutter.set_shutter(True, channel=self.hw.shutter_channel)
                time.sleep(0.5)
            
            raw_data = acquire_spectrum_synchronized(cam, self.hw)
            if raw_data.ndim == 2:
                raw_data = np.sum(raw_data, axis=0)
            
            if shutter and shutter.is_connected():
                shutter.set_shutter(False, channel=self.hw.shutter_channel) # Close after point
            
            # 4. Save
            result = MeasurementResult(
                timestamp=datetime.now(),
                integration_time=exposure_time,
                metadata=self.metadata.copy(),
                wavelengths=x_axis,
                intensities=raw_data,
                background=bg_data,
                background_exposure=exposure_time
            )
            result.process(self.processing_mode)
            
            result.metadata['Step'] = {
                'Step Type': 'XY Mapping',
                'X Position (mm)': x,
                'Y Position (mm)': y,
                'Point Index': current_point
            }
            
            # Safe filename (no dots)
            x_str = f"{x:.3f}".replace(".", "_")
            y_str = f"{y:.3f}".replace(".", "_")
            step_name = f"map_idx_{current_point:03d}_X_{x_str}_Y_{y_str}"
            save_path = os.path.join(self.data_dir, f"{step_name}.csv")
            
            dm = DataManager(data_root=self.data_dir)
            dm.save_spectrum(result, save_path)
            
            self.measurement_ready.emit(x_axis, result.intensities, step_name)

        if not self._running:
            self.finished.emit(False, "Mapping aborted")
        else:
            self.progress.emit(total_points, "Complete", 100)
            self.finished.emit(True, f"Mapping complete. Data saved to {self.data_dir}")


class PowerSeriesWorker(QThread):
    """
    Background worker to execute a power sweep sequence.
    Sets the polarizer to each target power and acquires a spectrum.
    """
    # step_index, status_text, progress_percent
    progress = pyqtSignal(int, str, int)
    # x_axis, y_axis, label
    measurement_ready = pyqtSignal(np.ndarray, np.ndarray, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, hardware_manager, powers_w: List[float], 
                 data_dir: str, metadata: Dict[str, Any], 
                 background: Optional[np.ndarray] = None,
                 background_exposure: Optional[float] = None,
                 processing_mode: str = "Raw Data",
                 stabilization_delay: float = 2.0):
        super().__init__()
        self.hw = hardware_manager
        self.powers_w = powers_w
        self.data_dir = data_dir
        self.metadata = metadata
        self.background = background
        self.background_exposure = background_exposure
        self.processing_mode = processing_mode
        self.stabilization_delay = stabilization_delay
        self._running = True
        self._pause_event = threading.Event()
        self._pause_event.set()

    def stop(self):
        self._running = False
        self._pause_event.set()

    def pause(self):
        self._pause_event.clear()

    def resume(self):
        self._pause_event.set()

    def run(self):
        try:
            self._execute_sequence()
        except Exception as e:
            logger.error(f"Power sequence execution failed: {e}")
            self.finished.emit(False, str(e))

    def _execute_sequence(self):
        polarizer = self.hw.polarizer
        shutter = self.hw.shutter
        cam = self.hw.get_spectroscopy_camera()
        cal = self.hw.polarizer_calibration

        if not polarizer or not polarizer.is_connected():
            raise RuntimeError("Polarizer (KDC101) not connected")
        if not cam or not cam.is_connected():
            raise RuntimeError("Spectrometer camera not connected")
        if not cal.points:
            raise RuntimeError("Polarizer calibration is empty.")

        os.makedirs(self.data_dir, exist_ok=True)
        total_steps = len(self.powers_w)

        for i, target_w in enumerate(self.powers_w):
            self._pause_event.wait()
            if not self._running: break
            
            step_idx = i + 1
            percent = int((i / total_steps) * 100)
            
            # 1. Set Power
            angle = cal.get_angle_for_power(target_w)
            if angle is None:
                raise ValueError(f"Power {format_power_w(target_w)} outside calibration range")
            
            p_str = format_power_w(target_w)
            self.progress.emit(step_idx, f"Moving to {p_str}", percent)
            
            if shutter: shutter.set_shutter(False, channel=self.hw.shutter_channel)
            polarizer.move_to(angle)
            while polarizer.is_moving() and self._running:
                self._pause_event.wait()
                time.sleep(0.1)
            
            if not self._running: break
            self._pause_event.wait()
            time.sleep(self.stabilization_delay)

            # 2. Measure
            self.progress.emit(step_idx, f"Acquiring {p_str}", percent)
            if shutter: shutter.set_shutter(True, channel=self.hw.shutter_channel)
            
            exposure_time = cam.get_exposure()
            time.sleep(max(1.0, exposure_time)) # Min wait for shutter
            
            x_axis = self.hw.get_wavelength_axis()
            if x_axis is None:
                det_size = cam.get_info().get('detector_size', (1024, 256))
                x_axis = np.arange(det_size[0])
            raw_data = acquire_spectrum_synchronized(cam, self.hw)
            if raw_data.ndim == 2:
                raw_data = np.sum(raw_data, axis=0)
            
            if shutter: shutter.set_shutter(False, channel=self.hw.shutter_channel)

            # 3. Process & Save
            result = MeasurementResult(
                timestamp=datetime.now(),
                integration_time=exposure_time,
                metadata=self.metadata.copy(),
                wavelengths=x_axis,
                intensities=raw_data,
                background=self.background,
                background_exposure=(self.background_exposure / 1000.0) if self.background_exposure else None
            )
            result.process(self.processing_mode)
            
            # Step metadata
            result.metadata['Step'] = {
                'Step Type': 'Power Series',
                'Sequence Step Number': step_idx,
                'Target Power (W)': target_w
            }
            if 'Laser' not in result.metadata: result.metadata['Laser'] = {}
            result.metadata['Laser']['Excitation Power (W)'] = target_w

            # Filename
            if target_w < 1e-6: p_file = f"{target_w*1e9:.1f}nW"
            elif target_w < 1e-3: p_file = f"{target_w*1e6:.1f}uW"
            else: p_file = f"{target_w*1e3:.2f}mW"
            p_file = p_file.replace(".", ",")
            
            step_name = f"power_{step_idx:03d}_P_{p_file}"
            save_path = os.path.join(self.data_dir, f"{step_name}.csv")
            
            dm = DataManager(data_root=self.data_dir)
            dm.save_spectrum(result, save_path)
            
            self.measurement_ready.emit(x_axis, result.intensities, step_name)

        if not self._running:
            self.finished.emit(False, "Sequence aborted")
        else:
            self.progress.emit(total_steps, "Complete", 100)
            self.finished.emit(True, f"Power series complete. Saved to {self.data_dir}")


class CustomSequenceWorker(QThread):
    """
    Background worker to execute a custom sequence step-by-step.
    Supports shutter open/close, polarizer angle/power, waits, stages X/Y/XY,
    monochromator wavelength, and camera spectrum collection.
    """
    # step_index (1-based), status_text, progress_percent
    progress = pyqtSignal(int, str, int)
    # x_axis, y_axis, label (for plotting and history)
    measurement_ready = pyqtSignal(np.ndarray, np.ndarray, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, hardware_manager, steps: List[Dict[str, Any]], 
                 data_dir: str, metadata: Dict[str, Any], 
                 background: Optional[np.ndarray] = None,
                 background_exposure: Optional[float] = None,
                 processing_mode: str = "Raw Data"):
        super().__init__()
        self.hw = hardware_manager
        self.raw_steps = steps
        self.steps = unroll_custom_sequence(steps)
        self.data_dir = data_dir
        self.metadata = metadata
        self.background = background
        self.background_exposure = background_exposure
        self.processing_mode = processing_mode
        self._running = True
        self._pause_event = threading.Event()
        self._pause_event.set()

    def stop(self):
        self._running = False
        self._pause_event.set()

    def pause(self):
        self._pause_event.clear()

    def resume(self):
        self._pause_event.set()

    def run(self):
        try:
            self._execute_sequence()
        except Exception as e:
            logger.error(f"Custom sequence execution failed: {e}")
            self.finished.emit(False, str(e))

    def _execute_sequence(self):
        polarizer = self.hw.polarizer
        shutter = self.hw.shutter
        stage_x = self.hw.stage_x
        stage_y = self.hw.stage_y
        mono = self.hw.mono
        cam = self.hw.get_spectroscopy_camera()
        cal = self.hw.polarizer_calibration

        os.makedirs(self.data_dir, exist_ok=True)
        total_steps = len(self.steps)
        if total_steps == 0:
            self.finished.emit(True, "Empty sequence completed.")
            return

        for idx, step in enumerate(self.steps):
            self._pause_event.wait()
            if not self._running: break

            step_num = idx + 1
            percent = int((idx / total_steps) * 100)
            action = step['action']
            params = step['params']
            comment = step['comment']
            orig_step_num = step.get('orig_step_num', step_num)
            iter_num = step.get('loop_iteration', 1)
            total_iters = step.get('total_iterations', 1)

            p_desc = step.get('params_desc', '').strip()
            if p_desc and p_desc.lower() not in ("capture spectrum", "collect spectrum", "capture"):
                param_suffix = f" ({p_desc})"
            else:
                param_suffix = ""

            if total_iters > 1:
                status_desc = f"Step {orig_step_num} (Pass {iter_num}/{total_iters}): {action}{param_suffix}"
            else:
                status_desc = f"Step {orig_step_num}: {action}{param_suffix}"

            self.progress.emit(step_num, status_desc, percent)
            logger.info(f"Custom Sequence: Executing {status_desc}")

            if action == "Wait / Stabilize":
                dur = params.get('duration', 0.0)
                end_time = time.time() + dur
                while time.time() < end_time and self._running:
                    self._pause_event.wait()
                    time.sleep(0.1)

            elif action == "Shutter (linked)":
                if not shutter:
                    raise RuntimeError("Shutter controller not configured")
                open_state = params.get('open', False)
                shutter.set_shutter(open_state, channel=self.hw.shutter_channel)
                time.sleep(0.5) # small stabilization delay

            elif action == "Polarizer Angle":
                if not polarizer or not polarizer.is_connected():
                    raise RuntimeError("Polarizer not connected")
                angle = params.get('angle', 0.0)
                polarizer.move_to(angle)
                while polarizer.is_moving() and self._running:
                    self._pause_event.wait()
                    time.sleep(0.1)
                time.sleep(0.5)

            elif action == "Polarizer Power (calibrated)":
                if not polarizer or not polarizer.is_connected():
                    raise RuntimeError("Polarizer not connected")
                if not cal or not cal.points:
                    raise RuntimeError("Polarizer calibration is empty.")
                p_w = params.get('power_w', 0.0)
                angle = cal.get_angle_for_power(p_w)
                if angle is None:
                    raise ValueError(f"Power {format_power_w(p_w)} outside calibration range")
                polarizer.move_to(angle)
                while polarizer.is_moving() and self._running:
                    self._pause_event.wait()
                    time.sleep(0.1)
                time.sleep(0.5)

            elif action == "Move Stage X":
                if not stage_x or not stage_x.is_connected():
                    raise RuntimeError("Stage X not connected")
                pos = params.get('position', 0.0)
                stage_x.move_to(pos)
                while stage_x.is_moving() and self._running:
                    self._pause_event.wait()
                    time.sleep(0.1)

            elif action == "Move Stage Y":
                if not stage_y or not stage_y.is_connected():
                    raise RuntimeError("Stage Y not connected")
                pos = params.get('position', 0.0)
                stage_y.move_to(pos)
                while stage_y.is_moving() and self._running:
                    self._pause_event.wait()
                    time.sleep(0.1)

            elif action == "Collect Spectrum":


                if not cam or not cam.is_connected():
                    raise RuntimeError("Spectrometer camera not connected")
                
                # Turn shutter on for acquisition if shutter exists
                if shutter:
                    shutter.set_shutter(True, channel=self.hw.shutter_channel)
                
                exposure_time = cam.get_exposure()
                # 3s or exposure time, whichever is longer
                stab_delay = max(3.0, exposure_time)
                
                # Check running/pause while waiting
                end_stab = time.time() + stab_delay
                while time.time() < end_stab and self._running:
                    self._pause_event.wait()
                    time.sleep(0.1)
                if not self._running: break

                # Determine the spectral axis (Wavelengths or Pixels)
                x_axis = self.hw.get_wavelength_axis()
                if x_axis is None:
                    det_size = cam.get_info().get('detector_size', (1024, 256))
                    x_axis = np.arange(det_size[0])

                raw_data = acquire_spectrum_synchronized(cam, self.hw)
                if raw_data.ndim == 2:
                    raw_data = np.sum(raw_data, axis=0)

                if shutter:
                    shutter.set_shutter(False, channel=self.hw.shutter_channel)

                # Process
                result = MeasurementResult(
                    timestamp=datetime.now(),
                    integration_time=exposure_time,
                    metadata=self.metadata,
                    wavelengths=x_axis,
                    intensities=raw_data,
                    background=self.background,
                    background_exposure=(self.background_exposure / 1000.0) if self.background_exposure else None
                )
                result.process(self.processing_mode)
                processed_data = result.intensities

                # Save
                custom_prefix = params.get('prefix', '').strip()
                if custom_prefix:
                    clean_prefix = "".join(c for c in custom_prefix if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
                else:
                    clean_prefix = ""

                base_prefix = clean_prefix if clean_prefix else f"step_{orig_step_num:03d}"

                if total_iters > 1:
                    step_name = f"{base_prefix}_iter{iter_num:02d}"
                else:
                    step_name = base_prefix
                if comment:
                    # Clean comment for filename
                    clean_comment = "".join(c for c in comment if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
                    if clean_comment:
                        step_name += f"_{clean_comment}"
                
                dm = DataManager(data_root=self.data_dir)
                fname = f"{step_name}.csv"
                save_path = os.path.join(self.data_dir, fname)
                collision_idx = 1
                while os.path.exists(save_path):
                    fname = f"{step_name}_{collision_idx}.csv"
                    save_path = os.path.join(self.data_dir, fname)
                    collision_idx += 1

                dm.save_spectrum(result, save_path)

                # Emit for plotting
                self.measurement_ready.emit(x_axis, processed_data, step_name)

        if self._running:
            self.progress.emit(total_steps, "Sequence Complete", 100)
            self.finished.emit(True, "Custom sequence executed successfully.")
        else:
            self.finished.emit(False, "Sequence aborted by user.")


class MapPreviewWidget(QWidget):
    """
    A small canvas that visualises the mapping scan pattern.
    Draws a bounding rectangle or circle and marks every point
    that will be visited with a red dot.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._points: List[Tuple[float, float]] = []
        self._x_min = self._x_max = 0.0
        self._y_min = self._y_max = 0.0
        self._shape = "rectangle"   # "rectangle" | "circle"
        self._diameter = 45.0       # only used when _shape == "circle"
        self._selected_index = -1
        self.setMinimumSize(160, 160)
        # Dark background matching app theme
        self.setStyleSheet("background-color: #1a1a2e; border-radius: 6px;")

    def set_selected_index(self, index: int):
        self._selected_index = index
        self.update()

    def set_data(self, points: List[Tuple[float, float]],
                 x_min: float, x_max: float, y_min: float, y_max: float,
                 shape: str = "rectangle", diameter: float = 45.0):
        self._points = points
        self._x_min = x_min
        self._x_max = x_max
        self._y_min = y_min
        self._y_max = y_max
        self._shape = shape
        self._diameter = diameter
        self.update()  # trigger repaint

    def clear(self):
        self._points = []
        self._selected_index = -1
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        margin = 18

        # Background (already set via stylesheet, but fill explicitly too)
        painter.fillRect(0, 0, w, h, QtGui.QColor("#1a1a2e"))

        if not self._points:
            # Draw placeholder text
            painter.setPen(QtGui.QColor("#555577"))
            font = painter.font()
            font.setPointSize(8)
            painter.setFont(font)
            painter.drawText(
                QtCore.QRect(0, 0, w, h),
                Qt.AlignmentFlag.AlignCenter,
                "No points to visualise"
            )
            painter.end()
            return

        # Compute coordinate bounds with a bit of padding
        pad_frac = 0.15
        dx = max(self._x_max - self._x_min, 1e-6)
        dy = max(self._y_max - self._y_min, 1e-6)
        side = max(dx, dy) * (1 + pad_frac)
        cx_data = (self._x_min + self._x_max) / 2.0
        cy_data = (self._y_min + self._y_max) / 2.0

        avail_w = w - 2 * margin
        avail_h = h - 2 * margin
        scale = min(avail_w / side, avail_h / side)

        # Map data coords → widget pixels
        def to_px(x, y):
            # X goes right-to-left (positive is left)
            px = margin + avail_w / 2 - (x - cx_data) * scale
            # Y goes bottom-to-top (positive is up)
            py = margin + avail_h / 2 - (y - cy_data) * scale
            return px, py

        # Draw bounding shape
        shape_pen = QtGui.QPen(QtGui.QColor("#4a9eff"), 1.5, Qt.PenStyle.DashLine)
        painter.setPen(shape_pen)
        painter.setBrush(QtGui.QBrush(QtGui.QColor(0, 80, 180, 30)))

        if self._shape == "circle":
            # Draw circle centred on data midpoint with given diameter
            r_px = (self._diameter / 2.0) * scale
            c_px, c_py = to_px(cx_data, cy_data)
            painter.drawEllipse(
                QtCore.QPointF(c_px, c_py), r_px, r_px
            )
        else:
            tl_x, tl_y = to_px(self._x_min, self._y_max)
            br_x, br_y = to_px(self._x_max, self._y_min)
            painter.drawRect(QtCore.QRectF(tl_x, tl_y, br_x - tl_x, br_y - tl_y))

        # Draw normal dots
        dot_r = max(1.5, min(3.0, 100.0 / max(len(self._points), 1) ** 0.5))
        painter.setPen(QtGui.QPen(QtGui.QColor("#ff4444"), 1))
        painter.setBrush(QtGui.QBrush(QtGui.QColor("#ff2222")))
        for i, (x, y) in enumerate(self._points):
            if i == self._selected_index:
                continue
            px, py = to_px(x, y)
            painter.drawEllipse(QtCore.QPointF(px, py), dot_r, dot_r)
            
        # Draw selected dot
        if 0 <= self._selected_index < len(self._points):
            x, y = self._points[self._selected_index]
            px, py = to_px(x, y)
            painter.setPen(QtGui.QPen(QtGui.QColor("#ffff00"), 2))
            painter.setBrush(QtGui.QBrush(QtGui.QColor("#ffee00")))
            painter.drawEllipse(QtCore.QPointF(px, py), dot_r * 1.5, dot_r * 1.5)

        # Axis labels (min/max)
        painter.setPen(QtGui.QColor("#888899"))
        font = painter.font()
        font.setPointSize(7)
        painter.setFont(font)
        painter.drawText(2, h - 2, f"X:{self._x_max:.1f}")
        painter.drawText(w - 45, h - 2, f"X:{self._x_min:.1f}")
        painter.drawText(2, margin - 2, f"Y:{self._y_max:.1f}")
        painter.drawText(2, h - margin + 10, f"Y:{self._y_min:.1f}")

        painter.end()


class AutomationPanel(QWidget):
    """Widget for power calibration and automated sequence procedures."""

    # Coordination signals for Measurement Monitoring
    # Total steps details, meas_power, start_index
    sequence_started = pyqtSignal(list, float, int)
    # step_idx, status_text, progress_percent
    step_progress = pyqtSignal(int, str, int)
    # x_axis, y_axis, label
    measurement_ready = pyqtSignal(np.ndarray, np.ndarray, str)
    # success, message
    sequence_finished = pyqtSignal(bool, str)

    def __init__(self):
        super().__init__()
        self.hw = HardwareManager()
        self._worker = None
        self._init_ui()
        logger.info("Automation panel initialized")

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)
        self.setLayout(layout)

        # Main splitter to allow resizing between Calibration and Sequence
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # 1. Polarizer Calibration (Needed for power targeting)
        pol_group = self._create_polarizer_calibration_group()
        splitter.addWidget(pol_group)

        # 2. Sequence Tabs
        self.seq_tabs = QTabWidget()
        
        # Heating Tab
        heating_group = self._create_laser_heating_group()
        self.seq_tabs.addTab(heating_group, "Laser Heating")
        
        # Power Series Tab
        power_group = self._create_power_series_group()
        self.seq_tabs.addTab(power_group, "Power Series")

        # XY Mapping Tab
        mapping_group = self._create_mapping_group()
        self.seq_tabs.addTab(mapping_group, "XY Mapping")
        
        splitter.addWidget(self.seq_tabs)

        # Stretch/Proportions
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1) # Equal width initially
        
        # 3. Custom Sequence Editor
        custom_seq_group = self._create_custom_sequence_group()
        layout.addWidget(custom_seq_group)

        # Add stretch at the bottom to push panels up and leave space
        layout.addStretch(1)

        # Initial Power Selection Sync
        self._update_power_selections()

    def _create_polarizer_calibration_group(self) -> QGroupBox:
        """Create controls for mapping power targets to polarizer angles."""
        group = QGroupBox("Polarizer-Power Calibration (Angle Mapping)")
        group.setStyleSheet("QGroupBox { font-weight: bold; }")
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5) # Unified margins
        group.setLayout(layout)

        # Toolbar
        btn_layout = QHBoxLayout()
        
        add_btn = QPushButton("+")
        add_btn.setFixedWidth(30)
        add_btn.clicked.connect(self._on_add_pol_point)
        btn_layout.addWidget(add_btn)
        
        remove_btn = QPushButton("-")
        remove_btn.setFixedWidth(30)
        remove_btn.clicked.connect(self._on_remove_pol_point)
        btn_layout.addWidget(remove_btn)
        
        clear_btn = QPushButton("Clear All")
        clear_btn.setFixedWidth(80)
        clear_btn.clicked.connect(self._on_clear_pol_points)
        btn_layout.addWidget(clear_btn)
        
        btn_layout.addStretch()

        self.pol_run_sel_btn = QPushButton("Calibrate Selected")
        self.pol_run_sel_btn.setFixedWidth(140)
        self.pol_run_sel_btn.clicked.connect(self._on_calibrate_selected)
        self.pol_run_sel_btn.setStyleSheet("background-color: #e8f5e9; font-weight: normal;")
        btn_layout.addWidget(self.pol_run_sel_btn)
        
        self.pol_run_btn = QPushButton("Calibrate All")
        self.pol_run_btn.setFixedWidth(120)
        self.pol_run_btn.clicked.connect(self._on_calibrate_all)
        self.pol_run_btn.setStyleSheet("background-color: #e3f2fd; font-weight: normal;")
        btn_layout.addWidget(self.pol_run_btn)
        
        layout.addLayout(btn_layout)

        # Table
        self.pol_table = QTableWidget()
        self.pol_table.setColumnCount(4)
        self.pol_table.setHorizontalHeaderLabels(["Target Power", "Unit", "Found Angle (°)", "Status"])
        pol_header = self.pol_table.horizontalHeader()
        if pol_header is not None:
            pol_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.pol_table.setSelectionBehavior(QHeaderView.SelectionBehavior.SelectRows)
        self.pol_table.setSelectionMode(QHeaderView.SelectionMode.ExtendedSelection)
        self.pol_table.setMinimumHeight(250)
        layout.addWidget(self.pol_table)
        
        return group

    def _on_add_pol_point(self):
        row = self.pol_table.rowCount()
        self.pol_table.insertRow(row)
        
        # Power
        spin = QDoubleSpinBox()
        spin.setRange(0, 10000)
        spin.setValue(10.0)
        self.pol_table.setCellWidget(row, 0, spin)
        
        # Unit
        unit_cb = QComboBox()
        unit_cb.addItems(["nW", "µW", "mW"])
        unit_cb.setCurrentText("mW")
        self.pol_table.setCellWidget(row, 1, unit_cb)
        
        # Angle item (initially empty)
        self.pol_table.setItem(row, 2, QTableWidgetItem("---"))
        self.pol_table.setItem(row, 3, QTableWidgetItem("Ready"))
        
        # Sync sequence menus
        self._update_power_selections()

    def _on_clear_pol_points(self):
        self.pol_table.setRowCount(0)
        self.hw.polarizer_calibration.clear()
        self._update_power_selections()

    def _on_remove_pol_point(self):
        """Remove all selected rows from the table."""
        sel_model = self.pol_table.selectionModel()
        selected_rows = [r.row() for r in sel_model.selectedRows()] if sel_model is not None else []
        if not selected_rows:
            # Fallback to last row if no selection exists
            curr = self.pol_table.rowCount() - 1
            if curr >= 0:
                selected_rows = [curr]

        if selected_rows:
            # Delete in descending order to avoid index shifts
            for r in sorted(selected_rows, reverse=True):
                self.pol_table.removeRow(r)
            self._update_power_selections()

    def _on_calibrate_selected(self):
        """Calibrate all currently selected rows."""
        sel_model = self.pol_table.selectionModel()
        selected_rows = [r.row() for r in sel_model.selectedRows()] if sel_model is not None else []
        
        # Fallback to current row if only looking at focus but no selection
        if not selected_rows:
            curr = self.pol_table.currentRow()
            if curr >= 0:
                selected_rows = [curr]

        if not selected_rows:
            QMessageBox.warning(self, "No Selection", "Please select one or more rows in the table to calibrate.")
            return
            
        self._start_calibration_sweep(sorted(selected_rows), is_all=False)

    def _on_calibrate_all(self):
        """Calibrate all rows in the table that are not already finished."""
        rows_to_calibrate = []
        for r in range(self.pol_table.rowCount()):
            status_item = self.pol_table.item(r, 3)
            if status_item and status_item.text() not in ["Done", "Loaded"]:
                rows_to_calibrate.append(r)
        
        if not rows_to_calibrate:
            QMessageBox.information(self, "Calibration Skip", 
                                    "All rows are already calibrated (Status: Done/Loaded).\n"
                                    "To recalibrate, clear the table or add new points.")
            return

        self._start_calibration_sweep(rows_to_calibrate, is_all=True)

    def _start_calibration_sweep(self, rows_to_calibrate: list, is_all: bool):
        """Common logic to start the calibration worker for a set of rows."""
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            if self.pol_run_btn.text() == "Stop":
                self.pol_run_btn.setText("Stopping...")
            if self.pol_run_sel_btn.text() == "Stop":
                self.pol_run_sel_btn.setText("Stopping...")
            return

        # 1. Hardware Connection Check
        polarizer = self.hw.polarizer
        pm = self.hw.get_instrument('pm100')
        
        missing = []
        if not polarizer or not polarizer.is_connected():
            missing.append("Polarizer (KDC101)")
        if not pm or not pm.is_connected():
            missing.append("Power Meter (Thorlabs PM100)")
            
        if missing:
            msg = "Calibration cannot start. The following hardware is not connected:\n\n"
            msg += "\n".join([f" - {m}" for m in missing])
            msg += "\n\nPlease connect them first using the 'Connect All' button or individual panels."
            QMessageBox.warning(self, "Hardware Not Connected", msg)
            return

        # 2. Prepare points
        points = []
        multipliers = {"nW": 1e-9, "µW": 1e-6, "mW": 1e-3}
        
        for r in rows_to_calibrate:
            spin = self.pol_table.cellWidget(r, 0)
            unit_cb = self.pol_table.cellWidget(r, 1)
            if isinstance(spin, QDoubleSpinBox) and isinstance(unit_cb, QComboBox):
                val = spin.value()
                unit = unit_cb.currentText()
                target_w = val * multipliers[unit]
                points.append((r, target_w))
                status_item = self.pol_table.item(r, 3)
                if status_item is not None:
                    status_item.setText("Queued")
        
        if not points:
            return

        # UI state for exclusive run
        if is_all:
            self.pol_run_btn.setText("Stop")
            self.pol_run_btn.setStyleSheet("background-color: #ffebee; color: red;")
            self.pol_run_sel_btn.setEnabled(False)
        else:
            self.pol_run_sel_btn.setText("Stop")
            self.pol_run_sel_btn.setStyleSheet("background-color: #ffebee; color: red;")
            self.pol_run_btn.setEnabled(False)
        
        self._worker = CalibrationSweepWorker(self.hw, points)
        self._worker.point_finished.connect(self._on_point_finished)
        self._worker.finished.connect(self._on_sweep_finished)
        self._worker.start()

    def _on_point_finished(self, row, success, angle, power, message):
        angle_item = self.pol_table.item(row, 2)
        status_item = self.pol_table.item(row, 3)
        if success:
            if angle_item is not None:
                angle_item.setText(f"{angle:.3f}")
            if status_item is not None:
                status_item.setText("Done")
                status_item.setForeground(Qt.GlobalColor.green)
            
            # Gray out / lock the input widgets
            p_spin = self.pol_table.cellWidget(row, 0)
            u_combo = self.pol_table.cellWidget(row, 1)
            if p_spin: p_spin.setEnabled(False)
            if u_combo: u_combo.setEnabled(False)
        else:
            if status_item is not None:
                status_item.setText(f"Error: {message}")
                status_item.setForeground(Qt.GlobalColor.red)

    def _on_sweep_finished(self, success, message):
        self.pol_run_btn.setText("Calibrate All")
        self.pol_run_btn.setEnabled(True)
        self.pol_run_btn.setStyleSheet("background-color: #e3f2fd; color: black; font-weight: bold;")
        
        self.pol_run_sel_btn.setText("Calibrate Selected")
        self.pol_run_sel_btn.setEnabled(True)
        self.pol_run_sel_btn.setStyleSheet("background-color: #e8f5e9; color: black; font-weight: normal;")
        
        # Refresh the calibration mapping from the table
        self._on_save_pol_cal(silent=True)
        self._update_power_selections(select_min=True)

        if not success:
            logger.warning(f"Calibration sweep ended: {message}")

    def _on_save_pol_cal(self, silent=False):
        if not silent:
            path, _ = QFileDialog.getSaveFileName(self, "Save Polarizer Calibration", "", "JSON Files (*.json)")
            if not path:
                return
        else:
            path = None
            
        cal = self.hw.polarizer_calibration
        cal.clear()
        
        for r in range(self.pol_table.rowCount()):
            spin = self.pol_table.cellWidget(r, 0)
            unit_cb = self.pol_table.cellWidget(r, 1)
            angle_item = self.pol_table.item(r, 2)
            
            if isinstance(spin, QDoubleSpinBox) and isinstance(unit_cb, QComboBox) and angle_item:
                angle_text = angle_item.text()
                if angle_text != "---":
                    try:
                        cal.add_point(spin.value(), unit_cb.currentText(), float(angle_text))
                    except ValueError:
                        pass
        
        if path:
            try:
                cal.save(path)
                QMessageBox.information(self, "Success", f"Calibration saved to {path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save calibration: {e}")
        
        # Ensure sequence editor is in sync with latest table state
        self._update_power_selections()

    def _on_load_pol_cal(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Polarizer Calibration", "", "JSON Files (*.json)")
        if not path:
            return
            
        try:
            self.hw.polarizer_calibration.load(path)
            # Sync table
            self.pol_table.setRowCount(0)
            for p in self.hw.polarizer_calibration.points:
                row = self.pol_table.rowCount()
                self.pol_table.insertRow(row)
                
                spin = QDoubleSpinBox()
                spin.setRange(0, 10000)
                spin.setValue(p['power'])
                spin.setEnabled(False) # Already calibrated
                self.pol_table.setCellWidget(row, 0, spin)
                
                unit_cb = QComboBox()
                unit_cb.addItems(["nW", "µW", "mW"])
                unit_cb.setCurrentText(p['unit'])
                unit_cb.setEnabled(False) # Already calibrated
                self.pol_table.setCellWidget(row, 1, unit_cb)
                
                self.pol_table.setItem(row, 2, QTableWidgetItem(f"{p['angle']:.3f}"))
                self.pol_table.setItem(row, 3, QTableWidgetItem("Loaded"))
            
            self._update_power_selections(select_min=True)
            QMessageBox.information(self, "Success", f"Loaded {len(self.hw.polarizer_calibration.points)} points.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load calibration: {e}")

    def _create_laser_heating_group(self) -> QGroupBox:
        """Create controls for the automated laser heating sequence."""
        group = QGroupBox("Laser Heating Sequence Editor")
        group.setStyleSheet("QGroupBox { font-weight: bold; }")
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5) # Unified margins
        group.setLayout(layout)

        # --- Sequence Table Toolbar ---
        table_toolbar = QHBoxLayout()
        
        add_btn = QPushButton("+")
        add_btn.setFixedWidth(30)
        add_btn.clicked.connect(self._on_add_heating_step)
        table_toolbar.addWidget(add_btn)
        
        remove_btn = QPushButton("-")
        remove_btn.setFixedWidth(30)
        remove_btn.clicked.connect(self._on_remove_heating_step)
        table_toolbar.addWidget(remove_btn)
        
        clear_btn = QPushButton("Clear All")
        clear_btn.setFixedWidth(80)
        clear_btn.clicked.connect(lambda: self.heating_table.setRowCount(0))
        table_toolbar.addWidget(clear_btn)
        
        table_toolbar.addSpacing(20)
        
        table_toolbar.addWidget(QLabel("Measurement (PL) Power:"))
        self.meas_power_combo = QComboBox()
        self.meas_power_combo.setToolTip("Select a calibrated power level for PL measurements")
        table_toolbar.addWidget(self.meas_power_combo)
        
        table_toolbar.addStretch()
        layout.addLayout(table_toolbar)

        # --- Bulk Insertion Tool (Scalability) ---
        bulk_group = QGroupBox("Bulk Step Insertion")
        bulk_group.setStyleSheet("QGroupBox { font-weight: normal; }")
        bulk_layout = QHBoxLayout()
        bulk_group.setLayout(bulk_layout)
        
        bulk_layout.addWidget(QLabel("Insert"))
        self.bulk_n_spin = QSpinBox()
        self.bulk_n_spin.setRange(1, 1000)
        self.bulk_n_spin.setValue(5)
        self.bulk_n_spin.setFixedWidth(60)
        bulk_layout.addWidget(self.bulk_n_spin)
        bulk_layout.addWidget(QLabel("steps at"))
        
        self.bulk_power_combo = QComboBox()
        self.bulk_power_combo.setFixedWidth(120)
        bulk_layout.addWidget(self.bulk_power_combo)
        
        bulk_layout.addWidget(QLabel("for"))
        self.bulk_dur_spin = QDoubleSpinBox()
        self.bulk_dur_spin.setRange(0.1, 3600)
        self.bulk_dur_spin.setValue(1.0)
        self.bulk_dur_spin.setFixedWidth(75)
        bulk_layout.addWidget(self.bulk_dur_spin)
        bulk_layout.addWidget(QLabel("s each"))
        
        insert_bulk_btn = QPushButton("Insert Steps")
        insert_bulk_btn.setFixedWidth(100)
        insert_bulk_btn.clicked.connect(self._on_insert_bulk_steps)
        bulk_layout.addWidget(insert_bulk_btn)
        
        bulk_layout.addStretch()
        
        layout.addWidget(bulk_group)

        # --- Table ---
        self.heating_table = ReorderableTableWidget()
        self.heating_table.setColumnCount(3)
        self.heating_table.setHorizontalHeaderLabels(["Step #", "Heat Power", "Duration (s)"])
        self.heating_table.order_changed.connect(self._reindex_heating_steps)
        heating_header = self.heating_table.horizontalHeader()
        if heating_header is not None:
            heating_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.heating_table)

        # --- Controls & Status ---
        ctrl_layout = QHBoxLayout()
        
        ctrl_layout.addWidget(QLabel("Start at Step:"))
        self.start_step_spin = QSpinBox()
        self.start_step_spin.setRange(0, 1000)
        self.start_step_spin.setValue(0)
        self.start_step_spin.setToolTip("0 = include baseline, 1+ = start at specific step index")
        self.start_step_spin.valueChanged.connect(self._reindex_heating_steps)
        ctrl_layout.addWidget(self.start_step_spin)
        
        ctrl_layout.addSpacing(20)
        
        ctrl_layout.addWidget(QLabel("Cooling Delay (s):"))
        self.cooling_delay_spin = QDoubleSpinBox()
        self.cooling_delay_spin.setRange(0, 60)
        self.cooling_delay_spin.setValue(1.0)
        self.cooling_delay_spin.setToolTip("Wait time after heating pulse to return to cryostat temperature")
        ctrl_layout.addWidget(self.cooling_delay_spin)
        
        ctrl_layout.addStretch()

        self.heating_run_btn = QPushButton("START SEQUENCE")
        self.heating_run_btn.setFixedWidth(160)
        self.heating_run_btn.clicked.connect(self._on_toggle_sequence)
        self.heating_run_btn.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold;")
        self.heating_run_btn.hide()
        ctrl_layout.addWidget(self.heating_run_btn)
        
        layout.addLayout(ctrl_layout)
        
        return group


    def _create_power_series_group(self) -> QGroupBox:
        """Create controls for the automated power series sequence."""
        group = QGroupBox("Power Series Sequence Editor")
        group.setStyleSheet("QGroupBox { font-weight: bold; }")
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        group.setLayout(layout)

        # --- Sequence Table Toolbar ---
        table_toolbar = QHBoxLayout()
        
        add_btn = QPushButton("+")
        add_btn.setFixedWidth(30)
        add_btn.clicked.connect(self._on_add_power_step)
        table_toolbar.addWidget(add_btn)
        
        remove_btn = QPushButton("-")
        remove_btn.setFixedWidth(30)
        remove_btn.clicked.connect(self._on_remove_power_step)
        table_toolbar.addWidget(remove_btn)
        
        clear_btn = QPushButton("Clear All")
        clear_btn.setFixedWidth(80)
        clear_btn.clicked.connect(self._on_clear_power_steps)
        table_toolbar.addWidget(clear_btn)
        
        table_toolbar.addStretch()
        layout.addLayout(table_toolbar)

        # --- Generator Tool ---
        gen_group = QGroupBox("Sweep Generator")
        gen_group.setStyleSheet("QGroupBox { font-weight: normal; }")
        gen_layout = QHBoxLayout()
        gen_group.setLayout(gen_layout)

        gen_layout.addWidget(QLabel("Start:"))
        self.ps_start_combo = QComboBox()
        self.ps_start_combo.setFixedWidth(120)
        gen_layout.addWidget(self.ps_start_combo)

        gen_layout.addWidget(QLabel("End:"))
        self.ps_end_combo = QComboBox()
        self.ps_end_combo.setFixedWidth(120)
        gen_layout.addWidget(self.ps_end_combo)

        gen_layout.addWidget(QLabel("Steps:"))
        self.ps_steps_spin = QSpinBox()
        self.ps_steps_spin.setRange(2, 100)
        self.ps_steps_spin.setValue(10)
        self.ps_steps_spin.setFixedWidth(60)
        gen_layout.addWidget(self.ps_steps_spin)

        self.ps_log_check = QCheckBox("Log")
        gen_layout.addWidget(self.ps_log_check)

        gen_btn = QPushButton("Generate")
        gen_btn.setFixedWidth(100)
        gen_btn.clicked.connect(self._on_generate_power_sweep)
        gen_layout.addWidget(gen_btn)
        
        gen_layout.addStretch()
        
        layout.addWidget(gen_group)

        # --- Table ---
        self.power_table = ReorderableTableWidget()
        self.power_table.setColumnCount(2)
        self.power_table.setHorizontalHeaderLabels(["Step #", "Power"])
        self.power_table.order_changed.connect(self._reindex_power_steps)
        power_header = self.power_table.horizontalHeader()
        if power_header is not None:
            power_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.power_table.setSelectionBehavior(QHeaderView.SelectionBehavior.SelectRows)
        self.power_table.setSelectionMode(QHeaderView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.power_table)

        # --- Parameters & Run ---
        param_layout = QHBoxLayout()
        param_layout.addWidget(QLabel("Stabilization Delay (s):"))
        self.ps_stab_spin = QDoubleSpinBox()
        self.ps_stab_spin.setRange(0, 60)
        self.ps_stab_spin.setValue(1.0)
        self.ps_stab_spin.setFixedWidth(80)
        param_layout.addWidget(self.ps_stab_spin)
        
        param_layout.addStretch()

        self.power_run_btn = QPushButton("START POWER SERIES")
        self.power_run_btn.setFixedWidth(160)
        self.power_run_btn.clicked.connect(self._on_run_power_series)
        self.power_run_btn.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold;")
        self.power_run_btn.hide()
        param_layout.addWidget(self.power_run_btn)
        
        layout.addLayout(param_layout)
        
        return group


    def get_cooling_delay(self) -> float:
        """Get the current cooling delay value in seconds."""
        return self.cooling_delay_spin.value()

    def get_power_series_steps(self) -> List[float]:
        """Get the list of target powers (W) from the power series table."""
        powers = []
        for r in range(self.power_table.rowCount()):
            p_combo = self.power_table.cellWidget(r, 1)
            if isinstance(p_combo, QComboBox):
                val = p_combo.currentData()
                if val is not None:
                    powers.append(float(val))
        return powers

    def get_ps_stabilization_delay(self) -> float:
        """Get the stabilization delay for power series in seconds."""
        return self.ps_stab_spin.value()

    def get_sequence_steps(self) -> List[Dict[str, Any]]:
        """Public method to retrieve the currently defined sequence steps."""
        steps = []
        for r in range(self.heating_table.rowCount()):
            # Step # in col 0
            
            # Power in col 1 (ComboBox)
            p_combo = self.heating_table.cellWidget(r, 1)
            if not isinstance(p_combo, QComboBox): continue
            
            # Duration in col 2 (DoubleSpinBox)
            d_spin = self.heating_table.cellWidget(r, 2)
            if not isinstance(d_spin, QDoubleSpinBox): continue
            
            # Get actual values
            target_w = p_combo.currentData()
            if target_w is None: 
                # Fallback if user data not set (shouldn't happen with _populate)
                # Parse text? No, safer to rely on _populate 
                continue
                
            duration = d_spin.value()
            
            steps.append({
                'target_w': target_w,
                'duration': duration
            })
        return steps

    def get_measurement_power(self) -> float:
        """Get the selected baseline/measurement power in Watts."""
        val = self.meas_power_combo.currentData()
        return val if val is not None else 0.0

    def _on_add_heating_step(self):
        # Insert at current row or at the end if no selection
        row = self.heating_table.currentRow()
        if row < 0:
            row = self.heating_table.rowCount()
        else:
            row += 1 # Insert AFTER current row
            
        self.heating_table.setSortingEnabled(False)
        self.heating_table.insertRow(row)
        
        # Step #
        item = QTableWidgetItem()
        item.setData(Qt.ItemDataRole.EditRole, row + 1)
        self.heating_table.setItem(row, 0, item)
        
        # Calibrated Power Selection
        p_combo = QComboBox()
        # Populate with current calibration points
        self._populate_power_combo(p_combo)
        self.heating_table.setCellWidget(row, 1, p_combo)
        
        # Duration (s)
        d_spin = QDoubleSpinBox()
        d_spin.setRange(0.1, 3600)
        d_spin.setValue(1.0)
        self.heating_table.setCellWidget(row, 2, d_spin)
        
        # Re-index all steps
        self._reindex_heating_steps()
        self.heating_table.setSortingEnabled(True)

    def _on_remove_heating_step(self):
        curr = self.heating_table.currentRow()
        if curr < 0:
            curr = self.heating_table.rowCount() - 1
            
        if curr >= 0:
            self.heating_table.setSortingEnabled(False)
            self.heating_table.removeRow(curr)
            self._reindex_heating_steps()
            self.heating_table.setSortingEnabled(True)

    def _on_insert_bulk_steps(self):
        n = self.bulk_n_spin.value()
        target_power_text = self.bulk_power_combo.currentText()
        duration = self.bulk_dur_spin.value()
        
        row = self.heating_table.currentRow()
        if row < 0:
            row = self.heating_table.rowCount()
        else:
            row += 1

        self.heating_table.setSortingEnabled(False)
        for _ in range(n):
            self.heating_table.insertRow(row)
            item = QTableWidgetItem()
            item.setData(Qt.ItemDataRole.EditRole, row + 1)
            self.heating_table.setItem(row, 0, item)
            
            p_combo = QComboBox()
            self._populate_power_combo(p_combo)
            p_combo.setCurrentText(target_power_text)
            self.heating_table.setCellWidget(row, 1, p_combo)
            
            d_spin = QDoubleSpinBox()
            d_spin.setRange(0.1, 3600)
            d_spin.setValue(duration)
            self.heating_table.setCellWidget(row, 2, d_spin)
            row += 1
            
        self.heating_table.setSortingEnabled(True)
        self._reindex_heating_steps()

    def _populate_power_combo(self, combo: QComboBox):
        """Populate a combo box with available calibrated powers."""
        current_text = combo.currentText()
        combo.clear()
        cal = self.hw.polarizer_calibration
        if not cal or not cal.points:
            combo.addItem("None (Calibrate first)")
            return

        # Sort points by power for neatness
        # Points are {'power': float, 'unit': str, 'angle': float}
        multipliers = {"nW": 1e-9, "µW": 1e-6, "mW": 1e-3}
        sorted_points = sorted(cal.points, key=lambda p: p['power'] * multipliers.get(p['unit'], 1.0))
        
        for p in sorted_points:
            label = f"{p['power']} {p['unit']}"
            # Store raw power in Watts as user data if needed for easy retrieval
            p_w = p['power'] * multipliers.get(p['unit'], 1.0)
            combo.addItem(label, p_w)
            
        # Try to restore previous selection if it still exists
        index = combo.findText(current_text)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _update_power_selections(self, select_min=True):
        """Refresh all power dropdowns in the UI when calibration changes."""
        self._populate_power_combo(self.meas_power_combo)
        self._populate_power_combo(self.bulk_power_combo)
        self._populate_power_combo(self.ps_start_combo)
        self._populate_power_combo(self.ps_end_combo)
        
        if select_min:
            if self.meas_power_combo.count() > 0:
                self.meas_power_combo.setCurrentIndex(0)
            if self.ps_start_combo.count() > 0:
                self.ps_start_combo.setCurrentIndex(0)
            if self.ps_end_combo.count() > 0:
                self.ps_end_combo.setCurrentIndex(self.ps_end_combo.count() - 1)

        for r in range(self.heating_table.rowCount()):
            p_combo = self.heating_table.cellWidget(r, 1)
            if isinstance(p_combo, QComboBox):
                self._populate_power_combo(p_combo)

        for r in range(self.power_table.rowCount()):
            p_combo = self.power_table.cellWidget(r, 1)
            if isinstance(p_combo, QComboBox):
                self._populate_power_combo(p_combo)

        # Update custom sequence power combo selections if they are active
        if hasattr(self, 'custom_seq_table'):
            for r in range(self.custom_seq_table.rowCount()):
                p_combo = self.custom_seq_table.cellWidget(r, 2)
                if isinstance(p_combo, QComboBox):
                    act_combo = self.custom_seq_table.cellWidget(r, 1)
                    if isinstance(act_combo, QComboBox) and act_combo.currentText() == "Polarizer Power (calibrated)":
                        self._populate_power_combo(p_combo)

    def _reindex_heating_steps(self):
        """Update the Step # column for all rows."""
        self.heating_table.setSortingEnabled(False)
        offset = self.start_step_spin.value() if self.start_step_spin.value() > 0 else 1
        for r in range(self.heating_table.rowCount()):
                # Use DisplayRole with int for numerical sorting
                item = QTableWidgetItem()
                item.setData(Qt.ItemDataRole.EditRole, r + offset)
                item.setText(f"{r + offset}") # redundancy for some styles
                self.heating_table.setItem(r, 0, item)
        self.heating_table.setSortingEnabled(True)

    def _on_import_sequence(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Sequence", "", "CSV Files (*.csv)")
        if not path: return
        
        try:
            with open(path, 'r') as f:
                reader = csv.reader(f)
                header = next(reader, None) # Skip header
                self.heating_table.setRowCount(0)
                for row_data in reader:
                    if len(row_data) < 2: continue
                    r = self.heating_table.rowCount()
                    self.heating_table.insertRow(r)
                    # Step #
                    item = QTableWidgetItem()
                    item.setData(Qt.ItemDataRole.EditRole, r + 1)
                    self.heating_table.setItem(r, 0, item)
                    
                    # Calibrated Power Selection
                    p_combo = QComboBox()
                    self._populate_power_combo(p_combo)
                    
                    # Try to match imported value (col 0 or 1 depending on format)
                    try:
                        # Col 1 in new export is raw power in Watts
                        if len(row_data) >= 3:
                            target_w = float(row_data[1])
                        else:
                            # Fallback to old format (mW in col 0)
                            target_w = float(row_data[0]) * 1e-3
                            
                        # Find nearest index in combo
                        best_idx = 0
                        min_diff = 1e9
                        for i in range(p_combo.count()):
                            val = p_combo.itemData(i)
                            if val is not None:
                                diff = abs(float(val) - target_w)
                                if diff < min_diff:
                                    min_diff = diff
                                    best_idx = i
                        p_combo.setCurrentIndex(best_idx)
                    except (ValueError, TypeError):
                        pass
                        
                    self.heating_table.setCellWidget(r, 1, p_combo)
                    
                    # Duration (s)
                    d_spin = QDoubleSpinBox()
                    d_spin.setRange(0.1, 3600)
                    try:
                        d_val = float(row_data[-1]) # Duration is usually last
                        d_spin.setValue(d_val)
                    except (ValueError, IndexError):
                        d_spin.setValue(1.0)
                    self.heating_table.setCellWidget(r, 2, d_spin)
                    pass
            
            self._reindex_heating_steps()
            QMessageBox.information(self, "Success", f"Imported {self.heating_table.rowCount()} steps.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to import sequence: {e}")

    def _on_export_sequence(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Sequence", "", "CSV Files (*.csv)")
        if not path: return
        
        try:
            with open(path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["Power (label)", "Power (W)", "Duration (s)"])
                for r in range(self.heating_table.rowCount()):
                    p_combo = self.heating_table.cellWidget(r, 1)
                    d_spin = self.heating_table.cellWidget(r, 2)
                    if isinstance(p_combo, QComboBox) and isinstance(d_spin, QDoubleSpinBox):
                        p_label = p_combo.currentText()
                        p_w = p_combo.currentData()
                        d = d_spin.value()
                        writer.writerow([p_label, p_w, d])
            QMessageBox.information(self, "Success", f"Sequence exported to {path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export sequence: {e}")

    def _on_toggle_sequence(self):
        if self._worker and self._worker.isRunning():
            self.stop_sequence()
            return

        # Prepare run
        steps = []
        for r in range(self.heating_table.rowCount()):
            p_combo = self.heating_table.cellWidget(r, 1)
            d_spin = self.heating_table.cellWidget(r, 2)
            if isinstance(p_combo, QComboBox) and isinstance(d_spin, QDoubleSpinBox):
                p_w = p_combo.currentData()
                if p_w is None:
                    QMessageBox.warning(self, "Uncalibrated Power", f"Step {r+1} has no calibrated power selected.")
                    return
                dur = d_spin.value()
                steps.append({'target_w': float(p_w), 'duration': dur})
        
        if not steps:
            QMessageBox.warning(self, "Empty Sequence", "Please add at least one heating step.")
            return

        # Check for background correction safety
        processing_mode = self.hw.data_processing_mode
        # Background frame usually lives in live_view
        background = None
        main_win = self.window()
        if hasattr(main_win, 'live_view'):
            background = main_win.live_view.background_frame
            
        if "Background" in processing_mode and background is None:
            ret = QMessageBox.question(self, "No Background", 
                                     "Background correction is ENABLED, but no background frame has been captured.\n\n"
                                     "Continue anyway (using Raw Data)?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ret == QMessageBox.StandardButton.No:
                return

        # Baseline power
        meas_p_w = self.meas_power_combo.currentData()
        if meas_p_w is None:
            QMessageBox.warning(self, "Uncalibrated Power", "Measurement (PL) power is not calibrated.")
            return
        meas_p_w = float(meas_p_w)

        # Data directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        data_dir = os.path.join(self.hw.config.get('paths', {}).get('data_root', './data'), f"heating_{timestamp}")

        # Metadata for the run
        metadata = self.hw.collect_metadata(manual_power_w=meas_p_w)
        
        # Get background and processing mode (usually from LiveView, but synced via Manager)
        # Note: AutomationPanel should ideally have a way to get the current background frame
        # For now we've added a placeholder or we can try to find it via the parent window
        background = None
        main_win = self.window()
        if hasattr(main_win, 'live_view'):
            background = main_win.live_view.background_frame
        
        processing_mode = self.hw.data_processing_mode
        cooling_delay = self.cooling_delay_spin.value()

        # Start worker
        self._worker = LaserHeatingWorker(
            self.hw, meas_p_w, steps, data_dir, 
            metadata=metadata,
            background=background,
            processing_mode=processing_mode,
            cooling_delay=cooling_delay,
            skip_step_0=(self.start_step_spin.value() > 1),
            start_index=self.start_step_spin.value()
        )
        self._worker.progress.connect(self._on_sequence_progress)
        self._worker.finished.connect(self._on_sequence_finished)
        self._worker.measurement_ready.connect(self.measurement_ready.emit)
        
        # Notify that sequence has started
        self.sequence_started.emit(steps, meas_p_w, max(0, self.start_step_spin.value()))

        self.heating_run_btn.setText("STOP SEQUENCE")
        self.heating_run_btn.setStyleSheet("background-color: #c0392b; color: white; font-weight: bold;")
        self.heating_run_btn.setEnabled(True)
        self._worker.start()

    def _on_sequence_progress(self, step_idx, status, percent):
        if step_idx >= 0:
            # Scroll to active row
            if 0 < step_idx <= self.heating_table.rowCount():
                item = self.heating_table.item(step_idx-1, 0)
                if item is not None:
                    self.heating_table.scrollToItem(item)
        # Forward to monitor
        self.step_progress.emit(step_idx, status, percent)
        
        if step_idx < 0:
            # -1 means just a status update (ignored now label is gone)
            pass

    def _on_sequence_finished(self, success, message):
        self.heating_run_btn.setText("START SEQUENCE")
        self.heating_run_btn.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold;")
        self.heating_run_btn.setEnabled(True)
        # Status label removed
        
        if success:
            QMessageBox.information(self, "Sequence Complete", message)
        # Forward to monitor
        self.sequence_finished.emit(success, message)
        if not success:
            if "aborted" not in message.lower():
                QMessageBox.critical(self, "Sequence Failed", message)

    def _on_generate_power_sweep(self):
        """Generate a range of powers from calibrated ones and populate the table."""
        start_w = self.ps_start_combo.currentData()
        end_w = self.ps_end_combo.currentData()
        steps = self.ps_steps_spin.value()

        if start_w is None or end_w is None:
            QMessageBox.warning(self, "Incomplete Selection", "Please select both start and end powers from the calibrated list.")
            return

        cal = self.hw.polarizer_calibration
        if not cal or not cal.points:
            QMessageBox.warning(self, "No Calibration", "No calibrated powers found. Please calibrate first.")
            return

        multipliers = {"nW": 1e-9, "µW": 1e-6, "mW": 1e-3}
        # Get all points sorted by power in Watts
        sorted_points = sorted(
            [(p['power'] * multipliers.get(p['unit'], 1.0), p['power'], p['unit']) for p in cal.points],
            key=lambda x: x[0]
        )

        min_w = min(start_w, end_w)
        max_w = max(start_w, end_w)
        epsilon = 1e-12
        filtered = [pt for pt in sorted_points if min_w - epsilon <= pt[0] <= max_w + epsilon]

        if start_w > end_w:
            filtered.reverse()

        if len(filtered) > steps:
            # Downsample to get exactly the requested number of steps
            indices = np.round(np.linspace(0, len(filtered) - 1, steps)).astype(int)
            filtered = [filtered[idx] for idx in indices]

        self.power_table.setRowCount(0)
        self.power_table.setSortingEnabled(False)
        self.power_table.blockSignals(True)
        try:
            for i, (p_w, p_val, p_unit) in enumerate(filtered):
                row = self.power_table.rowCount()
                self.power_table.insertRow(row)
                
                # Step # (non-editable)
                step_item = QTableWidgetItem(str(i+1))
                step_item.setFlags(step_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.power_table.setItem(row, 0, step_item)
                
                # Power Combo
                p_combo = QComboBox()
                self._populate_power_combo(p_combo)
                # Select the generated power in the combo
                idx = p_combo.findData(p_w)
                if idx >= 0:
                    p_combo.setCurrentIndex(idx)
                self.power_table.setCellWidget(row, 1, p_combo)
        finally:
            self.power_table.blockSignals(False)
        
        self.power_table.setSortingEnabled(True)

    def _on_add_power_step(self):
        # Insert at current row or at the end if no selection
        row = self.power_table.currentRow()
        if row < 0:
            row = self.power_table.rowCount()
        else:
            row += 1 # Insert AFTER current row
            
        self.power_table.setSortingEnabled(False)
        self.power_table.insertRow(row)
        
        # Step # (non-editable)
        step_item = QTableWidgetItem()
        step_item.setFlags(step_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.power_table.setItem(row, 0, step_item)
        
        # Power Combo
        p_combo = QComboBox()
        self._populate_power_combo(p_combo)
        self.power_table.setCellWidget(row, 1, p_combo)
        
        # Re-index all steps
        self._reindex_power_steps()
        self.power_table.setSortingEnabled(True)

    def _on_remove_power_step(self):
        sel_model = self.power_table.selectionModel()
        selected_rows = [r.row() for r in sel_model.selectedRows()] if sel_model is not None else []
        if not selected_rows:
            curr = self.power_table.currentRow()
            if curr >= 0:
                selected_rows = [curr]
            else:
                curr = self.power_table.rowCount() - 1
                if curr >= 0:
                    selected_rows = [curr]

        if selected_rows:
            self.power_table.setSortingEnabled(False)
            self.power_table.blockSignals(True)
            try:
                for r in sorted(selected_rows, reverse=True):
                    self.power_table.removeRow(r)
            finally:
                self.power_table.blockSignals(False)
            self._reindex_power_steps()
            self.power_table.setSortingEnabled(True)

    def _on_clear_power_steps(self):
        self.power_table.setRowCount(0)

    def _reindex_power_steps(self):
        """Update the Step # column for all rows in the power table."""
        self.power_table.setSortingEnabled(False)
        self.power_table.blockSignals(True)
        try:
            for r in range(self.power_table.rowCount()):
                item = self.power_table.item(r, 0)
                if not item:
                    item = QTableWidgetItem()
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.power_table.setItem(r, 0, item)
                item.setData(Qt.ItemDataRole.EditRole, r + 1)
                item.setText(str(r + 1))
        finally:
            self.power_table.blockSignals(False)
        self.power_table.setSortingEnabled(True)

    def _on_run_power_series(self):
        """Initialize and start the background power series worker."""
        if self._worker and self._worker.isRunning():
            self.stop_sequence()
            return

        powers = self.get_power_series_steps()

        if not powers:
            QMessageBox.warning(self, "Empty Sequence", "Please generate a power sweep first.")
            return

        # Prepare directory and metadata
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        data_dir = os.path.join(self.hw.config.get('paths', {}).get('data_root', './data'), f"power_series_{timestamp}")
        
        # Use average power from first step as initial reference for metadata collection
        metadata = self.hw.collect_metadata(manual_power_w=powers[0])
        processing_mode = self.hw.data_processing_mode
        stab_delay = self.ps_stab_spin.value()
        
        background = None
        main_win = self.window()
        if hasattr(main_win, 'live_view'):
            background = main_win.live_view.background_frame

        self._worker = PowerSeriesWorker(
            self.hw, powers, data_dir, metadata, 
            background=background,
            processing_mode=processing_mode,
            stabilization_delay=stab_delay
        )
        self._worker.progress.connect(self._on_ps_progress)
        self._worker.finished.connect(self._on_ps_finished)
        self._worker.measurement_ready.connect(self.measurement_ready.emit)
        
        # Notify that sequence has started
        self.sequence_started.emit(powers, powers[0], 1)
        
        # Update UI state
        self.power_run_btn.setText("STOP POWER SERIES")
        self.power_run_btn.setStyleSheet("background-color: #c0392b; color: white; font-weight: bold;")
        self.power_run_btn.setEnabled(True)
        self.heating_run_btn.setEnabled(False)
        
        self._worker.start()

    def _on_ps_progress(self, step_idx, status, percent):
        """Update the power table as the sequence progresses."""
        if 0 < step_idx <= self.power_table.rowCount():
            item = self.power_table.item(step_idx-1, 0)
            if item is not None:
                self.power_table.scrollToItem(item)
        
        self.step_progress.emit(step_idx, status, percent)

    def _on_ps_finished(self, success, message):
        """Handle completion of the power series sweep."""
        self.power_run_btn.setText("START POWER SERIES")
        self.power_run_btn.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold;")
        self.power_run_btn.setEnabled(True)
        self.heating_run_btn.setEnabled(True)
        
        if success:
            QMessageBox.information(self, "Power Series Complete", message)
            
        self.sequence_finished.emit(success, message)
        if not success and "aborted" not in message.lower():
            QMessageBox.critical(self, "Power Series Failed", message)

    def _create_mapping_group(self) -> QGroupBox:
        """Create controls for XY Mapping automated scan."""
        group = QGroupBox("XY Spatial Mapping")
        group.setStyleSheet("QGroupBox { font-weight: bold; }")
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        group.setLayout(layout)
        
        max_limit = self._get_stage_physical_limit() - 5.0

        # --- Grid Definition ---
        grid_group = QGroupBox("Grid Settings")
        grid_group.setStyleSheet("QGroupBox { font-weight: normal; }")
        grid_layout = QHBoxLayout()
        grid_group.setLayout(grid_layout)

        # Left side: Shape Selection
        shape_container = QWidget()
        shape_vlayout = QVBoxLayout(shape_container)
        shape_vlayout.setContentsMargins(0, 0, 0, 0)
        shape_vlayout.setSpacing(5)
        
        shape_row1 = QHBoxLayout()
        shape_row1.addWidget(QLabel("Scan Shape:"))
        self.map_shape_combo = QComboBox()
        self.map_shape_combo.addItems(["Rectangle (Full Grid)", "Circle (Circular Window)"])
        self.map_shape_combo.setFixedWidth(180)
        shape_row1.addWidget(self.map_shape_combo)
        shape_row1.addStretch()
        shape_vlayout.addLayout(shape_row1)
        
        shape_row2 = QHBoxLayout()
        self.map_diameter_label = QLabel("Diameter:")
        self.map_diameter_spin = QDoubleSpinBox()
        self.map_diameter_spin.setRange(0.1, max_limit)
        self.map_diameter_spin.setValue(max_limit)
        self.map_diameter_spin.setSingleStep(1.0)
        self.map_diameter_spin.setSuffix(" mm")
        self.map_diameter_spin.setFixedWidth(100)
        shape_row2.addWidget(self.map_diameter_label)
        shape_row2.addWidget(self.map_diameter_spin)
        shape_row2.addStretch()
        shape_vlayout.addLayout(shape_row2)
        
        # Connect change event
        self.map_shape_combo.currentIndexChanged.connect(self._on_map_shape_changed)

        grid_layout.addWidget(shape_container)
        
        # Add vertical line separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        grid_layout.addWidget(line)

        # Right side: X and Y range control rows
        range_container = QWidget()
        range_vlayout = QVBoxLayout(range_container)
        range_vlayout.setContentsMargins(0, 0, 0, 0)
        range_vlayout.setSpacing(5)

        # X Controls
        x_row = QHBoxLayout()
        x_lbl = QLabel("X range (mm):")
        x_lbl.setFixedWidth(85)
        x_row.addWidget(x_lbl)
        self.map_x_start = QDoubleSpinBox()
        self.map_x_start.setRange(0.0, max_limit)
        self.map_x_start.setFixedWidth(75)
        x_row.addWidget(self.map_x_start)
        x_row.addWidget(QLabel("to"))
        self.map_x_end = QDoubleSpinBox()
        self.map_x_end.setRange(0.0, max_limit)
        self.map_x_end.setFixedWidth(75)
        x_row.addWidget(self.map_x_end)
        
        x_row.addSpacing(10)
        x_row.addWidget(QLabel("Step (mm):"))
        self.map_x_step = QDoubleSpinBox()
        self.map_x_step.setRange(0.001, max_limit)
        self.map_x_step.setValue(5.0)
        self.map_x_step.setSingleStep(1.0)
        self.map_x_step.setFixedWidth(75)
        x_row.addWidget(self.map_x_step)
        x_row.addStretch()
        range_vlayout.addLayout(x_row)

        # Y Controls
        y_row = QHBoxLayout()
        y_lbl = QLabel("Y range (mm):")
        y_lbl.setFixedWidth(85)
        y_row.addWidget(y_lbl)
        self.map_y_start = QDoubleSpinBox()
        self.map_y_start.setRange(0.0, max_limit)
        self.map_y_start.setFixedWidth(75)
        y_row.addWidget(self.map_y_start)
        y_row.addWidget(QLabel("to"))
        self.map_y_end = QDoubleSpinBox()
        self.map_y_end.setRange(0.0, max_limit)
        self.map_y_end.setFixedWidth(75)
        y_row.addWidget(self.map_y_end)
        
        y_row.addSpacing(10)
        y_row.addWidget(QLabel("Step (mm):"))
        self.map_y_step = QDoubleSpinBox()
        self.map_y_step.setRange(0.001, max_limit)
        self.map_y_step.setValue(5.0)
        self.map_y_step.setSingleStep(1.0)
        self.map_y_step.setFixedWidth(75)
        y_row.addWidget(self.map_y_step)
        y_row.addStretch()
        range_vlayout.addLayout(y_row)

        grid_layout.addWidget(range_container)
        grid_layout.setStretch(0, 1)
        grid_layout.setStretch(2, 2)

        layout.addWidget(grid_group)

        # --- Table + Preview side-by-side ---
        content_splitter = QSplitter(Qt.Orientation.Horizontal)
        content_splitter.setChildrenCollapsible(False)

        self.map_table = QTableWidget()
        self.map_table.setColumnCount(3)
        self.map_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.map_table.setHorizontalHeaderLabels(["Idx", "X (mm)", "Y (mm)"])
        map_header = self.map_table.horizontalHeader()
        if map_header is not None:
            map_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.map_table.setMinimumWidth(200)
        content_splitter.addWidget(self.map_table)

        self.map_preview = MapPreviewWidget()
        self.map_preview.setMinimumWidth(200)
        self.map_preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        content_splitter.addWidget(self.map_preview)
        content_splitter.setStretchFactor(0, 2)  # table gets more space
        content_splitter.setStretchFactor(1, 1)  # preview gets less

        layout.addWidget(content_splitter)

        # Connect signals for live update
        self.map_x_start.valueChanged.connect(self._on_map_bounds_changed)
        self.map_x_end.valueChanged.connect(self._on_map_bounds_changed)
        self.map_x_step.valueChanged.connect(lambda _: self._on_generate_map())
        self.map_y_start.valueChanged.connect(self._on_map_bounds_changed)
        self.map_y_end.valueChanged.connect(self._on_map_bounds_changed)
        self.map_y_step.valueChanged.connect(lambda _: self._on_generate_map())
        self.map_diameter_spin.valueChanged.connect(self._update_map_spinbox_limits)
        self.map_diameter_spin.valueChanged.connect(lambda _: self._on_generate_map())
        self.map_table.itemSelectionChanged.connect(self._on_map_table_selection_changed)

        # --- Controls ---
        ctrl_layout = QHBoxLayout()
        
        ctrl_layout.addWidget(QLabel("Stabilization Delay (s):"))
        self.map_stab_spin = QDoubleSpinBox()
        self.map_stab_spin.setRange(0, 10)
        self.map_stab_spin.setValue(1.0)
        self.map_stab_spin.setFixedWidth(80)
        ctrl_layout.addWidget(self.map_stab_spin)
        
        ctrl_layout.addStretch()

        self.map_run_btn = QPushButton("START MAPPING")
        
        self.map_run_btn.setFixedWidth(160)
        self.map_run_btn.clicked.connect(self._on_run_mapping)
        self.map_run_btn.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold;")
        self.map_run_btn.hide()
        ctrl_layout.addWidget(self.map_run_btn)
        
        layout.addLayout(ctrl_layout)

        # Hide diameter fields initially
        self.map_diameter_label.setVisible(False)
        self.map_diameter_spin.setVisible(False)
        
        # Initial map generation
        QTimer.singleShot(0, self._on_generate_map)

        return group

    def _on_map_shape_changed(self):
        """Toggle diameter selection fields visibility."""
        is_circle = self.map_shape_combo.currentText() == "Circle (Circular Window)"
        self.map_diameter_label.setVisible(is_circle)
        self.map_diameter_spin.setVisible(is_circle)
        self._update_map_spinbox_limits()
        self._on_generate_map()

    def _get_stage_physical_limit(self) -> float:
        """Get the stage physical limit from config, defaulting to 50.0 mm."""
        hw_cfg = self.hw.config.get('hardware', {}).get('accessories', [])
        # Find stage_x or stage_y limit
        stage_cfg = next((c for c in hw_cfg if c['id'] in ('stage_x', 'stage_y')), None)
        if stage_cfg:
            return float(stage_cfg.get('physical_limit', 50.0))
        return 50.0

    def _update_map_spinbox_limits(self):
        """Limit the mapping range spinboxes to the diameter if using circular mapping."""
        is_circle = self.map_shape_combo.currentText() == "Circle (Circular Window)"
        max_limit = self._get_stage_physical_limit() - 5.0
        limit = self.map_diameter_spin.value() if is_circle else max_limit
        
        self.map_x_start.setMaximum(limit)
        self.map_x_end.setMaximum(limit)
        self.map_y_start.setMaximum(limit)
        self.map_y_end.setMaximum(limit)
        
    def _on_map_table_selection_changed(self):
        """Highlight the selected point in the map preview."""
        selected = self.map_table.selectedItems()
        if hasattr(self, 'map_preview'):
            if selected:
                row = selected[0].row()
                self.map_preview.set_selected_index(row)
            else:
                self.map_preview.set_selected_index(-1)


    def _on_map_bounds_changed(self):
        """Ensure start <= end. If they cross, push the other boundary."""
        sender = self.sender()
        self.map_x_start.blockSignals(True)
        self.map_x_end.blockSignals(True)
        self.map_y_start.blockSignals(True)
        self.map_y_end.blockSignals(True)
        
        if self.map_x_start.value() > self.map_x_end.value():
            if sender == self.map_x_start:
                self.map_x_end.setValue(self.map_x_start.value())
            elif sender == self.map_x_end:
                self.map_x_start.setValue(self.map_x_end.value())
                
        if self.map_y_start.value() > self.map_y_end.value():
            if sender == self.map_y_start:
                self.map_y_end.setValue(self.map_y_start.value())
            elif sender == self.map_y_end:
                self.map_y_start.setValue(self.map_y_end.value())
                
        self.map_x_start.blockSignals(False)
        self.map_x_end.blockSignals(False)
        self.map_y_start.blockSignals(False)
        self.map_y_end.blockSignals(False)
        self._on_generate_map()

    def _on_generate_map(self):
        """Populate the table with the points in the grid scan, filtering for circle if needed."""
        x_step = self.map_x_step.value()
        y_step = self.map_y_step.value()
        
        if x_step <= 1e-6 or y_step <= 1e-6:
            return
            
        x_min = self.map_x_start.value()
        x_max = self.map_x_end.value()
        y_min = self.map_y_start.value()
        y_max = self.map_y_end.value()
        
        # User requested mapping to start from the right bottom corner.
        # Since 0,0 is the right-bottom corner and +X goes Left, +Y goes Up:
        # Starting at right-bottom means starting at (x_min, y_min)
        xs = np.arange(x_min, x_max + x_step/10.0, x_step)
        ys = np.arange(y_min, y_max + y_step/10.0, y_step)

        points = []
        is_circle = self.map_shape_combo.currentText() == "Circle (Circular Window)"
        if is_circle:
            radius = self.map_diameter_spin.value() / 2.0
            # If 0,0 is the right bottom corner of the circular window,
            # then the physical center of the window is at (radius, radius)
            x_center = radius
            y_center = radius
            
            for y in ys:
                for x in xs:
                    dist = np.sqrt((x - x_center)**2 + (y - y_center)**2)
                    if dist <= radius + 1e-6:
                        points.append((x, y))
        else:
            for y in ys:
                for x in xs:
                    points.append((x, y))
        
        total = len(points)
        if total > 5000:
            # Silently return if > 5000 points to prevent UI freeze during live update
            self.map_table.setRowCount(0)
            if hasattr(self, 'map_preview'):
                self.map_preview.clear()
            return

        self.map_table.setRowCount(0)
        self.map_table.setSortingEnabled(False)
        idx = 1
        for x, y in points:
            row = self.map_table.rowCount()
            self.map_table.insertRow(row)
            self.map_table.setItem(row, 0, NumericTableWidgetItem(str(idx)))
            self.map_table.setItem(row, 1, NumericTableWidgetItem(f"{x:.3f}"))
            self.map_table.setItem(row, 2, NumericTableWidgetItem(f"{y:.3f}"))
            idx += 1
        self.map_table.setSortingEnabled(True)


        # Update the preview canvas
        is_circle = self.map_shape_combo.currentText() == "Circle (Circular Window)"
        
        # Use full circle view for circles, or configured ranges for rectangles
        if is_circle:
            diameter = self.map_diameter_spin.value()
            preview_x_min = 0.0
            preview_x_max = diameter
            preview_y_min = 0.0
            preview_y_max = diameter
        else:
            preview_x_min = x_min
            preview_x_max = x_max
            preview_y_min = y_min
            preview_y_max = y_max
        
        if hasattr(self, 'map_preview'):
            self.map_preview.set_data(
                points,
                x_min=preview_x_min, x_max=preview_x_max,
                y_min=preview_y_min, y_max=preview_y_max,
                shape="circle" if is_circle else "rectangle",
                diameter=self.map_diameter_spin.value() if is_circle else 0.0
            )

    def _on_run_mapping(self):
        """Start the background mapping worker."""
        if self._worker and self._worker.isRunning():
            self.stop_sequence()
            return

        if self.map_table.rowCount() == 0:
            self._on_generate_map()
        
        if self.map_table.rowCount() == 0: return

        # Extract coordinates from the table widget in the exact visual order
        points = []
        for row in range(self.map_table.rowCount()):
            x_item = self.map_table.item(row, 1)
            y_item = self.map_table.item(row, 2)
            if x_item is not None and y_item is not None:
                try:
                    x_val = float(x_item.text())
                    y_val = float(y_item.text())
                    points.append((x_val, y_val))
                except ValueError:
                    logger.error(f"Invalid coordinate values at row {row}: X='{x_item.text()}', Y='{y_item.text()}'")

        if len(points) == 0:
            QMessageBox.warning(self, "Empty Map", "No valid coordinate points found in the grid table.")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        data_dir = os.path.join(self.hw.config.get('paths', {}).get('data_root', './data'), f"map_{timestamp}")
        
        metadata = self.hw.collect_metadata()
        processing_mode = self.hw.data_processing_mode
        stab_delay = self.map_stab_spin.value()

        background = None
        main_win = self.window()
        if hasattr(main_win, 'live_view'):
            background = main_win.live_view.background_frame

        self._worker = MappingWorker(
            self.hw, points,
            data_dir, metadata,
            background=background,
            processing_mode=processing_mode,
            stabilization_delay=stab_delay
        )
        self._worker.progress.connect(self._on_mapping_progress)
        self._worker.finished.connect(self._on_mapping_finished)
        self._worker.measurement_ready.connect(self.measurement_ready.emit)
        
        # Update UI state
        self.map_run_btn.setText("STOP MAPPING")
        self.map_run_btn.setStyleSheet("background-color: #c0392b; color: white; font-weight: bold;")
        self.map_run_btn.setEnabled(True)
        self.heating_run_btn.setEnabled(False)
        self.power_run_btn.setEnabled(False)
        
        self.sequence_started.emit(points, 0.0, 1)
        self._worker.start()

    def _on_mapping_progress(self, idx, status, percent):
        if 0 < idx <= self.map_table.rowCount():
            item = self.map_table.item(idx-1, 0)
            if item is not None:
                self.map_table.scrollToItem(item)
        
        self.step_progress.emit(idx, status, percent)

    def _on_mapping_finished(self, success, message):
        self.map_run_btn.setText("START MAPPING")
        self.map_run_btn.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold;")
        self.map_run_btn.setEnabled(True)
        self.heating_run_btn.setEnabled(True)
        self.power_run_btn.setEnabled(True)
        
        if success:
            QMessageBox.information(self, "Mapping Complete", message)
            
        self.sequence_finished.emit(success, message)

    def _create_custom_sequence_group(self) -> QGroupBox:
        """Create controls for the generic custom sequence editor."""
        group = QGroupBox("General Custom Sequence Editor")
        group.setStyleSheet("QGroupBox { font-weight: bold; }")
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        group.setLayout(layout)

        # Toolbar
        toolbar = QHBoxLayout()
        
        add_btn = QPushButton("+")
        add_btn.setFixedWidth(30)
        add_btn.clicked.connect(self._on_add_custom_step)
        toolbar.addWidget(add_btn)
        
        remove_btn = QPushButton("-")
        remove_btn.setFixedWidth(30)
        remove_btn.clicked.connect(self._on_remove_custom_step)
        toolbar.addWidget(remove_btn)
        
        clear_btn = QPushButton("Clear All")
        clear_btn.setFixedWidth(80)
        clear_btn.clicked.connect(self._on_clear_custom_steps)
        toolbar.addWidget(clear_btn)
        
        toolbar.addSpacing(5)

        repeat_btn = QPushButton("Repeat / Loop...")
        repeat_btn.setToolTip("Repeat a range of steps in a loop or duplicate them")
        repeat_btn.clicked.connect(self._on_repeat_custom_steps_dialog)
        toolbar.addWidget(repeat_btn)
        
        toolbar.addSpacing(10)
        
        import_btn = QPushButton("Import JSON")
        import_btn.setFixedWidth(100)
        import_btn.clicked.connect(self._on_import_custom_sequence)
        toolbar.addWidget(import_btn)
        
        export_btn = QPushButton("Export JSON")
        export_btn.setFixedWidth(100)
        export_btn.clicked.connect(self._on_export_custom_sequence)
        toolbar.addWidget(export_btn)
        
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Table
        self.custom_seq_table = ReorderableTableWidget()
        self.custom_seq_table.setColumnCount(4)
        self.custom_seq_table.setHorizontalHeaderLabels(["Step #", "Action", "Parameters", "Label/Comment"])
        self.custom_seq_table.order_changed.connect(self._reindex_custom_steps)
        self.custom_seq_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.custom_seq_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        header = self.custom_seq_table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.custom_seq_table.setMinimumHeight(200)
        layout.addWidget(self.custom_seq_table)

        # Start button (Hidden, same as others)
        self.custom_run_btn = QPushButton("START CUSTOM SEQUENCE")
        self.custom_run_btn.setFixedWidth(160)
        self.custom_run_btn.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold;")
        self.custom_run_btn.hide()
        layout.addWidget(self.custom_run_btn)

        return group

    def _on_add_custom_step(self):
        row = self.custom_seq_table.currentRow()
        if row < 0:
            row = self.custom_seq_table.rowCount()
        else:
            row += 1
            
        self.custom_seq_table.insertRow(row)
        
        # 1. Step # (non-editable)
        step_item = QTableWidgetItem()
        step_item.setFlags(step_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.custom_seq_table.setItem(row, 0, step_item)
        
        # 2. Action (ComboBox)
        act_combo = QComboBox()
        act_combo.addItems([
            "Wait / Stabilize",
            "Shutter (linked)",
            "Polarizer Angle",
            "Polarizer Power (calibrated)",
            "Move Stage X",
            "Move Stage Y",
            "Collect Spectrum",
            "Repeat / Loop"
        ])
        act_combo.currentIndexChanged.connect(self._on_custom_action_changed)


        self.custom_seq_table.setCellWidget(row, 1, act_combo)
        
        # 3. Parameters (Default is Wait/Stabilize: spinbox)
        self._update_row_parameter_widget(row, "Wait / Stabilize")
        
        # 4. Comment / Label
        comment_item = QTableWidgetItem("")
        self.custom_seq_table.setItem(row, 3, comment_item)
        
        self._reindex_custom_steps()

    def _on_custom_action_changed(self):
        combo = self.sender()
        if not isinstance(combo, QComboBox):
            return
        
        # Find which row this combo belongs to
        row = -1
        for r in range(self.custom_seq_table.rowCount()):
            if self.custom_seq_table.cellWidget(r, 1) == combo:
                row = r
                break
                
        if row >= 0:
            action = combo.currentText()
            self._update_row_parameter_widget(row, action)

    def _update_row_parameter_widget(self, row: int, action: str):
        max_limit = self._get_stage_physical_limit() - 5.0
        
        if action == "Wait / Stabilize":
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 3600.0)
            spin.setValue(1.0)
            spin.setSuffix(" s")
            self.custom_seq_table.setCellWidget(row, 2, spin)
            
        elif action == "Shutter (linked)":
            combo = QComboBox()
            combo.addItem("Open", True)
            combo.addItem("Close", False)
            self.custom_seq_table.setCellWidget(row, 2, combo)
            
        elif action == "Polarizer Angle":
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 360.0)
            spin.setValue(0.0)
            spin.setSuffix(" °")
            self.custom_seq_table.setCellWidget(row, 2, spin)
            
        elif action == "Polarizer Power (calibrated)":
            combo = QComboBox()
            self._populate_power_combo(combo)
            self.custom_seq_table.setCellWidget(row, 2, combo)
            
        elif action in ("Move Stage X", "Move Stage Y"):
            spin = QDoubleSpinBox()
            spin.setRange(0.0, max_limit)
            spin.setValue(0.0)
            spin.setSuffix(" mm")
            self.custom_seq_table.setCellWidget(row, 2, spin)
            
        elif action == "Collect Spectrum":
            edit = QLineEdit()
            edit.setPlaceholderText(f"Prefix (default: step_{row + 1:03d})")
            self.custom_seq_table.setCellWidget(row, 2, edit)

        elif action == "Repeat / Loop":
            default_to = max(1, row)
            total_rows = max(1, self.custom_seq_table.rowCount())
            loop_widget = LoopParamWidget(from_step=1, to_step=default_to, count=2, max_steps=total_rows)
            self.custom_seq_table.setCellWidget(row, 2, loop_widget)

    def _reindex_custom_steps(self):
        total_rows = self.custom_seq_table.rowCount()
        for r in range(total_rows):
            item = self.custom_seq_table.item(r, 0)
            if not item:
                item = QTableWidgetItem()
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.custom_seq_table.setItem(r, 0, item)
            item.setData(Qt.ItemDataRole.EditRole, r + 1)
            item.setText(str(r + 1))
            
            # Update bounds on LoopParamWidget if present, or placeholder on QLineEdit
            param_widget = self.custom_seq_table.cellWidget(r, 2)
            if isinstance(param_widget, LoopParamWidget):
                param_widget.set_max_steps(total_rows)
            elif isinstance(param_widget, QLineEdit):
                param_widget.setPlaceholderText(f"Prefix (default: step_{r + 1:03d})")

    def _on_remove_custom_step(self):
        sel_model = self.custom_seq_table.selectionModel()
        selected_rows = [r.row() for r in sel_model.selectedRows()] if sel_model is not None else []
        if not selected_rows:
            curr = self.custom_seq_table.currentRow()
            if curr >= 0:
                selected_rows = [curr]
            else:
                curr = self.custom_seq_table.rowCount() - 1
                if curr >= 0:
                    selected_rows = [curr]
                    
        if selected_rows:
            for r in sorted(selected_rows, reverse=True):
                self.custom_seq_table.removeRow(r)
            self._reindex_custom_steps()

    def _on_clear_custom_steps(self):
        self.custom_seq_table.setRowCount(0)



    def _serialize_custom_row(self, row: int) -> Dict[str, Any]:
        act_combo = self.custom_seq_table.cellWidget(row, 1)
        action = act_combo.currentText() if isinstance(act_combo, QComboBox) else "Wait / Stabilize"
        
        param_widget = self.custom_seq_table.cellWidget(row, 2)
        params = {}
        if action == "Wait / Stabilize" and isinstance(param_widget, QDoubleSpinBox):
            params['duration'] = param_widget.value()
        elif action == "Shutter (linked)" and isinstance(param_widget, QComboBox):
            params['open'] = param_widget.currentData()
        elif action == "Polarizer Angle" and isinstance(param_widget, QDoubleSpinBox):
            params['angle'] = param_widget.value()
        elif action == "Polarizer Power (calibrated)" and isinstance(param_widget, QComboBox):
            params['power_w'] = param_widget.currentData()
        elif action in ("Move Stage X", "Move Stage Y") and isinstance(param_widget, QDoubleSpinBox):
            params['position'] = param_widget.value()
        elif action == "Repeat / Loop" and isinstance(param_widget, LoopParamWidget):
            from_s, to_s, cnt = param_widget.get_values()
            params['from_step'] = from_s
            params['to_step'] = to_s
            params['count'] = cnt
        elif action == "Collect Spectrum" and isinstance(param_widget, QLineEdit):
            prefix = param_widget.text().strip()
            if prefix:
                params['prefix'] = prefix
            
        comment = ""

        c_item = self.custom_seq_table.item(row, 3)
        if c_item:
            comment = c_item.text()
            
        return {
            'action': action,
            'params': params,
            'comment': comment
        }

    def _deserialize_custom_row(self, row: int, data: Dict[str, Any]):
        # Temporarily block signals to prevent index changed loops
        self.custom_seq_table.blockSignals(True)
        try:
            # Step #
            step_item = QTableWidgetItem(str(row + 1))
            step_item.setFlags(step_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.custom_seq_table.setItem(row, 0, step_item)
            
            # Action Combo
            act_combo = QComboBox()
            act_combo.addItems([
                "Wait / Stabilize",
                "Shutter (linked)",
                "Polarizer Angle",
                "Polarizer Power (calibrated)",
                "Move Stage X",
                "Move Stage Y",
                "Collect Spectrum",
                "Repeat / Loop"
            ])
            act_combo.setCurrentText(data['action'])
            act_combo.currentIndexChanged.connect(self._on_custom_action_changed)


            self.custom_seq_table.setCellWidget(row, 1, act_combo)
            
            # Parameters Widget
            self._update_row_parameter_widget(row, data['action'])
            param_widget = self.custom_seq_table.cellWidget(row, 2)
            
            # Apply parameters
            params = data.get('params', {})
            action = data['action']
            if action == "Wait / Stabilize" and isinstance(param_widget, QDoubleSpinBox):
                if 'duration' in params: param_widget.setValue(params['duration'])
            elif action == "Shutter (linked)" and isinstance(param_widget, QComboBox):
                if 'open' in params:
                    idx = param_widget.findData(params['open'])
                    if idx >= 0: param_widget.setCurrentIndex(idx)
            elif action == "Polarizer Angle" and isinstance(param_widget, QDoubleSpinBox):
                if 'angle' in params: param_widget.setValue(params['angle'])
            elif action == "Polarizer Power (calibrated)" and isinstance(param_widget, QComboBox):
                if 'power_w' in params:
                    idx = param_widget.findData(params['power_w'])
                    if idx >= 0: param_widget.setCurrentIndex(idx)
            elif action in ("Move Stage X", "Move Stage Y") and isinstance(param_widget, QDoubleSpinBox):
                if 'position' in params: param_widget.setValue(params['position'])
            elif action == "Repeat / Loop" and isinstance(param_widget, LoopParamWidget):
                from_s = params.get('from_step', 1)
                to_s = params.get('to_step', 1)
                cnt = params.get('count', 2)
                param_widget.set_values(from_s, to_s, cnt)
            elif action == "Collect Spectrum" and isinstance(param_widget, QLineEdit):
                if 'prefix' in params:
                    param_widget.setText(params['prefix'])
                
            # Comment

            comment_item = QTableWidgetItem(data.get('comment', ''))
            self.custom_seq_table.setItem(row, 3, comment_item)
        finally:
            self.custom_seq_table.blockSignals(False)

    def _on_export_custom_sequence(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Custom Sequence", "", "JSON Files (*.json)")
        if not path:
            return
        
        steps = []
        for r in range(self.custom_seq_table.rowCount()):
            steps.append(self._serialize_custom_row(r))
            
        import json
        try:
            with open(path, 'w') as f:
                json.dump(steps, f, indent=4)
            QMessageBox.information(self, "Success", f"Custom sequence saved to {path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save custom sequence: {e}")

    def _on_import_custom_sequence(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Custom Sequence", "", "JSON Files (*.json)")
        if not path:
            return
            
        import json
        try:
            with open(path, 'r') as f:
                steps = json.load(f)
            
            if not isinstance(steps, list):
                raise ValueError("JSON must contain a list of steps.")
                
            self.custom_seq_table.setRowCount(0)
            for r, step_data in enumerate(steps):
                self.custom_seq_table.insertRow(r)
                self._deserialize_custom_row(r, step_data)
                
            self._reindex_custom_steps()
            QMessageBox.information(self, "Success", f"Imported {len(steps)} steps.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to import custom sequence: {e}")

    def _on_repeat_custom_steps_dialog(self):
        from .sequence_dialog import RepeatCustomStepsDialog
        total_rows = self.custom_seq_table.rowCount()
        if total_rows == 0:
            QMessageBox.information(self, "No Steps", "Please add at least one step to the sequence before configuring a loop.")
            return

        sel_model = self.custom_seq_table.selectionModel()
        selected_rows = [r.row() for r in sel_model.selectedRows()] if sel_model is not None else []
        if selected_rows:
            sel_from = min(selected_rows) + 1
            sel_to = max(selected_rows) + 1
        else:
            curr = self.custom_seq_table.currentRow()
            if curr >= 0:
                sel_from = 1
                sel_to = curr + 1
            else:
                sel_from = 1
                sel_to = total_rows

        dlg = RepeatCustomStepsDialog(total_rows, sel_from=sel_from, sel_to=sel_to, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        f_step, t_step, count, action_mode = dlg.get_values()
        if action_mode == "loop_step":
            insert_row = t_step
            self.custom_seq_table.insertRow(insert_row)
            
            step_item = QTableWidgetItem()
            step_item.setFlags(step_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.custom_seq_table.setItem(insert_row, 0, step_item)
            
            act_combo = QComboBox()
            act_combo.addItems([
                "Wait / Stabilize",
                "Shutter (linked)",
                "Polarizer Angle",
                "Polarizer Power (calibrated)",
                "Move Stage X",
                "Move Stage Y",
                "Collect Spectrum",
                "Repeat / Loop"
            ])
            act_combo.setCurrentText("Repeat / Loop")
            act_combo.currentIndexChanged.connect(self._on_custom_action_changed)
            self.custom_seq_table.setCellWidget(insert_row, 1, act_combo)
            
            loop_widget = LoopParamWidget(f_step, t_step, count, max_steps=self.custom_seq_table.rowCount())
            self.custom_seq_table.setCellWidget(insert_row, 2, loop_widget)
            
            comment_item = QTableWidgetItem(f"Repeat steps {f_step}-{t_step} ({count}x)")
            self.custom_seq_table.setItem(insert_row, 3, comment_item)
            
            self._reindex_custom_steps()
            
        elif action_mode == "duplicate":
            if count <= 1:
                return
            
            rows_to_dup = []
            for r in range(f_step - 1, t_step):
                rows_to_dup.append(self._serialize_custom_row(r))
                
            insert_pos = t_step
            for _ in range(count - 1):
                for row_data in rows_to_dup:
                    self.custom_seq_table.insertRow(insert_pos)
                    self._deserialize_custom_row(insert_pos, row_data)
                    insert_pos += 1
                    
            self._reindex_custom_steps()

    def get_custom_sequence_steps(self) -> List[Dict[str, Any]]:
        """Retrieve the currently defined custom sequence steps."""
        steps = []
        for r in range(self.custom_seq_table.rowCount()):
            # Action (ComboBox)
            act_combo = self.custom_seq_table.cellWidget(r, 1)
            if not isinstance(act_combo, QComboBox): continue
            action = act_combo.currentText()
            
            # Parameters
            param_widget = self.custom_seq_table.cellWidget(r, 2)
            params = {}
            params_desc = ""
            
            if action == "Wait / Stabilize":
                if isinstance(param_widget, QDoubleSpinBox):
                    duration = param_widget.value()
                    params['duration'] = duration
                    params_desc = f"{duration:.2f} s"
            elif action == "Shutter (linked)":
                if isinstance(param_widget, QComboBox):
                    state = param_widget.currentData()
                    params['open'] = state
                    params_desc = "Open" if state else "Close"
            elif action == "Polarizer Angle":
                if isinstance(param_widget, QDoubleSpinBox):
                    angle = param_widget.value()
                    params['angle'] = angle
                    params_desc = f"{angle:.2f}°"
            elif action == "Polarizer Power (calibrated)":
                if isinstance(param_widget, QComboBox):
                    p_w = param_widget.currentData()
                    params['power_w'] = p_w
                    params_desc = param_widget.currentText()
            elif action in ("Move Stage X", "Move Stage Y"):
                if isinstance(param_widget, QDoubleSpinBox):
                    pos = param_widget.value()
                    params['position'] = pos
                    params_desc = f"{pos:.3f} mm"
            elif action == "Collect Spectrum":
                if isinstance(param_widget, QLineEdit):
                    prefix = param_widget.text().strip()
                    if prefix:
                        params['prefix'] = prefix
                        params_desc = f"Prefix: {prefix}"
                    else:
                        params_desc = ""
                else:
                    params_desc = ""
            elif action == "Repeat / Loop":
                if isinstance(param_widget, LoopParamWidget):
                    from_s, to_s, cnt = param_widget.get_values()
                else:
                    from_s = 1
                    to_s = 1
                    cnt = 2
                params['from_step'] = from_s
                params['to_step'] = to_s
                params['count'] = cnt
                params_desc = f"Steps {from_s} to {to_s} ({cnt}x total)"
                
            # Comment / Label

            comment = ""
            comment_item = self.custom_seq_table.item(r, 3)
            if comment_item:
                comment = comment_item.text()
                
            steps.append({
                'action': action,
                'params': params,
                'params_desc': params_desc,
                'comment': comment
            })
        return steps

    def stop_sequence(self):
        """Public method to abort an active sequence."""
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self.heating_run_btn.setText("STOPPING...")
            self.heating_run_btn.setEnabled(False)
            self.power_run_btn.setText("STOPPING...")
            self.power_run_btn.setEnabled(False)
            if hasattr(self, 'map_run_btn'):
                self.map_run_btn.setText("STOPPING...")
                self.map_run_btn.setEnabled(False)
            if hasattr(self, 'custom_run_btn'):
                self.custom_run_btn.setText("STOPPING...")
                self.custom_run_btn.setEnabled(False)
