"""
XY Stage control panel for controlling dual KDC101 motors.
"""

import logging
import threading
from ..qt import (
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QVBoxLayout, QWidget, Qt,
    pyqtSignal, pyqtSlot
)
from typing import cast, Optional
from ..hardware.manager import HardwareManager
from ..hardware.kdc101 import ThorlabsKDC101

logger = logging.getLogger(__name__)
class StageSettingsDialog(QDialog):
    """Dialog for XY Stage motor parameters (Velocity, Accel, Offset)."""
    x_vel_spin: QDoubleSpinBox
    x_accel_spin: QDoubleSpinBox
    x_offset_spin: QDoubleSpinBox
    y_vel_spin: QDoubleSpinBox
    y_accel_spin: QDoubleSpinBox
    y_offset_spin: QDoubleSpinBox

    def __init__(self, parent=None, x_params=None, y_params=None):
        super().__init__(parent)
        self.setWindowTitle("XY Stage Parameters")
        self.setModal(True)
        
        self.x_params = x_params or {'velocity': 2.0, 'acceleration': 2.0, 'zero_offset': 0.0}
        self.y_params = y_params or {'velocity': 2.0, 'acceleration': 2.0, 'zero_offset': 0.0}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        # Axis X Tab
        self.x_tab = QWidget()
        x_layout = QGridLayout(self.x_tab)
        self._add_axis_controls(x_layout, self.x_params, 'x')
        self.tabs.addTab(self.x_tab, "Axis X")
        
        # Axis Y Tab
        self.y_tab = QWidget()
        y_layout = QGridLayout(self.y_tab)
        self._add_axis_controls(y_layout, self.y_params, 'y')
        self.tabs.addTab(self.y_tab, "Axis Y")
        
        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_axis_controls(self, layout, params, prefix):
        # Velocity
        layout.addWidget(QLabel("Max Velocity (mm/s):"), 0, 0)
        vel_spin = QDoubleSpinBox()
        vel_spin.setRange(0.01, 25.0)
        vel_spin.setValue(params.get('velocity', 2.0))
        layout.addWidget(vel_spin, 0, 1)
        setattr(self, f"{prefix}_vel_spin", vel_spin)
        
        # Acceleration
        layout.addWidget(QLabel("Acceleration (mm/s²):"), 1, 0)
        accel_spin = QDoubleSpinBox()
        accel_spin.setRange(0.01, 50.0)
        accel_spin.setValue(params.get('acceleration', 2.0))
        layout.addWidget(accel_spin, 1, 1)
        setattr(self, f"{prefix}_accel_spin", accel_spin)

        # Zero Offset
        layout.addWidget(QLabel("Zero Offset (mm):"), 2, 0)
        offset_spin = QDoubleSpinBox()
        offset_spin.setRange(-50.0, 50.0)
        offset_spin.setDecimals(3)
        offset_spin.setValue(params.get('zero_offset', 0.0))
        layout.addWidget(offset_spin, 2, 1)
        setattr(self, f"{prefix}_offset_spin", offset_spin)

    def get_values(self):
        return {
            'x': {
                'velocity': self.x_vel_spin.value(),
                'acceleration': self.x_accel_spin.value(),
                'zero_offset': self.x_offset_spin.value()
            },
            'y': {
                'velocity': self.y_vel_spin.value(),
                'acceleration': self.y_accel_spin.value(),
                'zero_offset': self.y_offset_spin.value()
            }
        }

class StagePanel(QWidget):
    """Control panel for XY Stage (Dual KDC101)."""
    sig_status_changed = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.hw = HardwareManager()
        self._connecting = False
        self._init_ui()
        
        # Connect to Hardware Service signals
        service = self.hw.service
        service.stage_x_pos_changed.connect(self._on_x_pos_changed)
        service.stage_x_status_changed.connect(self._on_x_status_changed)
        service.stage_y_pos_changed.connect(self._on_y_pos_changed)
        service.stage_y_status_changed.connect(self._on_y_status_changed)
        
        self._update_ui_state()

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        g_layout = QGridLayout()
        g_layout.setSpacing(5)
        layout.addLayout(g_layout)
        
        row = 0
        # --- Top Section: Positions (Left) and Jog Controls (Right) ---
        top_layout = QHBoxLayout()
        top_layout.setSpacing(15)
        
        # 1. Position Display (Vertical Stack)
        coords_layout = QVBoxLayout()
        coords_layout.setSpacing(5)
        
        # X Position
        x_layout = QHBoxLayout()
        x_layout.addWidget(QLabel("X"))
        self.x_label = QLabel("---")
        self.x_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.x_label.setStyleSheet(
            "background-color: #f8f9fa; border: 1px solid #ced4da; border-radius: 4px; "
            "padding: 4px 10px; font-weight: bold; font-family: 'Courier New'; font-size: 20px; color: #00008b;"
            "min-width: 110px;"
        )
        x_layout.addWidget(self.x_label)
        self.x_unit = QLabel("mm")
        self.x_unit.setStyleSheet("font-size: 20px; font-weight: bold;")
        x_layout.addWidget(self.x_unit)
        coords_layout.addLayout(x_layout)
        
        # Y Position
        y_layout = QHBoxLayout()
        y_layout.addWidget(QLabel("Y"))
        self.y_label = QLabel("---")
        self.y_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.y_label.setStyleSheet(
            "background-color: #f8f9fa; border: 1px solid #ced4da; border-radius: 4px; "
            "padding: 4px 10px; font-weight: bold; font-family: 'Courier New'; font-size: 20px; color: #00008b;"
            "min-width: 110px;"
        )
        y_layout.addWidget(self.y_label)
        self.y_unit = QLabel("mm")
        self.y_unit.setStyleSheet("font-size: 20px; font-weight: bold;")
        y_layout.addWidget(self.y_unit)
        coords_layout.addLayout(y_layout)
        
        top_layout.addLayout(coords_layout)
        
        # Spacer
        top_layout.addStretch()
        
        # 2. Jog Controls (Arrow Pad - Right)
        jog_group = QGridLayout()
        jog_group.setSpacing(2)
        
        self.up_btn = QPushButton("▲")
        self.up_btn.setFixedSize(30, 26)
        self.up_btn.setStyleSheet("font-size: 14px; font-family: 'Segoe UI Symbol', 'Arial';")
        self.up_btn.clicked.connect(lambda: self._on_jog_clicked(0, 1))
        
        self.down_btn = QPushButton("▼")
        self.down_btn.setFixedSize(30, 26)
        self.down_btn.setStyleSheet("font-size: 14px; font-family: 'Segoe UI Symbol', 'Arial';")
        self.down_btn.clicked.connect(lambda: self._on_jog_clicked(0, -1))
        
        self.left_btn = QPushButton("◀")
        self.left_btn.setFixedSize(30, 26)
        self.left_btn.setStyleSheet("font-size: 14px; font-family: 'Segoe UI Symbol', 'Arial';")
        self.left_btn.clicked.connect(lambda: self._on_jog_clicked(-1, 0))
        
        self.right_btn = QPushButton("▶")
        self.right_btn.setFixedSize(30, 26)
        self.right_btn.setStyleSheet("font-size: 14px; font-family: 'Segoe UI Symbol', 'Arial';")
        self.right_btn.clicked.connect(lambda: self._on_jog_clicked(1, 0))
        
        jog_group.addWidget(self.up_btn, 0, 1)
        jog_group.addWidget(self.left_btn, 1, 0)
        jog_group.addWidget(self.right_btn, 1, 2)
        jog_group.addWidget(self.down_btn, 2, 1)
        
        top_layout.addLayout(jog_group)
        
        g_layout.addLayout(top_layout, row, 0, 1, 5)
        
        row += 1
        g_layout.addWidget(self._create_separator(), row, 0, 1, 5)
        
        row += 1
        # 3. Jog Step
        step_layout = QHBoxLayout()
        step_layout.addWidget(QLabel("Step:"))
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setRange(0.1, 10.0)
        self.step_spin.setValue(1.0)
        self.step_spin.setDecimals(3)
        self.step_spin.setFixedWidth(80)
        step_layout.addWidget(self.step_spin)
        step_layout.addWidget(QLabel("mm"))
        step_layout.addStretch()
        g_layout.addLayout(step_layout, row, 0, 1, 5)
        
        row += 1
        g_layout.addWidget(self._create_separator(), row, 0, 1, 5)
        
        row += 1
        # 4. Absolute Move
        abs_layout = QGridLayout()
        abs_layout.addWidget(QLabel("Target X:"), 0, 0)
        self.target_x_spin = QDoubleSpinBox()
        self.target_x_spin.setRange(0, 50)
        self.target_x_spin.setDecimals(3)
        self.target_x_spin.editingFinished.connect(lambda: self._on_target_changed('x'))
        abs_layout.addWidget(self.target_x_spin, 0, 1)
        abs_layout.addWidget(QLabel("mm"), 0, 2)
        
        # Home X Button
        self.home_x_btn = QPushButton("⌂")
        self.home_x_btn.setFixedSize(26, 22)
        self.home_x_btn.setStyleSheet("font-size: 18px; color: #007bff; font-family: 'Segoe UI Symbol', 'Arial'; padding: -2px;")
        self.home_x_btn.clicked.connect(lambda: self._on_home_clicked('x'))
        abs_layout.addWidget(self.home_x_btn, 0, 3)
        
        abs_layout.addWidget(QLabel("Target Y:"), 1, 0)
        self.target_y_spin = QDoubleSpinBox()
        self.target_y_spin.setRange(0, 50)
        self.target_y_spin.setDecimals(3)
        self.target_y_spin.editingFinished.connect(lambda: self._on_target_changed('y'))
        abs_layout.addWidget(self.target_y_spin, 1, 1)
        abs_layout.addWidget(QLabel("mm"), 1, 2)
        
        # Home Y Button
        self.home_y_btn = QPushButton("⌂")
        self.home_y_btn.setFixedSize(26, 22)
        self.home_y_btn.setStyleSheet("font-size: 18px; color: #007bff; font-family: 'Segoe UI Symbol', 'Arial'; padding: -2px;")
        self.home_y_btn.clicked.connect(lambda: self._on_home_clicked('y'))
        abs_layout.addWidget(self.home_y_btn, 1, 3)
        
        # STOP Button (Right of everything, spans both rows)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        self.stop_btn.setStyleSheet("""
            QPushButton { color: #dc3545; font-weight: bold; min-height: 48px; }
            QPushButton:disabled { color: gray; }
        """)
        abs_layout.addWidget(self.stop_btn, 0, 4, 2, 1)
        
        g_layout.addLayout(abs_layout, row, 0, 1, 5)
        
        # Connect spinboxes to move logic
        self.target_x_spin.editingFinished.connect(lambda: self._on_target_changed('x'))
        self.target_y_spin.editingFinished.connect(lambda: self._on_target_changed('y'))
        
        # 4. Parameters Button
        row += 1
        self.params_btn = QPushButton("Parameters")
        self.params_btn.clicked.connect(self._on_params_clicked)
        # Use full width to match the Polarizer panel style
        g_layout.addWidget(self.params_btn, row, 0, 1, 5)
        
        layout.addStretch()

    def _on_params_clicked(self):
        """Open settings dialog for XY stage."""
        # Get current params from hardware if available
        x_params = None
        y_params = None
        
        stage_x = cast(Optional[ThorlabsKDC101], self.hw.stage_x)
        stage_y = cast(Optional[ThorlabsKDC101], self.hw.stage_y)
        
        if stage_x and stage_x.is_connected():
            params = stage_x.get_velocity_params()
            x_params = {
                'velocity': params['max_velocity'],
                'acceleration': params['acceleration'],
                'zero_offset': stage_x.zero_offset
            }
        
        if stage_y and stage_y.is_connected():
            params = stage_y.get_velocity_params()
            y_params = {
                'velocity': params['max_velocity'],
                'acceleration': params['acceleration'],
                'zero_offset': stage_y.zero_offset
            }

        dialog = StageSettingsDialog(self, x_params, y_params)
        if dialog.exec():
            vals = dialog.get_values()
            
            # Apply to X
            if stage_x:
                try:
                    stage_x.set_velocity(vals['x']['velocity'])
                    stage_x.set_acceleration(vals['x']['acceleration'])
                    stage_x.set_zero_offset(vals['x']['zero_offset'])
                except Exception as e:
                    logger.error(f"Failed to set X stage params: {e}")

            # Apply to Y
            if stage_y:
                try:
                    stage_y.set_velocity(vals['y']['velocity'])
                    stage_y.set_acceleration(vals['y']['acceleration'])
                    stage_y.set_zero_offset(vals['y']['zero_offset'])
                except Exception as e:
                    logger.error(f"Failed to set Y stage params: {e}")

            logger.info("Stage parameters updated successfully")

    def _create_separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    @pyqtSlot(float)
    def _on_x_pos_changed(self, pos):
        self.x_label.setText(f"{pos:.3f}")
        
    @pyqtSlot(float)
    def _on_y_pos_changed(self, pos):
        self.y_label.setText(f"{pos:.3f}")

    @pyqtSlot(bool, bool)
    def _on_x_status_changed(self, is_conn, is_moving):
        if self._connecting and not is_conn:
            return
        self._update_ui_state()

    @pyqtSlot(bool, bool)
    def _on_y_status_changed(self, is_conn, is_moving):
        if self._connecting and not is_conn:
            return
        self._update_ui_state()

    def _update_ui_state(self):
        # 1. Check Hardware Connection
        x_active = bool(self.hw.stage_x and self.hw.stage_x.is_connected())
        y_active = bool(self.hw.stage_y and self.hw.stage_y.is_connected())
        
        self.up_btn.setEnabled(y_active)
        self.down_btn.setEnabled(y_active)
        self.left_btn.setEnabled(x_active)
        self.right_btn.setEnabled(x_active)
        self.target_x_spin.setEnabled(x_active)
        self.target_y_spin.setEnabled(y_active)
        self.stop_btn.setEnabled(x_active or y_active)
        self.home_x_btn.setEnabled(x_active)
        self.home_y_btn.setEnabled(y_active)
        self.step_spin.setEnabled(x_active or y_active)
        self.params_btn.setEnabled(x_active or y_active)

        if not x_active:
            self.x_label.setText("---")
        if not y_active:
            self.y_label.setText("---")
        
        # Status Signal & Styles
        if x_active and y_active:
            self.sig_status_changed.emit("Connected")
        elif x_active or y_active:
            self.sig_status_changed.emit("Partial")
        else:
            self.sig_status_changed.emit("Disconnected")

    def get_current_status(self):
        x_active = bool(self.hw.stage_x and self.hw.stage_x.is_connected())
        y_active = bool(self.hw.stage_y and self.hw.stage_y.is_connected())
        
        if x_active and y_active: return "Connected"
        if x_active or y_active: return "Partial"
        return "Disconnected"

    def _on_connect_clicked(self):
        """Handle connection request."""
        threading.Thread(target=self._do_connect, daemon=True).start()

    def _do_connect(self):
        self._connecting = True
        self.sig_status_changed.emit("Connecting...")

        try:
            # 1. Get configs from hardware list
            hw_cfg = self.hw.config.get('hardware', {}).get('accessories', [])
            x_cfg = next((c for c in hw_cfg if c['id'] == 'stage_x'), None)
            y_cfg = next((c for c in hw_cfg if c['id'] == 'stage_y'), None)

            # 2. Initialize and connect Stage X
            if x_cfg and not (self.hw.stage_x and self.hw.stage_x.is_connected()):
                logger.info("Connecting Stage X...")
                try:
                    stage_x = self.hw.initialize_instrument('stage_x', 'kdc101', x_cfg)
                    stage_x.connect()
                    logger.info("Stage X connected.")
                except Exception as e:
                    logger.error(f"Failed to connect Stage X: {e}")

            # 3. Initialize and connect Stage Y
            if y_cfg and not (self.hw.stage_y and self.hw.stage_y.is_connected()):
                logger.info("Connecting Stage Y...")
                try:
                    stage_y = self.hw.initialize_instrument('stage_y', 'kdc101', y_cfg)
                    stage_y.connect()
                    logger.info("Stage Y connected.")
                except Exception as e:
                    logger.error(f"Failed to connect Stage Y: {e}")
        finally:
            self._connecting = False
            # 4. Refresh UI to reflect actual connection state
            self._update_ui_state()

    def _on_jog_clicked(self, dx, dy):
        step = self.step_spin.value()
        stage_x = cast(Optional[ThorlabsKDC101], self.hw.stage_x)
        stage_y = cast(Optional[ThorlabsKDC101], self.hw.stage_y)
        if dx != 0 and stage_x is not None:
            threading.Thread(target=lambda: stage_x.move_by(dx * step), daemon=True).start()
        if dy != 0 and stage_y is not None:
            threading.Thread(target=lambda: stage_y.move_by(dy * step), daemon=True).start()

    def _on_target_changed(self, axis):
        stage_x = cast(Optional[ThorlabsKDC101], self.hw.stage_x)
        stage_y = cast(Optional[ThorlabsKDC101], self.hw.stage_y)
        if axis == 'x':
            val = self.target_x_spin.value()
            if stage_x is not None:
                threading.Thread(target=lambda: stage_x.move_to(val), daemon=True).start()
        else:
            val = self.target_y_spin.value()
            if stage_y is not None:
                threading.Thread(target=lambda: stage_y.move_to(val), daemon=True).start()

    def _on_stop_clicked(self):
        stage_x = cast(Optional[ThorlabsKDC101], self.hw.stage_x)
        stage_y = cast(Optional[ThorlabsKDC101], self.hw.stage_y)
        if stage_x is not None:
            stage_x.stop()
        if stage_y is not None:
            stage_y.stop()

    def _on_home_clicked(self, axis):
        """Perform homing on specific stage."""
        stage_x = cast(Optional[ThorlabsKDC101], self.hw.stage_x)
        stage_y = cast(Optional[ThorlabsKDC101], self.hw.stage_y)
        if axis == 'x':
            self.home_x_btn.setEnabled(False)
            target_motor = stage_x
        else:
            self.home_y_btn.setEnabled(False)
            target_motor = stage_y
            
        if not target_motor:
            return

        def do_home():
            try:
                target_motor.home()
            finally:
                self._update_ui_state()

        threading.Thread(target=do_home, daemon=True).start()
