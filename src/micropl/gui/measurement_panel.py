"""
Measurement panel for running experiments and viewing results.
"""

import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QProgressBar, QGroupBox, QTextEdit
)
from PyQt6.QtCore import Qt, QTimer

from .plot import PlotWidget

logger = logging.getLogger(__name__)


class MeasurementPanel(QWidget):
    """Widget for measurement control and data visualization."""

    def __init__(self):
        super().__init__()
        self._init_ui()
        self._running = False
        logger.info("Measurement panel initialized")

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Control group
        control_group = self._create_control_group()
        layout.addWidget(control_group)

        # Progress group
        progress_group = self._create_progress_group()
        layout.addWidget(progress_group)

        # Plots
        plot_group = self._create_plot_group()
        layout.addWidget(plot_group, stretch=1)

        # Log output
        log_group = self._create_log_group()
        layout.addWidget(log_group)

    def _create_control_group(self) -> QGroupBox:
        """Create measurement control buttons."""
        group = QGroupBox("Control")
        layout = QHBoxLayout()
        group.setLayout(layout)

        self.start_btn = QPushButton("Start Measurement")
        self.start_btn.clicked.connect(self.start_measurement)
        layout.addWidget(self.start_btn)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self.pause_measurement)
        self.pause_btn.setEnabled(False)
        layout.addWidget(self.pause_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_measurement)
        self.stop_btn.setEnabled(False)
        layout.addWidget(self.stop_btn)

        layout.addStretch()

        return group

    def _create_progress_group(self) -> QGroupBox:
        """Create progress display."""
        group = QGroupBox("Progress")
        layout = QVBoxLayout()
        group.setLayout(layout)

        # Status label
        self.status_label = QLabel("Status: Ready")
        layout.addWidget(self.status_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Step info
        self.step_label = QLabel("Step: 0/0")
        layout.addWidget(self.step_label)

        return group

    def _create_plot_group(self) -> QGroupBox:
        """Create plot displays."""
        group = QGroupBox("Data Visualization")
        layout = QVBoxLayout()
        group.setLayout(layout)

        # Main plot for spectra or time series
        self.main_plot = PlotWidget()
        self.main_plot.set_labels("Wavelength (nm)", "Intensity (a.u.)")
        layout.addWidget(self.main_plot)

        return group

    def _create_log_group(self) -> QGroupBox:
        """Create log output display."""
        group = QGroupBox("Log")
        layout = QVBoxLayout()
        group.setLayout(layout)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        layout.addWidget(self.log_text)

        return group

    def start_measurement(self):
        """Start measurement sequence."""
        logger.info("Starting measurement")

        self._running = True
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)

        self.status_label.setText("Status: Running")
        self.log_message("Measurement started")

        # TODO: Get sequence from sequence editor
        # TODO: Create Experiment instance
        # TODO: Start experiment in worker thread

        # Simulate progress for demonstration
        self._simulate_progress()

    def pause_measurement(self):
        """Pause measurement."""
        logger.info("Pausing measurement")
        self.status_label.setText("Status: Paused")
        self.log_message("Measurement paused")

        # TODO: Pause experiment

    def stop_measurement(self):
        """Stop measurement."""
        logger.info("Stopping measurement")

        self._running = False
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)

        self.status_label.setText("Status: Stopped")
        self.log_message("Measurement stopped")

        # TODO: Stop experiment

    def log_message(self, message: str):
        """Add message to log display."""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")

    def update_plot(self, x_data, y_data):
        """Update main plot with new data."""
        self.main_plot.plot(x_data, y_data)

    def _simulate_progress(self):
        """Simulate measurement progress (for demonstration)."""
        # This would be replaced by actual experiment progress updates

        self.progress = 0
        self.total_steps = 10

        def update():
            self.progress += 1
            percent = int(self.progress / self.total_steps * 100)
            self.progress_bar.setValue(percent)
            self.step_label.setText(f"Step: {self.progress}/{self.total_steps}")

            if self.progress >= self.total_steps:
                self.stop_measurement()
                self.log_message("Measurement complete")
                timer.stop()

        timer = QTimer()
        timer.timeout.connect(update)
        timer.start(500)  # Update every 500ms
