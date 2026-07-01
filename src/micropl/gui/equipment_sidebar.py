"""
EquipmentSidebar — a container for all hardware control panels.
"""

import logging
from typing import Dict, Any, List

from ..qt import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame, 
    Qt, QPushButton, QLabel, QApplication, QToolButton
)
from ..qt import QtGui, QtCore
QDrag, QPainter, QColor = QtGui.QDrag, QtGui.QPainter, QtGui.QColor
QMimeData, QEvent = QtCore.QMimeData, QtCore.QEvent
from .reorderable_container import ReorderableVBoxContainer
from ..hardware.manager import HardwareManager

# Individual Panels
from .monochromator_panel import MonochromatorPanel
from .powermeter_panel import PowerMeterPanel
from .polarizer_panel import PolarizerPanel
from .stage_panel import StagePanel # Assume it exists or is stubbed
from .shutter_panel import ShutterPanel

logger = logging.getLogger(__name__)


class CollapsiblePanel(QFrame):
    """
    A wrapper frame with a clickable header to show/hide its content.
    """
    def __init__(self, title: str, content_widget: QWidget, acc_id: str = "", parent=None):
        super().__init__(parent)
        self.acc_id = acc_id
        self._is_collapsed = False
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        
        # Header
        self.header = QFrame()
        self.header.setFixedHeight(30)
        self.header.setObjectName("header")
        self.header.installEventFilter(self)
        h_layout = QHBoxLayout(self.header)
        h_layout.setContentsMargins(10, 0, 5, 0)
        
        self.toggle_btn = QToolButton()
        self.toggle_btn.setArrowType(Qt.ArrowType.DownArrow)
        self.toggle_btn.setFixedSize(20, 20)
        self.toggle_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.toggle_btn.setAutoRaise(True)
        self.toggle_btn.setStyleSheet("""
            QToolButton { border: none; background: transparent; }
        """)
        self.toggle_btn.clicked.connect(self.toggle)
        h_layout.addWidget(self.toggle_btn)
        
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 11px;")
        h_layout.addWidget(self.title_label)
        
        h_layout.addStretch()
        
        self.connect_btn = QPushButton("ON")
        self.connect_btn.setFixedSize(20, 20)
        self.connect_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.connect_btn.setToolTip("Connect to Instrument")
        self.connect_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid #ced4da;
                border-radius: 3px;
                background-color: white;
                font-weight: bold;
                font-size: 10px;
                color: #495057;
            }
            QPushButton:hover {
                background-color: #e9ecef;
            }
            QPushButton:disabled {
                background-color: #f8f9fa;
                color: #adb5bd;
                border: 1px solid #e9ecef;
            }
        """)
        h_layout.addWidget(self.connect_btn)
        
        self.status_dot = QLabel("●")
        self.status_dot.setToolTip("Status: Disconnected")
        self.status_dot.setStyleSheet("color: #dc3545; font-size: 14px; margin-right: 5px;") # Red
        h_layout.addWidget(self.status_dot)
        
        self._layout.addWidget(self.header)
        
        # Content
        self.content_widget = content_widget
        self._layout.addWidget(self.content_widget)
        self._update_style()

    def set_status(self, status_text: str):
        """Update the status dot color based on keywords."""
        status_text = status_text.lower()
        self.status_dot.setToolTip(f"Status: {status_text.capitalize()}")
        
        # Priority 1: Disconnected / Error (Red)
        if any(word in status_text for word in ["disconnected", "error", "failed", "offline", "deconnected"]):
            self.status_dot.setStyleSheet("color: #dc3545; font-size: 14px; margin-right: 5px;")
            self.connect_btn.setEnabled(True)
        # Priority 2: Transitions or Partial States (Orange)
        elif any(word in status_text for word in ["connecting", "homing", "moving", "busy", "capturing", "seeking", "wait", "partial"]):
            self.status_dot.setStyleSheet("color: #fd7e14; font-size: 14px; margin-right: 5px;")
            # Disable during active transitions, but keep enabled for Partial state so user can retry
            if "partial" in status_text:
                self.connect_btn.setEnabled(True)
            elif any(word in status_text for word in ["connecting", "homing"]):
                self.connect_btn.setEnabled(False)
            else:
                self.connect_btn.setEnabled(True)
        # Priority 3: Ready (Green)
        elif any(word in status_text for word in ["connected", "ready", "stable"]):
            self.status_dot.setStyleSheet("color: #28a745; font-size: 14px; margin-right: 5px;")
            self.connect_btn.setEnabled(False)
        else:
            # Default Red for unknown/disconnected states
            self.status_dot.setStyleSheet("color: #dc3545; font-size: 14px; margin-right: 5px;")
            self.connect_btn.setEnabled(True)

    def _update_style(self):
        """Update the frame stylesheet with a vibrant orange theme."""
        self.setStyleSheet(f"""
            CollapsiblePanel {{
                border: 2px solid #FF9800;
                border-radius: 6px;
                background-color: white;
            }}
            #header {{
                background-color: #FFF3E0;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
                border-bottom: 1px solid #ced4da;
            }}
        """)

    def toggle(self):
        """Toggle content visibility."""
        self._is_collapsed = not self._is_collapsed
        self.content_widget.setVisible(not self._is_collapsed)
        self.toggle_btn.setArrowType(
            Qt.ArrowType.RightArrow if self._is_collapsed else Qt.ArrowType.DownArrow
        )
        self.updateGeometry()

    def eventFilter(self, obj, event):
        if obj == self.header:
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    self.drag_start_pos = event.pos()
                    return False
            elif event.type() == QEvent.Type.MouseMove:
                if not (event.buttons() & Qt.MouseButton.LeftButton):
                    return False
                if not hasattr(self, 'drag_start_pos'):
                    return False
                if (event.pos() - self.drag_start_pos).manhattanLength() < QApplication.startDragDistance():
                    return False
                
                # Start drag
                drag = QDrag(self)
                mime = QMimeData()
                mime.setData('application/x-equipment-panel', str(id(self)).encode())
                drag.setMimeData(mime)
                
                # Visual feedback
                pixmap = self.grab()
                painter = QPainter(pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
                painter.fillRect(pixmap.rect(), QColor(0, 0, 0, 150))
                painter.end()
                
                drag.setPixmap(pixmap)
                drag.setHotSpot(event.pos())
                drag.exec(Qt.DropAction.MoveAction)
                return True
        return super().eventFilter(obj, event)

class EquipmentSidebar(QWidget):
    """
    Vertical sidebar containing collapsible or fixed panels for each instrument.
    
    The order and visibility are driven by the hardware config's 'ui.panel_order'
    and the 'enabled' flag of each device.
    """
    
    def __init__(self, hw: HardwareManager, parent=None):
        super().__init__(parent)
        self.hw = hw
        self._wrappers: List[CollapsiblePanel] = [] # Track panel containers for clearing
        
        # Registry of available panel classes by ID
        # 'mono' is a special ID mapping to the active spectrometer
        self._panels = {
            'mono': MonochromatorPanel,
            'pm100': PowerMeterPanel,
            'polarizer': PolarizerPanel,
            'shutter': ShutterPanel,
            'stage': StagePanel
        }
        
        self._init_ui()
        
        # Re-build when hardware config changes
        self.hw.service.hw_config_changed.connect(self.rebuild)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Scroll Area for many panels
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        
        self.container = ReorderableVBoxContainer('application/x-equipment-panel')
        self.container.order_changed.connect(self._on_panel_order_changed)
        
        self.scroll_area.setWidget(self.container)
        layout.addWidget(self.scroll_area)
        
        self.rebuild()

    def rebuild(self):
        """
        Clear and repopulate panels from the current hardware config.
        Called on startup and whenever hw_config_changed fires.
        """
        # Clear existing
        for wrapper in self._wrappers:
            self.container.removeWidget(wrapper)
            wrapper.setParent(None)
            wrapper.deleteLater()
        self._wrappers.clear()

        hw_cfg = self.hw.config.get('hardware', {})
        accessories_cfg = hw_cfg.get('accessories', [])
        panel_order = list(hw_cfg.get('ui', {}).get('panel_order', []))

        # Build lookup: id -> accessory config
        acc_by_id: Dict[str, Dict[str, Any]] = {
            a['id']: a for a in accessories_cfg
        }

        # Also handle 'mono' which represents the active monochromator
        active_mono_id = self.hw.active_monochromator_id
        if active_mono_id and 'mono' in self._panels:
            mono_cfg = self.hw.get_monochromator_config(active_mono_id)
            acc_by_id.setdefault('mono', {
                'id': 'mono',
                'name': mono_cfg.get('name', 'Monochromator'),
                'enabled': True,
            })

        # Special case: If Stage X or Y are enabled, ensure 'stage' is available for the sidebar
        sx_cfg = acc_by_id.get('stage_x')
        sy_cfg = acc_by_id.get('stage_y')
        if (sx_cfg and sx_cfg.get('enabled')) or (sy_cfg and sy_cfg.get('enabled')):
            acc_by_id.setdefault('stage', {
                'id': 'stage',
                'name': 'XY Stage',
                'enabled': True
            })
        # Special case: If shutter is enabled in config, ensure it's in acc_by_id
        shutter_cfg = hw_cfg.get('shutter', {})
        if shutter_cfg.get('linked_id'):
            acc_by_id.setdefault('shutter', {
                'id': 'shutter',
                'name': 'System Shutter',
                'enabled': True
            })

        # Build ordered list: panel_order first, then any remaining registered panels
        ordered_ids = [pid for pid in panel_order if pid in self._panels]
        remaining = [pid for pid in self._panels if pid not in ordered_ids]
        ordered_ids.extend(remaining)

        insert_pos = 0
        for acc_id in ordered_ids:
            acc_cfg = acc_by_id.get(acc_id)
            if acc_cfg is None:
                 # If not in acc_by_id, it means it's disabled or not a configured accessory
                 continue
            
            if not acc_cfg.get('enabled', True):
                continue
            
            panel_class = self._panels.get(acc_id)
            if panel_class is None:
                continue

            try:
                # Instantiate panel
                panel_instance = panel_class()
                
                # Wrap in a collapsible frame
                title = acc_cfg.get('name', acc_id.capitalize())
                wrapper = CollapsiblePanel(title, panel_instance, acc_id=acc_id)
                
                # Connect status signal if it exists
                if hasattr(panel_instance, 'sig_status_changed'):
                    panel_instance.sig_status_changed.connect(wrapper.set_status)
                    # Initial sync
                    if hasattr(panel_instance, 'get_current_status'):
                        wrapper.set_status(panel_instance.get_current_status())
                
                # Wire the header connect button to the panel's connect method
                if hasattr(panel_instance, '_on_connect_clicked'):
                    wrapper.connect_btn.clicked.connect(panel_instance._on_connect_clicked)
                else:
                    # Hide the button if the panel doesn't support connection
                    wrapper.connect_btn.hide()
                
                self.container.addWidget(wrapper)
                self._wrappers.append(wrapper)
                
                logger.debug(f"Sidebar: Loaded panel {acc_id}")
            except Exception as e:
                logger.error(f"Sidebar: Failed to load panel {acc_id}: {e}")

        # Ensure stretch is at the end
        if self.container.count() > 0:
             pass

    def _on_panel_order_changed(self):
        new_order = []
        for i in range(self.container.count()):
            w = self.container.widgetAt(i)
            if isinstance(w, CollapsiblePanel) and w.acc_id:
                new_order.append(w.acc_id)
                
        hw_cfg = self.hw.config.setdefault('hardware', {})
        ui_cfg = hw_cfg.setdefault('ui', {})
        
        existing_order = ui_cfg.get('panel_order', [])
        final_order = new_order + [p for p in existing_order if p not in new_order]
        ui_cfg['panel_order'] = final_order
        
        logger.info(f"Equipment panel order updated in memory: {final_order}")
