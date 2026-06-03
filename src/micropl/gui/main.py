"""
Main window and application entry point for MicroPL GUI.
"""

import sys
import logging
from threading import Thread
from ..qt import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QTabWidget, QStatusBar, QMenuBar, QMenu,
    Qt, QAction, QSplitter, QFrame, QSizePolicy, QLabel
)

from .automation_panel import AutomationPanel
from .measurement_panel import MeasurementPanel
from .live_view import LiveView
from .monochromator_panel import MonochromatorPanel
from .powermeter_panel import PowerMeterPanel
from .polarizer_panel import PolarizerPanel
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
        
        if splash: splash.set_progress(65, "Loading Hardware Setup Tab...")
        self.setup_tab = SetupTab(self.hw)
        self.setup_tab.hw_config_changed.connect(self._on_hw_config_changed)


        splitter.addWidget(self.tabs)

        if splash: splash.set_progress(70, "Loading Equipment Sidebar...")
        # The sidebar now automatically manages panel creation based on active config
        self.equipment_sidebar = EquipmentSidebar(self.hw)

        # Build the Acquisition tab layout: [live_view | horizontal splitter | {sidebar + cameras}]
        # Using a horizontal splitter between the main view and the right column
        acq_main_splitter = QSplitter(Qt.Orientation.Horizontal)
        acq_main_splitter.setHandleWidth(6)
        acq_main_splitter.setStyleSheet("QSplitter::handle { background-color: #e0e0e0; }")
        
        # Left: Main Live View area
        acq_main_splitter.addWidget(self.live_view)

        # Right: Control Column (Equipment + Cameras)
        # Using a vertical splitter so user can adjust height of each section
        right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_splitter.setHandleWidth(6)
        right_splitter.setChildrenCollapsible(False)
        right_splitter.setStyleSheet("QSplitter::handle { background-color: #e0e0e0; }")
        right_splitter.setMinimumWidth(370) # Spacious width + scrollbar buffer
        right_splitter.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        
        # 1. Equipment Section
        eq_container = QWidget()
        eq_layout = QVBoxLayout(eq_container)
        eq_layout.setContentsMargins(0, 5, 0, 0)
        eq_layout.setSpacing(5)
        
        eq_title = QLabel("INSTRUMENTS")
        eq_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        eq_title.setStyleSheet("font-weight: bold; color: white; background-color: #fd7e14; font-size: 10px; letter-spacing: 1px; padding: 4px 6px; border-radius: 4px;")
        eq_layout.addWidget(eq_title)
        eq_layout.addWidget(self.equipment_sidebar)
        
        right_splitter.addWidget(eq_container)

        # 2. Camera Section
        cam_container = QWidget()
        cam_layout = QVBoxLayout(cam_container)
        cam_layout.setContentsMargins(0, 5, 0, 0)
        cam_layout.setSpacing(5)
        
        cam_title = QLabel("CAMERAS")
        cam_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cam_title.setStyleSheet("font-weight: bold; color: white; background-color: #007bff; font-size: 10px; letter-spacing: 1px; padding: 4px 6px; border-radius: 4px;")
        cam_layout.addWidget(cam_title)
        cam_layout.addWidget(self.live_view.camera_scroll)
        
        right_splitter.addWidget(cam_container)
        
        # Set initial stretches for the vertical splitter
        right_splitter.setStretchFactor(0, 2)
        right_splitter.setStretchFactor(1, 1)

        # Add the vertical splitter to the main horizontal splitter
        acq_main_splitter.addWidget(right_splitter)
        
        # Set stretches for the horizontal splitter (LiveView expands, Sidebar stays compact)
        acq_main_splitter.setStretchFactor(0, 1)
        acq_main_splitter.setStretchFactor(1, 0)
        
        # Force the splitter to a very spacious minimum position + scrollbar buffer
        acq_main_splitter.setSizes([10000, 370])
        
        # Make the main splitter the widget for the Acquisition tab
        acq_widget = acq_main_splitter

        # Instead of reparenting which shifts indices, insert the composed widget
        # and then add the other tabs. We'll rebuild the tabs array from scratch here:
        self.tabs.clear()
        self.tabs.addTab(acq_widget, "Acquisition")
        self.tabs.addTab(self.automation_panel, "Automation")
        self.tabs.addTab(self.measurement_panel, "Measurement")
        self.tabs.addTab(self.setup_tab, "⚙ Setup")
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
        self.measurement_panel.pause_requested.connect(self.live_view.pause_sequence)
        self.measurement_panel.resume_requested.connect(self.live_view.resume_sequence)
        self.measurement_panel.abort_requested.connect(self.live_view.stop_sequence)


    def _on_hw_config_changed(self):
        """Called when the Setup Tab applies new hardware config."""
        logger.info("Hardware config changed — rebuilding UI.")

        # 1. Refresh camera strip in LiveView
        self.live_view.rebuild_camera_strip()

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

        self.connect_action = QAction("Connect All", self)
        self.connect_action.triggered.connect(self.connect_hardware)
        hardware_menu.addAction(self.connect_action)

        self.disconnect_action = QAction("Disconnect All", self)
        self.disconnect_action.triggered.connect(self.disconnect_hardware)
        hardware_menu.addAction(self.disconnect_action)

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
        """Connect to all hardware components from configuration in a background thread."""
        logger.info("Initializing and connecting hardware from config...")
        
        self.connect_action.setEnabled(False)
        self.disconnect_action.setEnabled(False)
        self.statusbar.showMessage("Connecting all hardware...")

        import threading
        import time
        from PyQt6.QtCore import QTimer

        def _bg_connect():
            try:
                hw_cfg = self.hw.config.get('hardware', {})

                # 1. Initialize and connect cameras from config list
                cameras_cfg = hw_cfg.get('cameras', [])
                for cam_cfg in cameras_cfg:
                    if not cam_cfg.get('enabled', False):
                        continue
                    cam_id = cam_cfg['id']
                    driver = cam_cfg.get('driver', 'andor_camera')
                    
                    QTimer.singleShot(0, lambda cid=cam_id: self.statusbar.showMessage(f"Connecting camera {cid}..."))
                    
                    card = self.live_view.camera_panels.get(cam_id)
                    if card:
                        QTimer.singleShot(0, lambda c=card: c.update_connection_state(connected=False, connecting=True))

                    try:
                        if not self.hw.get_camera(cam_id):
                            self.hw.initialize_instrument(cam_id, driver, cam_cfg)
                            logger.info(f"Initialized camera '{cam_id}' ({cam_cfg.get('name', '')})")
                        
                        cam = self.hw.get_camera(cam_id)
                        if cam:
                            cam.connect()
                            logger.info(f"Camera '{cam_id}' connected successfully")
                            
                            # Sync calibration if it's the spectroscopy camera
                            if cam_id == self.hw.get_spectroscopy_camera_id():
                                self.hw.sync_calibration_with_hardware()
                    except Exception as e:
                        logger.error(f"Failed to connect camera '{cam_id}': {e}")
                    finally:
                        self.live_view.sig_cam_connect_done.emit(cam_id)
                        if card:
                            QTimer.singleShot(0, lambda c=card: c.connect_btn.setEnabled(True))
                        
                    # SDK stabilization delay
                    time.sleep(0.5)

                # 2. Initialize and connect monochromators
                monos_cfg = hw_cfg.get('monochromators', [])
                for mono_cfg in monos_cfg:
                    if not mono_cfg.get('enabled', False):
                        continue
                    mono_id = mono_cfg['id']
                    driver = mono_cfg.get('driver', 'horiba_serial')
                    
                    QTimer.singleShot(0, lambda mid=mono_id: self.statusbar.showMessage(f"Connecting monochromator {mid} (Homing)..."))
                    
                    mono_panel = None
                    for wrapper in self.equipment_sidebar._wrappers:
                        if wrapper.acc_id == 'mono':
                            mono_panel = wrapper.content_widget
                            break
                    if mono_panel:
                        QTimer.singleShot(0, lambda mp=mono_panel: mp.sig_status_changed.emit("Homing..."))
                        QTimer.singleShot(0, lambda mp=mono_panel: setattr(mp, '_connecting', True))
                        QTimer.singleShot(0, lambda mp=mono_panel: mp.connect_btn.setEnabled(False))

                    try:
                        if not self.hw.get_instrument(mono_id):
                            self.hw.initialize_instrument(mono_id, driver, mono_cfg)
                            logger.info(f"Initialized monochromator '{mono_id}' ({mono_cfg.get('name', '')})")
                        
                        mono = self.hw.get_instrument(mono_id)
                        if mono:
                            mono.connect()
                            logger.info(f"Monochromator '{mono_id}' connected successfully")
                            
                            # Apply defaults post-homing
                            default_wl = float(mono_cfg.get('center_wavelength', 500.0))
                            default_slit = float(mono_cfg.get('slit_width', 100.0))
                            default_grating_idx = int(mono_cfg.get('grating_idx', 1))
                            target_unit = "nm"
                            
                            logger.info(f"Applying targets post-homing: Index {default_grating_idx} grating, {default_wl} {target_unit}, {default_slit} um slits")
                            try:
                                mono.set_grating(default_grating_idx)
                                mono.set_spectral_position(default_wl, target_unit)
                                mono.set_slit_width(default_slit, slit_id=0)
                                mono.set_slit_width(default_slit, slit_id=2)
                                logger.info("Monochromator initialization and target move complete")
                            except Exception as ex:
                                logger.error(f"Failed to apply monochromator defaults: {ex}")
                    except Exception as e:
                        logger.error(f"Failed to connect monochromator '{mono_id}': {e}")
                    finally:
                        if mono_panel:
                            QTimer.singleShot(0, lambda mp=mono_panel: setattr(mp, '_connecting', False))
                            QTimer.singleShot(0, lambda mp=mono_panel: mp.connect_btn.setEnabled(True))
                    
                    time.sleep(0.1)

                # 3. Initialize accessories from config list
                accessories_cfg = hw_cfg.get('accessories', [])
                for acc_cfg in accessories_cfg:
                    if not acc_cfg.get('enabled', False):
                        continue
                    acc_id = acc_cfg['id']
                    driver = acc_cfg.get('driver', acc_id)
                    
                    QTimer.singleShot(0, lambda aid=acc_id: self.statusbar.showMessage(f"Connecting accessory {aid}..."))
                    
                    panel_id = acc_id
                    if acc_id in ('stage_x', 'stage_y'):
                        panel_id = 'stage'
                    
                    acc_panel = None
                    for wrapper in self.equipment_sidebar._wrappers:
                        if wrapper.acc_id == panel_id:
                            acc_panel = wrapper.content_widget
                            break
                    if acc_panel:
                        QTimer.singleShot(0, lambda ap=acc_panel: setattr(ap, '_connecting', True))
                        QTimer.singleShot(0, lambda ap=acc_panel: ap.connect_btn.setEnabled(False) if hasattr(ap, 'connect_btn') else None)

                    try:
                        if not self.hw.get_instrument(acc_id):
                            self.hw.initialize_instrument(acc_id, driver, acc_cfg)
                            logger.info(f"Initialized accessory '{acc_id}' ({acc_cfg.get('name', '')})")
                        
                        acc = self.hw.get_instrument(acc_id)
                        if acc:
                            acc.connect()
                            logger.info(f"Accessory '{acc_id}' connected successfully")
                    except Exception as e:
                        logger.error(f"Failed to connect accessory '{acc_id}': {e}")
                    finally:
                        if acc_panel:
                            QTimer.singleShot(0, lambda ap=acc_panel: setattr(ap, '_connecting', False))
                            QTimer.singleShot(0, lambda ap=acc_panel: ap.connect_btn.setEnabled(True) if hasattr(ap, 'connect_btn') else None)
                    
                    time.sleep(0.1)

            except Exception as e:
                logger.error(f"Error in background connection thread: {e}")
            finally:
                QTimer.singleShot(0, lambda: self.connect_action.setEnabled(True))
                QTimer.singleShot(0, lambda: self.disconnect_action.setEnabled(True))
                QTimer.singleShot(0, lambda: self.statusbar.showMessage("Hardware connected"))

        Thread(target=_bg_connect, daemon=True).start()

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
