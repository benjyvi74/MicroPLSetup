"""
Monochromator panel for controlling Horiba Monochromators.
"""

import logging
import threading
from ..qt import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGroupBox, QDoubleSpinBox, QSpinBox, QComboBox,
    QGridLayout, QFrame, Qt, QTimer, pyqtSlot, pyqtSignal,
    QApplication, QMessageBox
)

from ..hardware.manager import HardwareManager
from ..utils import conversions
from ..core.calibration import SpectrometerCalibration

logger = logging.getLogger(__name__)


class MonochromatorPanel(QWidget):
    """Widget for controlling the active monochromator's parameters."""
    sig_status_changed = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.hw = HardwareManager()
        self.current_unit = "nm"
        
        # Load defaults from active monochromator config
        mono_id = self.hw.active_monochromator_id
        mono_config = self.hw.get_monochromator_config(mono_id) if mono_id else {}
        
        self.display_name = mono_config.get('name', 'Monochromator')
        self._last_move_val = float(mono_config.get('center_wavelength', 500.0))
        self._last_move_unit = "nm"
        self._last_ent_slit_val = int(mono_config.get('slit_width', 100))
        self._last_exit_slit_val = int(mono_config.get('slit_width', 100))
        
        gratings = mono_config.get('gratings', [600, 1200, 1800])
        g_idx = int(mono_config.get('grating_idx', 1))
        self._last_grating_val = gratings[g_idx] if g_idx < len(gratings) else (gratings[0] if gratings else 1200)
        
        self._was_connected = False
        self._connecting = False 
        self.setMinimumWidth(340)
        self._init_ui()

    def _init_ui(self):
        """Initialize the user interface."""
        grid = QGridLayout(self)
        grid.setContentsMargins(10, 10, 10, 10)
        grid.setSpacing(5)

        row = 0
        # 1. Header: Position and Status
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("λ"))
        self.curr_pos_label = QLabel("---")
        self.curr_pos_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.curr_pos_label.setStyleSheet(
            "background-color: #f8f9fa; border: 1px solid #ced4da; border-radius: 4px; "
            "padding: 4px 10px; min-width: 110px; "
            "font-weight: bold; font-family: 'Courier New'; font-size: 20px; color: #00008b;"
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
        # 2. Spectral Position & Grating
        pos_ctrl_layout = QHBoxLayout()
        pos_ctrl_layout.addWidget(QLabel("λ:"))
        self.pos_spin = QDoubleSpinBox()
        self.pos_spin.setRange(0, 100000)
        self.pos_spin.setValue(500.0)
        self.pos_spin.setDecimals(3)
        self.pos_spin.setMinimumWidth(80)
        pos_ctrl_layout.addWidget(self.pos_spin)

        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["nm", "meV", "cm⁻¹"])
        self.unit_combo.setMinimumWidth(60)
        self.unit_combo.currentIndexChanged.connect(self._on_unit_changed)
        pos_ctrl_layout.addWidget(self.unit_combo)
        
        pos_ctrl_layout.addStretch()
        
        pos_ctrl_layout.addWidget(QLabel("Grating:"))
        mono_id = self.hw.active_monochromator_id
        mono_config = self.hw.get_monochromator_config(mono_id)
        
        self.grating_combo = QComboBox()
        gratings = mono_config.get('gratings', [600, 1200, 1800])
        self.grating_combo.addItems([str(g) for g in gratings])
        self.grating_combo.setFixedWidth(60)
        
        self.grating_combo.blockSignals(True)
        g_idx = int(mono_config.get('grating_idx', 1))
        if g_idx < self.grating_combo.count():
            self.grating_combo.setCurrentIndex(g_idx)
        else:
            self.grating_combo.setCurrentIndex(0)
        self.grating_combo.blockSignals(False)

        pos_ctrl_layout.addWidget(self.grating_combo)
        pos_ctrl_layout.addWidget(QLabel("g/mm"))
        
        grid.addLayout(pos_ctrl_layout, row, 0, 1, 2)

        row += 1
        # Separator
        grid.addWidget(self._create_separator(), row, 0, 1, 2)

        row += 1
        # 3. Slits (µm)
        grid.addWidget(QLabel("Slits (µm)"), row, 0)
        slits_layout = QHBoxLayout()
        slits_layout.addWidget(QLabel("Ent:"))
        self.ent_slit_spin = QSpinBox()
        self.ent_slit_spin.setRange(0, 2000)
        self.ent_slit_spin.setValue(100)
        self.ent_slit_spin.setFixedWidth(70)
        slits_layout.addWidget(self.ent_slit_spin)

        slits_layout.addWidget(QLabel("Exit:"))
        self.exit_slit_spin = QSpinBox()
        self.exit_slit_spin.setRange(0, 2000)
        self.exit_slit_spin.setValue(100)
        self.exit_slit_spin.setFixedWidth(70)
        slits_layout.addWidget(self.exit_slit_spin)
        
        slits_layout.addStretch()
        grid.addLayout(slits_layout, row, 1)

        # Apply state defaults to UI
        self.pos_spin.setValue(self._last_move_val)
        self.ent_slit_spin.setValue(self._last_ent_slit_val)
        self.exit_slit_spin.setValue(self._last_exit_slit_val)

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
        row += 1        # Connect Move on input
        self.pos_spin.editingFinished.connect(self._on_target_input_finished)

        # Connect Slit changes
        self.ent_slit_spin.editingFinished.connect(lambda: self._on_slit_set(0, self.ent_slit_spin.value()))
        self.exit_slit_spin.editingFinished.connect(lambda: self._on_slit_set(2, self.exit_slit_spin.value()))
        
        # Connect Grating change
        self.grating_combo.currentIndexChanged.connect(self._on_grating_set)

        # Connect Mirror changes
        self.ent_mirror_combo.currentIndexChanged.connect(
            lambda index: self._on_mirror_set("entrance", self.ent_mirror_combo.itemText(index))
        )
        self.exit_mirror_combo.currentIndexChanged.connect(
            lambda index: self._on_mirror_set("exit", self.exit_mirror_combo.itemText(index))
        )

        # Connect to Hardware Service signals
        service = self.hw.service
        service.mono_pos_changed.connect(self._on_pos_changed)
        service.mono_status_changed.connect(self._on_status_changed)
        
        # Initially disable all controls
        self._update_controls_enabled(False)

        logger.info("Monochromator panel initialized (Signal-driven)")

        # Disable focus for all buttons to prevent scroll-jumping
        for btn in self.findChildren(QPushButton):
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _update_controls_enabled(self, enabled: bool):
        """Enable or disable input controls."""
        self.pos_spin.setEnabled(enabled)
        self.unit_combo.setEnabled(enabled)
        self.ent_slit_spin.setEnabled(enabled)
        self.exit_slit_spin.setEnabled(enabled)
        self.grating_combo.setEnabled(enabled)
        self.ent_mirror_combo.setEnabled(enabled)
        self.exit_mirror_combo.setEnabled(enabled)

    def _create_separator(self) -> QFrame:
        """Create a horizontal separator line."""
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    @pyqtSlot(float)
    def _on_pos_changed(self, curr_nm):
        """Update position label from hardware service."""
        try:
            # Convert to current display unit
            display_val = curr_nm
            if self.current_unit == "meV":
                display_val = conversions.nm_to_meV(curr_nm)
            elif self.current_unit == "cm⁻¹":
                display_val = conversions.nm_to_inv_cm(curr_nm)
            
            self.curr_pos_label.setText(f"{display_val:.3f}")
        except Exception as e:
            logger.debug(f"Error updating mono pos display: {e}")

    @pyqtSlot(bool)
    def _on_status_changed(self, is_conn):
        """Update status indicators from hardware service."""
        # Ignore "Disconnected" signals if we are currently in a long connect() call
        if self._connecting and not is_conn:
            return
            
        if is_conn:
            self.sig_status_changed.emit("Connected")
            self._update_controls_enabled(True)
            
            # If just connected, read parameters and device info
            if not self._was_connected:
                self._was_connected = True
        else:
            self.sig_status_changed.emit("Disconnected")
            self.curr_pos_label.setText("---")
            self._update_controls_enabled(False)
            self._was_connected = False

    def _on_connect_clicked(self):
        """Try to connect to the monochromator."""
        from ..qt import QMessageBox
        
        mono = self.hw.mono
        if not mono:
            try:
                mono_id = self.hw.active_monochromator_id
                mono_cfg = self.hw.get_monochromator_config(mono_id)
                mono = self.hw.initialize_instrument(mono_id, mono_cfg.get('driver', 'horiba_serial'))
            except Exception as e:
                QMessageBox.critical(self, "Hardware Error", f"Failed to initialize Monochromator driver:\n{e}")
                return

        self._connecting = True
        self.sig_status_changed.emit("Homing...")
        QApplication.processEvents() # Ensure UI reflects status during homing
        
        # Capture current UI targets before thread starts
        target_wl = self.pos_spin.value()
        target_unit = self.unit_combo.currentText()
        if target_unit == "cm⁻¹": target_unit = "cm-1" # Normalize for driver
        
        def _connect_thread():
            try:
                mono.connect()
                logger.info("Monochromator connected and homed via individual panel button")
                
                # Apply defaults after homing to ensure hardware matches UI/Config
                mono_id = self.hw.active_monochromator_id
                mono_config = self.hw.get_monochromator_config(mono_id)
                default_wl = float(mono_config.get('center_wavelength', 500.0))
                default_slit = float(mono_config.get('slit_width', 100.0))
                default_grating_idx = int(mono_config.get('grating_idx', 1))
                
                logger.info(f"Applying targets post-homing: Index {default_grating_idx} grating, {target_wl} {target_unit}, {default_slit} um slits")
                try:
                    # Set grating BEFORE wavelength for better firmware consistency
                    mono.set_grating(default_grating_idx)
                    mono.set_spectral_position(target_wl, target_unit)
                    mono.set_slit_width(default_slit, slit_id=0)
                    mono.set_slit_width(default_slit, slit_id=2)
                    logger.info("Monochromator initialization and target move complete")
                except Exception as e:
                    logger.error(f"Failed to apply mono defaults: {e}")
                
            except Exception as e:
                logger.error(f"Failed to connect Monochromator: {e}")
                # We can't show a QMessageBox from a background thread easily without signals,
                # but the HardwareWorker will eventually emit is_connected=False which will enable the button.
            finally:
                self._connecting = False
                # Re-enable button on UI thread
                QTimer.singleShot(0, lambda: self.connect_btn.setEnabled(True))
        
        threading.Thread(target=_connect_thread, daemon=True).start()


    def _check_wavelength_limit(self, wavelength_nm: float) -> bool:
        """
        Check whether wavelength_nm is within the physical limit of the
        currently selected grating. Shows a QMessageBox warning and returns
        False if out of range; returns True if the move is allowed.
        """
        try:
            grating_g_mm = int(self.grating_combo.currentText())
        except ValueError:
            return True  # Can't determine grating — allow move

        max_wl = SpectrometerCalibration.get_max_wavelength_nm(grating_g_mm)

        if wavelength_nm > max_wl:
            QMessageBox.warning(
                self,
                "Wavelength Out of Range",
                f"The requested wavelength (<b>{wavelength_nm:.1f} nm</b>) exceeds the "
                f"maximum the monochromator can reach with the current grating "
                f"(<b>{grating_g_mm} g/mm</b>).<br><br>"
                f"Maximum allowed: <b>{max_wl:.1f} nm</b>"
            )
            return False
        return True

    def _on_target_input_finished(self):
        """Handle target input finished (Enter or focus lost)."""
        val = self.pos_spin.value()
        unit = self.unit_combo.currentText()
        
        # Only move if the device is connected
        mono = self.hw.mono
        if not mono or not mono.is_connected():
            return

        # Only move if the value/unit changed from our last move command
        if val == self._last_move_val and unit == self._last_move_unit:
            return

        # Convert to nm for the limit check
        val_nm = val
        if unit == "meV":
            val_nm = conversions.meV_to_nm(val)
        elif unit == "cm⁻¹":
            val_nm = conversions.inv_cm_to_nm(val)

        if not self._check_wavelength_limit(val_nm):
            # Reset spinbox to the last accepted value so it doesn't stay wrong
            self.pos_spin.blockSignals(True)
            self.pos_spin.setValue(self._last_move_val)
            self.pos_spin.blockSignals(False)
            return

        logger.info(f"Target changed to {val} {unit}, triggering move.")
        if mono:
            def _move_thread():
                try:
                    mono.set_spectral_position(val, unit)
                    self._last_move_val = val
                    self._last_move_unit = unit
                except Exception as e:
                    logger.error(f"Failed to move: {e}")
            
            threading.Thread(target=_move_thread, daemon=True).start()

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
            if self.hw.service:
                self.hw.service.spectral_unit_changed.emit(new_unit)
            self.wave_unit_label.setText(new_unit) # Update actual display label
            
            # Update current position display label immediately
            self._on_pos_changed(self.hw.current_wavelength)
            
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
        if not mono or not mono.is_connected():
            return
            
        if mono:
            def _set_slit():
                try:
                    mono.set_slit_width(width_um, slit_id=slit_id)
                    logger.info(f"Slit {slit_id} set to {width_um} um")
                except Exception as e:
                    logger.error(f"Failed to set slit: {e}")
            
            threading.Thread(target=_set_slit, daemon=True).start()

    def _on_grating_set(self):
        """Handle grating switch automatically on selection change."""
        density = int(self.grating_combo.currentText())
        
        # Guard against redundant switches
        if density == self._last_grating_val:
            return

        mono = self.hw.mono
        if not mono or not mono.is_connected():
            return
            
        logger.info(f"Grating selection changed to {density} g/mm, triggering switch.")
        if mono:
            def _set_grating():
                try:
                    mono.set_grating_by_density(density)
                    self._last_grating_val = density
                    
                    # RE-SEND WAVELENGTH TO ADJUST POSITION
                    # The FHR640 requires the wavelength drive to re-move after a turret switch
                    val = self.pos_spin.value()
                    unit = self.unit_combo.currentText()
                    mono.set_spectral_position(val, unit)
                    
                    logger.info(f"Grating successfully switched to {density} g/mm and position adjusted to {val} {unit}")
                except Exception as e:
                    logger.error(f"Failed to switch grating: {e}")
            
            threading.Thread(target=_set_grating, daemon=True).start()

    def _on_mirror_set(self, port: str, position: str):
        """Handle mirror apply button click."""
        mono = self.hw.mono
        if not mono or not mono.is_connected():
            return
            
        if mono:
            def _set_mirror():
                try:
                    mono.set_mirror(port=port, position=position.lower())
                    logger.info(f"{port.capitalize()} mirror set to {position}")
                except Exception as e:
                    logger.error(f"Failed to set mirror: {e}")
            
            threading.Thread(target=_set_mirror, daemon=True).start()
    def get_current_status(self) -> str:
        """Return a string representing the current connection/operational status."""
        mono = self.hw.get_instrument('mono')
        if not mono or not mono.is_connected():
            return "Disconnected"
        if self._connecting:
            return "Connecting"
        return "Connected"
