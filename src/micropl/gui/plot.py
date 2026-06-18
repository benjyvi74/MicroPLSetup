"""
Plot widgets for high-performance data visualization using PyQtGraph.
"""

import logging
from typing import Optional, List
import numpy as np

from ..qt import (
    QWidget, QVBoxLayout, pyqtSignal, Qt, 
    QTableWidget, QTableWidgetItem, QFrame, QHeaderView
)
import pyqtgraph as pg

logger = logging.getLogger(__name__)

# Set global PyQtGraph options for better aesthetics
pg.setConfigOption('background', 'k')  # Black background
pg.setConfigOption('foreground', 'w')  # White axes/labels
pg.setConfigOption('antialias', False) # Performance choice: False is much faster for dynamic data

class PlotWidget(QWidget):
    """Widget for displaying 1D plots using PyQtGraph."""

    sigMouseMoved = pyqtSignal(float, float)
    sigAutoRangeDisabled = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._xlabel = "X"
        self._ylabel = "Y"

        self._curve = None
        self._crosshair_enabled = True
        self._markers = [] # List of active marker items
        self._in_auto_scale = False # Flag to avoid race condition/re-entrancy in sigStateChanged
        self._init_ui()

        logger.debug("PlotWidget (PyQtGraph) initialized")

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        # Create PyQtGraph PlotWidget
        self.pw = pg.PlotWidget()
        layout.addWidget(self.pw)

        _pi = self.pw.getPlotItem()
        assert _pi is not None
        self._plot_item = _pi
        self._plot_item.showGrid(x=True, y=True, alpha=0.3)
        
        # Performance Upgrade: 
        # Only draw min/max of data in regions with high density (when zoomed out/compressed)
        self._plot_item.setDownsampling(mode='peak', auto=True, ds=1)
        
        # Style the plot for a premium look
        self._plot_item.getAxis('left').setPen(pg.mkPen(color='w', width=1))
        self._plot_item.getAxis('bottom').setPen(pg.mkPen(color='w', width=1))

        # Crosshair lines
        marker_pen = pg.mkPen(color=(255, 160, 0, 204), width=1, style=Qt.PenStyle.DotLine)
        self.vLine = pg.InfiniteLine(angle=90, movable=False, pen=marker_pen)
        self.hLine = pg.InfiniteLine(angle=0, movable=False, pen=marker_pen)
        self._plot_item.addItem(self.vLine, ignoreBounds=True)
        self._plot_item.addItem(self.hLine, ignoreBounds=True)
        self.vLine.hide()
        self.hLine.hide()

        # Legend
        self._legend = None

        # State for robust event filtering
        self._mouse_inside = False

        # Mouse event proxy
        scene = self.pw.scene()
        if scene is not None:
            self.proxy = pg.SignalProxy(scene.sigMouseMoved, rateLimit=60, slot=self.mouseMoved)  # type: ignore[attr-defined]

        # Auto-range synchronization
        self._plot_item.vb.sigStateChanged.connect(self._check_auto_range)

    def _check_auto_range(self, vb, *args):
        """Emit signal if any axis has auto-range disabled."""
        if getattr(self, '_in_auto_scale', False):
            return
        auto_x, auto_y = vb.autoRangeEnabled()
        if not auto_x or not auto_y:
            self.sigAutoRangeDisabled.emit()

    def show_legend(self, enabled: bool):
        """Toggle plot legend."""
        if enabled:
            if self._legend is None:
                self._legend = self.pw.addLegend(offset=(30, 10))
        else:
            if self._legend is not None:
                self.pw.removeItem(self._legend)
                self._legend = None

    def plot(self, x_data, y_data, label: Optional[str] = None, clear: bool = True):
        """Plot data."""
        if clear:
            self.pw.clear()
            self._curve = None

        pen = pg.mkPen(color='#00ffcc', width=2)
        self._curve = self.pw.plot(x_data, y_data, pen=pen, name=label)

        self._plot_item.setLabel('bottom', self._xlabel)
        self._plot_item.setLabel('left', self._ylabel)

    def update_plot(self, x_data, y_data):
        """Fast update of plot data."""
        if self._curve is None:
            self.plot(x_data, y_data)
            return
        self._curve.setData(x_data, y_data)

    def plot_multiple(self, data_series: list):
        """Plot multiple data series."""
        self.pw.clear()
        colors = ['#00ffcc', '#ff00ff', '#ffff00', '#00ffff', '#ffffff']
        for i, (x_data, y_data, label) in enumerate(data_series):
            color = colors[i % len(colors)]
            self.pw.plot(x_data, y_data, pen=pg.mkPen(color=color, width=1.5), name=label)
        self._plot_item.setLabel('bottom', self._xlabel)
        self._plot_item.setLabel('left', self._ylabel)

    def set_labels(self, xlabel: str, ylabel: str):
        """Set axis labels."""
        self._xlabel = xlabel
        self._ylabel = ylabel
        self._plot_item.setLabel('bottom', xlabel)
        self._plot_item.setLabel('left', ylabel)

    def clear(self):
        """Clear the plot."""
        self.pw.clear()
        self._curve = None
        self._plot_item.setLabel('bottom', self._xlabel)
        self._plot_item.setLabel('left', self._ylabel)
        self._plot_item.addItem(self.vLine, ignoreBounds=True)
        self._plot_item.addItem(self.hLine, ignoreBounds=True)
        for m in self._markers:
            self._plot_item.addItem(m, ignoreBounds=True)

    def add_marker(self, type: str):
        """Add a movable marker to the plot."""
        self.remove_markers()
        vb = self._plot_item.vb
        rect = vb.viewRect()
        cx, cy = rect.center().x(), rect.center().y()
        pen = pg.mkPen(color=(255, 160, 0, 204), width=2, style=Qt.PenStyle.DotLine)
        if 'x' in type.lower():
            m = pg.InfiniteLine(pos=cx, angle=90, movable=True, pen=pen)
            self._plot_item.addItem(m, ignoreBounds=True)
            self._markers.append(m)
        if 'y' in type.lower():
            m = pg.InfiniteLine(pos=cy, angle=0, movable=True, pen=pen)
            self._plot_item.addItem(m, ignoreBounds=True)
            self._markers.append(m)

    def remove_markers(self):
        """Remove all active markers."""
        for m in self._markers:
            self.pw.removeItem(m)
        self._markers = []

    def enterEvent(self, event):
        """Track mouse entry."""
        self._mouse_inside = True
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Clear coordinates when mouse leaves the widget area."""
        self._mouse_inside = False
        self.vLine.hide()
        self.hLine.hide()
        self.sigMouseMoved.emit(np.nan, np.nan)
        super().leaveEvent(event)

    def mouseMoved(self, evt):
        if not self._mouse_inside:
            return
        pos = evt[0]
        if self.pw.sceneBoundingRect().contains(pos) and self._crosshair_enabled:
            mousePoint = self._plot_item.vb.mapSceneToView(pos)
            self.vLine.setPos(mousePoint.x())
            self.hLine.setPos(mousePoint.y())
            self.vLine.show()
            self.hLine.show()
            self.sigMouseMoved.emit(mousePoint.x(), mousePoint.y())
        else:
            self.vLine.hide()
            self.hLine.hide()
            self.sigMouseMoved.emit(np.nan, np.nan)

    def set_crosshair_enabled(self, enabled: bool):
        self._crosshair_enabled = enabled
        if not enabled:
            self.vLine.hide()
            self.hLine.hide()

    def set_mouse_enabled(self, x: bool, y: bool):
        """Enable/disable mouse interaction for X and Y axes."""
        self._plot_item.setMouseEnabled(x=x, y=y)

    def set_rect_mode(self, enabled: bool):
        """Toggle between Pan and Rect (Box Zoom) modes."""
        if enabled:
            self.pw.setMouseMode(pg.ViewBox.RectMode)
        else:
            self.pw.setMouseMode(pg.ViewBox.PanMode)

    def auto_scale_all(self):
        """Auto-scale both axes."""
        self._in_auto_scale = True
        try:
            self._plot_item.enableAutoRange()
            self._plot_item.autoRange()
        finally:
            self._in_auto_scale = False

    def auto_scale_x(self):
        """Auto-scale only X axis."""
        self._in_auto_scale = True
        try:
            self._plot_item.enableAutoRange(axis='x')
            self._plot_item.autoRange(axis='x')
        finally:
            self._in_auto_scale = False

    def auto_scale_y(self):
        """Auto-scale only Y axis."""
        self._in_auto_scale = True
        try:
            self._plot_item.enableAutoRange(axis='y')
            self._plot_item.autoRange(axis='y')
        finally:
            self._in_auto_scale = False

    def disable_auto_scale(self):
        """Disable auto-scaling on both axes."""
        self._plot_item.disableAutoRange()


class ImagePlotWidget(QWidget):
    """Widget for displaying 2D image data using PyQtGraph."""

    sigMouseMoved = pyqtSignal(float, float)
    sigAutoRangeDisabled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._first_frame = True
        self._last_data_range = None
        self._markers = [] # List of active marker items
        self._mouse_inside = False
        self._init_ui()
        
        # Mouse event proxy for coordinate tracking
        self.proxy = pg.SignalProxy(self.imv.getView().scene().sigMouseMoved, rateLimit=60, slot=self.mouseMoved)
        
        logger.debug("ImagePlotWidget (PyQtGraph) initialized")

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self.imv = pg.ImageView(view=pg.PlotItem())
        self.imv.ui.menuBtn.hide()
        self.imv.ui.roiBtn.hide()
        
        hist = self.imv.getHistogramWidget()
        hist.axis.setWidth(60)
        
        hist.axis.mouseDoubleClickEvent = lambda ev: self.imv.autoLevels()
        hist.mouseDoubleClickEvent = lambda ev: self.imv.autoLevels()
        
        self.imv.getView().setAspectLocked(True)
        self.imv.getView().invertY(False) 
        
        pi = self.imv.getView() 
        pi.showAxis('bottom')
        pi.showAxis('left')
        
        layout.addWidget(self.imv)

        # Auto-range synchronization
        self.imv.getView().vb.sigStateChanged.connect(self._check_auto_range)

    def _check_auto_range(self, vb, *args):
        """Emit signal if any axis has auto-range disabled."""
        auto_x, auto_y = vb.autoRangeEnabled()
        if not auto_x or not auto_y:
            self.sigAutoRangeDisabled.emit()

    def enterEvent(self, event):
        """Track mouse entry."""
        self._mouse_inside = True
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Clear coordinates when mouse leaves the widget area."""
        self._mouse_inside = False
        self.sigMouseMoved.emit(np.nan, np.nan)
        super().leaveEvent(event)

    def mouseMoved(self, evt):
        if not self._mouse_inside:
            return
        pos = evt[0]
        if self.imv.getView().sceneBoundingRect().contains(pos):
            mousePoint = self.imv.getView().vb.mapSceneToView(pos)
            self.sigMouseMoved.emit(mousePoint.x(), mousePoint.y())
        else:
            self.sigMouseMoved.emit(np.nan, np.nan)

    def set_mouse_enabled(self, x: bool, y: bool):
        """Enable/disable mouse interaction for X and Y axes."""
        self.imv.getView().setMouseEnabled(x=x, y=y)

    def set_aspect_locked(self, locked: bool):
        """Toggle aspect ratio locking."""
        self.imv.getView().setAspectLocked(locked)

    def imshow(self, image: np.ndarray, extent=None, auto_levels: bool = False):
        """Display 2D image."""
        do_levels = self._first_frame or auto_levels
        self.imv.setImage(image.T, autoRange=self._first_frame, autoLevels=do_levels)
        
        if extent:
            x0, x1, y0, y1 = extent
            self.imv.getImageItem().setRect(pg.QtCore.QRectF(x0, y0, x1-x0, y1-y0))
            current_range = abs(x1 - x0)
            range_changed = False
            if self._last_data_range is not None:
                range_changed = abs(current_range - self._last_data_range) / self._last_data_range > 0.5
            
            if self._first_frame or range_changed:
                # IMPORTANT: Only auto-snap to the new range if the user hasn't manually zoomed
                auto_x, auto_y = self.imv.getView().vb.autoRangeEnabled()
                if self._first_frame or (auto_x and auto_y):
                    rect = pg.QtCore.QRectF(x0, y0, x1-x0, y1-y0)
                    self.imv.getView().setRange(rect)
                
                self._last_data_range = current_range
        
        if self._first_frame:
            self._first_frame = False
            self.imv.setPredefinedGradient('inferno')
            self.imv.getView().invertY(False) 

    def set_labels(self, xlabel: str, ylabel: str):
        """Set axis labels for the image view."""
        pi = self.imv.getView()
        pi.setLabel('bottom', xlabel)
        pi.setLabel('left', ylabel)

    def set_colormap(self, colormap: str):
        """Set colormap for image display."""
        try:
            self.imv.setPredefinedGradient(colormap)
        except:
            logger.warning(f"Colormap {colormap} not found in PyQtGraph PREDEFINED_GRADIENTS")

    def clear(self):
        """Clear the image."""
        self.imv.clear()
        self._first_frame = True
        self._markers = []

    def add_marker(self, type: str):
        """Add a movable marker to the plot."""
        self.remove_markers()
        vb = self.imv.getView()
        rect = vb.viewRect()
        cx, cy = rect.center().x(), rect.center().y()
        pen = pg.mkPen(color=(255, 160, 0, 204), width=2, style=Qt.PenStyle.DotLine)
        if 'x' in type.lower():
            m = pg.InfiniteLine(pos=cx, angle=90, movable=True, pen=pen)
            vb.addItem(m, ignoreBounds=True)
            self._markers.append(m)
        if 'y' in type.lower():
            m = pg.InfiniteLine(pos=cy, angle=0, movable=True, pen=pen)
            vb.addItem(m, ignoreBounds=True)
            self._markers.append(m)

    def remove_markers(self):
        """Remove all active markers."""
        vb = self.imv.getView()
        for m in self._markers:
            vb.removeItem(m)
        self._markers = []

    def auto_scale_all(self):
        """Auto-scale only intensity levels (brightness/contrast), preserving zoom."""
        self.imv.autoLevels()


class CoordinateWidget(QFrame):
    """
    Reusable coordinate display widget with a consistent 1x4 table style.
    Encapsulates both the table and the decorative border frame.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)
        self.setMinimumWidth(180) # Allow shrinking
        self.setStyleSheet("""
            QFrame {
                border: 1px solid #999;
                background-color: #f0f0f0;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Internal Table
        self.table = QTableWidget(1, 4)
        h_header = self.table.horizontalHeader()
        if h_header is not None:
            h_header.hide()
        v_header = self.table.verticalHeader()
        if v_header is not None:
            v_header.hide()
        self.table.setShowGrid(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setRowHeight(0, 26)
        
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #f0f0f0;
                gridline-color: #999;
                font-family: monospace;
                font-size: 10px;
            }
            QTableWidget::item {
                padding: 0px;
                color: #00008b;
                font-weight: bold;
            }
        """)
        
        # Headers
        self._x_header = QTableWidgetItem(" X ")
        self._y_header = QTableWidgetItem(" Y ")
        self.table.setItem(0, 0, self._x_header)
        self.table.setItem(0, 2, self._y_header)
        self._x_header.setBackground(pg.QtGui.QColor("#ddd"))
        self._y_header.setBackground(pg.QtGui.QColor("#ddd"))
        self._x_header.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._y_header.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Values
        self._x_value = QTableWidgetItem("  ---  ")
        self._y_value = QTableWidgetItem("  ---  ")
        self.table.setItem(0, 1, self._x_value)
        self.table.setItem(0, 3, self._y_value)
        self._x_value.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._y_value.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Geometry
        header = self.table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        
        layout.addWidget(self.table)

    def set_coords(self, x: float, y: float, x_fmt: str = ".3f", y_fmt: str = ".3f"):
        """Update coordinate values. Use NaN to clear."""
        if np.isnan(x) or np.isnan(y):
            self._x_value.setText("  ---  ")
            self._y_value.setText("  ---  ")
        else:
            self._x_value.setText(f" {x:{x_fmt}} ")
            self._y_value.setText(f" {y:{y_fmt}} ")

    def clear(self):
        """Force clear the coordinates."""
        self.set_coords(np.nan, np.nan)


class SpatialMapWidget(QWidget):
    """Widget for displaying 2D spatial scatter plot of measurements using PyQtGraph."""

    sigPointHovered = pyqtSignal(dict)
    sigPointClicked = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bg_overlay = None
        self._highlight_item = None
        self._points_data = []
        self._selected_index = -1
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self.pw = pg.PlotWidget()
        layout.addWidget(self.pw)

        _pi = self.pw.getPlotItem()
        assert _pi is not None
        self._plot_item = _pi
        self._plot_item.showGrid(x=True, y=True, alpha=0.3)
        self._plot_item.setAspectLocked(True) # Keep 1:1 spatial aspect ratio (wafer physical dimensions)

        # Style the plot for a premium look
        self._plot_item.getAxis('left').setPen(pg.mkPen(color='w', width=1))
        self._plot_item.getAxis('bottom').setPen(pg.mkPen(color='w', width=1))
        self._plot_item.setLabel('bottom', "X Position (mm)")
        self._plot_item.setLabel('left', "Y Position (mm)")

        # Create ScatterPlotItem
        self.scatter = pg.ScatterPlotItem(
            size=14, 
            pen=pg.mkPen(width=1, color='w'), 
            hoverable=True,
            tip=None # Disable default hover tooltip to use our info label
        )
        self.pw.addItem(self.scatter)

        # Create ColorBarItem and add to plot layout
        self.colorbar = pg.ColorBarItem(width=15)
        self._plot_item.layout.addItem(self.colorbar, 2, 4)
        self.colorbar.setVisible(False)

        # Connect signals
        self.scatter.sigClicked.connect(self._on_scatter_clicked)
        self.scatter.sigHovered.connect(self._on_scatter_hovered)

    def _on_scatter_clicked(self, scatter, points, ev):
        if points:
            spot = points[0]
            data = spot.data()
            if data:
                self._selected_index = data.get('index', -1)
                self.sigPointClicked.emit(data)
                self._draw_highlight(data['x'], data['y'])

    def _on_scatter_hovered(self, scatter, points, ev):
        if points:
            spot = points[0]
            data = spot.data()
            if data:
                self.sigPointHovered.emit(data)
        else:
            self.sigPointHovered.emit({})

    def draw_background_shape(self, shape_type: str, x_start: float, x_end: float, y_start: float, y_end: float, diameter: float):
        """Draw circular or rectangular scan boundary overlay behind points."""
        self.remove_background_shape()

        pen = pg.QtGui.QPen(pg.QtGui.QColor(74, 158, 255, 180), 1.5, pg.QtCore.Qt.PenStyle.DashLine)
        brush = pg.QtGui.QBrush(pg.QtGui.QColor(0, 80, 180, 20))

        if shape_type.lower() == "circle" or "circle" in shape_type.lower():
            cx = (x_start + x_end) / 2.0
            cy = (y_start + y_end) / 2.0
            r = diameter / 2.0
            self._bg_overlay = pg.QtWidgets.QGraphicsEllipseItem(cx - r, cy - r, diameter, diameter)
        else:
            x_min = min(x_start, x_end)
            y_min = min(y_start, y_end)
            dx = abs(x_end - x_start)
            dy = abs(y_end - y_start)
            self._bg_overlay = pg.QtWidgets.QGraphicsRectItem(x_min, y_min, dx, dy)

        self._bg_overlay.setPen(pen)
        self._bg_overlay.setBrush(brush)
        self._bg_overlay.setZValue(-100) # Draw behind the scatter points
        self.pw.addItem(self._bg_overlay)

    def remove_background_shape(self):
        """Remove background shape overlay if it exists."""
        if self._bg_overlay is not None:
            self.pw.removeItem(self._bg_overlay)
            self._bg_overlay = None

    def _draw_highlight(self, x: float, y: float):
        """Highlight the selected point with a yellow border circle."""
        self.remove_highlight()
        
        # Spot size is 14. We draw a circle of size 1.4 mm centered on (x,y)
        self._highlight_item = pg.QtWidgets.QGraphicsEllipseItem(x - 0.7, y - 0.7, 1.4, 1.4)
        pen = pg.QtGui.QPen(pg.QtGui.QColor("#ffff00"), 2)
        self._highlight_item.setPen(pen)
        self._highlight_item.setZValue(100) # Draw on top
        self.pw.addItem(self._highlight_item)

    def remove_highlight(self):
        """Remove selection highlight item."""
        if self._highlight_item is not None:
            self.pw.removeItem(self._highlight_item)
            self._highlight_item = None

    def update_points(self, points_data: List[dict], selected_index: int, metric: str, colormap_name: str,
                      auto_scale: bool = True, min_val: Optional[float] = None, max_val: Optional[float] = None):
        """
        Update scatter plot spots colored dynamically by metric and colormap.
        points_data: List of dicts, each having {'x', 'y', 'peak_wavelength', 'peak_intensity', 'integrated_intensity', 'index'}
        """
        self._points_data = points_data
        self._selected_index = selected_index

        if not points_data:
            self.scatter.clear()
            self.remove_highlight()
            self.colorbar.setVisible(False)
            return

        # Extract values for color mapping
        values = np.array([p[metric] for p in points_data])
        
        # Calculate auto-limits if requested or if manual limits are not set
        if auto_scale or min_val is None or max_val is None:
            min_val = np.min(values) if len(values) > 0 else 0.0
            max_val = np.max(values) if len(values) > 0 else 1.0

        try:
            cmap = pg.colormap.get(colormap_name)
        except:
            cmap = pg.colormap.get('viridis')

        # Clip values to the custom range to avoid normalization going out of bounds
        clipped_values = np.clip(values, min_val, max_val)

        # Normalize and map to QColors
        if max_val != min_val:
            normalized = (clipped_values - min_val) / (max_val - min_val)
        else:
            normalized = np.ones_like(values) * 0.5

        spots = []
        for p, norm_val in zip(points_data, normalized):
            color = cmap.mapToQColor(norm_val)
            spots.append({
                'pos': (p['x'], p['y']),
                'brush': pg.QtGui.QBrush(color),
                'data': p
            })

        self.scatter.setData(spots)

        # Update and show colorbar map and levels
        self.colorbar.setColorMap(cmap)
        self.colorbar.setLevels((min_val, max_val))
        self.colorbar.setVisible(True)

        # Re-draw highlight if a valid point is selected
        self.remove_highlight()
        if 0 <= selected_index < len(points_data):
            sel_pt = points_data[selected_index]
            self._draw_highlight(sel_pt['x'], sel_pt['y'])

    def clear(self):
        """Clear all spots, highlights, and overlays."""
        self.scatter.clear()
        self.remove_background_shape()
        self.remove_highlight()
        self.colorbar.setVisible(False)
        self._points_data = []
        self._selected_index = -1
