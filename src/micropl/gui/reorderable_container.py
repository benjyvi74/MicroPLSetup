"""
reorderable_container.py — A QVBoxLayout wrapper that natively supports drag-and-drop reordering.
"""

from typing import Optional

from ..qt import QtGui, pyqtSignal, QVBoxLayout, QWidget

class ReorderableVBoxContainer(QWidget):
    """
    A custom widget with a QVBoxLayout that accepts drag-and-drop 
    operations to physically reorder its child widgets.
    """
    order_changed = pyqtSignal()
    
    def __init__(self, mime_type: str, parent=None):
        super().__init__(parent)
        self.mime_type = mime_type
        self.setAcceptDrops(True)
        self._drop_y = -1
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.main_layout.setSpacing(8)
        self.main_layout.addStretch()
        
    def addWidget(self, widget):
        """Add a widget just before the final stretch."""
        idx = self.main_layout.count() - 1
        if idx < 0: idx = 0
        self.main_layout.insertWidget(idx, widget)
        
    def removeWidget(self, widget):
        self.main_layout.removeWidget(widget)
        
    def count(self) -> int:
        return max(0, self.main_layout.count() - 1)
        
    def widgetAt(self, index: int) -> Optional[QWidget]:
        item = self.main_layout.itemAt(index)
        if item:
            return item.widget()
        return None

    def dragEnterEvent(self, e):
        """Accept drags matching the target mime type."""
        if e.mimeData().hasFormat(self.mime_type):
            e.accept()
            self._drop_y = int(e.position().y())
            self.update()
        else:
            e.ignore()
            
    def dragMoveEvent(self, e):
        e.accept()
        self._drop_y = int(e.position().y())
        self.update()
        
    def dragLeaveEvent(self, e):
        self._drop_y = -1
        self.update()
        
    def dropEvent(self, e):
        """Handle the drop and rearrange the layout."""
        self._drop_y = -1
        self.update()
        
        widget_id_str = e.mimeData().data(self.mime_type).data().decode()
        
        # Find the source widget in our layout by memory address ID
        source_widget = None
        for i in range(self.main_layout.count() - 1): # Ignore stretch
            item = self.main_layout.itemAt(i)
            w = item.widget() if item is not None else None
            if w and str(id(w)) == widget_id_str:
                source_widget = w
                break
                
        if not source_widget:
            e.ignore()
            return
            
        # Determine insertion index based on vertical drop position
        pos_y = e.position().y()
        target_index = 0
        
        for i in range(self.main_layout.count() - 1):
            item = self.main_layout.itemAt(i)
            w = item.widget() if item is not None else None
            if w and w != source_widget:
                if pos_y > w.geometry().center().y():
                    target_index += 1
                else:
                    break
                    
        # Apply the move
        self.main_layout.removeWidget(source_widget)
        if target_index >= self.main_layout.count() - 1:
            target_index = self.main_layout.count() - 1
            if target_index < 0: target_index = 0
            
        self.main_layout.insertWidget(target_index, source_widget)
        self.order_changed.emit()
        e.accept()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._drop_y >= 0:
            painter = QtGui.QPainter(self)
            # Blue line for visual feedback
            pen = QtGui.QPen(QtGui.QColor(33, 150, 243)) 
            pen.setWidth(4)
            painter.setPen(pen)
            
            # Find the closest gap
            target_y = self.main_layout.contentsMargins().top()
            for i in range(self.main_layout.count() - 1):
                item = self.main_layout.itemAt(i)
                w = item.widget() if item is not None else None
                if w:
                    if self._drop_y > w.geometry().center().y():
                        target_y = w.geometry().bottom() + self.main_layout.spacing() // 2
                    else:
                        if i == 0:
                            target_y = max(0, w.geometry().top() - self.main_layout.spacing() // 2)
                        break
            
            painter.drawLine(0, target_y, self.width(), target_y)
