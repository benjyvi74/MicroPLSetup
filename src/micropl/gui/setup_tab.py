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

        inner_layout.addWidget(self._build_cameras_section())
        inner_layout.addWidget(self._build_monochromator_section())
        inner_layout.addWidget(self._build_accessories_section())
        inner_layout.addWidget(self._build_panel_order_section())
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
        box.setStyleSheet("QGroupBox { font-weight: bold; font-size: 13px; }")
        layout = QVBoxLayout(box)

        # Table: enabled | name | driver | index | temperature | role
        self.cameras_table = QTableWidget(0, 6)
        self.cameras_table.setHorizontalHeaderLabels(
            ["Enabled", "Name", "Driver", "Camera Index", "Temperature (°C)", "Role"]
        )
        header = self.cameras_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.cameras_table.verticalHeader().setVisible(False)
        self.cameras_table.setAlternatingRowColors(True)
        layout.addWidget(self.cameras_table)

        btn_row = QHBoxLayout()
        add_cam_btn = QPushButton("Add Camera")
        add_cam_btn.clicked.connect(self._add_camera_row)
        rm_cam_btn = QPushButton("Remove Selected")
        rm_cam_btn.clicked.connect(lambda: self._remove_selected_row(self.cameras_table))
        btn_row.addWidget(add_cam_btn)
        btn_row.addWidget(rm_cam_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        return box

    # -- Monochromator -------------------------------------------------------

    def _build_monochromator_section(self) -> QGroupBox:
        box = QGroupBox("Monochromator")
        box.setStyleSheet("QGroupBox { font-weight: bold; font-size: 13px; }")
        layout = QHBoxLayout(box)

        self.mono_enabled_chk = QCheckBox("Enabled")
        layout.addWidget(self.mono_enabled_chk)

        layout.addWidget(QLabel("Port:"))
        self.mono_port_edit = QLineEdit()
        self.mono_port_edit.setPlaceholderText("e.g. COM1 or Simulate")
        self.mono_port_edit.setFixedWidth(180)
        layout.addWidget(self.mono_port_edit)

        layout.addWidget(QLabel("Default grating (l/mm):"))
        self.mono_grating_spin = QSpinBox()
        self.mono_grating_spin.setRange(100, 3600)
        self.mono_grating_spin.setValue(1200)
        layout.addWidget(self.mono_grating_spin)

        layout.addStretch()
        return box

    # -- Accessories ---------------------------------------------------------

    def _build_accessories_section(self) -> QGroupBox:
        box = QGroupBox("Accessories")
        box.setStyleSheet("QGroupBox { font-weight: bold; font-size: 13px; }")
        layout = QVBoxLayout(box)

        # Table: enabled | name | driver | id | port / serial
        self.acc_table = QTableWidget(0, 5)
        self.acc_table.setHorizontalHeaderLabels(
            ["Enabled", "Name", "Driver", "ID", "Port / Serial"]
        )
        header = self.acc_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.acc_table.verticalHeader().setVisible(False)
        self.acc_table.setAlternatingRowColors(True)
        layout.addWidget(self.acc_table)

        btn_row = QHBoxLayout()
        add_acc_btn = QPushButton("Add Accessory")
        add_acc_btn.clicked.connect(self._add_accessory_row)
        rm_acc_btn = QPushButton("Remove Selected")
        rm_acc_btn.clicked.connect(lambda: self._remove_selected_row(self.acc_table))
        btn_row.addWidget(add_acc_btn)
        btn_row.addWidget(rm_acc_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        return box

    # -- Panel Order ---------------------------------------------------------

    def _build_panel_order_section(self) -> QGroupBox:
        box = QGroupBox("Sidebar Panel Order")
        box.setStyleSheet("QGroupBox { font-weight: bold; font-size: 13px; }")
        layout = QHBoxLayout(box)

        self.panel_order_list = QListWidget()
        self.panel_order_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.panel_order_list.setMaximumHeight(150)
        layout.addWidget(self.panel_order_list, stretch=1)

        btn_col = QVBoxLayout()
        up_btn = QPushButton("▲ Up")
        down_btn = QPushButton("▼ Down")
        up_btn.clicked.connect(self._move_panel_up)
        down_btn.clicked.connect(self._move_panel_down)
        btn_col.addWidget(up_btn)
        btn_col.addWidget(down_btn)
        btn_col.addStretch()
        layout.addLayout(btn_col)

        note = QLabel("Drag or use buttons to set the default sidebar order.")
        note.setStyleSheet("color: #888; font-size: 11px;")
        note.setWordWrap(True)
        note.setMaximumWidth(220)
        layout.addWidget(note)
        return box

    # -----------------------------------------------------------------------
    # Populate from config
    # -----------------------------------------------------------------------

    def _populate_from_config(self):
        hw_cfg = self.hw.config.get('hardware', {})

        # Cameras
        self.cameras_table.setRowCount(0)
        for cam in hw_cfg.get('cameras', []):
            self._add_camera_row(cam)

        # Mono
        mono_cfg = hw_cfg.get('fhr640', {})
        self.mono_enabled_chk.setChecked(mono_cfg.get('enabled', True))
        self.mono_port_edit.setText(str(mono_cfg.get('port', 'COM1')))
        self.mono_grating_spin.setValue(mono_cfg.get('grating', 1200))

        # Accessories
        self.acc_table.setRowCount(0)
        for acc in hw_cfg.get('accessories', []):
            self._add_accessory_row(acc)

        # Panel order
        self.panel_order_list.clear()
        ui_cfg = hw_cfg.get('ui', {})
        for panel_id in ui_cfg.get('panel_order', []):
            self.panel_order_list.addItem(QListWidgetItem(panel_id))

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

        # Driver
        driver_combo = QComboBox()
        driver_combo.addItems(['andor_camera', 'stage'])
        driver = cfg.get('driver', 'andor_camera')
        idx = driver_combo.findText(driver)
        if idx >= 0:
            driver_combo.setCurrentIndex(idx)
        self.cameras_table.setCellWidget(row, 2, driver_combo)

        # Camera index
        idx_spin = QSpinBox()
        idx_spin.setRange(0, 8)
        idx_spin.setValue(cfg.get('camera_index', row))
        self.cameras_table.setCellWidget(row, 3, idx_spin)

        # Temperature
        temp_spin = QSpinBox()
        temp_spin.setRange(-100, 50)
        temp_spin.setValue(cfg.get('temperature', -20))
        self.cameras_table.setCellWidget(row, 4, temp_spin)

        # Role
        role_combo = QComboBox()
        role_combo.addItems(['spectroscopy', 'visualisation', 'general'])
        role = cfg.get('role', 'general')
        role_idx = role_combo.findText(role)
        if role_idx >= 0:
            role_combo.setCurrentIndex(role_idx)
        self.cameras_table.setCellWidget(row, 5, role_combo)

        # Stash the original camera ID for reference
        name_item.setData(Qt.ItemDataRole.UserRole, cfg.get('id', f'camera_{row}'))

    def _add_accessory_row(self, cfg: Dict[str, Any] = None):
        cfg = cfg or {}
        row = self.acc_table.rowCount()
        self.acc_table.insertRow(row)

        # Enabled
        chk = QCheckBox()
        chk.setChecked(cfg.get('enabled', True))
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
        available = list_available_drivers()
        driver_combo.addItems(available)
        driver = cfg.get('driver', '')
        d_idx = driver_combo.findText(driver)
        if d_idx >= 0:
            driver_combo.setCurrentIndex(d_idx)
        self.acc_table.setCellWidget(row, 2, driver_combo)

        # ID (editable)
        id_item = QTableWidgetItem(cfg.get('id', ''))
        self.acc_table.setItem(row, 3, id_item)

        # Port / serial (first relevant string value)
        port_val = str(cfg.get('port') or cfg.get('serial_number') or '')
        self.acc_table.setItem(row, 4, QTableWidgetItem(port_val))

    def _remove_selected_row(self, table: QTableWidget):
        selected = table.selectionModel().selectedRows()
        for idx in sorted(selected, reverse=True):
            table.removeRow(idx.row())

    def _move_panel_up(self):
        row = self.panel_order_list.currentRow()
        if row > 0:
            item = self.panel_order_list.takeItem(row)
            self.panel_order_list.insertItem(row - 1, item)
            self.panel_order_list.setCurrentRow(row - 1)

    def _move_panel_down(self):
        row = self.panel_order_list.currentRow()
        if row < self.panel_order_list.count() - 1:
            item = self.panel_order_list.takeItem(row)
            self.panel_order_list.insertItem(row + 1, item)
            self.panel_order_list.setCurrentRow(row + 1)

    # -----------------------------------------------------------------------
    # Apply
    # -----------------------------------------------------------------------

    def _on_apply(self):
        """Collect table data, validate, save to YAML, and emit signal."""
        try:
            new_cameras = self._collect_cameras()
            new_mono = self._collect_mono()
            new_accessories = self._collect_accessories()
            new_panel_order = [
                self.panel_order_list.item(i).text()
                for i in range(self.panel_order_list.count())
            ]

            # Sync any IDs in panel_order that now match accessories
            acc_ids = {acc['id'] for acc in new_accessories}
            new_panel_order = [p for p in new_panel_order if p in acc_ids]
            # Add newly enabled accessories that are missing from the order
            for acc in new_accessories:
                if acc['id'] not in new_panel_order:
                    new_panel_order.append(acc['id'])

            # Write back to in-memory config
            hw_cfg = self.hw.config.setdefault('hardware', {})
            hw_cfg['cameras'] = new_cameras
            hw_cfg['fhr640'].update(new_mono)
            hw_cfg['accessories'] = new_accessories
            hw_cfg.setdefault('ui', {})['panel_order'] = new_panel_order

            # Update active_camera_id to first enabled
            self.hw.active_camera_id = self.hw._get_default_active_camera_id()

            # Persist to YAML
            self.hw.save_config()

            self.hw_config_changed.emit()
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
            driver_combo = self.cameras_table.cellWidget(row, 2)
            idx_spin = self.cameras_table.cellWidget(row, 3)
            temp_spin = self.cameras_table.cellWidget(row, 4)
            role_combo = self.cameras_table.cellWidget(row, 5)

            cam_id = name_item.data(Qt.ItemDataRole.UserRole) or f'camera_{row}'
            cameras.append({
                'id': cam_id,
                'name': name_item.text(),
                'driver': driver_combo.currentText(),
                'role': role_combo.currentText(),
                'camera_index': idx_spin.value(),
                'temperature': temp_spin.value(),
                'enabled': chk.isChecked(),
                # Preserve other fields from original config
                **{k: v for k, v in self.hw.get_camera_config(cam_id).items()
                   if k not in ('id', 'name', 'driver', 'role', 'camera_index', 'temperature', 'enabled')}
            })
        return cameras

    def _collect_mono(self) -> Dict[str, Any]:
        return {
            'enabled': self.mono_enabled_chk.isChecked(),
            'port': self.mono_port_edit.text(),
            'grating': self.mono_grating_spin.value(),
        }

    def _collect_accessories(self) -> List[Dict[str, Any]]:
        accessories = []
        for row in range(self.acc_table.rowCount()):
            chk_widget = self.acc_table.cellWidget(row, 0)
            chk = chk_widget.findChild(QCheckBox)
            name_item = self.acc_table.item(row, 1)
            driver_combo = self.acc_table.cellWidget(row, 2)
            id_item = self.acc_table.item(row, 3)
            port_item = self.acc_table.item(row, 4)

            acc_id = id_item.text() if id_item else f'acc_{row}'
            accessories.append({
                'id': acc_id,
                'name': name_item.text() if name_item else '',
                'driver': driver_combo.currentText(),
                'enabled': chk.isChecked(),
                # Preserve other fields already in config (port, serial, etc.)
                **{k: v for k, v in self.hw.get_accessory_config(acc_id).items()
                   if k not in ('id', 'name', 'driver', 'enabled')}
            })
        return accessories
