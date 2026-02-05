"""
Live view panel for real-time camera display.
"""

import logging
import numpy as np
from ..qt import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGroupBox, QDoubleSpinBox, QComboBox,
    QSpinBox, QGridLayout, Qt, QTimer, QImage, QPixmap,
    QLineEdit, QFrame, QMenu, QStackedWidget
)

from .plot import PlotWidget, ImagePlotWidget

logger = logging.getLogger(__name__)


from ..hardware.manager import HardwareManager

class LiveView(QWidget):
    """Widget for live camera display."""

    def __init__(self):
        super().__init__()
        self.hw = HardwareManager()
        self.current_camera = None
        self.background_frame = None
        self._acquiring = False
        self._timer = QTimer()
        self._timer.timeout.connect(self._update_frame)
        self._temp_timer = QTimer()
        self._temp_timer.timeout.connect(self._update_temperature)
        
        self._background_exposure = None # Store exposure time of captured background
        self._dispersion = 0.026 # Default dispersion for FHR640 @ 1200 g/mm (nm/px)
        
        self._init_ui()
        
        self._temp_timer.start(2000) # Update temperature every 2s
        logger.info("Live view initialized")

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        self.setLayout(layout)

        # Main consolidated control group
        control_group = self._create_main_control_group()
        layout.addWidget(control_group)

        # Display Stack (Image vs Spectrum)
        self.display_stack = QStackedWidget()
        
        # 1. Image View (now using PyQtGraph via ImagePlotWidget)
        self.image_plot = ImagePlotWidget()
        self.display_stack.addWidget(self.image_plot)
        
        # 2. Spectrum View (now using PyQtGraph via PlotWidget)
        self.spectrum_plot = PlotWidget()
        self.spectrum_plot.set_labels("Pixel", "Counts")
        self.display_stack.addWidget(self.spectrum_plot)
        
        layout.addWidget(self.display_stack, stretch=10) # Heavy stretch for data area

        # Acquisition settings
        settings_group = self._create_settings_group()
        layout.addWidget(settings_group)
        
        # Finally, populate choices to trigger initial synchronization
        self.camera_combo.addItems(["Visualisation", "Spectrometer"])

    def _create_main_control_group(self) -> QGroupBox:
        """Create the consolidated camera control group."""
        group = QGroupBox("Camera Selection Mode") # Removed underscores as requested
        group.setStyleSheet("QGroupBox { font-weight: bold; }")
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(20)
        group.setLayout(layout)

        # 1. Left Section: Selection
        selection_layout = QGridLayout()
        selection_layout.setSpacing(5)
        
        selection_layout.addWidget(QLabel("Camera:"), 0, 0)
        self.camera_combo = QComboBox()
        self.camera_combo.currentTextChanged.connect(self._on_camera_changed)
        selection_layout.addWidget(self.camera_combo, 0, 1)

        self.cam_connect_btn = QPushButton("Connect")
        self.cam_connect_btn.setFixedWidth(55)
        self.cam_connect_btn.setStyleSheet("font-size: 10px; height: 16px; padding: 0px;")
        self.cam_connect_btn.clicked.connect(self._on_cam_connect_clicked)
        selection_layout.addWidget(self.cam_connect_btn, 0, 2)

        selection_layout.addWidget(QLabel("Readout:"), 1, 0)
        self.readout_combo = QComboBox()
        self.readout_combo.currentTextChanged.connect(self._on_readout_mode_changed)
        selection_layout.addWidget(self.readout_combo, 1, 1)
        
        layout.addLayout(selection_layout)

        # Vertical line separator
        line_view = QFrame()
        line_view.setFrameShape(QFrame.Shape.VLine)
        line_view.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line_view)

        # View Mode / Units
        view_layout = QVBoxLayout()
        view_layout_h = QHBoxLayout()
        view_layout_h.addWidget(QLabel("View:"))
        self.view_combo = QComboBox()
        self.view_combo.addItems(["Image", "Spectrum"])
        self.view_combo.currentTextChanged.connect(self._on_view_mode_changed)
        view_layout_h.addWidget(self.view_combo)
        view_layout.addLayout(view_layout_h)
        
        unit_layout_h = QHBoxLayout()
        unit_layout_h.addWidget(QLabel("Units:"))
        self.spec_unit_combo = QComboBox()
        self.spec_unit_combo.addItems(["Spectral Units", "Pixel"])
        unit_layout_h.addWidget(self.spec_unit_combo)
        view_layout.addLayout(unit_layout_h)
        
        layout.addLayout(view_layout)

        # Vertical line separator
        line1 = QFrame()
        line1.setFrameShape(QFrame.Shape.VLine)
        line1.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line1)

        # 2. Middle Section: ROI/Binning Table
        roi_layout = QGridLayout()
        roi_layout.setSpacing(4)
        
        # Headers
        roi_layout.addWidget(QLabel(""), 0, 0)
        roi_layout.addWidget(QLabel("Start"), 0, 1)
        roi_layout.addWidget(QLabel("End"), 0, 2)
        roi_layout.addWidget(QLabel("Bin"), 0, 3)

        # X row
        roi_layout.addWidget(QLabel("X:"), 1, 0)
        self.x_start_box = QSpinBox()
        self.x_start_box.setRange(0, 4096)
        roi_layout.addWidget(self.x_start_box, 1, 1)
        
        self.x_end_box = QSpinBox()
        self.x_end_box.setRange(1, 4096)
        roi_layout.addWidget(self.x_end_box, 1, 2)
        
        self.x_bin_box = QSpinBox()
        self.x_bin_box.setRange(1, 1024)
        roi_layout.addWidget(self.x_bin_box, 1, 3)

        # Y row
        roi_layout.addWidget(QLabel("Y:"), 2, 0)
        self.y_start_box = QSpinBox()
        self.y_start_box.setRange(0, 4096)
        roi_layout.addWidget(self.y_start_box, 2, 1)
        
        self.y_end_box = QSpinBox()
        self.y_end_box.setRange(1, 4096)
        roi_layout.addWidget(self.y_end_box, 2, 2)
        
        self.y_bin_box = QSpinBox()
        self.y_bin_box.setRange(1, 1024)
        roi_layout.addWidget(self.y_bin_box, 2, 3)

        # Buttons (compact)
        self.apply_roi_btn = QPushButton("Apply")
        self.apply_roi_btn.setFixedWidth(55)
        self.apply_roi_btn.clicked.connect(self.apply_roi)
        roi_layout.addWidget(self.apply_roi_btn, 1, 4)
        
        self.presets_btn = QPushButton("Presets")
        self.presets_btn.setFixedWidth(70)
        self._setup_presets_menu()
        roi_layout.addWidget(self.presets_btn, 2, 4)
        
        layout.addLayout(roi_layout)

        # Vertical line separator
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.VLine)
        line2.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line2)

        # 3. Right Section: Temperature
        temp_layout = QGridLayout()
        temp_layout.setSpacing(5)
        
        temp_layout.addWidget(QLabel("Set:"), 0, 0)
        self.set_temp_box = QDoubleSpinBox()
        self.set_temp_box.setRange(-100, 20)
        self.set_temp_box.setSuffix(" °C")
        self.set_temp_box.valueChanged.connect(self.update_set_temperature)
        temp_layout.addWidget(self.set_temp_box, 0, 1)

        temp_layout.addWidget(QLabel("Real:"), 1, 0)
        self.real_temp_box = QLineEdit()
        self.real_temp_box.setReadOnly(True)
        self.real_temp_box.setFixedWidth(100)
        self.real_temp_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.real_temp_box.setText("N/A")
        self.real_temp_box.setToolTip("Current sensor temperature. Shows (Hold) during acquisition.")
        temp_layout.addWidget(self.real_temp_box, 1, 1)
        
        layout.addLayout(temp_layout)
        layout.addStretch()

        return group

    def _setup_presets_menu(self):
        """Setup the ROI presets menu."""
        menu = QMenu(self)
        
        img_action = menu.addAction("Image Visualisation")
        img_action.triggered.connect(lambda: self._apply_preset("image_vis"))
        
        spec_action = menu.addAction("Center Spectrometer")
        spec_action.triggered.connect(lambda: self._apply_preset("center_spec"))
        
        slit_action = menu.addAction("Slit Image")
        slit_action.triggered.connect(lambda: self._apply_preset("slit_image"))
        
        self.presets_btn.setMenu(menu)

    def _apply_preset(self, preset_type):
        """Apply a predefined ROI preset."""
        if preset_type == "image_vis":
            self.x_start_box.setValue(253)
            self.x_end_box.setValue(752)
            self.y_start_box.setValue(252)
            self.y_end_box.setValue(753)
            self.x_bin_box.setValue(1)
            self.y_bin_box.setValue(1)
        elif preset_type == "center_spec":
            self.x_start_box.setValue(0)
            self.x_end_box.setValue(1024)
            self.y_start_box.setValue(113)
            self.y_end_box.setValue(142)
            self.x_bin_box.setValue(1)
            self.y_bin_box.setValue(30)
        elif preset_type == "slit_image":
            self.x_start_box.setValue(0)
            self.x_end_box.setValue(1024)
            self.y_start_box.setValue(1)
            self.y_end_box.setValue(256)
            self.x_bin_box.setValue(1)
            self.y_bin_box.setValue(8)
            
        self.apply_roi()

    def _on_view_mode_changed(self, view_mode):
        """Switch between Image and Spectrum view."""
        if view_mode == "Spectrum":
            self.display_stack.setCurrentIndex(1)
        else:
            self.display_stack.setCurrentIndex(0)
        logger.info(f"View mode changed to {view_mode}")

    def _create_settings_group(self) -> QGroupBox:
        """Create acquisition settings controls."""
        group = QGroupBox("Acquisition")
        layout = QHBoxLayout()
        group.setLayout(layout)

        # Exposure control
        layout.addWidget(QLabel("Exposure (ms):"))
        self.exposure_box = QSpinBox() # Use integer ms
        self.exposure_box.setRange(1, 1000000)
        self.exposure_box.setSingleStep(100)
        self.exposure_box.setValue(100) # 100ms default
        # Only update hardware when user confirms with Enter or loses focus
        self.exposure_box.editingFinished.connect(self.update_exposure)
        layout.addWidget(self.exposure_box)

        # Data Type
        layout.addWidget(QLabel("Data Type:"))
        self.data_type_combo = QComboBox()
        self.data_type_combo.addItems(["Raw", "Background correction"])
        layout.addWidget(self.data_type_combo)

        # Buttons
        self.live_btn = QPushButton("Live")
        self.live_btn.setCheckable(True)
        self.live_btn.setMinimumWidth(80)
        self.live_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                font-weight: bold;
                border-radius: 4px;
                padding: 4px;
            }
            QPushButton:hover {
                background-color: #218838;
            }
            QPushButton:checked {
                background-color: #dc3545;
            }
            QPushButton:checked:hover {
                background-color: #c82333;
            }
        """)
        self.live_btn.clicked.connect(self._on_live_toggled)
        layout.addWidget(self.live_btn)

        self.background_btn = QPushButton("Take Background")
        self.background_btn.clicked.connect(self.take_background)
        layout.addWidget(self.background_btn)

        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.save_image)
        layout.addWidget(self.save_btn)

        layout.addStretch()

        return group

    def _on_camera_changed(self, camera_name):
        """Handle camera selection change."""
        self.stop_live_view()
        
        if camera_name == "Visualisation":
            self.current_camera = self.hw.vis_camera
            modes = ["Image"]
        else:
            self.current_camera = self.hw.spec_camera
            modes = ["Image", "FVB", "Single track"]

        # Refresh readout modes
        self.readout_combo.blockSignals(True)
        self.readout_combo.clear()
        self.readout_combo.addItems(modes)
        # Default to Image
        self.readout_combo.setCurrentText("Image")
        self.readout_combo.blockSignals(False)
        # Trigger layout update for "Image" mode (enable Y controls)
        self._on_readout_mode_changed("Image")
            
        if self.current_camera and self.current_camera.is_connected():
            info = self.current_camera.get_info()
            
            # Update set temperature box
            self.set_temp_box.blockSignals(True)
            self.set_temp_box.setValue(info.get('target_temperature', -20))
            self.set_temp_box.blockSignals(False)
            
            # Update exposure in UI (converting back to integer ms)
            self.exposure_box.blockSignals(True)
            self.exposure_box.setValue(int(info.get('exposure_time', 0.1) * 1000))
            self.exposure_box.blockSignals(False)

            # Update ROI limits based on detector size
            detector_size = info.get('detector_size', (2048, 512))
            width, height = detector_size
            self.x_start_box.setRange(0, width - 1)
            self.x_end_box.setRange(1, width)
            self.y_start_box.setRange(0, height - 1)
            self.y_end_box.setRange(1, height)
            
            # Get current ROI and sync UI
            roi = self.current_camera.get_roi()
            self.x_start_box.setValue(roi[0])
            self.x_end_box.setValue(roi[1])
            self.y_start_box.setValue(roi[2])
            self.y_end_box.setValue(roi[3])
            self.x_bin_box.setValue(roi[4])
            self.y_bin_box.setValue(roi[5])
        else:
            logger.warning(f"Camera {camera_name} not connected")
            # Sync set temperature box with last known/intended target
            self.set_temp_box.blockSignals(True)
            # Default to -70 for spectrometer, -20 for vis as a sensible visual hint
            hint_temp = -70 if camera_name == "Spectrometer" else -20
            self.set_temp_box.setValue(hint_temp)
            self.set_temp_box.blockSignals(False)

            # Set generic limits for UI safety
            self.x_start_box.setRange(0, 4096)
            self.x_end_box.setRange(1, 4096)
            self.y_start_box.setRange(0, 4096)
            self.y_end_box.setRange(1, 4096)
            self.y_bin_box.setRange(1, 1024)
            self.cam_connect_btn.setVisible(True)

        # Automatically apply ROI preset for Visualisation camera on selection
        if camera_name == "Visualisation":
            self._apply_preset("image_vis")
            
        # Reset poll count for "..." logic
        self._spec_poll_count = 0
        
        # Force immediate UI refresh for temperature
        self._update_temperature()

    def _on_cam_connect_clicked(self):
        """Try to connect the currently selected camera."""
        from ..qt import QMessageBox
        
        selected = self.camera_combo.currentText()
        logger.info(f"Attempting individual connection for {selected} camera")
        
        try:
            self.cam_connect_btn.setEnabled(False)
            self.cam_connect_btn.setText("Wait...")
            
            # Trust the HardwareManager to use the correct config from default.yaml
            if selected == "Visualisation":
                if not self.hw.vis_camera:
                    self.hw.initialize_instrument('vis_camera', 'andor_camera')
                self.hw.vis_camera.connect()
            else:
                if not self.hw.spec_camera:
                    self.hw.initialize_instrument('spec_camera', 'andor_camera')
                self.hw.spec_camera.connect()
                
            logger.info(f"{selected} camera connected successfully")
            self._on_camera_changed(selected) # Refresh UI state
        except Exception as e:
            logger.error(f"Failed to connect {selected} camera: {e}")
            QMessageBox.critical(self, "Connection Failed", f"Could not connect to {selected} camera:\n{e}")
        finally:
            self.cam_connect_btn.setEnabled(True)
            self.cam_connect_btn.setText("Connect")
            self._on_camera_changed(selected)

    def _on_readout_mode_changed(self, mode):
        """Handle readout mode change with automatic ROI configuration."""
        logger.info(f"Readout mode changed to {mode}")
        
        # Get detector size (use defaults if disconnected)
        width, height = 2048, 512
        if self.current_camera and self.current_camera.is_connected():
            info = self.current_camera.get_info()
            detector_size = info.get('detector_size', (2048, 512))
            width, height = detector_size

        if mode == "FVB":
            # Gray out everything in ROI section
            for box in [self.x_start_box, self.x_end_box, self.x_bin_box,
                        self.y_start_box, self.y_end_box, self.y_bin_box]:
                box.setEnabled(False)
            self.apply_roi_btn.setEnabled(False)
            self.presets_btn.setEnabled(False)
            
            # Auto-switch to Spectrum view
            self.view_combo.setCurrentText("Spectrum")
            
            # We do NOT call setValue or apply_roi here to preserve previous user ROI
            # the driver handles the FVB geometry internally via set_readout_mode
        elif mode == "Single track":
            # Enable all because user can still tweak single track ROI
            for box in [self.x_start_box, self.x_end_box, self.x_bin_box,
                        self.y_start_box, self.y_end_box, self.y_bin_box]:
                box.setEnabled(True)
            self.apply_roi_btn.setEnabled(True)
            self.presets_btn.setEnabled(True)

            # Automatically apply the Center Spectrometer preset for a calibrated starting point
            self._apply_preset("center_spec")
            
            # Auto-switch to Spectrum view
            self.view_combo.setCurrentText("Spectrum")
        else:
            # Image mode
            for box in [self.x_start_box, self.x_end_box, self.x_bin_box,
                        self.y_start_box, self.y_end_box, self.y_bin_box]:
                box.setEnabled(True)
            self.apply_roi_btn.setEnabled(True)
            self.presets_btn.setEnabled(True)
            
            # Auto-switch to Image view
            self.view_combo.setCurrentText("Image")

        # Update driver mode if connected
        if self.current_camera and self.current_camera.is_connected():
            try:
                self.current_camera.set_readout_mode(mode)
            except Exception as e:
                logger.error(f"Failed to set readout mode: {e}")

    def _on_live_toggled(self, checked):
        """Toggle live acquisition."""
        if checked:
            self.start_live_view()
        else:
            self.stop_live_view()

    def start_live_view(self):
        """Start live camera acquisition."""
        if not self.current_camera:
            self._on_camera_changed(self.camera_combo.currentText())

        if not self.current_camera or not self.current_camera.is_connected():
            logger.error("Selected camera not connected")
            self.live_btn.setChecked(False)
            return

        logger.info(f"Starting live view on {self.current_camera.model}")

        try:
            self.current_camera.start_acquisition()
            self._acquiring = True
            self.live_btn.setText("Abort")
            self.live_btn.setChecked(True)
            # Faster polling for "live" feel (33 fps max)
            self._timer.start(30)
        except Exception as e:
            logger.error(f"Failed to start live view: {e}")
            self.live_btn.setChecked(False)

    def stop_live_view(self):
        """Stop live camera acquisition."""
        if not self._acquiring:
            return

        logger.info("Stopping live view")
        self._timer.stop()
        self._acquiring = False
        self.live_btn.setText("Live")
        self.live_btn.setChecked(False)

        if self.current_camera and self.current_camera.is_connected():
            try:
                self.current_camera.stop_acquisition()
            except Exception as e:
                logger.error(f"Error stopping camera: {e}")

    def apply_roi(self):
        """Apply ROI settings to the current camera."""
        if not self.current_camera or not self.current_camera.is_connected():
            return

        try:
            x_start = self.x_start_box.value()
            x_end = self.x_end_box.value()
            x_bin = self.x_bin_box.value()
            y_start = self.y_start_box.value()
            y_end = self.y_end_box.value()
            y_bin = self.y_bin_box.value()

            # Stop acquisition if running
            was_acquiring = self._acquiring
            if was_acquiring:
                self.stop_live_view()

            self.current_camera.set_roi(x_start, x_end, y_start, y_end, x_bin, y_bin)
            logger.info(f"ROI applied: x=[{x_start}:{x_end}], y=[{y_start}:{y_end}], bin=({x_bin},{y_bin})")

            if was_acquiring:
                self.start_live_view()
        except Exception as e:
            logger.error(f"Failed to apply ROI: {e}")

    def take_background(self):
        """Capture a background frame."""
        if not self.current_camera or not self.current_camera.is_connected():
            logger.error("Camera not connected")
            return

        logger.info("Taking background frame")
        try:
            # If acquiring, stop temporarily
            was_acquiring = self._acquiring
            if was_acquiring:
                self.stop_live_view()
                
            # Capture multiple frames and average for a cleaner background
            frames = []
            print("Capturing background (5 frames)...")
            # Clear buffer
            for _ in range(5):
                self.current_camera.read_newest_image() # Flush any stale frames
                
            for _ in range(5):
                frame = self.current_camera.acquire_image()
                if frame is not None:
                    frames.append(frame.astype(np.float32))
                time.sleep(0.01)
            
            if frames:
                self.background_frame = np.mean(frames, axis=0)
                self._background_exposure = self.exposure_box.value()
                logger.info(f"Background captured (averaged 5 frames) at {self._background_exposure} ms")
            else:
                logger.error("Failed to capture background frames")
            
            if was_acquiring:
                self.start_live_view()
        except Exception as e:
            logger.error(f"Failed to take background: {e}")

    def save_image(self):
        """Save a snapshot from camera."""
        if not self.current_camera or not self.current_camera.is_connected():
            logger.error("Camera not connected")
            return

        logger.info("Saving image snapshot")
        try:
            image = self.current_camera.acquire_image()
            self.display_image(image)
            # Future implement: actual file save if requested, 
            # for now renaming method as requested by renaming button.
        except Exception as e:
            logger.error(f"Failed to save image: {e}")

    def update_set_temperature(self, temp):
        """Update target temperature on the camera."""
        if self.current_camera and self.current_camera.is_connected():
            try:
                self.current_camera.set_temperature(temp)
                logger.info(f"Target temperature updated to {temp} °C")
            except Exception as e:
                logger.error(f"Failed to set temperature: {e}")

    def _get_spectral_x(self, n_pixels: int) -> np.ndarray:
        """Calculate spectral x-axis (nm, meV, cm-1) based on mono position."""
        # Default pixel coordinates
        pixels = np.arange(n_pixels)
        
        # Check if we have a linked monochromator
        mono = self.hw.mono
        if not mono or not mono.is_connected() or self.camera_combo.currentText() != "Spectrometer":
            return pixels
            
        try:
            center_nm = mono.get_current_wavelength()
            # Crude linear dispersion: nm(pixel) = center_nm + (pixel - center_index) * dispersion
            # iDus DU420 has 1024 pixels (26um each). Center is 511.5
            center_px = n_pixels / 2.0 - 0.5
            
            # FHR640 @ 1200 g/mm dispersion is ~0.026 nm/px
            # If grating is 600, dispersion is ~0.052, etc.
            # We can try to guess from config if available
            grating = mono.config.get('grating', 1200)
            dispersion = 0.026 * (1200 / grating)
            
            x_nm = center_nm + (pixels - center_px) * dispersion
            
            # Convert to desired view unit
            unit_mode = self.spec_unit_combo.currentText()
            if unit_mode == "Pixel":
                return pixels
                
            # Use the global unit synchronized with the Monochromator Panel
            unit = self.hw.spectral_unit
            if unit == "nm":
                return x_nm
            elif unit == "meV":
                # Avoid division by zero
                x_nm = np.where(x_nm == 0, 1e-9, x_nm)
                return 1239.84193 / x_nm
            elif unit == "cm⁻¹" or unit == "cm-1":
                x_nm = np.where(x_nm == 0, 1e-9, x_nm)
                return 1e7 / x_nm
            else:
                return x_nm
        except Exception as e:
            logger.debug(f"Spectral sync failed: {e}")
            return pixels

    def update_exposure(self):
        """Update camera exposure time (input in ms)."""
        if self.current_camera and self.current_camera.is_connected():
            try:
                exposure_ms = self.exposure_box.value()
                exposure_s = exposure_ms / 1000.0
                self.current_camera.set_exposure(exposure_s)
                logger.info(f"Exposure set to {exposure_ms} ms ({exposure_s} s)")
                
                # Check background compatibility
                if self.background_frame is not None and self._background_exposure != exposure_ms:
                    logger.warning(f"Exposure mismatch! Current: {exposure_ms} ms, BG: {self._background_exposure} ms. Background correction may be invalid.")
            except Exception as e:
                logger.error(f"Failed to set exposure: {e}")

    def _update_temperature(self):
        """Update temperature display with dynamic styling (Red/Blue)."""
        try:
            camera_name = self.camera_combo.currentText()
            
            # 1. Determine target and camera instance from HardwareManager
            if camera_name == "Visualisation":
                target = self.hw.vis_camera_config.get('temperature', -20)
                camera = self.hw.vis_camera
            else:
                target = self.hw.spec_camera_config.get('temperature', -70)
                camera = self.hw.spec_camera
            
            real_temp = None
            is_connected = False
            
            # 2. Try to get temperature from active camera
            if camera:
                try:
                    real_temp = camera.get_temperature()
                    is_connected = camera.is_connected()
                except Exception as e:
                    logger.debug(f"get_temperature failed for {camera_name}: {e}")
            
            # 3. Apply user-specific display logic
            display_text = "N/A"
            style_mode = "disconnected"
            status_tooltip = "Current sensor temperature."
            
            if is_connected:
                # If connected, try to show reading
                cooling_status = camera.get_cooling_status()
                status_tooltip = f"Hardware Status: {cooling_status}"
                
                if real_temp is not None and isinstance(real_temp, (int, float)) and not np.isnan(real_temp):
                    is_busy = camera.is_acquiring()
                    if is_busy:
                        display_text = f"{real_temp:.1f} °C (Busy)"
                        style_mode = "cached"
                    else:
                        display_text = f"{real_temp:.1f} °C (Live)"
                        style_mode = "stable"
                else:
                    # Still waiting for numeric stabilization
                    display_text = "..." 
                    style_mode = "disconnected"
            else:
                # Disconnected state
                if camera_name == "Visualisation":
                    display_text = f"{target:.1f} °C"
                else:
                    display_text = "N/A"
                style_mode = "disconnected"
            
            # 4. Update the UI widget
            self.real_temp_box.setText(display_text)
            self.real_temp_box.setToolTip(status_tooltip)
            
            # 5. Apply Styles
            if style_mode == "stable":
                set_temp = self.set_temp_box.value()
                diff = abs(real_temp - set_temp)
                if diff < 1.0:
                    self.real_temp_box.setStyleSheet(
                        "background-color: #2196F3; color: white; font-weight: bold; border: 1px solid #1976D2; border-radius: 4px;"
                    )
                else:
                    self.real_temp_box.setStyleSheet(
                        "background-color: #F44336; color: white; font-weight: bold; border: 1px solid #D32F2F; border-radius: 4px;"
                    )
            elif style_mode == "cached":
                # Distinct "Hold" look: Amber/Yellow
                self.real_temp_box.setStyleSheet(
                    "background-color: #FFC107; color: black; font-weight: bold; border: 1px solid #FFA000; border-radius: 4px;"
                )
            else: # disconnected or N/A
                self.real_temp_box.setStyleSheet(
                    "background-color: transparent; border: 1px solid #ced4da; color: gray;"
                )
                
        except Exception as e:
            logger.error(f"Critical error in temperature UI update: {e}")
            self.real_temp_box.setText("Err") # Show 'Err' if crashing

    def display_image(self, image: np.ndarray):
        """
        Display image on screen.

        Args:
            image: 2D numpy array with image data
        """
        # PyQtGraph handles normalization and display efficiently
        self.image_plot.imshow(image)

    def _update_frame(self):
        """Read frame from camera and display it."""
        if not self.current_camera or not self.current_camera.is_acquiring():
            return

        try:
            # Use read_newest_image to minimize lag in Live View
            image = self.current_camera.read_newest_image()
            if image is not None:
                # Background correction
                if self.data_type_combo.currentText() == "Background correction" and self.background_frame is not None:
                    if image.shape == self.background_frame.shape:
                        # Check exposure mismatch
                        current_exp = self.exposure_box.value()
                        if current_exp != self._background_exposure:
                            # Log every 50 frames to avoid flooding while still warning
                            if getattr(self, '_exp_warn_counter', 0) % 50 == 0:
                                logger.warning(f"Background mismatch: BG taken at {self._background_exposure} ms, current is {current_exp} ms.")
                            self._exp_warn_counter = getattr(self, '_exp_warn_counter', 0) + 1

                        # Perform subtraction in float32 to allow negative values (noise) without wrap-around
                        # We do NOT cast back to image.dtype (usually uint16) because that causes the spikes.
                        image = image.astype(np.float32) - self.background_frame.astype(np.float32)
                    else:
                        logger.warning("Background shape mismatch, skipping correction")

                if self.view_combo.currentText() == "Image":
                    # If we accidentally have 1D data in image view, try to reshape or ignore
                    if image.ndim == 2:
                        self.display_image(image)
                    else:
                        logger.debug("Received 1D data in Image view mode. Reshaping to 1xN.")
                        self.display_image(image.reshape(1, -1))
                else:
                    # Spectrum View
                    if image.ndim == 2:
                        spectrum = np.sum(image, axis=0)
                    else:
                        spectrum = image
                    
                    x = self._get_spectral_x(len(spectrum))
                    # Use optimized update_plot method
                    self.spectrum_plot.update_plot(x, spectrum)

        except Exception as e:
            logger.error(f"Error updating frame: {e}")
            self.stop_live_view()
