"""
Live view panel for real-time camera display.
"""

import logging
import numpy as np
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGroupBox, QSlider
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap

logger = logging.getLogger(__name__)


class LiveView(QWidget):
    """Widget for live camera display."""

    def __init__(self):
        super().__init__()
        self._init_ui()
        self._acquiring = False
        logger.info("Live view initialized")

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Control group
        control_group = self._create_control_group()
        layout.addWidget(control_group)

        # Image display
        image_group = self._create_image_group()
        layout.addWidget(image_group, stretch=1)

        # Settings
        settings_group = self._create_settings_group()
        layout.addWidget(settings_group)

    def _create_control_group(self) -> QGroupBox:
        """Create control buttons."""
        group = QGroupBox("Control")
        layout = QHBoxLayout()
        group.setLayout(layout)

        self.start_btn = QPushButton("Start Live View")
        self.start_btn.clicked.connect(self.start_live_view)
        layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_live_view)
        self.stop_btn.setEnabled(False)
        layout.addWidget(self.stop_btn)

        self.snapshot_btn = QPushButton("Take Snapshot")
        self.snapshot_btn.clicked.connect(self.take_snapshot)
        layout.addWidget(self.snapshot_btn)

        layout.addStretch()

        return group

    def _create_image_group(self) -> QGroupBox:
        """Create image display area."""
        group = QGroupBox("Camera View")
        layout = QVBoxLayout()
        group.setLayout(layout)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(640, 480)
        self.image_label.setStyleSheet("QLabel { background-color: black; }")
        self.image_label.setText("No image")

        layout.addWidget(self.image_label)

        return group

    def _create_settings_group(self) -> QGroupBox:
        """Create camera settings controls."""
        group = QGroupBox("Settings")
        layout = QHBoxLayout()
        group.setLayout(layout)

        # Exposure control
        layout.addWidget(QLabel("Exposure:"))
        self.exposure_slider = QSlider(Qt.Orientation.Horizontal)
        self.exposure_slider.setRange(1, 1000)  # 0.001 to 1.0 seconds
        self.exposure_slider.setValue(100)
        self.exposure_slider.valueChanged.connect(self.update_exposure)
        layout.addWidget(self.exposure_slider)

        self.exposure_label = QLabel("0.1 s")
        layout.addWidget(self.exposure_label)

        # Gain control
        layout.addWidget(QLabel("Gain:"))
        self.gain_slider = QSlider(Qt.Orientation.Horizontal)
        self.gain_slider.setRange(1, 100)
        self.gain_slider.setValue(1)
        self.gain_slider.valueChanged.connect(self.update_gain)
        layout.addWidget(self.gain_slider)

        self.gain_label = QLabel("1")
        layout.addWidget(self.gain_label)

        layout.addStretch()

        return group

    def start_live_view(self):
        """Start live camera acquisition."""
        logger.info("Starting live view")

        self._acquiring = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        # TODO: Start camera acquisition
        # TODO: Connect to camera update signal

        # Simulate camera updates
        self._start_simulation()

    def stop_live_view(self):
        """Stop live camera acquisition."""
        logger.info("Stopping live view")

        self._acquiring = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        # TODO: Stop camera acquisition

        if hasattr(self, '_timer'):
            self._timer.stop()

    def take_snapshot(self):
        """Capture a snapshot from camera."""
        logger.info("Taking snapshot")
        # TODO: Capture and save single frame

    def update_exposure(self, value):
        """Update camera exposure time."""
        exposure = value / 1000.0  # Convert to seconds
        self.exposure_label.setText(f"{exposure:.3f} s")
        logger.debug(f"Exposure set to {exposure} s")

        # TODO: Send exposure command to camera

    def update_gain(self, value):
        """Update camera gain."""
        self.gain_label.setText(str(value))
        logger.debug(f"Gain set to {value}")

        # TODO: Send gain command to camera

    def display_image(self, image: np.ndarray):
        """
        Display image on screen.

        Args:
            image: 2D numpy array with image data
        """
        # Normalize to 0-255
        if image.max() > 0:
            normalized = (image / image.max() * 255).astype(np.uint8)
        else:
            normalized = image.astype(np.uint8)

        # Convert to QImage
        height, width = normalized.shape
        bytes_per_line = width

        q_image = QImage(
            normalized.data,
            width,
            height,
            bytes_per_line,
            QImage.Format.Format_Grayscale8
        )

        # Scale to fit label while maintaining aspect ratio
        pixmap = QPixmap.fromImage(q_image)
        scaled_pixmap = pixmap.scaled(
            self.image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        self.image_label.setPixmap(scaled_pixmap)

    def _start_simulation(self):
        """Start simulated camera feed (for demonstration)."""

        def update_frame():
            # Generate fake image
            image = np.random.poisson(100, (512, 512)).astype(np.uint16)

            # Add a fake feature (bright spot)
            cx, cy = 256, 256
            y, x = np.ogrid[:512, :512]
            mask = (x - cx)**2 + (y - cy)**2 <= 50**2
            image[mask] += 500

            self.display_image(image)

        self._timer = QTimer()
        self._timer.timeout.connect(update_frame)
        self._timer.start(100)  # Update every 100ms
