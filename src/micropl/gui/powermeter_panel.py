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
import time
from collections import deque

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


class PowerTraceWindow(QDialog):
    """Window for displaying continuous power trace using PyQtGraph."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Power vs. Time Trace")
        self.resize(800, 400)
        
        # Data buffers
        self.max_points = 1000
        self.times = deque(maxlen=self.max_points)
        self.powers = deque(maxlen=self.max_points)
        self.start_time = time.time()
        
        self._init_ui()
        logger.debug("PowerTraceWindow initialized")

    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        from .plot import PlotWidget
        self.plot = PlotWidget()
        self.plot.set_labels("Time (s)", "Power")
        layout.addWidget(self.plot)
        
        controls = QHBoxLayout()
        self.clear_btn = QPushButton("Clear Trace")
        self.clear_btn.clicked.connect(self.clear_data)
        controls.addWidget(self.clear_btn)
        
        controls.addStretch()
        self.status_label = QLabel("Tracing...")
        controls.addWidget(self.status_label)
        
        layout.addLayout(controls)

    def add_point(self, power_watts: float):
        """Add a new power point to the trace."""
        current_time = time.time() - self.start_time
        self.times.append(current_time)
        self.powers.append(power_watts)
        
        # Determine best display unit based on the latest value
        abs_p = abs(power_watts)
        if abs_p < 1e-9: 
            unit, scale = "pW", 1e12
        elif abs_p < 1e-6:
            unit, scale = "nW", 1e9
        elif abs_p < 1e-3:
            unit, scale = "µW", 1e6
        elif abs_p < 1:
            unit, scale = "mW", 1e3
        else:
            unit, scale = "W", 1.0
            
        self.plot.set_labels("Time (s)", f"Power ({unit})")
        
        # Scale all points to the same unit for display
        display_powers = [p * scale for p in self.powers]
        self.plot.update_plot(list(self.times), display_powers)

    def clear_data(self):
        """Reset the trace data."""
        self.times.clear()
        self.powers.clear()
        self.start_time = time.time()
        self.plot.clear()


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
        self._background_offset = 0.0
        self.trace_window = None
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
        # 3. Primary Controls (Config + Background)
        ctrl_layout = QHBoxLayout()
        
        self.config_btn = QPushButton("Config...")
        self.config_btn.clicked.connect(self._on_config_clicked)
        ctrl_layout.addWidget(self.config_btn)

        self.bg_btn = QPushButton("Take Background")
        self.bg_btn.clicked.connect(self._on_take_background)
        ctrl_layout.addWidget(self.bg_btn)

        self.trace_btn = QPushButton("Time Trace")
        self.trace_btn.clicked.connect(self._on_trace_clicked)
        self.trace_btn.setEnabled(False)
        ctrl_layout.addWidget(self.trace_btn)
        
        self.clear_bg_btn = QPushButton("Clear")
        self.clear_bg_btn.clicked.connect(self._on_clear_background)
        self.clear_bg_btn.setVisible(False)
        self.clear_bg_btn.setFixedWidth(50)
        self.clear_bg_btn.setStyleSheet("color: #d63031; font-weight: bold;") 
        ctrl_layout.addWidget(self.clear_bg_btn)
        
        group_layout.addLayout(ctrl_layout, row, 0, 1, 2)

        row += 1
        # 4. Footer: Sensor Info and Status
        footer_layout = QHBoxLayout()
        self.sensor_label = QLabel("Sensor: ---")
        self.sensor_label.setStyleSheet("color: gray; font-size: 10px;")
        footer_layout.addWidget(self.sensor_label)
        
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

    def _update_status(self):
        """Update power reading and status."""
        pm = self.hw.get_instrument('pm100')
        is_conn = pm and pm.is_connected()
        
        if is_conn:
            try:
                # Read raw power
                p_raw = pm.read_power()
                
                # Apply background correction
                p_net = p_raw - self._background_offset
                
                self._display_power(p_net)
                self.status_label.setText("Connected")
                self.status_label.setStyleSheet("color: green; font-size: 10px;")
                self.connect_btn.setEnabled(False)
                self.connect_btn.setVisible(True)
                
                # Enable controls
                self.wave_spin.setEnabled(True)
                self.config_btn.setEnabled(True)
                self.bg_btn.setEnabled(True)
                self.trace_btn.setEnabled(True)
                
                # Update trace window if open
                if self.trace_window and self.trace_window.isVisible():
                    self.trace_window.add_point(p_net)

                # If just connected, sync parameters
                if not self._was_connected:
                    self._sync_hardware_params()
                    info = pm.get_info()
                    model = info.get('sensor_model', 'Unknown')
                    sn = info.get('sensor_sn', '---')
                    self.sensor_label.setText(f"Sensor: {model} (S/N: {sn})")
                    self._was_connected = True
            except Exception as e:
                logger.error(f"Power Meter communication error: {e}")
                self.power_label.setText("Error")
                self.status_label.setText("Error")
                self.status_label.setStyleSheet("color: red; font-size: 10px;")
                self.sensor_label.setText("Sensor: Error")
                self._was_connected = False
                try: pm.disconnect()
                except: pass
        else:
            self.power_label.setText("---")
            self.status_label.setText("Disconnected")
            self.status_label.setStyleSheet("color: red; font-size: 10px;")
            self.connect_btn.setEnabled(True)
            self.connect_btn.setVisible(True)
            self.sensor_label.setText("Sensor: ---")
            self.wave_spin.setEnabled(False)
            self.config_btn.setEnabled(False)
            self.bg_btn.setEnabled(False)
            self.trace_btn.setEnabled(False)
            self.clear_bg_btn.setVisible(False)
            self._was_connected = False
            if self.trace_window:
                self.trace_window.close()

    def _on_take_background(self):
        """Take current reading as software background offset."""
        pm = self.hw.get_instrument('pm100')
        if pm and pm.is_connected():
            try:
                self._background_offset = pm.read_power()
                self.clear_bg_btn.setVisible(True)
                logger.info(f"Power meter software background set: {self._background_offset:.6e} W")
            except Exception as e:
                logger.error(f"Failed to take background: {e}")

    def _on_clear_background(self):
        """Clear software background offset."""
        self._background_offset = 0.0
        self.clear_bg_btn.setVisible(False)
        logger.info("Power meter software background cleared")

    def _on_connect_clicked(self):
        """Try to connect to the power meter."""
        from ..qt import QMessageBox
        
        pm = self.hw.get_instrument('pm100')
        if not pm:
            try:
                pm = self.hw.initialize_instrument('pm100', 'pm100')
            except Exception as e:
                QMessageBox.critical(self, "Hardware Error", f"Failed to initialize Power Meter driver:\n{e}")
                return

        try:
            self.status_label.setText("Connecting...")
            self.status_label.setStyleSheet("color: orange; font-size: 10px;")
            self.connect_btn.setEnabled(False)
            
            pm.connect()
            logger.info("Power meter connected via individual panel button")
            self._update_status()
        except Exception as e:
            logger.error(f"Failed to connect Power Meter: {e}")
            QMessageBox.critical(self, "Connection Failed", f"Could not connect to Power Meter:\n{e}")
            self._update_status()
        finally:
            self.connect_btn.setEnabled(True)

    def _display_power(self, val):
        """Format and display power with appropriate precision."""
        val_str, unit = self._get_power_string_and_unit(val)
        self.power_label.setText(val_str)
        self.unit_label.setText(unit)

    def _get_power_string_and_unit(self, val):
        """Helper to get formatted power value and unit string."""
        if abs(val) < 1e-9:
            return f"{val*1e12:.3f}", "pW"
        elif abs(val) < 1e-6:
            return f"{val*1e9:.3f}", "nW"
        elif abs(val) < 1e-3:
            return f"{val*1e6:.3f}", "µW"
        elif abs(val) < 1:
            return f"{val*1000:.3f}", "mW"
        else:
            return f"{val:.3f}", "W"

    def _on_trace_clicked(self):
        """Open or show the power trace window."""
        if self.trace_window is None:
            self.trace_window = PowerTraceWindow(self)
        
        self.trace_window.show()
        self.trace_window.raise_()
        self.trace_window.activateWindow()

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
