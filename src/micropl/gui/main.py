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

from .automation_panel import AutomationPanel
from .measurement_panel import MeasurementPanel
from .live_view import LiveView
from .monochromator_panel import MonochromatorPanel
from .powermeter_panel import PowerMeterPanel
from .kdc101_panel import KDC101Panel
from .setup_tab import SetupTab
from .equipment_sidebar import EquipmentSidebar

from ..hardware.manager import HardwareManager

from .log_viewer import QtLogHandler, LogViewerDialog
from .splash import MicroPLSplash

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window for MicroPL."""

    def __init__(self, splash=None):
        super().__init__()

        self.setWindowTitle("MicroPL - Micro-Photoluminescence Automation")
        self.setGeometry(100, 100, 1400, 900)

        if splash: splash.set_progress(10, "Initializing Logging Engine...")
        # Initialize Logging Bridge
        self.log_handler = QtLogHandler()
        self.log_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        self.log_dialog = LogViewerDialog(self)
        self.log_handler.signaler.log_ready.connect(self.log_dialog.append_log)
        logging.getLogger().addHandler(self.log_handler)

        if splash: splash.set_progress(20, "Starting Hardware Service Processes...")
        self.hw = HardwareManager()
        self.hw.service.start() # Start the background hardware service
        
        self._init_ui(splash)
        
        if splash: splash.set_progress(90, "Loading Menus & Status Bar...")
        self._init_menubar()
        self._init_statusbar()

        if splash: splash.set_progress(100, "Ready.")
        logger.info("Main window initialized")

    def show_logs(self):
        """Show the non-blocking log viewer dialog."""
        self.log_dialog.show()
        self.log_dialog.raise_()
        self.log_dialog.activateWindow()

    def closeEvent(self, event):
        """Handle application closure and stop background threads."""
        logger.info("Closing application...")
        if hasattr(self.hw, '_service') and self.hw._service:
            self.hw.service.stop()
        self.disconnect_hardware()
        event.accept()

    def _init_ui(self, splash=None):
        """Initialize the user interface."""
        if splash: splash.set_progress(30, "Setting up Main Window Layout...")
        # Create main splitter for left/right layout
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        # Left side: Tabs
        self.tabs = QTabWidget()
        
        # Create panels
        if splash: splash.set_progress(40, "Loading Automation UI...")
        self.automation_panel = AutomationPanel()
        
        if splash: splash.set_progress(50, "Loading Measurement UI...")
        self.measurement_panel = MeasurementPanel()
        
        if splash: splash.set_progress(60, "Loading Live View...")
        self.live_view = LiveView()
        
        # Add tabs
        self.tabs.addTab(self.live_view, "Acquisition")
        self.tabs.addTab(self.automation_panel, "Automation")
        self.tabs.addTab(self.measurement_panel, "Measurement")

        if splash: splash.set_progress(65, "Loading Hardware Setup Tab...")
        self.setup_tab = SetupTab(self.hw)
        self.setup_tab.hw_config_changed.connect(self._on_hw_config_changed)
        self.tabs.addTab(self.setup_tab, "⚙ Setup")

        splitter.addWidget(self.tabs)

        if splash: splash.set_progress(70, "Loading Equipment Panels...")
        # Build individual equipment panels (these are reused by the sidebar)
        self.mono_panel       = MonochromatorPanel()
        self.powermeter_panel = PowerMeterPanel()
        if splash: splash.set_progress(80, "Loading Motor Controls...")
        self.kdc101_panel     = KDC101Panel()

        # Equipment sidebar — panels dict maps accessory ID -> panel widget
        # 'mono' is not a YAML accessory but has its own MonochromatorPanel.
        # It is registered in the sidebar under the fhr640 section separately.
        panels = {
            'pm100':  self.powermeter_panel,
            'kdc101': self.kdc101_panel,
        }
        # Also expose mono_panel via the sidebar if monochromator is enabled
        mono_cfg = hw_cfg = self.hw.config.get('hardware', {}).get('fhr640', {})
        if mono_cfg.get('enabled', True):
            panels['mono'] = self.mono_panel
            # Temporarily add 'mono' to the panel_order if not already there
            ui_cfg = self.hw.config.get('hardware', {}).get('ui', {})
            if 'mono' not in ui_cfg.get('panel_order', []):
                ui_cfg.setdefault('panel_order', []).insert(0, 'mono')
        self.equipment_sidebar = EquipmentSidebar(self.hw, panels)

        # Build the Acquisition tab layout: [sidebar | live_view]
        acq_widget = QWidget()
        acq_layout = QHBoxLayout(acq_widget)
        acq_layout.setContentsMargins(0, 0, 0, 0)
        acq_layout.setSpacing(0)
        acq_layout.addWidget(self.equipment_sidebar)

        # Thin separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        acq_layout.addWidget(sep)

        acq_layout.addWidget(self.live_view, stretch=1)

        # Replace the raw live_view in the first tab with the composed widget
        self.tabs.removeTab(0)
        self.tabs.insertTab(0, acq_widget, "Acquisition")
        self.tabs.setCurrentIndex(0)

        # --- SIGNAL CONNECTIONS (INTER-PANEL) ---
        # 1. Automation -> Measurement Monitor
        self.automation_panel.sequence_started.connect(self.measurement_panel.on_sequence_started)
        self.automation_panel.step_progress.connect(self.measurement_panel.on_step_progress)
        self.automation_panel.measurement_ready.connect(self.measurement_panel.on_measurement_ready)
        self.automation_panel.sequence_finished.connect(self.measurement_panel.on_sequence_finished)
        
        # 2. LiveView -> Measurement Monitor
        # (Allows monitoring even if sequence is started from the pop-up/LiveView workflow)
        self.live_view.sequence_started.connect(self.measurement_panel.on_sequence_started)
        self.live_view.step_progress.connect(self.measurement_panel.on_step_progress)
        self.live_view.measurement_ready.connect(self.measurement_panel.on_measurement_ready)
        self.live_view.sequence_finished.connect(self.measurement_panel.on_sequence_finished)
        
        # 3. Measurement Monitor -> Automation/LiveView (Abort)
        self.measurement_panel.stop_requested.connect(self.automation_panel.stop_sequence)
        self.measurement_panel.stop_requested.connect(self.live_view.stop_sequence)


    def _on_hw_config_changed(self):
        """Called when the Setup Tab applies new hardware config."""
        logger.info("Hardware config changed — rebuilding UI.")

        # 1. Refresh camera strip in LiveView
        cameras_cfg = self.hw.config.get('hardware', {}).get('cameras', [])
        camera_names = [c['name'] for c in cameras_cfg if c.get('enabled', False)]
        self.live_view.camera_combo.blockSignals(True)
        self.live_view.camera_combo.clear()
        self.live_view.camera_combo.addItems(camera_names)
        self.live_view.camera_combo.blockSignals(False)
        if camera_names:
            self.live_view._on_camera_changed(camera_names[0])

        # 2. Rebuild equipment sidebar
        self.equipment_sidebar.rebuild()

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

        hardware_menu.addSeparator()
        setup_action = QAction("Hardware Setup...", self)
        setup_action.triggered.connect(lambda: self.tabs.setCurrentWidget(self.setup_tab))
        hardware_menu.addAction(setup_action)

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
        """Connect to all hardware components from configuration."""
        logger.info("Initializing and connecting hardware from config...")
        hw_cfg = self.hw.config.get('hardware', {})

        # 1. Initialize and connect cameras from config list
        cameras_cfg = hw_cfg.get('cameras', [])
        for cam_cfg in cameras_cfg:
            if not cam_cfg.get('enabled', False):
                continue
            cam_id = cam_cfg['id']
            driver = cam_cfg.get('driver', 'andor_camera')
            if not self.hw.get_camera(cam_id):
                self.hw.initialize_instrument(cam_id, driver, cam_cfg)
                logger.info(f"Initialized camera '{cam_id}' ({cam_cfg.get('name', '')})")

        # 2. Initialize monochromator if enabled
        mono_cfg = hw_cfg.get('fhr640', {})
        if mono_cfg.get('enabled', True) and not self.hw.get_instrument('mono'):
            self.hw.initialize_instrument('mono', 'fhr640', mono_cfg)

        # 3. Initialize accessories from config list
        accessories_cfg = hw_cfg.get('accessories', [])
        for acc_cfg in accessories_cfg:
            if not acc_cfg.get('enabled', False):
                continue
            acc_id = acc_cfg['id']
            driver = acc_cfg.get('driver', acc_id)
            if not self.hw.get_instrument(acc_id):
                self.hw.initialize_instrument(acc_id, driver, acc_cfg)
                logger.info(f"Initialized accessory '{acc_id}' ({acc_cfg.get('name', '')})")

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


def main(app=None, splash=None):
    """Application entry point."""
    # Setup logging if not already done by run.py
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

    # Fallback if run directly without run.py
    if app is None:
        app = QApplication(sys.argv)
        app.setStyle('Fusion')
        
    if splash: 
        splash.set_progress(10, "Initializing Main Window...")

    # Create main window, passing splash for progress updates
    window = MainWindow(splash=splash)
    
    # Show main window and finish (hide) splash
    window.show()
    if splash:
        splash.finish(window)

    logger.info("Application started")

    # Run event loop only if not managed contextually by run.py
    if not splash:
        sys.exit(app.exec())
    return window


if __name__ == '__main__':
    main()
