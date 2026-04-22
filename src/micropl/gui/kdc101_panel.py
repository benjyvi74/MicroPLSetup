import logging
from ..qt import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGroupBox, QDoubleSpinBox, QGridLayout, 
    QFrame, Qt, QTimer, pyqtSlot, QDialog, QDialogButtonBox,
    QThread, pyqtSignal, QComboBox, QApplication, QButtonGroup
)
import numpy as np
import time
import threading

from ..hardware.manager import HardwareManager

logger = logging.getLogger(__name__)


class PowerSeeker(QThread):
    """
    Background worker for iterative power-targeted polarizer control.
    Uses slope detection to move towards target power.
    """
    finished = pyqtSignal(bool, str) # Success, Message
    progress = pyqtSignal(float, float) # Current Power, Angle

    def __init__(self, hardware_manager, target_power_w, tolerance=0.01):
        super().__init__()
        self.hw = hardware_manager
        self.target_power = target_power_w
        self.tolerance = tolerance
        self._running = True
        self.min_step = 0.05 # Minimum angle step for precision
        self.max_step = 5.0  # Maximum test/initial step

    def stop(self):
        self._running = False

    def _read_average_power(self, pm, duration=0.5):
        """Read power over a duration (in seconds) and return the average."""
        start_time = time.time()
        readings = []
        while self._running and (time.time() - start_time) < duration:
            try:
                readings.append(pm.read_power())
            except Exception:
                pass
            time.sleep(0.05)
            
        if not readings:
            # Fallback if loop was instantly broken or all reads failed
            return pm.read_power()
            
        return sum(readings) / len(readings)

    def run(self):
        kdc = self.hw.kdc101
        pm = self.hw.get_instrument('pm100')
        
        if not kdc or not kdc.is_connected():
            self.finished.emit(False, "Motor not connected")
            return
        if not pm:
            self.finished.emit(False, "Power meter not connected")
            return

        try:
            # 1. Initial measurement (averaged to start from a stable baseline)
            current_p = self._read_average_power(pm, duration=0.5)
            current_angle = kdc.get_position()
            self.progress.emit(current_p, current_angle)
            
            error = abs(current_p - self.target_power)
            direction = 1 # Start with positive rotation
            
            logger.info(f"Starting power seek: Target={self.target_power}W, Current={current_p}W")

            # 2. Iterative loop
            step_size = 1.0 # Initial test step
            
            while self._running and error > (self.target_power * self.tolerance):
                # Take a test step
                kdc.move_by(direction * step_size)
                
                # Wait for move to settle
                time.sleep(0.3)
                while kdc.is_moving() and self._running:
                    time.sleep(0.1)
                
                # Measure averaged power
                new_p = self._read_average_power(pm, duration=0.5)
                new_angle = kdc.get_position()
                self.progress.emit(new_p, new_angle)
                
                new_error = abs(new_p - self.target_power)
                
                # Slope detection: If moving away, reverse and reduce step
                if new_error > error:
                    direction *= -1
                    step_size *= 0.5
                    logger.debug(f"Power moving away (Error {error:.2e} -> {new_error:.2e}). Reversing. Step={step_size}")
                else:
                    # If moving closer, keep going. Maybe increase step if far?
                    # Basic proportional logic: step proportional to error, clamped
                    # Note: Power follows cos^2, so sensitivity varies.
                    pass
                
                error = new_error
                
                # Safety break if step too small
                if step_size < self.min_step:
                    logger.info("Reached minimum step size resolution")
                    break

            if not self._running:
                self.finished.emit(False, "Stopped by user")
            else:
                self.finished.emit(True, f"Target reached: {current_p:.2e}W")

        except Exception as e:
            logger.error(f"Power seeking error: {e}")
            self.finished.emit(False, str(e))


class KDC101SettingsDialog(QDialog):
    """Dialog for KDC101 motor parameters."""

    def __init__(self, parent=None, current_params=None):
        super().__init__(parent)
        self.setWindowTitle("KDC101 Parameters")
        self.setModal(True)
        
        self.params = current_params or {
            'velocity': 1.0, 'acceleration': 1.0,
            'jog_step': 0.1, 'backlash': 0.01
        }
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        grid = QGridLayout()
        layout.addLayout(grid)
        
        # 1. Velocity
        grid.addWidget(QLabel("Max Velocity (°/s):"), 0, 0)
        self.vel_spin = QDoubleSpinBox()
        self.vel_spin.setRange(0.01, 25.0)
        self.vel_spin.setValue(self.params.get('velocity', 1.0))
        grid.addWidget(self.vel_spin, 0, 1)
        
        # 2. Acceleration
        grid.addWidget(QLabel("Acceleration (°/s²):"), 1, 0)
        self.accel_spin = QDoubleSpinBox()
        self.accel_spin.setRange(0.01, 50.0)
        self.accel_spin.setValue(self.params.get('acceleration', 1.0))
        grid.addWidget(self.accel_spin, 1, 1)

        # 3. Zero Origin Offset
        grid.addWidget(QLabel("Zero Offset (°):"), 2, 0)
        self.zero_spin = QDoubleSpinBox()
        self.zero_spin.setRange(-360.0, 360.0)
        self.zero_spin.setDecimals(3)
        self.zero_spin.setValue(self.params.get('zero_offset', 0.0))
        grid.addWidget(self.zero_spin, 2, 1)
        
        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self):
        return {
            'velocity': self.vel_spin.value(),
            'acceleration': self.accel_spin.value(),
            'zero_offset': self.zero_spin.value()
        }


class KDC101Panel(QWidget):
    """Widget for KDC101 motor controller (optimized for PRM1Z8 rotation)."""

    def __init__(self):
        super().__init__()
        self.hw = HardwareManager()
        self._params = {
            'velocity': 1.0, 'acceleration': 1.0
        }
        self._connecting = False # Guard flag for connection cycles
        self._init_ui()
        
        # Connect to Hardware Service signals
        service = self.hw.service
        service.kdc_pos_changed.connect(self._on_pos_changed)
        service.kdc_status_changed.connect(self._on_status_changed)
        service.shutter_changed.connect(self._on_shutter_changed)
        
        # Internal state
        self._was_connected = False
        self._seeker = None
        self._last_move_val = 0.0 # Track last commanded position to avoid redundant moves
        
        # Initially disable all controls
        self._update_controls_enabled(False)
        
        logger.info("KDC101 panel initialized (Signal-driven with auto-move)")

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        # Main Group
        group = QGroupBox("Polarizer Control")
        group.setStyleSheet("QGroupBox { font-weight: bold; }")
        group_layout = QGridLayout()
        group_layout.setSpacing(5) # Restored spacing
        # removed setContentsMargins to restore default
        group.setLayout(group_layout)

        row = 0
        # 1. Status and Position (Combined)
        pos_layout = QHBoxLayout()
        # removed pos_layout.setSpacing
        pos_layout.addWidget(QLabel("Angle"))
        self.pos_label = QLabel("---")
        self.pos_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pos_label.setStyleSheet(
            "background-color: #f8f9fa; border: 1px solid #ced4da; border-radius: 4px; "
            "padding: 4px 10px; min-width: 110px; "  # Restored padding
            "font-weight: bold; font-family: 'Courier New'; font-size: 20px; color: #00008b;" # Restored font size
        )
        pos_layout.addWidget(self.pos_label)
        self.unit_label = QLabel("°")
        self.unit_label.setStyleSheet("font-size: 20px; font-weight: bold;") # Restored font size
        pos_layout.addWidget(self.unit_label)
        
        pos_layout.addStretch()
        
        # Moving Indicator moved here
        self.moving_indicator = QLabel("Moving")
        self.moving_indicator.setStyleSheet("color: gray; font-size: 10px; font-weight: bold;")
        pos_layout.addWidget(self.moving_indicator)
        
        group_layout.addLayout(pos_layout, row, 0, 1, 2)
        
        row += 1
        # Separator (Standard)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        # removed max-height style
        group_layout.addWidget(line, row, 0, 1, 2)
        
        row += 1
        # 2. Target and Step Control (Combined on one line)
        target_step_layout = QHBoxLayout()
        
        target_step_layout.addWidget(QLabel("Target:"))
        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(-360, 360)
        self.target_spin.setDecimals(3)
        self.target_spin.setFixedWidth(80) # Restored width
        self.target_spin.editingFinished.connect(self._on_move_triggered)
        target_step_layout.addWidget(self.target_spin)
        target_step_layout.addWidget(QLabel("°"))
        
        target_step_layout.addStretch()
        
        target_step_layout.addWidget(QLabel("Step:"))
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setRange(0.001, 360)
        self.step_spin.setValue(1.0)
        self.step_spin.setDecimals(3)
        self.step_spin.setFixedWidth(70)
        target_step_layout.addWidget(self.step_spin)
        target_step_layout.addWidget(QLabel("°"))
        
        # Add buttons with zero extra spacing
        self.step_back_btn = QPushButton("-")
        self.step_back_btn.setFixedWidth(25)
        self.step_back_btn.clicked.connect(lambda: self._on_step_clicked(-1))
        
        self.step_fwd_btn = QPushButton("+")
        self.step_fwd_btn.setFixedWidth(25)
        self.step_fwd_btn.clicked.connect(lambda: self._on_step_clicked(1))
        
        target_step_layout.addWidget(self.step_back_btn)
        target_step_layout.addWidget(self.step_fwd_btn)
        
        group_layout.addLayout(target_step_layout, row, 0, 1, 2)
        
        row += 1
        # Separator (Between Target and Power Target)
        line_sep = QFrame()
        line_sep.setFrameShape(QFrame.Shape.HLine)
        line_sep.setFrameShadow(QFrame.Shadow.Sunken)
        group_layout.addWidget(line_sep, row, 0, 1, 2)
        
        row += 1
        # 3. Power Target (Renamed and anchored as requested)
        p_target_row_layout = QHBoxLayout()
        
        p_target_row_layout.addWidget(QLabel("Power Target:"))
        self.p_target_spin = QDoubleSpinBox()
        self.p_target_spin.setRange(0, 1000)
        self.p_target_spin.setDecimals(2)
        self.p_target_spin.setFixedWidth(80)
        p_target_row_layout.addWidget(self.p_target_spin)
        
        self.p_unit_combo = QComboBox()
        self.p_unit_combo.addItems(["nW", "µW", "mW"])
        self.p_unit_combo.setCurrentText("µW")
        self.p_unit_combo.setFixedWidth(60)
        p_target_row_layout.addWidget(self.p_unit_combo)
        
        self.seek_btn = QPushButton("Seek")
        self.seek_btn.setFixedWidth(60)
        self.seek_btn.clicked.connect(self._on_seek_clicked)
        p_target_row_layout.addWidget(self.seek_btn)
        
        p_target_row_layout.addStretch()
        
        group_layout.addLayout(p_target_row_layout, row, 0, 1, 2)
 
        row += 1
        # 4. Parameters & Stop
        action_layout = QHBoxLayout()
        action_layout.setSpacing(10)
        
        self.param_btn = QPushButton("Parameters")
        self.param_btn.clicked.connect(self._on_parameters_clicked)
        action_layout.addWidget(self.param_btn, 1) # Expand equally
        
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        self.stop_btn.setStyleSheet("""
            QPushButton { color: red; }
            QPushButton:disabled { color: gray; }
        """)
        action_layout.addWidget(self.stop_btn, 1) # Expand equally
        
        group_layout.addLayout(action_layout, row, 0, 1, 2)

        row += 1
        # Separator (Between Actions and Shutter)
        line_shutter = QFrame()
        line_shutter.setFrameShape(QFrame.Shape.HLine)
        line_shutter.setFrameShadow(QFrame.Shadow.Sunken)
        group_layout.addWidget(line_shutter, row, 0, 1, 2)
 
        row += 1
        # 5. Shutter (Newly Merged)
        shutter_layout = QHBoxLayout()
        shutter_layout.addWidget(QLabel("Shutter:"))
        
        self.shutter_btn_group = QButtonGroup(self)
        self.shutter_btn_group.setExclusive(True)
        
        self.shutter_open_btn = QPushButton("OPEN")
        self.shutter_open_btn.setCheckable(True)
        self.shutter_open_btn.setStyleSheet("""
            QPushButton:checked { background-color: #2ecc71; color: white; font-weight: bold; }
            QPushButton:disabled { background-color: #bdc3c7; color: #7f8c8d; }
            QPushButton { min-height: 24px; }
        """)
        self.shutter_open_btn.clicked.connect(lambda: self._set_shutter(True))
        
        self.shutter_close_btn = QPushButton("CLOSE")
        self.shutter_close_btn.setCheckable(True)
        self.shutter_close_btn.setStyleSheet("""
            QPushButton:checked { background-color: #e74c3c; color: white; font-weight: bold; }
            QPushButton:disabled { background-color: #bdc3c7; color: #7f8c8d; }
            QPushButton { min-height: 24px; }
        """)
        self.shutter_close_btn.clicked.connect(lambda: self._set_shutter(False))
        
        self.shutter_btn_group.addButton(self.shutter_open_btn)
        self.shutter_btn_group.addButton(self.shutter_close_btn)
        self.shutter_close_btn.setChecked(True)
        
        shutter_layout.addWidget(self.shutter_open_btn)
        shutter_layout.addWidget(self.shutter_close_btn)
        group_layout.addLayout(shutter_layout, row, 0, 1, 2)

        row += 1
        row += 1
        # 6. Footer: Device info and Status
        footer_layout = QHBoxLayout()
        self.device_info_label = QLabel("Device: ---")
        self.device_info_label.setStyleSheet("color: gray; font-size: 10px;")
        footer_layout.addWidget(self.device_info_label)
        
        footer_layout.addStretch()
        
        self.status_label = QLabel("Disconnected")
        self.status_label.setStyleSheet("color: red; font-size: 10px;")
        footer_layout.addWidget(self.status_label)
        
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setFixedWidth(55)
        self.connect_btn.setStyleSheet("font-size: 10px; height: 16px; padding: 0px;")
        self.connect_btn.clicked.connect(self._on_connect_clicked)
        footer_layout.addWidget(self.connect_btn)
        
        group_layout.addLayout(footer_layout, row, 0, 1, 2)

        layout.addWidget(group)
        layout.addStretch()
        
    def _update_controls_enabled(self, enabled: bool):
        """Enable or disable input controls."""
        self.target_spin.setEnabled(enabled)
        self.step_spin.setEnabled(enabled)
        self.step_back_btn.setEnabled(enabled)
        self.step_fwd_btn.setEnabled(enabled)
        self.p_target_spin.setEnabled(enabled)
        self.p_unit_combo.setEnabled(enabled)
        self.seek_btn.setEnabled(enabled)
        self.param_btn.setEnabled(enabled)
        self.stop_btn.setEnabled(enabled)
        self.shutter_open_btn.setEnabled(enabled)
        self.shutter_close_btn.setEnabled(enabled)

    @pyqtSlot(float)
    def _on_pos_changed(self, pos):
        """Update position label from hardware service."""
        # pos is now already offset-corrected by the driver
        self.pos_label.setText(f"{pos:.3f}")

    @pyqtSlot(bool, bool)
    def _on_status_changed(self, is_conn, is_moving):
        """Update status indicators from hardware service."""
        if self._connecting and not is_conn:
            return
            
        if is_conn:
            # Indicators
            self.moving_indicator.setStyleSheet(
                "color: blue; font-size: 10px; font-weight: bold;" if is_moving else "color: gray; font-size: 10px; font-weight: bold;"
            )
            
            # Status label
            if not (self._seeker and self._seeker.isRunning()):
                self.status_label.setText("Connected")
                self.status_label.setStyleSheet("color: green; font-size: 10px;")
            
            self.connect_btn.setEnabled(False)
            self.connect_btn.setVisible(True)
            
            # Enable controls
            self._update_controls_enabled(True)
            
            # If just connected, read parameters and device info
            if not self._was_connected:
                # We still do these one-off calls on the UI thread for now,
                # but they only happen once on connection.
                try:
                    kdc = self.hw.kdc101
                    if kdc:
                        self._read_hardware_params()
                        info = kdc.get_info()
                        model = info.get('model', 'KDC101')
                        sn = info.get('serial_number', '---')
                        self.device_info_label.setText(f"Device: {model} (S/N: {sn})")
                        self._was_connected = True
                except Exception as e:
                    logger.debug(f"Failed to read one-off metadata: {e}")
        else:
            self.status_label.setText("Disconnected")
            self.status_label.setStyleSheet("color: red; font-size: 10px;")
            self.connect_btn.setEnabled(True)
            self.connect_btn.setVisible(True)
            self.pos_label.setText("---")
            self.moving_indicator.setStyleSheet("color: gray; font-size: 10px; font-weight: bold;")
            self.device_info_label.setText("Device: ---")
            
            # Disable controls
            self._update_controls_enabled(False)
            self._was_connected = False
            self.shutter_close_btn.setChecked(True) # Default visual on disconnect

    def _on_connect_clicked(self):
        """Try to connect to the KDC101."""
        from ..qt import QMessageBox
        
        kdc = self.hw.kdc101
        if not kdc:
            try:
                kdc = self.hw.initialize_instrument('kdc101', 'kdc101')
            except Exception as e:
                QMessageBox.critical(self, "Hardware Error", f"Failed to initialize KDC101 driver:\n{e}")
                return

        self.connect_btn.setEnabled(False)
        self.status_label.setText("Connecting...")
        self.status_label.setStyleSheet("color: orange; font-size: 10px;")
        QApplication.processEvents()
        
        self._connecting = True
        def _connect_thread():
            try:
                kdc.connect()
                logger.info("KDC101 connected via panel button")
            except Exception as e:
                logger.error(f"Failed to connect KDC101: {e}")
                # Similar to mono, we let the service handle status reporting
            finally:
                self._connecting = False
                QTimer.singleShot(0, lambda: self.connect_btn.setEnabled(True))
        
        threading.Thread(target=_connect_thread, daemon=True).start()

    def _read_hardware_params(self):
        """Read current parameters from hardware."""
        kdc = self.hw.kdc101
        if kdc and kdc.is_connected():
            try:
                v_params = kdc.get_velocity_params()
                j_params = kdc.get_jog_parameters()
                backlash = kdc.get_backlash()
                
                self._params = {
                    'velocity': v_params['max_velocity'],
                    'acceleration': v_params['acceleration']
                }
                logger.info(f"KDC101 hardware params synchronized: {self._params}")
            except Exception as e:
                logger.error(f"Failed to read KDC101 params: {e}")
                # Don't overwrite existing params with defaults if we already had something
                if not hasattr(self, '_params') or self._params is None:
                    self._params = {'velocity': 1.0, 'acceleration': 1.0}

    def _on_parameters_clicked(self):
        """Open settings dialog."""
        dialog = KDC101SettingsDialog(self, self._params)
        if dialog.exec():
            new_params = dialog.get_values()
            kdc = self.hw.kdc101
            if kdc:
                try:
                    kdc.set_velocity(new_params['velocity'])
                    kdc.set_acceleration(new_params['acceleration'])
                    kdc.set_zero_offset(new_params['zero_offset'])
                    
                    # Immediately re-read from hardware to verify
                    logger.info("Re-reading parameters from hardware for verification")
                    self._read_hardware_params()
                except Exception as e:
                    logger.error(f"Failed to update KDC101 parameters: {e}")

    def _on_move_triggered(self):
        """Handle absolute move when input is finished (Enter or focus lost)."""
        val = self.target_spin.value()
        
        # Only move if the device is connected
        kdc = self.hw.kdc101
        if not kdc or not kdc.is_connected():
            return

        # Only move if the value has changed from our last move command
        if val == self._last_move_val:
            return

        logger.info(f"Target angle changed to {val:.3f}°, triggering move.")
        if kdc:
            def _move():
                try:
                    kdc.move_to(val)
                    self._last_move_val = val
                    logger.info(f"KDC101 move to {val:.3f}° successful")
                except Exception as e:
                    logger.error(f"KDC101 move failed: {e}")
            
            threading.Thread(target=_move, daemon=True).start()

    def _on_step_clicked(self, direction: int):
        """Handle relative move."""
        kdc = self.hw.kdc101
        if kdc:
            def _step():
                try:
                    delta = direction * self.step_spin.value()
                    kdc.move_by(delta)
                    logger.info(f"KDC101 stepping by {delta}")
                except Exception as e:
                    logger.error(f"KDC101 step failed: {e}")
            
            threading.Thread(target=_step, daemon=True).start()

    def _on_stop_clicked(self):
        """Handle emergency stop."""
        if self._seeker and self._seeker.isRunning():
            self._seeker.stop()
            logger.info("Power seeking aborted")

        kdc = self.hw.kdc101
        if kdc:
            try:
                kdc.stop()
                logger.info("KDC101 stopped")
            except Exception as e:
                logger.error(f"KDC101 stop failed: {e}")

    def _on_seek_clicked(self):
        """Start the power seeker worker."""
        if self._seeker and self._seeker.isRunning():
            self._seeker.stop()
            return

        # Calculate target in Watts
        value = self.p_target_spin.value()
        unit = self.p_unit_combo.currentText()
        multipliers = {"nW": 1e-9, "µW": 1e-6, "mW": 1e-3}
        target_w = value * multipliers[unit]

        self.seek_btn.setText("Stop")
        self.status_label.setText("Seeking...")
        self.status_label.setStyleSheet("color: orange; font-size: 10px;")
        
        self._seeker = PowerSeeker(self.hw, target_w)
        self._seeker.finished.connect(self._on_seek_finished)
        self._seeker.progress.connect(self._on_seek_progress)
        self._seeker.start()

    def _on_seek_progress(self, power, angle):
        """Update UI during seek."""
        # angle is already offset-corrected by the driver
        self.pos_label.setText(f"{angle:.3f}")
        # Note: We no longer update status_label here to keep it simply as 'Seeking...'

    def _on_seek_finished(self, success, message):
        """Handle completion of power seek."""
        self.seek_btn.setText("Seek")
        if success:
            logger.info(f"Power seek successful: {message}")
            self.status_label.setText("Target Reached")
            self.status_label.setStyleSheet("color: green; font-size: 10px;")
        else:
            logger.warning(f"Power seek failed: {message}")
            self.status_label.setText("Seek Failed")
            self.status_label.setStyleSheet("color: red; font-size: 10px;")

    @pyqtSlot(bool)
    def _on_shutter_changed(self, open_state: bool):
        """Update shutter button state from hardware feedback."""
        if open_state:
            self.shutter_open_btn.setChecked(True)
        else:
            self.shutter_close_btn.setChecked(True)

    def _set_shutter(self, open: bool):
        """Send shutter command to hardware."""
        kdc = self.hw.kdc101
        if kdc and kdc.is_connected():
            try:
                kdc.set_shutter(open)
                logger.info(f"Shutter {'opened' if open else 'closed'}")
            except Exception as e:
                logger.error(f"Shutter command failed: {e}")
                # Revert visual state
                if open: self.shutter_close_btn.setChecked(True)
                else: self.shutter_open_btn.setChecked(True)
