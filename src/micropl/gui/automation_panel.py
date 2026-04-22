import logging
import time
import threading
import os
import json
import csv
import datetime
import numpy as np
from typing import List, Dict, Any, Optional
from ..qt import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QSpinBox, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, Qt, QComboBox,
    QHeaderView, QThread, pyqtSignal, QFileDialog,
    QMessageBox
)

from ..hardware.manager import HardwareManager

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
        kdc = self.hw.kdc101
        pm = self.hw.get_instrument('pm100')

        if not kdc or not kdc.is_connected():
            self.finished.emit(False, "Motor not connected")
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
        kdc = self.hw.kdc101
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
            kdc.move_by(direction * step_size)
            
            time.sleep(0.3)
            while kdc.is_moving() and self._running:
                time.sleep(0.1)
                
            new_p = pm.read_power()
            new_error = abs(new_p - target_w)
            
            if new_error > error:
                direction *= -1
                step_size *= 0.6
            
            error = new_error
            if step_size < min_step:
                break
                
        return True, kdc.get_position(), pm.read_power()



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
                 cooling_delay: float = 5.0,
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
        logger.info(f"Worker initialized with cooling_delay={self.cooling_delay}s")

    def _calculate_move_time(self, delta_theta: float, v_c: float = 25.0, a: float = 25.0) -> float:
        """Calculate polarizer move time using trapezoidal/triangular motion model."""
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
        kdc = self.hw.kdc101
        cal = self.hw.polarizer_calibration
        
        # Get velocity and acceleration for move time estimation
        kdc_config = self.hw.config.get('hardware', {}).get('kdc101', {})
        v_c = kdc_config.get('velocity', 25.0)
        a = kdc_config.get('acceleration', 25.0)
        
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
        current_angle = kdc.get_position() if kdc else base_angle
        
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
        kdc = self.hw.kdc101
        cam = self.hw.get_spectroscopy_camera()
        cal = self.hw.polarizer_calibration

        # 1. Validation
        if not kdc or not kdc.is_connected():
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
            
            kdc.set_shutter(False) # Safety first
            kdc.move_to(angle)
            while kdc.is_moving() and self._running:
                time.sleep(0.1)
            if not self._running: return False
            time.sleep(1.0) # Stabilization
            return True

        # Helper to acquire and save data for a single step
        def measure(step_name, step_meta, step_idx):
            self.progress.emit(-1, "Measuring spectrum", 0)
            kdc.set_shutter(True)
            
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
            
            # If Live View is active, we synchronize to ensure we don't 
            # try to access the camera driver while it's mid-acquisition.
            if cam.is_acquiring() and hasattr(self.hw, 'service') and self.hw.service:
                frame_ready_event = threading.Event()
                captured_frame = None

                def on_frame(data):
                    nonlocal captured_frame
                    captured_frame = data
                    frame_ready_event.set()

                # Connect temporarily to the service signal
                # Use DirectConnection because on_frame is thread-safe (just sets event)
                self.hw.service.spec_frame_ready.connect(on_frame, Qt.ConnectionType.DirectConnection)
                
                try:
                    # Synchronization with Live View
                    # Wait long enough for exposure + overhead
                    timeout = (exposure_time * 3.0) + 2.0 
                    
                    # Wait for 1-2 frames to ensure the new state (shutter open) is captured
                    # (First frame might have started BEFORE shutter opened)
                    if frame_ready_event.wait(timeout):
                        frame_ready_event.clear()
                        if frame_ready_event.wait(timeout):
                            raw_data = captured_frame
                        else:
                            logger.warning(f"Live capture (2nd frame) timed out after {timeout}s")
                            raw_data = cam.acquire_spectrum()
                    else:
                        logger.warning(f"Live capture (1st frame) timed out after {timeout}s")
                        raw_data = cam.acquire_spectrum()
                finally:
                    self.hw.service.spec_frame_ready.disconnect(on_frame)
            else:
                raw_data = cam.acquire_spectrum()
            
            # Ensure data is 1D for spectrum saving
            if raw_data.ndim == 2:
                logger.debug(f"Collapsing 2D frame {raw_data.shape} to 1D spectrum")
                raw_data = np.sum(raw_data, axis=0)
            
            kdc.set_shutter(False)
            
            # 2. Process Data (Background Correction + Time Normalization)
            # Use the unified processing logic from HardwareManager
            from ..core.measurement import MeasurementResult
            from ..core.data_manager import DataManager
            from datetime import datetime
            
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
            # is merged into the 'laser' group if it belongs there
            if 'laser' in step_meta:
                 if 'laser' not in full_meta:
                     full_meta['laser'] = {}
                 full_meta['laser'].update(step_meta['laser'])
            else:
                 # Check for flat keys that should be in laser
                 laser_keys = ['Excitation Power (W)', 'Wavelength (nm)', 'Mode']
                 for k in laser_keys:
                     if k in step_meta:
                         if 'laser' not in full_meta:
                             full_meta['laser'] = {}
                         full_meta['laser'][k] = step_meta[k]
                 
            # Merge remaining step_meta
            for k, v in step_meta.items():
                if k != 'laser' and k not in ['Excitation Power (W)', 'Wavelength (nm)', 'Mode']:
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
                'step': {
                    'Step Type': 'Baseline',
                    'Sequence Step Number': 0
                },
                'laser': {
                    'Excitation Power (W)': self.meas_power_w
                }
            }
            # Step 0 filename matching the pattern: P=0mW (heating power), t=0s
            if not measure("step_000_P_0,0mW_t_0s", meta_0, 0): return
            current_phase += 2
        
        # --- LOOP STEPS ---
        offset = self.start_index if self.start_index > 0 else 1
        for i, step in enumerate(self.steps):
            if not self._running: break
            
            step_idx = i + offset
            h_power = step['target_w']
            h_duration = step['duration']
            
            # 1. Heating Phase
            percent = int((current_phase / total_phases) * 100)
            if not set_power(h_power, f"Heating {step_idx}", step_idx): break
            
            p_str = format_power_w(h_power)
            self.progress.emit(step_idx, f"Heating at {p_str} for {h_duration}s", percent)
            
            kdc.set_shutter(True)
            # Timed sleep
            end_time = time.time() + h_duration
            while time.time() < end_time and self._running:
                time.sleep(0.1)
            kdc.set_shutter(False)
            current_phase += 1
            if not self._running: break

            # 2. Measurement Phase
            percent = int((current_phase / total_phases) * 100)
            # set_power will emit its own "Moving for Measure X..." status
            if not set_power(self.meas_power_w, f"Measure {step_idx}", step_idx): break
            
            # Open shutter for Live View observation during cooling
            kdc.set_shutter(True)

            # --- THERMALIZATION / COOLING DELAY ---
            if self.cooling_delay > 0:
                self.progress.emit(step_idx, f"Cooling for {self.cooling_delay}s", percent)
                end_cooling = time.time() + self.cooling_delay
                while time.time() < end_cooling and self._running:
                    time.sleep(0.5)
                if not self._running: break

            p_str = format_power_w(h_power)
            meta_step = {
                'step': {
                    'Step Type': 'Laser Heating Cycle',
                    'Sequence Step Number': step_idx,
                    'Heating Power (W)': h_power,
                    'Heating Duration (s)': h_duration
                },
                'laser': {
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
            kdc.set_shutter(False)
            self.finished.emit(False, "Sequence aborted by user")
        else:
            # Leave shutter OPEN after successful completion as requested
            kdc.set_shutter(True)
            
            # Emit the correct final absolute step index
            offset = self.start_index if self.start_index > 0 else 1
            last_idx = (len(self.steps) - 1) + offset if len(self.steps) > 0 else 0
            
            self.progress.emit(last_idx, "Status: Complete", 100)
            self.finished.emit(True, f"Successfully completed sequence. Data saved to {self.data_dir}")


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
        from ..qt import QSplitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # 1. Polarizer Calibration (Needed for power targeting)
        pol_group = self._create_polarizer_calibration_group()
        splitter.addWidget(pol_group)

        # 2. Laser Heating Sequence
        heating_group = self._create_laser_heating_group()
        splitter.addWidget(heating_group)

        # Stretch/Proportions
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1) # Equal width initially
        
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
        
        add_btn = QPushButton("Add Level")
        add_btn.setFixedWidth(80)
        add_btn.clicked.connect(self._on_add_pol_point)
        btn_layout.addWidget(add_btn)
        
        remove_btn = QPushButton("Remove")
        remove_btn.setFixedWidth(80)
        remove_btn.clicked.connect(self._on_remove_pol_point)
        btn_layout.addWidget(remove_btn)
        
        btn_layout.addStretch()

        self.pol_run_sel_btn = QPushButton("Calibrate Selected")
        self.pol_run_sel_btn.setFixedWidth(140)
        self.pol_run_sel_btn.clicked.connect(self._on_calibrate_selected)
        self.pol_run_sel_btn.setStyleSheet("background-color: #e8f5e9; font-weight: normal;")
        btn_layout.addWidget(self.pol_run_sel_btn)
        
        self.pol_run_btn = QPushButton("Calibrate All")
        self.pol_run_btn.setFixedWidth(120)
        self.pol_run_btn.clicked.connect(self._on_calibrate_all)
        self.pol_run_btn.setStyleSheet("background-color: #e3f2fd; font-weight: bold;")
        btn_layout.addWidget(self.pol_run_btn)
        
        layout.addLayout(btn_layout)

        # Table
        self.pol_table = QTableWidget()
        self.pol_table.setColumnCount(4)
        self.pol_table.setHorizontalHeaderLabels(["Target Power", "Unit", "Found Angle (°)", "Status"])
        self.pol_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.pol_table.setSelectionBehavior(QHeaderView.SelectionBehavior.SelectRows)
        self.pol_table.setSelectionMode(QHeaderView.SelectionMode.ExtendedSelection)
        self.pol_table.setMinimumHeight(250)
        layout.addWidget(self.pol_table)
        
        # Persistence
        io_layout = QHBoxLayout()
        save_btn = QPushButton("Save Table")
        save_btn.clicked.connect(self._on_save_pol_cal)
        io_layout.addWidget(save_btn)
        
        load_btn = QPushButton("Load Table")
        load_btn.clicked.connect(self._on_load_pol_cal)
        io_layout.addWidget(load_btn)
        
        clear_btn = QPushButton("Clear All")
        clear_btn.clicked.connect(lambda: self.pol_table.setRowCount(0))
        io_layout.addWidget(clear_btn)
        
        layout.addLayout(io_layout)
        
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
        selected_rows = [r.row() for r in self.pol_table.selectionModel().selectedRows()]
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
        selected_rows = [r.row() for r in self.pol_table.selectionModel().selectedRows()]
        
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
        kdc = self.hw.kdc101
        pm = self.hw.get_instrument('pm100')
        
        missing = []
        if not kdc or not kdc.is_connected():
            missing.append("Polarizer (KDC101)")
        if not pm or not pm.is_connected():
            missing.append("Power Meter (PM100)")
            
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
            if spin and unit_cb:
                val = spin.value()
                unit = unit_cb.currentText()
                target_w = val * multipliers[unit]
                points.append((r, target_w))
                self.pol_table.item(r, 3).setText("Queued")
        
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
        if success:
            self.pol_table.item(row, 2).setText(f"{angle:.3f}")
            self.pol_table.item(row, 3).setText("Done")
            self.pol_table.item(row, 3).setForeground(Qt.GlobalColor.green)
            
            # Gray out / lock the input widgets
            p_spin = self.pol_table.cellWidget(row, 0)
            u_combo = self.pol_table.cellWidget(row, 1)
            if p_spin: p_spin.setEnabled(False)
            if u_combo: u_combo.setEnabled(False)
        else:
            self.pol_table.item(row, 3).setText(f"Error: {message}")
            self.pol_table.item(row, 3).setForeground(Qt.GlobalColor.red)

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
            
            if spin and unit_cb and angle_item:
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

        # --- Baseline measurement config ---
        base_layout = QHBoxLayout()
        base_layout.addWidget(QLabel("Measurement (PL) Power:"))
        self.meas_power_combo = QComboBox()
        self.meas_power_combo.setToolTip("Select a calibrated power level for PL measurements")
        base_layout.addWidget(self.meas_power_combo)
        
        base_layout.addStretch()
        layout.addLayout(base_layout)

        # --- Sequence Table Toolbar ---
        table_toolbar = QHBoxLayout()
        
        add_btn = QPushButton("Add Step")
        add_btn.clicked.connect(self._on_add_heating_step)
        table_toolbar.addWidget(add_btn)
        
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self._on_remove_heating_step)
        table_toolbar.addWidget(remove_btn)
        
        clear_btn = QPushButton("Clear All")
        clear_btn.clicked.connect(lambda: self.heating_table.setRowCount(0))
        table_toolbar.addWidget(clear_btn)
        
        from ..qt import QFrame
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        table_toolbar.addWidget(line)
        
        import_btn = QPushButton("Import CSV")
        import_btn.clicked.connect(self._on_import_sequence)
        table_toolbar.addWidget(import_btn)
        
        export_btn = QPushButton("Export CSV")
        export_btn.clicked.connect(self._on_export_sequence)
        table_toolbar.addWidget(export_btn)
        
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
        bulk_layout.addWidget(self.bulk_n_spin)
        bulk_layout.addWidget(QLabel("steps at"))
        
        self.bulk_power_combo = QComboBox()
        bulk_layout.addWidget(self.bulk_power_combo)
        
        bulk_layout.addWidget(QLabel("for"))
        self.bulk_dur_spin = QDoubleSpinBox()
        self.bulk_dur_spin.setRange(0.1, 3600)
        self.bulk_dur_spin.setValue(1.0)
        bulk_layout.addWidget(self.bulk_dur_spin)
        bulk_layout.addWidget(QLabel("s each"))
        
        insert_bulk_btn = QPushButton("Insert Steps")
        insert_bulk_btn.clicked.connect(self._on_insert_bulk_steps)
        bulk_layout.addWidget(insert_bulk_btn)
        
        layout.addWidget(bulk_group)

        # --- Table ---
        self.heating_table = QTableWidget()
        self.heating_table.setColumnCount(4)
        self.heating_table.setHorizontalHeaderLabels(["Step #", "Heat Power", "Duration (s)", "Status"])
        self.heating_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
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
        self.cooling_delay_spin.setValue(5.0)
        self.cooling_delay_spin.setSuffix(" s")
        self.cooling_delay_spin.setToolTip("Wait time after heating pulse to return to cryostat temperature")
        ctrl_layout.addWidget(self.cooling_delay_spin)
        
        ctrl_layout.addStretch()
        
        layout.addLayout(ctrl_layout)
        
        return group


    def get_cooling_delay(self) -> float:
        """Get the current cooling delay value in seconds."""
        return self.cooling_delay_spin.value()

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
        
        # Status
        self.heating_table.setItem(row, 3, QTableWidgetItem("Ready"))
        
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
            
            self.heating_table.setItem(row, 3, QTableWidgetItem("Ready"))
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

    def _update_power_selections(self, select_min=False):
        """Refresh all power dropdowns in the UI when calibration changes."""
        self._populate_power_combo(self.meas_power_combo)
        self._populate_power_combo(self.bulk_power_combo)
        
        if select_min and self.meas_power_combo.count() > 0:
            # First item in the combo is the lowest power because _populate_power_combo sorts them
            self.meas_power_combo.setCurrentIndex(0)

        for r in range(self.heating_table.rowCount()):
            p_combo = self.heating_table.cellWidget(r, 1)
            if isinstance(p_combo, QComboBox):
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
            import csv
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
                    
                    self.heating_table.setItem(r, 3, QTableWidgetItem("Ready"))
            
            self._reindex_heating_steps()
            QMessageBox.information(self, "Success", f"Imported {self.heating_table.rowCount()} steps.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to import sequence: {e}")

    def _on_export_sequence(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Sequence", "", "CSV Files (*.csv)")
        if not path: return
        
        try:
            import csv
            with open(path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["Power (label)", "Power (W)", "Duration (s)"])
                for r in range(self.heating_table.rowCount()):
                    p_combo = self.heating_table.cellWidget(r, 1)
                    p_label = p_combo.currentText()
                    p_w = p_combo.currentData()
                    d = self.heating_table.cellWidget(r, 2).value()
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
            p_w = p_combo.currentData()
            if p_w is None:
                QMessageBox.warning(self, "Uncalibrated Power", f"Step {r+1} has no calibrated power selected.")
                return
            dur = self.heating_table.cellWidget(r, 2).value()
            steps.append({'target_w': float(p_w), 'duration': dur})
            self.heating_table.item(r, 3).setText("Queued")
        
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
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
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
            start_index=max(1, self.start_step_spin.value())
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
            # (Row highlighting logic remains)
            # Update table status
            if 0 < step_idx <= self.heating_table.rowCount():
                self.heating_table.scrollToItem(self.heating_table.item(step_idx-1, 3))
                self.heating_table.item(step_idx-1, 3).setText("Running...")
                self.heating_table.item(step_idx-1, 3).setForeground(Qt.GlobalColor.blue)
                # Mark previous as done
                if step_idx > 1:
                    self.heating_table.item(step_idx-2, 3).setText("Done")
                    self.heating_table.item(step_idx-2, 3).setForeground(Qt.GlobalColor.green)
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
            # Mark last step as done
            rc = self.heating_table.rowCount()
            if rc > 0:
                self.heating_table.item(rc-1, 3).setText("Done")
                self.heating_table.item(rc-1, 3).setForeground(Qt.GlobalColor.green)
            QMessageBox.information(self, "Sequence Complete", message)
        # Forward to monitor
        self.sequence_finished.emit(success, message)
        if not success:
            if "aborted" not in message.lower():
                QMessageBox.critical(self, "Sequence Failed", message)

    def stop_sequence(self):
        """Public method to abort an active sequence."""
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self.heating_run_btn.setText("STOPPING...")
            self.heating_run_btn.setEnabled(False)
