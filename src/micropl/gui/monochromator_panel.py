"""
Monochromator panel for controlling the Horiba FHR640.
"""

import logging
from ..qt import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGroupBox, QDoubleSpinBox, QComboBox,
    QGridLayout, QFrame, Qt, QTimer, pyqtSlot
)

from ..hardware.manager import HardwareManager
from ..utils import conversions

logger = logging.getLogger(__name__)


class MonochromatorPanel(QWidget):
    """Widget for controlling FHR640 monochromator parameters."""

    def __init__(self):
        super().__init__()
        self.hw = HardwareManager()
        self.current_unit = "nm"
        self._last_move_val = None
        self._last_move_unit = None
        self._last_ent_slit_val = None
        self._last_exit_slit_val = None
        self._was_connected = False
        self._init_ui()
        logger.info("Monochromator panel initialized")

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        # Main Group Box
        group = QGroupBox("Monochromator")
        grid = QGridLayout()
        grid.setSpacing(5)
        group.setLayout(grid)

        row = 0
        # 1. Header: Position and Status
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("λ:"))
        self.curr_pos_label = QLabel("---")
        self.curr_pos_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.curr_pos_label.setStyleSheet(
            "background-color: #f8f9fa; border: 1px solid #ced4da; border-radius: 4px; "
            "padding: 4px 10px; min-width: 110px; "
            "font-weight: bold; font-family: monospace; font-size: 20px; color: #00008b;"
        )
        header_layout.addWidget(self.curr_pos_label)
        
        self.wave_unit_label = QLabel("nm")
        self.wave_unit_label.setStyleSheet("font-size: 20px; font-weight: bold;")
        header_layout.addWidget(self.wave_unit_label)
        header_layout.addStretch()
        
        grid.addLayout(header_layout, row, 0, 1, 2)

        row += 1
        # Separator
        grid.addWidget(self._create_separator(), row, 0, 1, 2)

        row += 1
        # 2. Spectral Position Control
        grid.addWidget(QLabel("Set λ:"), row, 0)
        pos_ctrl_layout = QHBoxLayout()
        self.pos_spin = QDoubleSpinBox()
        self.pos_spin.setRange(0, 100000)
        self.pos_spin.setValue(500.0)
        self.pos_spin.setDecimals(3)
        self.pos_spin.setFixedWidth(90)
        pos_ctrl_layout.addWidget(self.pos_spin)

        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["nm", "meV", "cm⁻¹"])
        self.unit_combo.setFixedWidth(65)
        self.unit_combo.currentIndexChanged.connect(self._on_unit_changed)
        pos_ctrl_layout.addWidget(self.unit_combo)
        
        pos_ctrl_layout.addStretch()
        grid.addLayout(pos_ctrl_layout, row, 1)

        row += 1
        # Separator
        grid.addWidget(self._create_separator(), row, 0, 1, 2)

        row += 1
        # 3. Slits (µm)
        grid.addWidget(QLabel("Slits (µm):"), row, 0)
        slits_layout = QHBoxLayout()
        slits_layout.addWidget(QLabel("Ent:"))
        self.ent_slit_spin = QDoubleSpinBox()
        self.ent_slit_spin.setRange(0, 7000)
        self.ent_slit_spin.setValue(100.0)
        self.ent_slit_spin.setFixedWidth(70)
        slits_layout.addWidget(self.ent_slit_spin)

        slits_layout.addWidget(QLabel("Exit:"))
        self.exit_slit_spin = QDoubleSpinBox()
        self.exit_slit_spin.setRange(0, 7000)
        self.exit_slit_spin.setValue(100.0)
        self.exit_slit_spin.setFixedWidth(70)
        slits_layout.addWidget(self.exit_slit_spin)
        
        slits_layout.addStretch()
        grid.addLayout(slits_layout, row, 1)

        row += 1
        # Separator
        grid.addWidget(self._create_separator(), row, 0, 1, 2)

        row += 1
        # 4. Grating
        grid.addWidget(QLabel("Grating:"), row, 0)
        grating_layout = QHBoxLayout()
        self.grating_combo = QComboBox()
        self.grating_combo.addItems(["600", "1200", "1800"])
        self.grating_combo.setCurrentText("1200")
        self.grating_combo.setFixedWidth(60)
        grating_layout.addWidget(self.grating_combo)
        grating_layout.addWidget(QLabel("g/mm"))

        self.grating_set_btn = QPushButton("Switch")
        self.grating_set_btn.clicked.connect(self._on_grating_set)
        self.grating_set_btn.setFixedWidth(60)
        grating_layout.addWidget(self.grating_set_btn)
        
        grating_layout.addStretch()
        grid.addLayout(grating_layout, row, 1)

        row += 1
        # Separator
        grid.addWidget(self._create_separator(), row, 0, 1, 2)

        row += 1
        # 5. Mirror Ports
        grid.addWidget(QLabel("Mirrors:"), row, 0)
        mirror_layout = QHBoxLayout()
        mirror_layout.addWidget(QLabel("Ent:"))
        self.ent_mirror_combo = QComboBox()
        self.ent_mirror_combo.addItems(["Direct", "Side"])
        self.ent_mirror_combo.setFixedWidth(70)
        mirror_layout.addWidget(self.ent_mirror_combo)

        mirror_layout.addWidget(QLabel("Exit:"))
        self.exit_mirror_combo = QComboBox()
        self.exit_mirror_combo.addItems(["Direct", "Side"])
        self.exit_mirror_combo.setFixedWidth(70)
        mirror_layout.addWidget(self.exit_mirror_combo)
        
        mirror_layout.addStretch()
        grid.addLayout(mirror_layout, row, 1)

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
        
        grid.addLayout(footer_layout, row, 0, 1, 2)

        layout.addWidget(group)
        layout.addStretch()

        # Connect Move on input
        self.pos_spin.editingFinished.connect(self._on_target_input_finished)

        # Connect Slit changes
        self.ent_slit_spin.editingFinished.connect(lambda: self._on_slit_set(0, self.ent_slit_spin.value()))
        self.exit_slit_spin.editingFinished.connect(lambda: self._on_slit_set(2, self.exit_slit_spin.value()))
        
        # Connect Mirror changes
        self.ent_mirror_combo.currentIndexChanged.connect(
            lambda index: self._on_mirror_set("entrance", self.ent_mirror_combo.itemText(index))
        )
        self.exit_mirror_combo.currentIndexChanged.connect(
            lambda index: self._on_mirror_set("exit", self.exit_mirror_combo.itemText(index))
        )

        # Polling timer for status
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_status)
        self.timer.start(2000) # 0.5 Hz is enough for mono

    def _create_separator(self) -> QFrame:
        """Create a horizontal separator line."""
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    def _update_status(self):
        """Update connection status and position."""
        mono = self.hw.mono
        is_conn = mono and mono.is_connected()
        
        if is_conn:
            self.status_label.setText("Connected")
            self.status_label.setStyleSheet("color: green; font-size: 10px;")
            self.connect_btn.setEnabled(False)
            self.connect_btn.setVisible(True)
            try:
                curr_nm = mono.get_current_wavelength()
                
                # Convert to current display unit
                display_val = curr_nm
                if self.current_unit == "meV":
                    display_val = conversions.nm_to_meV(curr_nm)
                elif self.current_unit == "cm-1":
                    display_val = conversions.nm_to_inv_cm(curr_nm)
                
                self.curr_pos_label.setText(f"{display_val:.3f}")
                
                # Update device info if just connected
                if not self._was_connected:
                    info = mono.get_info()
                    model = info.get('model', 'FHR640')
                    port = info.get('port', '---')
                    self.device_info_label.setText(f"Device: {model} (Port: {port})")
                    self._was_connected = True
                    
            except Exception as e:
                logger.error(f"Monochromator communication error: {e}")
                self.curr_pos_label.setText("Error")
                self.status_label.setText("Error")
                self.status_label.setStyleSheet("color: red; font-size: 10px;")
                self._was_connected = False
                try: mono.disconnect()
                except: pass
        else:
            self.status_label.setText("Disconnected")
            self.status_label.setStyleSheet("color: red; font-size: 10px;")
            self.connect_btn.setEnabled(True)
            self.connect_btn.setVisible(True)
            self.curr_pos_label.setText("---")
            self.device_info_label.setText("Device: ---")
            self._was_connected = False

    def _on_connect_clicked(self):
        """Try to connect to the monochromator."""
        from ..qt import QMessageBox
        
        # 1. Ensure instrument is initialized
        mono = self.hw.mono
        if not mono:
            try:
                mono = self.hw.initialize_instrument('mono', 'fhr640')
            except Exception as e:
                QMessageBox.critical(self, "Hardware Error", f"Failed to initialize Monochromator driver:\n{e}")
                return

        # 2. Try to connect
        try:
            self.status_label.setText("Connecting...")
            self.status_label.setStyleSheet("color: orange; font-size: 10px;")
            self.connect_btn.setEnabled(False)
            
            mono.connect()
            logger.info("Monochromator connected via individual panel button")
            self._update_status()
        except Exception as e:
            logger.error(f"Failed to connect Monochromator: {e}")
            QMessageBox.critical(self, "Connection Failed", f"Could not connect to Monochromator:\n{e}")
            self._update_status()
        finally:
            self.connect_btn.setEnabled(True)

    def _on_target_input_finished(self):
        """Handle target input finished (Enter or focus lost)."""
        val = self.pos_spin.value()
        unit = self.unit_combo.currentText()
        
        # Only move if the value/unit changed from our last move command
        if val == self._last_move_val and unit == self._last_move_unit:
            return
            
        logger.info(f"Target changed to {val} {unit}, triggering move.")
        
        mono = self.hw.mono
        if mono:
            try:
                mono.set_spectral_position(val, unit)
                self._last_move_val = val
                self._last_move_unit = unit
                # Force status update to show movement started or new value
                self._update_status()
            except Exception as e:
                logger.error(f"Failed to move: {e}")

    def _on_unit_changed(self):
        """Handle unit change and convert current value."""
        new_unit = self.unit_combo.currentText()
        old_unit = self.current_unit
        
        if new_unit == old_unit:
            return
            
        val = self.pos_spin.value()
        
        # Blocking signals to prevent a move during conversion
        self.pos_spin.blockSignals(True)
        
        try:
            # First convert to nm as intermediate
            if old_unit == "meV":
                val = conversions.meV_to_nm(val)
            elif old_unit == "cm⁻¹":
                val = conversions.inv_cm_to_nm(val)
            
            # Now convert nm to new unit
            if new_unit == "meV":
                val = conversions.nm_to_meV(val)
            elif new_unit == "cm⁻¹":
                val = conversions.nm_to_inv_cm(val)
                
            self.pos_spin.setValue(val)
            self.current_unit = new_unit
            self.hw.spectral_unit = new_unit # Sync with global shared state
            self.wave_unit_label.setText(new_unit) # Update actual display label
            logger.info(f"Converted value to {val:.3f} {new_unit}")
        except Exception as e:
            logger.error(f"Error during unit conversion: {e}")
        finally:
            self.pos_spin.blockSignals(False)

    def _on_slit_set(self, slit_id: int, width_um: float):
        """Handle slit set button click."""
        # Only set if the value actually changed from our last command
        if slit_id == 0:
            if width_um == self._last_ent_slit_val:
                return
            self._last_ent_slit_val = width_um
        elif slit_id == 2:
            if width_um == self._last_exit_slit_val:
                return
            self._last_exit_slit_val = width_um

        mono = self.hw.mono
        if mono:
            try:
                mono.set_slit_width(width_um, slit_id=slit_id)
                logger.info(f"Slit {slit_id} set to {width_um} um")
            except Exception as e:
                logger.error(f"Failed to set slit: {e}")

    def _on_grating_set(self):
        """Handle grating switch button click."""
        density = int(self.grating_combo.currentText())
        mono = self.hw.mono
        if mono:
            try:
                mono.set_grating_by_density(density)
                logger.info(f"Grating switched to {density} g/mm")
            except Exception as e:
                logger.error(f"Failed to switch grating: {e}")

    def _on_mirror_set(self, port: str, position: str):
        """Handle mirror apply button click."""
        mono = self.hw.mono
        if mono:
            try:
                mono.set_mirror(port=port, position=position.lower())
                logger.info(f"{port.capitalize()} mirror set to {position}")
            except Exception as e:
                logger.error(f"Failed to set mirror: {e}")
