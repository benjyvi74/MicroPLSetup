"""
Main window and application entry point for MicroPL GUI.
"""

import sys
import logging
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QTabWidget, QStatusBar, QMenuBar, QMenu
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction

from .calibration_panel import CalibrationPanel
from .sequence_editor import SequenceEditor
from .measurement_panel import MeasurementPanel
from .live_view import LiveView

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window for MicroPL."""

    def __init__(self):
        super().__init__()

        self.setWindowTitle("MicroPL - Micro-Photoluminescence Automation")
        self.setGeometry(100, 100, 1400, 900)

        self._init_ui()
        self._init_menubar()
        self._init_statusbar()

        logger.info("Main window initialized")

    def _init_ui(self):
        """Initialize the user interface."""
        # Central widget with tabs
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # Create panels
        self.calibration_panel = CalibrationPanel()
        self.sequence_editor = SequenceEditor()
        self.measurement_panel = MeasurementPanel()
        self.live_view = LiveView()

        # Add tabs
        self.tabs.addTab(self.calibration_panel, "Calibration")
        self.tabs.addTab(self.sequence_editor, "Sequence")
        self.tabs.addTab(self.measurement_panel, "Measurement")
        self.tabs.addTab(self.live_view, "Live View")

    def _init_menubar(self):
        """Initialize the menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("File")

        load_config_action = QAction("Load Configuration", self)
        load_config_action.triggered.connect(self.load_configuration)
        file_menu.addAction(load_config_action)

        save_config_action = QAction("Save Configuration", self)
        save_config_action.triggered.connect(self.save_configuration)
        file_menu.addAction(save_config_action)

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Hardware menu
        hardware_menu = menubar.addMenu("Hardware")

        connect_action = QAction("Connect All", self)
        connect_action.triggered.connect(self.connect_hardware)
        hardware_menu.addAction(connect_action)

        disconnect_action = QAction("Disconnect All", self)
        disconnect_action.triggered.connect(self.disconnect_hardware)
        hardware_menu.addAction(disconnect_action)

        # Help menu
        help_menu = menubar.addMenu("Help")

        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def _init_statusbar(self):
        """Initialize the status bar."""
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.statusbar.showMessage("Ready")

    def load_configuration(self):
        """Load configuration from file."""
        logger.info("Load configuration requested")
        # TODO: Implement configuration loading
        self.statusbar.showMessage("Configuration loaded")

    def save_configuration(self):
        """Save configuration to file."""
        logger.info("Save configuration requested")
        # TODO: Implement configuration saving
        self.statusbar.showMessage("Configuration saved")

    def connect_hardware(self):
        """Connect to all hardware."""
        logger.info("Connecting to hardware...")
        # TODO: Implement hardware connection
        self.statusbar.showMessage("Hardware connected")

    def disconnect_hardware(self):
        """Disconnect from all hardware."""
        logger.info("Disconnecting hardware...")
        # TODO: Implement hardware disconnection
        self.statusbar.showMessage("Hardware disconnected")

    def show_about(self):
        """Show about dialog."""
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.about(
            self,
            "About MicroPL",
            "MicroPL - Micro-Photoluminescence Automation System\n\n"
            "Version 0.1.0\n\n"
            "A comprehensive system for automated micro-PL measurements."
        )


def main():
    """Application entry point."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Create application
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # Modern look

    # Create and show main window
    window = MainWindow()
    window.show()

    logger.info("Application started")

    # Run event loop
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
