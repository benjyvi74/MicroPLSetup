"""
Plot widgets for data visualization.
"""

import logging
from typing import Optional
import numpy as np

from PyQt6.QtWidgets import QWidget, QVBoxLayout
import matplotlib
matplotlib.use('QtAgg')
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

logger = logging.getLogger(__name__)


class PlotWidget(QWidget):
    """Widget for displaying 1D plots using matplotlib."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._init_ui()
        self._xlabel = "X"
        self._ylabel = "Y"

        logger.debug("PlotWidget initialized")

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Create matplotlib figure
        self.figure = Figure(figsize=(8, 6))
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout.addWidget(self.canvas)

        self.axes = self.figure.add_subplot(111)

    def plot(self, x_data, y_data, label: Optional[str] = None, clear: bool = True):
        """
        Plot data.

        Args:
            x_data: X axis data
            y_data: Y axis data
            label: Optional label for legend
            clear: Clear previous plots if True
        """
        if clear:
            self.axes.clear()

        self.axes.plot(x_data, y_data, label=label)

        self.axes.set_xlabel(self._xlabel)
        self.axes.set_ylabel(self._ylabel)

        if label:
            self.axes.legend()

        self.axes.grid(True, alpha=0.3)
        self.figure.tight_layout()
        self.canvas.draw()

    def plot_multiple(self, data_series: list):
        """
        Plot multiple data series.

        Args:
            data_series: List of (x, y, label) tuples
        """
        self.axes.clear()

        for x_data, y_data, label in data_series:
            self.axes.plot(x_data, y_data, label=label)

        self.axes.set_xlabel(self._xlabel)
        self.axes.set_ylabel(self._ylabel)
        self.axes.legend()
        self.axes.grid(True, alpha=0.3)

        self.figure.tight_layout()
        self.canvas.draw()

    def set_labels(self, xlabel: str, ylabel: str):
        """Set axis labels."""
        self._xlabel = xlabel
        self._ylabel = ylabel

        self.axes.set_xlabel(xlabel)
        self.axes.set_ylabel(ylabel)
        self.canvas.draw()

    def clear(self):
        """Clear the plot."""
        self.axes.clear()
        self.axes.set_xlabel(self._xlabel)
        self.axes.set_ylabel(self._ylabel)
        self.canvas.draw()


class ImagePlotWidget(QWidget):
    """Widget for displaying 2D image data."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._init_ui()
        self._colormap = 'viridis'

        logger.debug("ImagePlotWidget initialized")

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Create matplotlib figure
        self.figure = Figure(figsize=(8, 8))
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout.addWidget(self.canvas)

        self.axes = self.figure.add_subplot(111)
        self.colorbar = None

    def imshow(self, image: np.ndarray, extent=None):
        """
        Display 2D image.

        Args:
            image: 2D numpy array
            extent: Optional [left, right, bottom, top] extents
        """
        self.axes.clear()

        im = self.axes.imshow(
            image,
            cmap=self._colormap,
            origin='lower',
            extent=extent,
            aspect='auto'
        )

        # Update or create colorbar
        if self.colorbar:
            self.colorbar.remove()

        self.colorbar = self.figure.colorbar(im, ax=self.axes)

        self.figure.tight_layout()
        self.canvas.draw()

    def set_colormap(self, colormap: str):
        """Set colormap for image display."""
        self._colormap = colormap

    def clear(self):
        """Clear the image."""
        self.axes.clear()
        if self.colorbar:
            self.colorbar.remove()
            self.colorbar = None
        self.canvas.draw()
