import logging
import threading
import time
from typing import Optional, cast

from ..hardware.kdc101 import ThorlabsKDC101
from ..hardware.manager import HardwareManager
from ..qt import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QThread,
    QVBoxLayout,
    QWidget,
    Qt,
    pyqtSignal,
    pyqtSlot,
)

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
        polarizer = cast(Optional[ThorlabsKDC101], self.hw.polarizer)
        pm = self.hw.get_instrument('pm100')
        
        if not polarizer or not polarizer.is_connected():
            self.finished.emit(False, "Motor not connected")
            return
        if not pm:
            self.finished.emit(False, "Power meter not connected")
            return

        try:
            # 1. Initial measurement (averaged to start from a stable baseline)
            current_p = self._read_average_power(pm, duration=0.5)
            current_angle = polarizer.get_position()
            self.progress.emit(current_p, current_angle)
            
            error = abs(current_p - self.target_power)
            direction = 1 # Start with positive rotation
            
            logger.info(f"Starting power seek: Target={self.target_power}W, Current={current_p}W")

            # 2. Iterative loop
            step_size = 1.0 # Initial test step
            
            while self._running and error > (self.target_power * self.tolerance):
                # Take a test step
                polarizer.move_by(direction * step_size)
                
                # Wait for move to settle
                time.sleep(0.3)
                while polarizer.is_moving() and self._running:
                    time.sleep(0.1)
                
                # Measure averaged power
                new_p = self._read_average_power(pm, duration=0.5)
                new_angle = polarizer.get_position()
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


class PolarizerSettingsDialog(QDialog):
    """Dialog for polarizer motor parameters."""

    def __init__(self, parent=None, current_params=None):
        super().__init__(parent)
        self.setWindowTitle("Polarizer Parameters")
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


class PolarizerPanel(QWidget):
    """
    Dedicated control panel for the polarizer motor.
    Provides angle control and iterative power-seeking automation.
    """
    sig_status_changed = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.hw = HardwareManager()
        self.setMinimumWidth(340)
        self._params = {
            'velocity': 1.0, 'acceleration': 1.0, 'zero_offset': 0.0
        }
        self._connecting = False # Guard flag for connection cycles
        self._init_ui()
        
        # Connect to Hardware Service signals
        service = self.hw.service
        service.polarizer_pos_changed.connect(self._on_pos_changed)
        service.polarizer_status_changed.connect(self._on_status_changed)
        
        # Internal state
        self._was_connected = False
        self._seeker = None
        self._last_move_val = 0.0 # Track last commanded position to avoid redundant moves
        
        # Initially disable all controls
        self._update_controls_enabled(False)
        
        logger.info("Polarizer panel initialized (Signal-driven with auto-move)")

    def _init_ui(self):
        """Initialize the user interface."""
        self._main_layout = QVBoxLayout()
        self.setLayout(self._main_layout)
        self._main_layout.setContentsMargins(10, 10, 10, 10)
        
        group_layout = QGridLayout()
        group_layout.setContentsMargins(0, 0, 0, 0)
        group_layout.setSpacing(5)
        self._main_layout.addLayout(group_layout)

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
        # 2. Target Row: Target, Home, Stop
        target_layout = QHBoxLayout()
        target_layout.addWidget(QLabel("Target:"))
        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(-360, 360)
        self.target_spin.setDecimals(3)
        self.target_spin.setMinimumWidth(70)
        self.target_spin.editingFinished.connect(self._on_move_triggered)
        target_layout.addWidget(self.target_spin)
        target_layout.addWidget(QLabel("°"))
        
        target_layout.addStretch()
        
        # Home Button
        self.home_btn = QPushButton("⌂")
        self.home_btn.setFixedSize(26, 22)
        self.home_btn.setStyleSheet("font-size: 18px; color: #007bff; font-family: 'Segoe UI Symbol', 'Arial'; padding: -2px;")
        self.home_btn.clicked.connect(self._on_home_clicked)
        target_layout.addWidget(self.home_btn)
        
        # Stop Button
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setFixedSize(80, 22)
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        self.stop_btn.setStyleSheet("""
            QPushButton { color: #dc3545; font-weight: bold; }
            QPushButton:disabled { color: gray; }
        """)
        target_layout.addWidget(self.stop_btn)
        group_layout.addLayout(target_layout, row, 0, 1, 2)
        
        row += 1
        # 3. Step Row: Step, buttons
        step_row_layout = QHBoxLayout()
        step_row_layout.addWidget(QLabel("Step:  ")) # Added spaces for alignment
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setRange(0.001, 360)
        self.step_spin.setValue(1.0)
        self.step_spin.setDecimals(3)
        self.step_spin.setMinimumWidth(70)
        step_row_layout.addWidget(self.step_spin)
        step_row_layout.addWidget(QLabel("°"))
        
        self.step_back_btn = QPushButton("-")
        self.step_back_btn.setFixedSize(26, 22)
        self.step_back_btn.clicked.connect(lambda: self._on_step_clicked(-1))
        
        self.step_fwd_btn = QPushButton("+")
        self.step_fwd_btn.setFixedSize(26, 22)
        self.step_fwd_btn.clicked.connect(lambda: self._on_step_clicked(1))
        
        step_row_layout.addSpacing(5)
        step_row_layout.addWidget(self.step_back_btn)
        step_row_layout.addWidget(self.step_fwd_btn)
        step_row_layout.addStretch()
        
        group_layout.addLayout(step_row_layout, row, 0, 1, 2)
        
        row += 1
        # Separator
        line_sep = QFrame()
        line_sep.setFrameShape(QFrame.Shape.HLine)
        line_sep.setFrameShadow(QFrame.Shadow.Sunken)
        group_layout.addWidget(line_sep, row, 0, 1, 2)
        
        row += 1
        # 4. Power Target Row
        p_target_row_layout = QHBoxLayout()
        p_target_row_layout.addWidget(QLabel("Power Target:"))
        self.p_target_spin = QDoubleSpinBox()
        self.p_target_spin.setRange(0, 1000)
        self.p_target_spin.setDecimals(2)
        self.p_target_spin.setMinimumWidth(70)
        p_target_row_layout.addWidget(self.p_target_spin)
        
        self.p_unit_combo = QComboBox()
        self.p_unit_combo.addItems(["nW", "µW", "mW"])
        self.p_unit_combo.setCurrentText("µW")
        self.p_unit_combo.setMinimumWidth(55)
        p_target_row_layout.addWidget(self.p_unit_combo)
        
        self.seek_btn = QPushButton("Seek")
        self.seek_btn.setMinimumWidth(55)
        self.seek_btn.clicked.connect(self._on_seek_clicked)
        p_target_row_layout.addWidget(self.seek_btn)
        p_target_row_layout.addStretch()
        
        group_layout.addLayout(p_target_row_layout, row, 0, 1, 2)
 
        row += 1
        # 5. Parameters (Bottom)
        self.param_btn = QPushButton("Parameters")
        self.param_btn.clicked.connect(self._on_parameters_clicked)
        group_layout.addWidget(self.param_btn, row, 0, 1, 2)

        row += 1

        # Disable focus for all buttons to prevent scroll-jumping
        for btn in self.findChildren(QPushButton):
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            
        # Final layout assembly
        self._main_layout.addStretch()

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
        self.home_btn.setEnabled(enabled)

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
                self.sig_status_changed.emit("Connected")
            
            # Enable controls
            self._update_controls_enabled(True)
            
            # If just connected, read parameters and device info
            if not self._was_connected:
                # We still do these one-off calls on the UI thread for now,
                # but they only happen once on connection.
                try:
                    polarizer = self.hw.polarizer
                    if polarizer:
                        self._read_hardware_params()
                        self._was_connected = True
                except Exception as e:
                    logger.debug(f"Failed to read one-off metadata: {e}")
        else:
            self.sig_status_changed.emit("Disconnected")
            self.pos_label.setText("---")
            self.moving_indicator.setStyleSheet("color: gray; font-size: 10px; font-weight: bold;")
            
            # Disable controls
            self._update_controls_enabled(False)
            self._was_connected = False

    def _on_connect_clicked(self):
        """Try to connect to the polarizer."""
        polarizer = self.hw.polarizer
        if not polarizer:
            try:
                polarizer = self.hw.initialize_instrument('polarizer', 'kdc101')
            except Exception as e:
                QMessageBox.critical(self, "Hardware Error", f"Failed to initialize polarizer driver:\n{e}")
                return

        self._connecting = True
        self.sig_status_changed.emit("Connecting...")
        QApplication.processEvents()
        def _connect_thread():
            try:
                polarizer.connect()
                logger.info("Polarizer connected via panel button")
            except Exception as e:
                logger.error(f"Failed to connect polarizer: {e}")
                # Similar to mono, we let the service handle status reporting
            finally:
                self._connecting = False
        
        threading.Thread(target=_connect_thread, daemon=True).start()

    def _read_hardware_params(self):
        """Read current parameters from hardware."""
        polarizer = cast(Optional[ThorlabsKDC101], self.hw.polarizer)
        if polarizer and polarizer.is_connected():
            try:
                v_params = polarizer.get_velocity_params()
                
                self._params = {
                    'velocity': v_params['max_velocity'],
                    'acceleration': v_params['acceleration'],
                    'zero_offset': getattr(polarizer, 'zero_offset', 0.0)
                }
                logger.info(f"Polarizer hardware params synchronized: {self._params}")
            except Exception as e:
                logger.error(f"Failed to read polarizer params: {e}")
                # Don't overwrite existing params with defaults if we already had something
                if not hasattr(self, '_params') or self._params is None:
                    self._params = {
                        'velocity': 1.0,
                        'acceleration': 1.0,
                        'zero_offset': getattr(polarizer, 'zero_offset', 0.0) if polarizer else 0.0
                    }

    def _on_parameters_clicked(self):
        """Open settings dialog."""
        dialog = PolarizerSettingsDialog(self, self._params)
        if dialog.exec():
            new_params = dialog.get_values()
            polarizer = cast(Optional[ThorlabsKDC101], self.hw.polarizer)
            if polarizer:
                try:
                    polarizer.set_velocity(new_params['velocity'])
                    polarizer.set_acceleration(new_params['acceleration'])
                    polarizer.set_zero_offset(new_params['zero_offset'])
                    
                    # Immediately re-read from hardware to verify
                    logger.info("Re-reading parameters from hardware for verification")
                    self._read_hardware_params()
                except Exception as e:
                    logger.error(f"Failed to update polarizer parameters: {e}")

    def _on_move_triggered(self):
        """Handle absolute move when input is finished (Enter or focus lost)."""
        val = self.target_spin.value()
        
        # Only move if the device is connected
        polarizer = cast(Optional[ThorlabsKDC101], self.hw.polarizer)
        if not polarizer or not polarizer.is_connected():
            return

        # Only move if the value has changed from our last move command
        if val == self._last_move_val:
            return

        logger.info(f"Target angle changed to {val:.3f}°, triggering move.")
        if polarizer:
            def _move():
                try:
                    polarizer.move_to(val)
                    self._last_move_val = val
                    logger.info(f"Polarizer move to {val:.3f}° successful")
                except Exception as e:
                    logger.error(f"Polarizer move failed: {e}")
            
            threading.Thread(target=_move, daemon=True).start()

    def _on_step_clicked(self, direction: int):
        """Handle relative move."""
        polarizer = cast(Optional[ThorlabsKDC101], self.hw.polarizer)
        if polarizer:
            def _step():
                try:
                    delta = direction * self.step_spin.value()
                    polarizer.move_by(delta)
                    logger.info(f"Polarizer stepping by {delta}")
                except Exception as e:
                    logger.error(f"Polarizer step failed: {e}")
            
            threading.Thread(target=_step, daemon=True).start()

    def _on_stop_clicked(self):
        """Handle emergency stop."""
        if self._seeker and self._seeker.isRunning():
            self._seeker.stop()
            logger.info("Power seeking aborted")

        polarizer = cast(Optional[ThorlabsKDC101], self.hw.polarizer)
        if polarizer:
            try:
                polarizer.stop()
                logger.info("Polarizer stopped")
            except Exception as e:
                logger.error(f"Polarizer stop failed: {e}")

    def _on_home_clicked(self):
        """Perform homing on polarizer."""
        polarizer = cast(Optional[ThorlabsKDC101], self.hw.polarizer)
        if not polarizer or not polarizer.is_connected():
            return

        self.sig_status_changed.emit("Homing...")
        self.home_btn.setEnabled(False)
        
        def do_home():
            try:
                polarizer.home()
            finally:
                self.sig_status_changed.emit(self.get_current_status())
                self.home_btn.setEnabled(True)
        
        threading.Thread(target=do_home, daemon=True).start()

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
        self.sig_status_changed.emit("Seeking...")
        
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
            self.sig_status_changed.emit("Target Reached")
        else:
            logger.warning(f"Power seek failed: {message}")
            self.sig_status_changed.emit("Seek Failed")

    def update_panel(self):
        """Update UI from hardware state. Called periodically."""
        polarizer = cast(Optional[ThorlabsKDC101], self.hw.polarizer)
        if polarizer:
            is_connected = polarizer.is_connected()
            if is_connected and not self._connecting:
                # Periodic position update if not moving/connecting
                try:
                    pos = polarizer.get_position()
                    self.pos_label.setText(f"{pos:.3f}")
                except:
                    pass
            
            self._update_controls_enabled(is_connected)
            self.sig_status_changed.emit(self.get_current_status())

    def get_current_status(self) -> str:
        """Return a string representing the current connection/operational status."""
        polarizer = self.hw.polarizer
        if not polarizer or not polarizer.is_connected():
            return "Disconnected"
        if self._connecting:
            return "Connecting"
        if self._seeker and self._seeker.isRunning():
            return "Seeking"
        return "Connected"
