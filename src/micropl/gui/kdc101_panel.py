import logging
from ..qt import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGroupBox, QDoubleSpinBox, QGridLayout, 
    QFrame, Qt, QTimer, pyqtSlot, QDialog, QDialogButtonBox
)

from ..hardware.manager import HardwareManager

logger = logging.getLogger(__name__)


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

        # 3. Jog Step
        grid.addWidget(QLabel("Jog Step (°):"), 2, 0)
        self.jog_spin = QDoubleSpinBox()
        self.jog_spin.setRange(0.001, 360.0)
        self.jog_spin.setDecimals(3)
        self.jog_spin.setValue(self.params.get('jog_step', 0.1))
        grid.addWidget(self.jog_spin, 2, 1)

        # 4. Backlash
        grid.addWidget(QLabel("Backlash (°):"), 3, 0)
        self.back_spin = QDoubleSpinBox()
        self.back_spin.setRange(0, 5.0)
        self.back_spin.setDecimals(4)
        self.back_spin.setValue(self.params.get('backlash', 0.01))
        grid.addWidget(self.back_spin, 3, 1)
        
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
            'jog_step': self.jog_spin.value(),
            'backlash': self.back_spin.value()
        }


class KDC101Panel(QWidget):
    """Widget for KDC101 motor controller (optimized for PRM1Z8 rotation)."""

    def __init__(self):
        super().__init__()
        self.hw = HardwareManager()
        self._velocity_params = {'max_velocity': 1.0, 'acceleration': 10.0}
        self._init_ui()
        
        # Polling timer for status/position
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_status)
        self.timer.start(500)  # Update every 500ms
        
        logger.info("KDC101 panel initialized")

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        # Main Group
        group = QGroupBox("Polarizer Control")
        group_layout = QGridLayout()
        group_layout.setSpacing(5)
        group.setLayout(group_layout)

        row = 0
        # 1. Status and Position
        pos_layout = QHBoxLayout()
        pos_layout.addWidget(QLabel("Pos:"))
        self.pos_label = QLabel("0.000")
        self.pos_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pos_label.setStyleSheet(
            "background-color: #f8f9fa; border: 1px solid #ced4da; border-radius: 4px; "
            "padding: 4px 10px; min-width: 110px; "
            "font-weight: bold; font-family: monospace; font-size: 20px; color: #00008b;"
        )
        pos_layout.addWidget(self.pos_label)
        self.unit_label = QLabel("°")
        self.unit_label.setStyleSheet("font-size: 20px; font-weight: bold;")
        pos_layout.addWidget(self.unit_label)
        pos_layout.addStretch()
        
        self.status_label = QLabel("Disconnected")
        self.status_label.setStyleSheet("color: red;")
        pos_layout.addWidget(self.status_label)
        
        group_layout.addLayout(pos_layout, row, 0, 1, 2)
        
        row += 1
        # Homed and Moving indicators
        status_info_layout = QHBoxLayout()
        self.homed_indicator = QLabel("Homed")
        self.homed_indicator.setStyleSheet("color: gray; font-size: 10px; font-weight: bold;")
        status_info_layout.addWidget(self.homed_indicator)
        
        self.moving_indicator = QLabel("Moving")
        self.moving_indicator.setStyleSheet("color: gray; font-size: 10px; font-weight: bold;")
        status_info_layout.addWidget(self.moving_indicator)
        
        status_info_layout.addStretch()
        group_layout.addLayout(status_info_layout, row, 0, 1, 2)
        
        row += 1
        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        group_layout.addWidget(line, row, 0, 1, 2)
        
        row += 1
        # 2. Absolute Move
        group_layout.addWidget(QLabel("Target:"), row, 0)
        move_layout = QHBoxLayout()
        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(-360, 360)
        self.target_spin.setDecimals(3)
        self.target_spin.setFixedWidth(80)
        move_layout.addWidget(self.target_spin)
        move_layout.addWidget(QLabel("°"))
        
        self.move_btn = QPushButton("Move")
        self.move_btn.setFixedWidth(60)
        self.move_btn.clicked.connect(self._on_move_clicked)
        move_layout.addWidget(self.move_btn)
        group_layout.addLayout(move_layout, row, 1)
        
        row += 1
        # 3. Step Control
        group_layout.addWidget(QLabel("Step:"), row, 0)
        step_layout = QHBoxLayout()
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setRange(0.001, 360)
        self.step_spin.setValue(1.0)
        self.step_spin.setDecimals(3)
        self.step_spin.setFixedWidth(80)
        step_layout.addWidget(self.step_spin)
        step_layout.addWidget(QLabel("°"))
        
        self.step_back_btn = QPushButton("-")
        self.step_back_btn.setFixedWidth(30)
        self.step_back_btn.clicked.connect(lambda: self._on_step_clicked(-1))
        
        self.step_fwd_btn = QPushButton("+")
        self.step_fwd_btn.setFixedWidth(30)
        self.step_fwd_btn.clicked.connect(lambda: self._on_step_clicked(1))
        
        step_layout.addWidget(self.step_back_btn)
        step_layout.addWidget(self.step_fwd_btn)
        group_layout.addLayout(step_layout, row, 1)
        
        row += 1
        # 4. Params and Home
        btn_layout = QHBoxLayout()
        self.param_btn = QPushButton("Params")
        self.param_btn.clicked.connect(self._on_parameters_clicked)
        btn_layout.addWidget(self.param_btn)
        
        self.home_btn = QPushButton("Home")
        self.home_btn.clicked.connect(self._on_home_clicked)
        btn_layout.addWidget(self.home_btn)
        group_layout.addLayout(btn_layout, row, 0, 1, 2)

        row += 1
        # 5. Stop
        self.stop_btn = QPushButton("STOP")
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        self.stop_btn.setStyleSheet("background-color: #ffcccc; color: red; font-weight: bold; min-height: 30px;")
        row += 1
        # 6. Device info
        self.device_info_label = QLabel("Device: ---")
        self.device_info_label.setStyleSheet("color: gray; font-size: 10px;")
        group_layout.addWidget(self.device_info_label, row, 0, 1, 2)

        layout.addWidget(group)
        layout.addStretch()
        
        # Internal state to track connection
        self._was_connected = False

    def _update_status(self):
        """Update position and status labels."""
        kdc = self.hw.kdc101
        is_conn = kdc and kdc.is_connected()
        
        if is_conn:
            try:
                pos = kdc.get_position()
                self.pos_label.setText(f"{pos:.3f}")
                
                # Digital status indicators
                homed = kdc.is_homed()
                self.homed_indicator.setStyleSheet(
                    "color: green; font-size: 10px; font-weight: bold;" if homed else "color: gray; font-size: 10px; font-weight: bold;"
                )
                
                moving = kdc.is_moving()
                self.moving_indicator.setStyleSheet(
                    "color: blue; font-size: 10px; font-weight: bold;" if moving else "color: gray; font-size: 10px; font-weight: bold;"
                )
                
                self.status_label.setText("Connected")
                self.status_label.setStyleSheet("color: green;")
                
                # Enable controls
                self.move_btn.setEnabled(True)
                self.step_back_btn.setEnabled(True)
                self.step_fwd_btn.setEnabled(True)
                self.home_btn.setEnabled(True)
                self.param_btn.setEnabled(True)
                
                # If just connected, read parameters and device info
                if not self._was_connected:
                    self._read_hardware_params()
                    info = kdc.get_device_info()
                    model = info.get('model', 'Unknown')
                    sn = info.get('serial', '---')
                    self.device_info_label.setText(f"Device: {model} (S/N: {sn})")
                    self._was_connected = True
                    
            except Exception:
                self.status_label.setText("Error")
                self.status_label.setStyleSheet("color: red;")
                self.device_info_label.setText("Device: Error")
        else:
            self.status_label.setText("Disconnected")
            self.status_label.setStyleSheet("color: red;")
            self.pos_label.setText("---")
            self.homed_indicator.setStyleSheet("color: gray; font-size: 10px; font-weight: bold;")
            self.moving_indicator.setStyleSheet("color: gray; font-size: 10px; font-weight: bold;")
            self.device_info_label.setText("Device: ---")
            
            # Disable controls
            self.move_btn.setEnabled(False)
            self.step_back_btn.setEnabled(False)
            self.step_fwd_btn.setEnabled(False)
            self.home_btn.setEnabled(False)
            self.param_btn.setEnabled(False)
            self._was_connected = False

    def _read_hardware_params(self):
        """Read current parameters from hardware."""
        kdc = self.hw.kdc101
        if kdc:
            try:
                v_params = kdc.get_velocity_params()
                jog_params = kdc.get_jog_parameters()
                backlash = kdc.get_backlash()
                
                self._params = {
                    'velocity': v_params['max_velocity'],
                    'acceleration': v_params['acceleration'],
                    'jog_step': jog_params.get('step_size', 0.1),
                    'backlash': backlash
                }
                logger.info(f"KDC101 hardware params read: {self._params}")
            except Exception as e:
                logger.error(f"Failed to read KDC101 params: {e}")

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
                    kdc.set_jog_parameters(step_size=new_params['jog_step'])
                    kdc.set_backlash(new_params['backlash'])
                    self._params = new_params
                    logger.info("KDC101 parameters updated via dialog")
                except Exception as e:
                    logger.error(f"Failed to update KDC101 parameters: {e}")

    def _on_move_clicked(self):
        """Handle absolute move."""
        kdc = self.hw.kdc101
        if kdc:
            try:
                target = self.target_spin.value()
                kdc.move_to(target)
                logger.info(f"KDC101 moving to {target}")
            except Exception as e:
                logger.error(f"KDC101 move failed: {e}")

    def _on_step_clicked(self, direction: int):
        """Handle relative move."""
        kdc = self.hw.kdc101
        if kdc:
            try:
                delta = direction * self.step_spin.value()
                kdc.move_by(delta)
                logger.info(f"KDC101 stepping by {delta}")
            except Exception as e:
                logger.error(f"KDC101 step failed: {e}")

    def _on_home_clicked(self):
        """Handle homing."""
        kdc = self.hw.kdc101
        if kdc:
            try:
                logger.info("KDC101 homing started")
                # Use a separate thread or just block if it's fast enough in background
                # Hardware driver move_to/home might be blocking or non-blocking depending on pylablib setup
                # ThorlabsKDC101.home is blocking (sync=True).
                # To avoid freezing UI, we might want to run this in a thread.
                # However, for now, let's keep it simple.
                kdc.home() 
            except Exception as e:
                logger.error(f"KDC101 homing failed: {e}")

    def _on_stop_clicked(self):
        """Handle emergency stop."""
        kdc = self.hw.kdc101
        if kdc:
            try:
                kdc.stop()
                logger.info("KDC101 stopped")
            except Exception as e:
                logger.error(f"KDC101 stop failed: {e}")
