import logging
from typing import List, Dict, Any, Optional
from ..qt import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView, Qt
)

from .automation_panel import format_power_w

logger = logging.getLogger(__name__)

class SequenceSummaryDialog(QDialog):
    """
    Dialog to review and confirm a laser heating sequence before execution.
    Allows toggling 'Skip Step 0'.
    """
    def __init__(self, steps: List[Dict[str, Any]], cooling_delay: float = 0.0, start_index: int = 1, parent=None):
        super().__init__(parent)
        self.steps = steps
        self.cooling_delay = cooling_delay
        self.start_index = start_index
        self.setWindowTitle("Review Heating Sequence")
        self.resize(500, 450)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Header
        layout.addWidget(QLabel("<b>Sequence Summary</b>"))
        
        # Summary Table
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Step #", "Heat Power", "Duration"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        # Populate table
        # Step 0 explicit row
        self.table.insertRow(0)
        self.table.setItem(0, 0, QTableWidgetItem("0 (Initial)"))
        self.table.setItem(0, 1, QTableWidgetItem("-"))
        self.table.setItem(0, 2, QTableWidgetItem("-"))
        
        # Dim Step 0 if we are starting from a later index
        if self.start_index > 0:
            for c in range(3):
                item = self.table.item(0, c)
                item.setText(item.text() + " (Skipped)")
                item.setForeground(Qt.GlobalColor.gray)

        # Labels match AutomationPanel re-indexing logic
        offset = self.start_index if self.start_index > 0 else 1
        
        for i, step in enumerate(self.steps):
            row = i + 1
            self.table.insertRow(row)
            step_num = i + offset
            self.table.setItem(row, 0, QTableWidgetItem(str(step_num)))
            
            p_val = step.get('target_w', 0.0)
            p_str = format_power_w(p_val)
            self.table.setItem(row, 1, QTableWidgetItem(p_str))
            
            d_val = step.get('duration', 0.0)
            self.table.setItem(row, 2, QTableWidgetItem(f"{d_val} s"))

        layout.addWidget(self.table)

        # Options
        self.skip_checkbox = QCheckBox("Skip Step 0 (Initial Measurement)")
        # If start_index > 1, we MUST skip step 0 (already done in previous run), so disable toggle
        if self.start_index > 1:
            self.skip_checkbox.setChecked(True)
            self.skip_checkbox.setEnabled(False)
        else:
            # For a fresh run (start index 1), don't skip by default
            self.skip_checkbox.setChecked(False)
            self.skip_checkbox.setEnabled(True)
        
        self.skip_checkbox.setToolTip("If checked, the sequence will start directly with Heating Step 1.")
        layout.addWidget(self.skip_checkbox)

        # Info
        info_layout = QVBoxLayout()
        
        delay_lbl = QLabel(f"<b>Cooling Delay: {self.cooling_delay} s</b>")
        delay_lbl.setStyleSheet("color: #d35400;")
        info_layout.addWidget(delay_lbl)
        
        info_lbl = QLabel("Note: Data will be saved to the folder/prefix defined in the main window.\n"
                         "Background correction and Time Normalization will be applied.")
        info_lbl.setStyleSheet("color: gray; font-style: italic;")
        info_lbl.setWordWrap(True)
        info_layout.addWidget(info_lbl)
        
        layout.addLayout(info_layout)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        run_btn = QPushButton("Run Sequence")
        run_btn.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold;")
        run_btn.clicked.connect(self.accept)
        btn_layout.addWidget(run_btn)
        
        layout.addLayout(btn_layout)

    def should_skip_step_0(self) -> bool:
        return self.skip_checkbox.isChecked()
