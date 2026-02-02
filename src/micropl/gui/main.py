"""
Main window and application entry point for MicroPL GUI.
"""

import sys
import logging
from ..qt import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QTabWidget, QStatusBar, QMenuBar, QMenu,
    Qt, QAction, QSplitter, QFrame
)

from .calibration_panel import CalibrationPanel
from .sequence_editor import SequenceEditor
from .measurement_panel import MeasurementPanel
from .live_view import LiveView
from .monochromator_panel import MonochromatorPanel
from .powermeter_panel import PowerMeterPanel
from .kdc101_panel import KDC101Panel
from .shutter_panel import ShutterPanel

from ..hardware.andor_camera import discover_cameras
from ..hardware.manager import HardwareManager

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window for MicroPL."""

    def __init__(self):
        super().__init__()

        self.setWindowTitle("MicroPL - Micro-Photoluminescence Automation")
        self.setGeometry(100, 100, 1400, 900)

        self.hw = HardwareManager()
        self._init_ui()
        self._init_menubar()
        self._init_statusbar()

        logger.info("Main window initialized")

    def _init_ui(self):
        """Initialize the user interface."""
        # Create main splitter for left/right layout
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        # Left side: Tabs
        self.tabs = QTabWidget()
        
        # Create panels
        self.calibration_panel = CalibrationPanel()
        self.sequence_editor = SequenceEditor()
        self.measurement_panel = MeasurementPanel()
        self.live_view = LiveView()
        
        # Add tabs (Monochromator moved to right panel)
        self.tabs.addTab(self.calibration_panel, "Calibration")
        self.tabs.addTab(self.sequence_editor, "Sequence")
        self.tabs.addTab(self.measurement_panel, "Measurement")
        self.tabs.addTab(self.live_view, "Acquisition")
        
        splitter.addWidget(self.tabs)

        # Right side: Control panel
        right_panel = QWidget()
        right_layout = QVBoxLayout()
        right_panel.setLayout(right_layout)
        
        # Add control panels vertically with separators
        self.mono_panel = MonochromatorPanel()
        self.powermeter_panel = PowerMeterPanel()
        self.kdc101_panel = KDC101Panel()
        self.shutter_panel = ShutterPanel()
        
        right_layout.addWidget(self.mono_panel)
        right_layout.addWidget(self._create_separator())
        right_layout.addWidget(self.powermeter_panel)
        right_layout.addWidget(self._create_separator())
        right_layout.addWidget(self.kdc101_panel)
        right_layout.addWidget(self.shutter_panel)
        right_layout.addStretch()
        
        # Set minimum width for right panel
        right_panel.setMinimumWidth(400)
        
        splitter.addWidget(right_panel)
        
        # Set initial sizes: 70% left, 30% right
        splitter.setSizes([1000, 400])

    def _create_separator(self) -> QFrame:
        """Create a horizontal line separator."""
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setLineWidth(2)
        return separator

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
        """Connect to all hardware components using auto-discovery for cameras."""
        logger.info("Discovering and connecting hardware...")
        
        # 1. Discover Cameras
        available_cameras = discover_cameras()
        logger.info(f"Discovered {len(available_cameras)} Andor camera(s)")
        
        vis_config = None
        spec_config = None
        
        # Automatically assign roles based on model
        for cam_id, info in available_cameras.items():
            model = info['model']
            if 'DL604M' in model:
                vis_config = info.copy()
                vis_config['temperature'] = -20
                logger.info(f"Assigned {model} ({cam_id}) to Visualisation role")
            elif 'DU420' in model:
                spec_config = info.copy()
                spec_config['temperature'] = -70
                logger.info(f"Assigned {model} ({cam_id}) to Spectrometer role")

        # 2. Initialize Visualisation Camera
        if not self.hw.vis_camera:
            if vis_config:
                self.hw.initialize_instrument('vis_camera', 'andor_camera', vis_config)
            else:
                # Fallback to defaults if not discovered
                logger.warning("Visualisation camera (DL604M) not discovered, using defaults")
                self.hw.initialize_instrument('vis_camera', 'andor_camera', {
                    'model': 'DL604M',
                    'sdk_version': 2,
                    'camera_index': 0,
                    'temperature': -20
                })
            
        # 3. Initialize Spectrometer Camera
        if not self.hw.spec_camera:
            if spec_config:
                self.hw.initialize_instrument('spec_camera', 'andor_camera', spec_config)
            else:
                # Fallback
                logger.warning("Spectrometer camera (DU420) not discovered, using defaults")
                self.hw.initialize_instrument('spec_camera', 'andor_camera', {
                    'model': 'DU420A-BR-DD',
                    'sdk_version': 2,
                    'camera_index': 1,
                    'temperature': -70
                })

        # 4. Initialize Monochromator, Power Meter, and KDC101
        if not self.hw.get_instrument('mono'):
            self.hw.initialize_instrument('mono', 'fhr640')
        
        if not self.hw.get_instrument('pm100'):
            self.hw.initialize_instrument('pm100', 'pm100')
            
        if not self.hw.get_instrument('kdc101'):
            self.hw.initialize_instrument('kdc101', 'kdc101')

        self.hw.connect_all()
        self.statusbar.showMessage("Hardware connected")

    def disconnect_hardware(self):
        """Disconnect from all hardware."""
        logger.info("Disconnecting hardware...")
        self.hw.disconnect_all()
        self.statusbar.showMessage("Hardware disconnected")

    def show_about(self):
        """Show about dialog."""
        from .qt import QMessageBox
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
