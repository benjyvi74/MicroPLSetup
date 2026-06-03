"""
Hardware Setup Tab — allows users to configure active hardware from the UI.
Changes are saved to default.yaml and emitted via hw_config_changed signal.
"""

import logging
from typing import Any, Dict, List

from ..qt import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QCheckBox, QComboBox, QSpinBox,
    QDoubleSpinBox, QLineEdit, QLabel, QListWidget,
    QListWidgetItem, pyqtSignal, QMessageBox, QScrollArea,
    QFrame, Qt, QSizePolicy,
)
from ..hardware.manager import HardwareManager
from ..hardware.factory import list_available_drivers

logger = logging.getLogger(__name__)


class SetupTab(QWidget):
    """
    Hardware Setup Tab.

    Displays three sections (Cameras, Monochromator, Accessories) plus a panel
    order list. The Apply button persists changes to default.yaml and emits
    hw_config_changed so the rest of the UI can rebuild accordingly.
    """
    hw_config_changed = pyqtSignal()

    def __init__(self, hw: HardwareManager, parent=None):
        super().__init__(parent)
        self.hw = hw
        self._init_ui()
        self._populate_from_config()

    # -----------------------------------------------------------------------
    # UI construction
    # -----------------------------------------------------------------------

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(16, 16, 16, 16)

        title = QLabel("Hardware Setup")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #e0e0e0;")
        root.addWidget(title)

        subtitle = QLabel(
            "Configure which hardware is available in this session. "
            "Click <b>Apply</b> to save changes and reload the interface."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #aaa; margin-bottom: 6px;")
        root.addWidget(subtitle)

        # --- scroll area so it works on small screens ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setSpacing(14)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

        # Preset selection panel at the top of scrollable area
        inner_layout.addWidget(self._build_presets_section())

        # Equipment tables arranged horizontally
        tables_row = QHBoxLayout()
        tables_row.addWidget(self._build_cameras_section())
        tables_row.addWidget(self._build_monochromator_section())
        tables_row.addWidget(self._build_accessories_section())
        inner_layout.addLayout(tables_row)
        
        inner_layout.addStretch()

        # --- Apply button ---
        apply_row = QHBoxLayout()
        apply_row.addStretch()
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setFixedWidth(120)
        self.apply_btn.setStyleSheet(
            "QPushButton { background-color: #2196F3; color: white; font-weight: bold; "
            "border-radius: 6px; padding: 8px 18px; font-size: 13px; }"
            "QPushButton:hover { background-color: #1976D2; }"
        )
        self.apply_btn.clicked.connect(self._on_apply)
        apply_row.addWidget(self.apply_btn)
        root.addLayout(apply_row)

    # -- Cameras -------------------------------------------------------------

    def _build_cameras_section(self) -> QGroupBox:
        box = QGroupBox("Cameras")
        box.setStyleSheet("QGroupBox { font-weight: bold; font-size: 13px; } QWidget { font-weight: normal; }")
        layout = QVBoxLayout(box)

        # Table: enabled | name | model | driver | serial_number | index | temperature | role
        self.cameras_table = QTableWidget(0, 8)
        self.cameras_table.setHorizontalHeaderLabels(
            ["Enabled", "Name", "Model", "Driver", "Serial Number", "Camera Index", "Temperature (°C)", "Role"]
        )
        header = self.cameras_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        self.cameras_table.verticalHeader().setVisible(False)
        self.cameras_table.setAlternatingRowColors(True)
        layout.addWidget(self.cameras_table)
        return box

    # -- Monochromator ------------------------------------------------------    
    def _build_monochromator_section(self) -> QGroupBox:
        box = QGroupBox("Monochromators")
        box.setStyleSheet("QGroupBox { font-weight: bold; font-size: 13px; } QWidget { font-weight: normal; }")
        layout = QVBoxLayout(box)

        # Table: enabled | name | driver | grating_idx
        self.mono_table = QTableWidget(0, 4)
        self.mono_table.setHorizontalHeaderLabels(
            ["Enabled", "Name", "Driver", "Default Grating Index"]
        )
        header = self.mono_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.mono_table.verticalHeader().setVisible(False)
        self.mono_table.setAlternatingRowColors(True)
        self.mono_table.setSelectionBehavior(QHeaderView.SelectionBehavior.SelectRows)
        layout.addWidget(self.mono_table)
        return box

    # -- Accessories ---------------------------------------------------------

    def _build_accessories_section(self) -> QGroupBox:
        box = QGroupBox("Accessories")
        box.setStyleSheet("QGroupBox { font-weight: bold; font-size: 13px; } QWidget { font-weight: normal; }")
        layout = QVBoxLayout(box)

        # Table: enabled | name | driver | id | serial_number
        self.acc_table = QTableWidget(0, 5)
        self.acc_table.setHorizontalHeaderLabels(
            ["Enabled", "Name", "Driver", "ID", "Serial Number"]
        )
        header = self.acc_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.acc_table.verticalHeader().setVisible(False)
        self.acc_table.setAlternatingRowColors(True)
        self.acc_table.setSelectionBehavior(QHeaderView.SelectionBehavior.SelectRows)
        layout.addWidget(self.acc_table)

        # System Shutter Link
        shutter_row = QHBoxLayout()
        shutter_row.setContentsMargins(0, 10, 0, 0)
        shutter_label = QLabel("<b>Laser Shutter:</b> Linked to")
        shutter_row.addWidget(shutter_label)
        
        self.shutter_combo = QComboBox()
        self.shutter_combo.setFixedWidth(180)
        shutter_row.addWidget(self.shutter_combo)
        
        shutter_row.addWidget(QLabel("on Channel"))
        self.shutter_channel_spin = QSpinBox()
        self.shutter_channel_spin.setRange(1, 2)
        shutter_row.addWidget(self.shutter_channel_spin)
        
        shutter_note = QLabel("(Select which KDC101 acts as the system shutter)")
        shutter_note.setStyleSheet("color: #888; font-size: 11px;")
        shutter_row.addWidget(shutter_note)
        shutter_row.addStretch()
        
        layout.addLayout(shutter_row)
        
        return box

    # -- Panel Order ---------------------------------------------------------


    # -----------------------------------------------------------------------
    # Populate from config
    # -----------------------------------------------------------------------

    def _populate_from_config(self):
        hw_cfg = self.hw.config.get('hardware', {})

        # Cameras
        self.cameras_table.setRowCount(0)
        for cam in hw_cfg.get('cameras', []):
            self._add_camera_row(cam)

        # Monochromators
        self.mono_table.setRowCount(0)
        for mono in hw_cfg.get('monochromators', []):
            self._add_monochromator_row(mono)

        # Accessories
        self.acc_table.setRowCount(0)
        for acc in hw_cfg.get('accessories', []):
            self._add_accessory_row(acc)

        # Global Config
        shutter_cfg = hw_cfg.get('shutter', {})
        shutter_id = shutter_cfg.get('linked_id', 'polarizer')
        shutter_channel = shutter_cfg.get('channel', 1)
        
        self._refresh_shutter_options()
        
        # Select current
        idx = self.shutter_combo.findData(shutter_id)
        if idx >= 0:
            self.shutter_combo.setCurrentIndex(idx)
        else:
            self.shutter_combo.setCurrentIndex(0)
            
        self.shutter_channel_spin.setValue(shutter_channel)

        # Update quick preset selection dropdown to show active configuration
        if hasattr(self, 'preset_combo'):
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentIndex(self._detect_active_preset())
            self.preset_combo.blockSignals(False)

    def _refresh_shutter_options(self):
        """Update shutter combo with only the currently 'Enabled' KDC101 devices."""
        # Store current selection to restore it if possible
        current_id = self.shutter_combo.currentData()
        
        self.shutter_combo.blockSignals(True)
        self.shutter_combo.clear()
        self.shutter_combo.addItem("None", None)
        
        # Check Polarizer (it's hardcoded as 'polarizer' ID in manager but might be in accessories)
        # Actually, let's just look at the accessories table for anything using 'kdc101'
        for r in range(self.acc_table.rowCount()):
            # Column 0: Enabled checkbox
            chk_widget = self.acc_table.cellWidget(r, 0)
            if not chk_widget: continue
            chk = chk_widget.findChild(QCheckBox)
            if not chk or not chk.isChecked(): continue
            
            # Column 2: Driver
            driver_combo = self.acc_table.cellWidget(r, 2)
            if not isinstance(driver_combo, QComboBox): continue
            if driver_combo.currentText() != 'kdc101': continue
            
            # Column 3: ID
            item_id = self.acc_table.item(r, 3).text()
            name = self.acc_table.item(r, 1).text()
            self.shutter_combo.addItem(f"{name} ({item_id})", item_id)

        # Restore selection
        idx = self.shutter_combo.findData(current_id)
        if idx >= 0:
            self.shutter_combo.setCurrentIndex(idx)
        
        self.shutter_combo.blockSignals(False)


    # -----------------------------------------------------------------------
    # Row helpers
    # -----------------------------------------------------------------------

    def _add_camera_row(self, cfg: Dict[str, Any] = None):
        cfg = cfg or {}
        row = self.cameras_table.rowCount()
        self.cameras_table.insertRow(row)

        # Enabled checkbox
        chk = QCheckBox()
        chk.setChecked(cfg.get('enabled', True))
        chk_widget = QWidget()
        chk_layout = QHBoxLayout(chk_widget)
        chk_layout.addWidget(chk)
        chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chk_layout.setContentsMargins(0, 0, 0, 0)
        self.cameras_table.setCellWidget(row, 0, chk_widget)

        # Name
        name_item = QTableWidgetItem(cfg.get('name', f'Camera {row}'))
        self.cameras_table.setItem(row, 1, name_item)

        # Model
        model_item = QTableWidgetItem(cfg.get('model', '---'))
        model_item.setFlags(model_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.cameras_table.setItem(row, 2, model_item)

        # Driver
        driver_combo = QComboBox()
        driver_combo.addItems(['andor_camera'])
        driver = cfg.get('driver', 'andor_camera')
        idx = driver_combo.findText(driver)
        if idx >= 0:
            driver_combo.setCurrentIndex(idx)
        self.cameras_table.setCellWidget(row, 3, driver_combo)

        # Serial Number
        serial_val = cfg.get('serial_number')
        serial_str = str(serial_val) if serial_val is not None else ''
        serial_item = QTableWidgetItem(serial_str)
        self.cameras_table.setItem(row, 4, serial_item)

        # Camera index
        idx_spin = QSpinBox()
        idx_spin.setRange(0, 8)
        idx_spin.setValue(cfg.get('camera_index', row))
        self.cameras_table.setCellWidget(row, 5, idx_spin)

        # Temperature
        temp_spin = QSpinBox()
        temp_spin.setRange(-100, 50)
        temp_spin.setValue(cfg.get('temperature', -20))
        self.cameras_table.setCellWidget(row, 6, temp_spin)

        # Role
        role_combo = QComboBox()
        role_combo.addItems(['spectroscopy', 'visualisation', 'general'])
        role = cfg.get('role', 'general')
        role_idx = role_combo.findText(role)
        if role_idx >= 0:
            role_combo.setCurrentIndex(role_idx)
        self.cameras_table.setCellWidget(row, 7, role_combo)

        # Stash the original camera ID for reference
        name_item.setData(Qt.ItemDataRole.UserRole, cfg.get('id', f'camera_{row}'))

    def _add_monochromator_row(self, cfg: Dict[str, Any] = None):
        cfg = cfg or {}
        row = self.mono_table.rowCount()
        self.mono_table.insertRow(row)

        # Enabled (Exclusive)
        chk = QCheckBox()
        chk.setChecked(cfg.get('enabled', False))
        chk.toggled.connect(lambda checked, r=row: self._on_mono_enabled_toggled(checked, r))
        
        chk_widget = QWidget()
        chk_layout = QHBoxLayout(chk_widget)
        chk_layout.addWidget(chk)
        chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chk_layout.setContentsMargins(0, 0, 0, 0)
        self.mono_table.setCellWidget(row, 0, chk_widget)

        # Name
        name_item = QTableWidgetItem(cfg.get('name', f'Spectrometer {row}'))
        self.mono_table.setItem(row, 1, name_item)

        # Driver
        driver_combo = QComboBox()
        driver_combo.addItems(['horiba_serial', 'horiba_sdk'])
        driver = cfg.get('driver', 'horiba_serial')
        idx = driver_combo.findText(driver)
        if idx >= 0:
            driver_combo.setCurrentIndex(idx)
        self.mono_table.setCellWidget(row, 2, driver_combo)

        # Grating Idx
        idx_spin = QSpinBox()
        idx_spin.setRange(0, 5) # Default range
        idx_spin.setValue(cfg.get('grating_idx', 1))
        self.mono_table.setCellWidget(row, 3, idx_spin)

        # Stash ID
        name_item.setData(Qt.ItemDataRole.UserRole, cfg.get('id', f'mono_{row}'))

    def _on_mono_enabled_toggled(self, checked: bool, row: int):
        """Ensure only one monochromator is enabled at a time."""
        if not checked:
            return
        
        # Disable all other checkboxes
        for r in range(self.mono_table.rowCount()):
            if r != row:
                chk_widget = self.mono_table.cellWidget(r, 0)
                if chk_widget:
                    chk = chk_widget.findChild(QCheckBox)
                    if chk:
                        chk.blockSignals(True)
                        chk.setChecked(False)
                        chk.blockSignals(False)

    def _add_accessory_row(self, cfg: Dict[str, Any] = None):
        cfg = cfg or {}
        row = self.acc_table.rowCount()
        self.acc_table.insertRow(row)

        # Enabled
        chk = QCheckBox()
        chk.setChecked(cfg.get('enabled', True))
        chk.toggled.connect(lambda _: self._refresh_shutter_options())
        chk_widget = QWidget()
        chk_layout = QHBoxLayout(chk_widget)
        chk_layout.addWidget(chk)
        chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chk_layout.setContentsMargins(0, 0, 0, 0)
        self.acc_table.setCellWidget(row, 0, chk_widget)

        # Name
        self.acc_table.setItem(row, 1, QTableWidgetItem(cfg.get('name', '')))

        # Driver
        driver_combo = QComboBox()
        available = [d for d in list_available_drivers() if d not in ['andor_camera', 'horiba_serial', 'horiba_sdk']]
        driver_combo.addItems(available)
        driver = cfg.get('driver', '')
        d_idx = driver_combo.findText(driver)
        if d_idx >= 0:
            driver_combo.setCurrentIndex(d_idx)
        driver_combo.currentIndexChanged.connect(lambda _: self._refresh_shutter_options())
        self.acc_table.setCellWidget(row, 2, driver_combo)

        # ID (editable)
        id_item = QTableWidgetItem(cfg.get('id', ''))
        self.acc_table.setItem(row, 3, id_item)

        # Serial Number (editable except for pm100)
        acc_id = cfg.get('id', '')
        if acc_id == 'pm100':
            serial_item = QTableWidgetItem('N/A')
            serial_item.setFlags(serial_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        else:
            serial_val = cfg.get('serial_number')
            serial_str = str(serial_val) if serial_val is not None else ''
            serial_item = QTableWidgetItem(serial_str)
        self.acc_table.setItem(row, 4, serial_item)

    def _remove_selected_row(self, table: QTableWidget):
        rows = set()
        for idx in table.selectedIndexes():
            rows.add(idx.row())
        
        if not rows and table.currentRow() >= 0:
            rows.add(table.currentRow())
            
        for row in sorted(list(rows), reverse=True):
            table.removeRow(row)

    # -----------------------------------------------------------------------
    # Apply
    # -----------------------------------------------------------------------

    def _on_apply(self):
        """Collect table data, validate, save to YAML, and emit signal."""
        try:
            new_cameras = self._collect_cameras()
            new_monos = self._collect_monos()
            new_accessories = self._collect_accessories()
            shutter_id = self.shutter_combo.currentData()
            
            # Preserve existing panel order from config
            hw_cfg = self.hw.config.get('hardware', {})
            new_panel_order = list(hw_cfg.get('ui', {}).get('panel_order', []))

            # Sync any IDs in panel_order that now match accessories or the active mono
            valid_ids = {acc['id'] for acc in new_accessories}
            if any(m.get('enabled', False) for m in new_monos):
                valid_ids.add('mono')
            
            # Special case: 'stage' panel is valid if either axis is present
            if 'stage_x' in valid_ids or 'stage_y' in valid_ids:
                valid_ids.add('stage')
                
            # Special case: 'shutter' panel is valid if a device is linked
            if shutter_id:
                valid_ids.add('shutter')

            shutter_channel = self.shutter_channel_spin.value()

            new_panel_order = [p for p in new_panel_order if p in valid_ids]
            
            # Add newly enabled accessories/mono that are missing from the order
            for item_id in valid_ids:
                if item_id not in new_panel_order:
                    new_panel_order.append(item_id)

            # Write back to in-memory config
            hw_cfg = self.hw.config.setdefault('hardware', {})
            hw_cfg['cameras'] = new_cameras
            hw_cfg['monochromators'] = new_monos
            hw_cfg['accessories'] = new_accessories
            hw_cfg['ui']['panel_order'] = new_panel_order
            hw_cfg['shutter'] = {
                'linked_id': shutter_id,
                'channel': shutter_channel
            }
            
            # Update active IDs in manager
            self.hw.active_camera_id = self.hw._get_default_active_camera_id()
            self.hw.active_monochromator_id = self.hw._get_default_active_monochromator_id()
            
            # Sync calibration engine from the new active mono
            self.hw.sync_calibration_with_hardware()

            # Persist to YAML
            self.hw.save_config()

            self.hw_config_changed.emit()
            if self.hw.service:
                self.hw.service.hw_config_changed.emit()
            logger.info("Hardware configuration applied and saved.")

            QMessageBox.information(
                self, "Applied",
                "Hardware configuration saved.\n"
                "The interface will update to reflect the new hardware selection."
            )
        except Exception as e:
            logger.error(f"Failed to apply settings: {e}")
            QMessageBox.critical(self, "Error", f"Failed to apply settings:\n{e}")

    def _collect_cameras(self) -> List[Dict[str, Any]]:
        cameras = []
        for row in range(self.cameras_table.rowCount()):
            chk_widget = self.cameras_table.cellWidget(row, 0)
            chk = chk_widget.findChild(QCheckBox)
            name_item = self.cameras_table.item(row, 1)
            model_item = self.cameras_table.item(row, 2)
            driver_combo = self.cameras_table.cellWidget(row, 3)
            serial_item = self.cameras_table.item(row, 4)
            idx_spin = self.cameras_table.cellWidget(row, 5)
            temp_spin = self.cameras_table.cellWidget(row, 6)
            role_combo = self.cameras_table.cellWidget(row, 7)

            serial_text = serial_item.text().strip() if serial_item else ''
            if serial_text.isdigit():
                serial_val = int(serial_text)
            elif serial_text:
                serial_val = serial_text
            else:
                serial_val = None

            cam_id = name_item.data(Qt.ItemDataRole.UserRole) or f'camera_{row}'
            cameras.append({
                'id': cam_id,
                'name': name_item.text(),
                'driver': driver_combo.currentText(),
                'role': role_combo.currentText(),
                'camera_index': idx_spin.value(),
                'temperature': temp_spin.value(),
                'serial_number': serial_val,
                'enabled': chk.isChecked(),
                # Preserve other fields from original config (except serial_number)
                **{k: v for k, v in self.hw.get_camera_config(cam_id).items()
                   if k not in ('id', 'name', 'driver', 'role', 'camera_index', 'temperature', 'enabled', 'serial_number')}
            })
        return cameras

    def _collect_monos(self) -> List[Dict[str, Any]]:
        monos = []
        for row in range(self.mono_table.rowCount()):
            chk_widget = self.mono_table.cellWidget(row, 0)
            chk = chk_widget.findChild(QCheckBox)
            name_item = self.mono_table.item(row, 1)
            driver_combo = self.mono_table.cellWidget(row, 2)
            idx_spin = self.mono_table.cellWidget(row, 3)

            mono_id = name_item.data(Qt.ItemDataRole.UserRole) or f'mono_{row}'
            monos.append({
                'id': mono_id,
                'name': name_item.text(),
                'driver': driver_combo.currentText(),
                'enabled': chk.isChecked(),
                'grating_idx': idx_spin.value(),
                # Preserve calibration, grating lists, and port
                **{k: v for k, v in self.hw.get_monochromator_config(mono_id).items()
                   if k not in ('id', 'name', 'driver', 'enabled', 'grating_idx')}
            })
        return monos

    def _collect_accessories(self) -> List[Dict[str, Any]]:
        accessories = []
        for row in range(self.acc_table.rowCount()):
            chk_widget = self.acc_table.cellWidget(row, 0)
            chk = chk_widget.findChild(QCheckBox)
            name_item = self.acc_table.item(row, 1)
            driver_combo = self.acc_table.cellWidget(row, 2)
            id_item = self.acc_table.item(row, 3)
            serial_item = self.acc_table.item(row, 4)

            acc_id = id_item.text() if id_item else f'acc_{row}'

            serial_val = None
            if serial_item:
                serial_text = serial_item.text().strip()
                if serial_text and serial_text not in ('N/A', '-', 'None'):
                    serial_val = serial_text

            acc_data = {
                'id': acc_id,
                'name': name_item.text() if name_item else '',
                'driver': driver_combo.currentText(),
                'enabled': chk.isChecked(),
                # Preserve other fields already in config (port, etc.)
                **{k: v for k, v in self.hw.get_accessory_config(acc_id).items()
                   if k not in ('id', 'name', 'driver', 'enabled', 'serial_number')}
            }
            if serial_val is not None:
                acc_data['serial_number'] = serial_val

            accessories.append(acc_data)
        return accessories

    # -- Presets -------------------------------------------------------------

    def _build_presets_section(self) -> QGroupBox:
        box = QGroupBox("Quick Setup Presets")
        box.setStyleSheet("QGroupBox { font-weight: bold; font-size: 13px; } QWidget { font-weight: normal; }")
        layout = QHBoxLayout(box)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        label = QLabel("Select Preconfigured Setup:")
        label.setStyleSheet("font-weight: normal; color: #e0e0e0;")
        layout.addWidget(label)

        self.preset_combo = QComboBox()
        self.preset_combo.addItems([
            "-- Select a preset configuration --",
            "IR micro PL - iDus Si",
            "IR micro PL - iDus InGaAs 1024",
            "IR micro PL - iDus InGaAs 512",
            "Macro PL - iDus Si"
        ])
        self.preset_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.preset_combo)

        load_btn = QPushButton("Load Preset")
        load_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; font-weight: bold; "
            "border-radius: 4px; padding: 6px 14px; }"
            "QPushButton:hover { background-color: #45a049; }"
        )
        load_btn.clicked.connect(self._on_load_preset)
        layout.addWidget(load_btn)

        return box

    def _on_load_preset(self):
        preset_idx = self.preset_combo.currentIndex()
        if preset_idx == 0:
            return  # The placeholder item

        preset_name = self.preset_combo.currentText()
        logger.info(f"Loading preset: {preset_name}")
        
        try:
            self.hw.apply_preset_by_name(preset_name)
            # Re-populate UI tables with the newly loaded settings
            self._populate_from_config()
            logger.info("Preset loaded successfully into memory.")
        except Exception as e:
            logger.error(f"Failed to load preset: {e}")
            QMessageBox.critical(self, "Preset Error", f"Failed to load preset:\n{e}")

    def _detect_active_preset(self) -> int:
        """Auto-detect which preset is active based on current config."""
        hw_cfg = self.hw.config.get('hardware', {})
        
        # Check if Macro PL matches
        # Macro PL has iHR320 (mono_1) enabled and FHR640 (mono_0) disabled
        mono_1_enabled = False
        mono_0_enabled = False
        for mono in hw_cfg.get('monochromators', []):
            if mono.get('id') == 'mono_1':
                mono_1_enabled = mono.get('enabled', False)
            elif mono.get('id') == 'mono_0':
                mono_0_enabled = mono.get('enabled', False)
                
        if mono_1_enabled and not mono_0_enabled:
            return 4  # Macro PL
            
        # If FHR640 is enabled, check which spectroscopy camera is enabled
        if mono_0_enabled and not mono_1_enabled:
            cam_1_enabled = False
            cam_2_enabled = False
            cam_3_enabled = False
            for cam in hw_cfg.get('cameras', []):
                if cam.get('id') == 'camera_1':
                    cam_1_enabled = cam.get('enabled', False)
                elif cam.get('id') == 'camera_2':
                    cam_2_enabled = cam.get('enabled', False)
                elif cam.get('id') == 'camera_3':
                    cam_3_enabled = cam.get('enabled', False)
                    
            if cam_1_enabled:
                return 1  # IR micro PL - iDus Si
            elif cam_2_enabled:
                return 2  # IR micro PL - iDus InGaAs 1024
            elif cam_3_enabled:
                return 3  # IR micro PL - iDus InGaAs 512
                
        return 0  # Placeholder / Custom
