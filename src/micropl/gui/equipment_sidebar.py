"""
EquipmentSidebar — scrollable, collapsible, draggable panel container.

Each enabled accessory gets a PanelWrapper that can be collapsed/expanded
and reordered by dragging. The panel_order from the YAML config sets the
initial order.
"""

import logging
from typing import Dict, Any, List, Optional

from ..qt import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QScrollArea, QFrame, Qt, QSizePolicy, pyqtSignal,
)
from ..hardware.manager import HardwareManager

logger = logging.getLogger(__name__)


class PanelWrapper(QFrame):
    """
    Collapsible wrapper around an equipment panel widget.

    Provides a title bar with collapse/expand toggle and a drag handle icon.
    """

    def __init__(self, title: str, panel: QWidget, panel_id: str, parent=None):
        super().__init__(parent)
        self.panel_id = panel_id
        self.inner_panel = panel
        self._collapsed = False

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "PanelWrapper { border: 1px solid #333; border-radius: 6px; "
            "background-color: #1a1a2e; margin: 2px 0px; }"
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- Title bar ---
        title_bar = QWidget()
        title_bar.setStyleSheet(
            "QWidget { background-color: #252540; border-radius: 5px; }"
        )
        title_bar.setCursor(Qt.CursorShape.SizeAllCursor)
        title_bar.setFixedHeight(32)
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(8, 2, 4, 2)
        tb_layout.setSpacing(6)

        # Drag handle
        drag_label = QLabel("⠿")
        drag_label.setStyleSheet("color: #666; font-size: 14px;")
        drag_label.setCursor(Qt.CursorShape.OpenHandCursor)
        tb_layout.addWidget(drag_label)

        # Title
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: bold; font-size: 12px; color: #e0e0e0;")
        tb_layout.addWidget(title_label, stretch=1)

        # Collapse button
        self.collapse_btn = QPushButton("▾")
        self.collapse_btn.setFixedSize(22, 22)
        self.collapse_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #aaa; border: none; font-size: 14px; }"
            "QPushButton:hover { color: white; }"
        )
        self.collapse_btn.clicked.connect(self.toggle_collapse)
        tb_layout.addWidget(self.collapse_btn)

        layout.addWidget(title_bar)

        # --- Inner panel ---
        layout.addWidget(panel)

    def toggle_collapse(self):
        """Toggle collapsed/expanded state."""
        self._collapsed = not self._collapsed
        self.inner_panel.setVisible(not self._collapsed)
        self.collapse_btn.setText("▸" if self._collapsed else "▾")
        logger.debug(f"Panel '{self.panel_id}' {'collapsed' if self._collapsed else 'expanded'}")


class EquipmentSidebar(QWidget):
    """
    Scrollable vertical sidebar holding PanelWrapper-wrapped equipment panels.

    Order is driven by the 'ui.panel_order' key in hardware config.
    Supports drag-and-drop reordering (swap-on-release model).
    """

    def __init__(self, hw: HardwareManager, panels: Dict[str, QWidget], parent=None):
        """
        Args:
            hw: HardwareManager instance (for config access).
            panels: dict mapping accessory_id -> already-constructed panel widget.
        """
        super().__init__(parent)
        self.hw = hw
        self._panels = panels          # {accessory_id: QWidget}
        self._wrappers: List[PanelWrapper] = []

        self.setMinimumWidth(260)
        self.setMaximumWidth(380)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Scroll area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setSpacing(4)
        self._container_layout.setContentsMargins(6, 6, 6, 6)
        self._container_layout.addStretch()

        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll)

        self.rebuild()

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def rebuild(self):
        """
        Clear and repopulate panels from the current hardware config.
        Called on startup and whenever hw_config_changed fires.
        """
        for wrapper in self._wrappers:
            self._container_layout.removeWidget(wrapper)
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

        # Also handle 'mono' which is not in accessories but may be in panels dict
        mono_cfg = hw_cfg.get('fhr640', {})
        if 'mono' in self._panels and mono_cfg.get('enabled', True):
            acc_by_id.setdefault('mono', {
                'id': 'mono',
                'name': 'Monochromator',
                'enabled': mono_cfg.get('enabled', True),
            })

        # Build ordered list: panel_order first, then any remaining registered panels
        ordered_ids = [pid for pid in panel_order if pid in self._panels]
        remaining = [pid for pid in self._panels if pid not in ordered_ids]
        ordered_ids.extend(remaining)

        insert_pos = 0
        for acc_id in ordered_ids:
            acc_cfg = acc_by_id.get(acc_id, {})
            # For known accessories, respect enabled flag; for unregistered, default True
            if acc_cfg and not acc_cfg.get('enabled', True):
                continue
            panel = self._panels.get(acc_id)
            if panel is None:
                continue

            title = acc_cfg.get('name', acc_id)
            wrapper = PanelWrapper(title, panel, acc_id, parent=self._container)
            self._wrappers.append(wrapper)
            self._container_layout.insertWidget(insert_pos, wrapper)
            insert_pos += 1

        logger.info(f"EquipmentSidebar rebuilt with {len(self._wrappers)} panels")

    def add_panel(self, acc_id: str, panel: QWidget):
        """Register a new panel widget and rebuild the sidebar."""
        self._panels[acc_id] = panel
        self.rebuild()

    # -----------------------------------------------------------------------
    # Drag-and-drop reordering (simple swap model)
    # -----------------------------------------------------------------------
    # Qt drag-and-drop within a QScrollArea requires overriding mouse events.
    # We use a lightweight approach: track which wrapper was pressed, and on
    # mouse-release over a different wrapper, swap their positions.

    def _find_wrapper_at(self, pos) -> Optional[PanelWrapper]:
        """Find the PanelWrapper at a position in the container's coordinate space."""
        child = self._container.childAt(pos)
        while child is not None:
            if isinstance(child, PanelWrapper):
                return child
            child = child.parent() if hasattr(child, 'parent') else None
        return None
