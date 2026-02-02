"""
Sequence editor for n-P-t table.
"""

import logging
from ..qt import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QToolBar, QFileDialog, Qt, QAction
)

logger = logging.getLogger(__name__)


class SequenceEditor(QWidget):
    """Widget for editing measurement sequences (n-P-t table)."""

    def __init__(self):
        super().__init__()
        self._init_ui()
        logger.info("Sequence editor initialized")

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Toolbar
        toolbar = self._create_toolbar()
        layout.addWidget(toolbar)

        # Sequence table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Sample #",
            "Power (W)",
            "Time (s)",
            "Position (x, y)",
            "Wavelength (nm)"
        ])

        # Make table stretch to fill space
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self.table)

        # Load some example data
        self._load_example_data()

    def _create_toolbar(self) -> QToolBar:
        """Create toolbar with editing actions."""
        toolbar = QToolBar()

        # Add row
        add_action = QAction("Add Row", self)
        add_action.triggered.connect(self.add_row)
        toolbar.addAction(add_action)

        # Remove row
        remove_action = QAction("Remove Row", self)
        remove_action.triggered.connect(self.remove_row)
        toolbar.addAction(remove_action)

        toolbar.addSeparator()

        # Clear all
        clear_action = QAction("Clear All", self)
        clear_action.triggered.connect(self.clear_all)
        toolbar.addAction(clear_action)

        toolbar.addSeparator()

        # Load sequence
        load_action = QAction("Load Sequence", self)
        load_action.triggered.connect(self.load_sequence)
        toolbar.addAction(load_action)

        # Save sequence
        save_action = QAction("Save Sequence", self)
        save_action.triggered.connect(self.save_sequence)
        toolbar.addAction(save_action)

        toolbar.addSeparator()

        # Generate sequences
        generate_action = QAction("Generate Sequence...", self)
        generate_action.triggered.connect(self.generate_sequence)
        toolbar.addAction(generate_action)

        return toolbar

    def add_row(self):
        """Add a new row to the sequence."""
        row = self.table.rowCount()
        self.table.insertRow(row)

        # Set default values
        self.table.setItem(row, 0, QTableWidgetItem("1"))  # Sample
        self.table.setItem(row, 1, QTableWidgetItem("0.1"))  # Power
        self.table.setItem(row, 2, QTableWidgetItem("1.0"))  # Time
        self.table.setItem(row, 3, QTableWidgetItem(""))  # Position
        self.table.setItem(row, 4, QTableWidgetItem("700"))  # Wavelength

        logger.debug(f"Added row {row}")

    def remove_row(self):
        """Remove selected row."""
        current_row = self.table.currentRow()
        if current_row >= 0:
            self.table.removeRow(current_row)
            logger.debug(f"Removed row {current_row}")

    def clear_all(self):
        """Clear all rows from sequence."""
        self.table.setRowCount(0)
        logger.info("Sequence cleared")

    def load_sequence(self):
        """Load sequence from file."""
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Load Sequence",
            "",
            "CSV Files (*.csv);;All Files (*)"
        )

        if filename:
            logger.info(f"Loading sequence from {filename}")
            # TODO: Implement sequence loading
            # - Parse CSV or JSON file
            # - Populate table with data

    def save_sequence(self):
        """Save sequence to file."""
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Sequence",
            "",
            "CSV Files (*.csv);;All Files (*)"
        )

        if filename:
            logger.info(f"Saving sequence to {filename}")
            # TODO: Implement sequence saving
            # - Extract data from table
            # - Write to CSV or JSON

    def generate_sequence(self):
        """Open dialog to generate common sequence types."""
        logger.info("Generate sequence dialog requested")
        # TODO: Implement sequence generation dialog
        # - Power sweep
        # - Time series
        # - Multi-sample
        # - Grid scan

    def _load_example_data(self):
        """Load example data for demonstration."""
        example_data = [
            ("1", "0.1", "1.0", "", "700"),
            ("1", "0.2", "1.0", "", "700"),
            ("1", "0.5", "1.0", "", "700"),
            ("1", "1.0", "1.0", "", "700"),
            ("2", "0.5", "2.0", "(10, 10)", "750"),
        ]

        self.table.setRowCount(len(example_data))
        for row, data in enumerate(example_data):
            for col, value in enumerate(data):
                self.table.setItem(row, col, QTableWidgetItem(value))

    def get_sequence(self):
        """
        Extract sequence data from table.

        Returns:
            List of step dictionaries
        """
        sequence = []

        for row in range(self.table.rowCount()):
            step = {
                'sample_number': int(self.table.item(row, 0).text()),
                'power': float(self.table.item(row, 1).text()),
                'integration_time': float(self.table.item(row, 2).text()),
            }

            # Optional position
            pos_text = self.table.item(row, 3).text()
            if pos_text:
                # Parse "(x, y)" format
                pos_text = pos_text.strip('()')
                if ',' in pos_text:
                    x, y = pos_text.split(',')
                    step['position'] = (float(x), float(y))

            # Optional wavelength
            wl_text = self.table.item(row, 4).text()
            if wl_text:
                step['wavelength'] = float(wl_text)

            sequence.append(step)

        return sequence
