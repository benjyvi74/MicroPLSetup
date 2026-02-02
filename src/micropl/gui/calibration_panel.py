"""
Calibration panel for power calibration.
"""

import logging
from ..qt import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QSpinBox, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, Qt
)

logger = logging.getLogger(__name__)


class CalibrationPanel(QWidget):
    """Widget for power calibration procedures."""

    def __init__(self):
        super().__init__()
        self._init_ui()
        logger.info("Calibration panel initialized")

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Power calibration group
        power_group = self._create_power_calibration_group()
        layout.addWidget(power_group)

        # Alignment group
        alignment_group = self._create_alignment_group()
        layout.addWidget(alignment_group)

        # Stretch to push everything to top
        layout.addStretch()

    def _create_power_calibration_group(self) -> QGroupBox:
        """Create power calibration controls."""
        group = QGroupBox("Power Calibration")
        layout = QVBoxLayout()
        group.setLayout(layout)

        # Parameters
        params_layout = QHBoxLayout()

        params_layout.addWidget(QLabel("Number of points:"))
        self.num_points_spin = QSpinBox()
        self.num_points_spin.setRange(3, 100)
        self.num_points_spin.setValue(10)
        params_layout.addWidget(self.num_points_spin)

        params_layout.addWidget(QLabel("Min Power (W):"))
        self.min_power_spin = QDoubleSpinBox()
        self.min_power_spin.setRange(0.0, 1.0)
        self.min_power_spin.setValue(0.1)
        self.min_power_spin.setSingleStep(0.01)
        params_layout.addWidget(self.min_power_spin)

        params_layout.addWidget(QLabel("Max Power (W):"))
        self.max_power_spin = QDoubleSpinBox()
        self.max_power_spin.setRange(0.0, 1.0)
        self.max_power_spin.setValue(1.0)
        self.max_power_spin.setSingleStep(0.01)
        params_layout.addWidget(self.max_power_spin)

        params_layout.addStretch()
        layout.addLayout(params_layout)

        # Buttons
        button_layout = QHBoxLayout()

        self.start_calibration_btn = QPushButton("Start Calibration")
        self.start_calibration_btn.clicked.connect(self.start_calibration)
        button_layout.addWidget(self.start_calibration_btn)

        self.save_calibration_btn = QPushButton("Save Calibration")
        self.save_calibration_btn.clicked.connect(self.save_calibration)
        button_layout.addWidget(self.save_calibration_btn)

        self.load_calibration_btn = QPushButton("Load Calibration")
        self.load_calibration_btn.clicked.connect(self.load_calibration)
        button_layout.addWidget(self.load_calibration_btn)

        button_layout.addStretch()
        layout.addLayout(button_layout)

        # Calibration data table
        self.calibration_table = QTableWidget()
        self.calibration_table.setColumnCount(2)
        self.calibration_table.setHorizontalHeaderLabels(["Setpoint (W)", "Measured (W)"])
        layout.addWidget(self.calibration_table)

        return group

    def _create_alignment_group(self) -> QGroupBox:
        """Create alignment controls."""
        group = QGroupBox("Alignment")
        layout = QVBoxLayout()
        group.setLayout(layout)

        button_layout = QHBoxLayout()

        self.find_peak_btn = QPushButton("Find Peak Intensity")
        self.find_peak_btn.clicked.connect(self.find_peak)
        button_layout.addWidget(self.find_peak_btn)

        self.set_reference_btn = QPushButton("Set Reference Position")
        self.set_reference_btn.clicked.connect(self.set_reference)
        button_layout.addWidget(self.set_reference_btn)

        self.goto_reference_btn = QPushButton("Go to Reference")
        self.goto_reference_btn.clicked.connect(self.goto_reference)
        button_layout.addWidget(self.goto_reference_btn)

        button_layout.addStretch()
        layout.addLayout(button_layout)

        # Position display
        pos_layout = QHBoxLayout()
        pos_layout.addWidget(QLabel("Reference Position:"))
        self.ref_position_label = QLabel("Not set")
        pos_layout.addWidget(self.ref_position_label)
        pos_layout.addStretch()
        layout.addLayout(pos_layout)

        return group

    def start_calibration(self):
        """Start power calibration procedure."""
        num_points = self.num_points_spin.value()
        min_power = self.min_power_spin.value()
        max_power = self.max_power_spin.value()

        logger.info(f"Starting calibration: {num_points} points, "
                   f"{min_power}-{max_power} W")

        # TODO: Implement calibration procedure
        # - Create PowerCalibration instance
        # - Run calibration
        # - Update table with results

        # Placeholder: populate table with dummy data
        self.calibration_table.setRowCount(num_points)
        for i in range(num_points):
            setpoint = min_power + (max_power - min_power) * i / (num_points - 1)
            measured = setpoint * 0.95  # Dummy: 5% loss

            self.calibration_table.setItem(i, 0, QTableWidgetItem(f"{setpoint:.4f}"))
            self.calibration_table.setItem(i, 1, QTableWidgetItem(f"{measured:.4f}"))

    def save_calibration(self):
        """Save calibration to file."""
        logger.info("Saving calibration")
        # TODO: Implement save to file

    def load_calibration(self):
        """Load calibration from file."""
        logger.info("Loading calibration")
        # TODO: Implement load from file

    def find_peak(self):
        """Find peak intensity position."""
        logger.info("Finding peak intensity")
        # TODO: Implement peak finding

    def set_reference(self):
        """Set current position as reference."""
        logger.info("Setting reference position")
        # TODO: Get current stage position and store
        self.ref_position_label.setText("(0.0, 0.0) mm")

    def goto_reference(self):
        """Move stage to reference position."""
        logger.info("Moving to reference position")
        # TODO: Command stage to move to reference
