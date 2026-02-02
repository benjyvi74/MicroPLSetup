"""
Power meter control panel.
"""

import logging
from ..qt import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGroupBox, QDoubleSpinBox, QGridLayout, 
    QFrame, Qt, QTimer, pyqtSlot, QDialog, QDialogButtonBox,
    QCheckBox, QSpinBox, QComboBox
)

from ..hardware.manager import HardwareManager

logger = logging.getLogger(__name__)


class PMSettingsDialog(QDialog):
    """Dialog for Power Meter configuration."""

    def __init__(self, parent=None, current_params=None):
        super().__init__(parent)
        self.setWindowTitle("Power Meter Configuration")
        self.setModal(True)
        
        self.params = current_params or {
            'averaging': 1, 'autorange': True, 
            'range': 'auto', 'ranges': [],
            'beam_diameter': 1.0
        }
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        form_layout = QGridLayout()
        layout.addLayout(form_layout)
        
        # 1. Averaging
        form_layout.addWidget(QLabel("Averaging Count:"), 0, 0)
        self.avg_spin = QSpinBox()
        self.avg_spin.setRange(1, 1000)
        self.avg_spin.setValue(self.params['averaging'])
        form_layout.addWidget(self.avg_spin, 0, 1)
        
        # 2. Auto-range / Range
        self.autorange_check = QCheckBox("Auto-range")
        self.autorange_check.setChecked(self.params['autorange'])
        self.autorange_check.toggled.connect(self._on_autorange_toggled)
        form_layout.addWidget(self.autorange_check, 1, 0, 1, 2)
        
        form_layout.addWidget(QLabel("Manual Range:"), 2, 0)
        self.range_combo = QComboBox()
        for r in self.params['ranges']:
            # Format nicely, e.g. "1.00 mW"
            if r < 1e-3: label = f"{r*1e6:.1f} µW"
            elif r < 1: label = f"{r*1e3:.1f} mW"
            else: label = f"{r:.1f} W"
            self.range_combo.addItem(label, r)
        
        self.range_combo.setEnabled(not self.params['autorange'])
        form_layout.addWidget(self.range_combo, 2, 1)

        # 3. Beam Diameter
        form_layout.addWidget(QLabel("Beam Diam (mm):"), 3, 0)
        self.beam_spin = QDoubleSpinBox()
        self.beam_spin.setRange(0.01, 100.0)
        self.beam_spin.setDecimals(2)
        self.beam_spin.setValue(self.params.get('beam_diameter', 1.0))
        form_layout.addWidget(self.beam_spin, 3, 1)
        
        # 4. Zeroing
        self.zero_btn = QPushButton("Zero Sensor (Dark)")
        self.zero_btn.clicked.connect(self._on_zero_clicked)
        layout.addWidget(self.zero_btn)
        
        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_autorange_toggled(self, checked):
        self.range_combo.setEnabled(not checked)

    def _on_zero_clicked(self):
        """Perform zero calibration."""
        hw = HardwareManager()
        pm = hw.get_instrument('pm100')
        if pm and pm.is_connected():
            try:
                pm.zero()
                logger.info("Power meter zeroed")
            except Exception as e:
                logger.error(f"Failed to zero power meter: {e}")

    def get_values(self):
        return {
            'averaging': self.avg_spin.value(),
            'autorange': self.autorange_check.isChecked(),
            'range': self.range_combo.currentData() if not self.autorange_check.isChecked() else 'auto',
            'beam_diameter': self.beam_spin.value()
        }


class PowerMeterPanel(QWidget):
    """Widget for power meter control and display."""

    def __init__(self):
        super().__init__()
        self.hw = HardwareManager()
        self._init_ui()
        
        # Polling timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_status)
        self.timer.start(500)  # 2 Hz update
        
        self._was_connected = False
        logger.info("Power meter panel initialized")

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        group = QGroupBox("Power Meter")
        group_layout = QGridLayout()
        group_layout.setSpacing(5)
        group.setLayout(group_layout)

        row = 0
        # 1. Power and Status (Header row)
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("Power :"))
        self.power_label = QLabel("---")
        self.power_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.power_label.setStyleSheet(
            "background-color: #f8f9fa; border: 1px solid #ced4da; border-radius: 4px; "
            "padding: 4px 10px; min-width: 110px; "
            "font-weight: bold; font-family: monospace; font-size: 20px; color: #00008b;"
        )
        header_layout.addWidget(self.power_label)
        
        self.unit_label = QLabel("W")
        self.unit_label.setStyleSheet("font-size: 20px; font-weight: bold;")
        header_layout.addWidget(self.unit_label)
        
        header_layout.addStretch()
        
        self.status_label = QLabel("Disconnected")
        self.status_label.setStyleSheet("color: red;")
        header_layout.addWidget(self.status_label)
        
        group_layout.addLayout(header_layout, row, 0, 1, 2)

        row += 1
        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        group_layout.addWidget(line, row, 0, 1, 2)

        row += 1
        # 2. Wavelength
        group_layout.addWidget(QLabel("λ:"), row, 0)
        wave_layout = QHBoxLayout()
        self.wave_spin = QDoubleSpinBox()
        self.wave_spin.setRange(200, 2500)
        self.wave_spin.setDecimals(1)
        self.wave_spin.setValue(532.0)
        self.wave_spin.setFixedWidth(80)
        self.wave_spin.editingFinished.connect(self._on_wavelength_changed)
        wave_layout.addWidget(self.wave_spin)
        wave_layout.addWidget(QLabel("nm"))
        wave_layout.addStretch()
        group_layout.addLayout(wave_layout, row, 1)

        row += 1
        # 3. Config Button
        self.config_btn = QPushButton("Measure Config...")
        self.config_btn.clicked.connect(self._on_config_clicked)
        group_layout.addWidget(self.config_btn, row, 0, 1, 2)

        row += 1
        # 4. Sensor Info
        self.sensor_label = QLabel("Sensor: ---")
        self.sensor_label.setStyleSheet("color: gray; font-size: 10px;")
        group_layout.addWidget(self.sensor_label, row, 0, 1, 2)

        layout.addWidget(group)
        layout.addStretch()

    def _update_status(self):
        """Update power reading and status."""
        pm = self.hw.get_instrument('pm100')
        is_conn = pm and pm.is_connected()
        
        if is_conn:
            try:
                # Read power
                p_val = pm.read_power()
                self._display_power(p_val)
                self.status_label.setText("Connected")
                self.status_label.setStyleSheet("color: green;")
                
                # Enable controls
                self.wave_spin.setEnabled(True)
                self.config_btn.setEnabled(True)
                
                # If just connected, sync parameters
                if not self._was_connected:
                    self._sync_hardware_params()
                    info = pm.get_info()
                    model = info.get('sensor_model', 'Unknown')
                    sn = info.get('sensor_sn', '---')
                    self.sensor_label.setText(f"Sensor: {model} (S/N: {sn})")
                    self._was_connected = True
            except Exception:
                self.power_label.setText("Error")
                self.status_label.setText("Error")
                self.status_label.setStyleSheet("color: red;")
                self.sensor_label.setText("Sensor: Error")
        else:
            self.power_label.setText("---")
            self.status_label.setText("Disconnected")
            self.status_label.setStyleSheet("color: red;")
            self.sensor_label.setText("Sensor: ---")
            self.wave_spin.setEnabled(False)
            self.config_btn.setEnabled(False)
            self._was_connected = False

    def _display_power(self, val):
        """Format and display power with appropriate precision."""
        if abs(val) < 1e-9:
            self.power_label.setText(f"{val*1e12:.3f}")
            self.unit_label.setText("pW")
        elif abs(val) < 1e-6:
            self.power_label.setText(f"{val*1e9:.3f}")
            self.unit_label.setText("nW")
        elif abs(val) < 1e-3:
            self.power_label.setText(f"{val*1e6:.3f}")
            self.unit_label.setText("µW")
        elif abs(val) < 1:
            self.power_label.setText(f"{val*1000:.3f}")
            self.unit_label.setText("mW")
        else:
            self.power_label.setText(f"{val:.3f}")
            self.unit_label.setText("W")

    def _on_wavelength_changed(self):
        """Update wavelength on hardware."""
        pm = self.hw.get_instrument('pm100')
        if pm and pm.is_connected():
            try:
                pm.set_wavelength(self.wave_spin.value())
            except Exception as e:
                logger.error(f"Failed to set wavelength: {e}")

    def _sync_hardware_params(self):
        """Read current parameters from hardware."""
        pm = self.hw.get_instrument('pm100')
        if pm:
            try:
                self.wave_spin.blockSignals(True)
                self.wave_spin.setValue(pm.get_wavelength())
                self.wave_spin.blockSignals(False)
            except Exception:
                pass

    def _on_config_clicked(self):
        """Open settings dialog."""
        pm = self.hw.get_instrument('pm100')
        if not pm: return
        
        current_params = {
            'averaging': pm.get_averaging_count(),
            'autorange': pm.get_autorange(),
            'ranges': pm.get_ranges(),
            'beam_diameter': pm.get_beam_diameter()
        }
        
        dialog = PMSettingsDialog(self, current_params)
        if dialog.exec():
            vals = dialog.get_values()
            try:
                pm.set_averaging_count(vals['averaging'])
                pm.set_autorange(vals['autorange'])
                if not vals['autorange'] and vals['range'] is not None:
                    pm.set_range(vals['range'])
                pm.set_beam_diameter(vals['beam_diameter'])
                logger.info("Power meter configuration updated")
            except Exception as e:
                logger.error(f"Failed to update power meter config: {e}")
