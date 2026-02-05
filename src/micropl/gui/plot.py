"""
Plot widgets for high-performance data visualization using PyQtGraph.
"""

import logging
from typing import Optional
import numpy as np

from ..qt import QWidget, QVBoxLayout
import pyqtgraph as pg

logger = logging.getLogger(__name__)

# Set global PyQtGraph options for better aesthetics
pg.setConfigOption('background', 'k')  # Black background
pg.setConfigOption('foreground', 'w')  # White axes/labels
pg.setConfigOption('antialias', False) # Performance choice: False is much faster for dynamic data

class PlotWidget(QWidget):
    """Widget for displaying 1D plots using PyQtGraph."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._xlabel = "X"
        self._ylabel = "Y"
        self._plot_item = None
        self._curve = None
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

        self._plot_item = self.pw.getPlotItem()
        self._plot_item.showGrid(x=True, y=True, alpha=0.3)
        
        # Performance Upgrade: 
        # Only draw min/max of data in regions with high density (when zoomed out/compressed)
        self._plot_item.setDownsampling(mode='peak', auto=True, ds=1)
        # Don't spend CPU cycles on data outside the visible range
        self._plot_item.setClipToView(True)
        
        # Style the plot for a premium look
        self._plot_item.getAxis('left').setPen(pg.mkPen(color='w', width=1))
        self._plot_item.getAxis('bottom').setPen(pg.mkPen(color='w', width=1))

    def plot(self, x_data, y_data, label: Optional[str] = None, clear: bool = True):
        """
        Plot data.
        """
        if clear:
            self.pw.clear()
            self._curve = None

        # Vibrant cyan/green color for the main data
        pen = pg.mkPen(color='#00ffcc', width=2)
        self._curve = self.pw.plot(x_data, y_data, pen=pen, name=label)

        self._plot_item.setLabel('bottom', self._xlabel)
        self._plot_item.setLabel('left', self._ylabel)

    def update_plot(self, x_data, y_data):
        """
        Fast update of plot data.
        """
        if self._curve is None:
            self.plot(x_data, y_data)
            return

        self._curve.setData(x_data, y_data)

    def plot_multiple(self, data_series: list):
        """
        Plot multiple data series.
        """
        self.pw.clear()
        
        # Use a cycle of vibrant colors
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


class ImagePlotWidget(QWidget):
    """Widget for displaying 2D image data using PyQtGraph."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._first_frame = True
        self._init_ui()
        logger.debug("ImagePlotWidget (PyQtGraph) initialized")

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        # Use ImageView for feature-rich image display (includes colorbar, histogram)
        self.imv = pg.ImageView()
        # Hide unnecessary buttons for a cleaner look
        self.imv.ui.menuBtn.hide()
        self.imv.ui.roiBtn.hide()
        
        # Stability fix: Pin the histogram axis width to prevent "jumping"
        # as the label text length (decimal places) changes with intensity.
        hist = self.imv.getHistogramWidget()
        hist.axis.setWidth(60) # Fixed 60px width for labels
        
        # Performance tweaks
        self.imv.getView().setAspectLocked(True)
        
        layout.addWidget(self.imv)

    def imshow(self, image: np.ndarray, extent=None):
        """
        Display 2D image.
        """
        # pyqtgraph uses (x, y) order, numpy is (y, x)
        # We need to transpose for correct display if it's typical detector data
        
        # Only auto-scale and auto-level on the first frame to prevent "laggy" jumping histogram
        self.imv.setImage(image.T, autoRange=self._first_frame, autoLevels=self._first_frame)
        
        if self._first_frame:
            self._first_frame = False
            self.imv.setPredefinedGradient('viridis')

        if extent:
            # extent format: [left, right, bottom, top]
            x0, x1, y0, y1 = extent
            rect = pg.QtCore.QRectF(x0, y0, x1-x0, y1-y0)
            self.imv.getView().setRange(rect)

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
