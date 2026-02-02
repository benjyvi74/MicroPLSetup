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
        
        self.status_label = QLabel("Disconnected")
        self.status_label.setStyleSheet("color: red;")
        header_layout.addWidget(self.status_label)
        
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
        self.unit_combo.addItems(["nm", "meV", "cm-1"])
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
            self.status_label.setStyleSheet("color: green;")
            try:
                curr = mono.get_current_wavelength()
                self.curr_pos_label.setText(f"{curr:.3f}")
            except Exception:
                self.curr_pos_label.setText("Error")
        else:
            self.status_label.setText("Disconnected")
            self.status_label.setStyleSheet("color: red;")
            self.curr_pos_label.setText("---")

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
            elif old_unit == "cm-1":
                val = conversions.inv_cm_to_nm(val)
            
            # Now convert nm to new unit
            if new_unit == "meV":
                val = conversions.nm_to_meV(val)
            elif new_unit == "cm-1":
                val = conversions.nm_to_inv_cm(val)
                
            self.pos_spin.setValue(val)
            self.current_unit = new_unit
            logger.info(f"Converted value to {val:.3f} {new_unit}")
        except Exception as e:
            logger.error(f"Error during unit conversion: {e}")
        finally:
            self.pos_spin.blockSignals(False)

    def _on_slit_set(self, slit_id: int, width_um: float):
        """Handle slit set button click."""
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
