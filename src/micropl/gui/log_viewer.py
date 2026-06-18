import logging
from ..qt import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
    QPlainTextEdit, pyqtSignal, QObject, Qt
)

class LogSignaler(QObject):
    """Bridge to emit logs from the logging handler to the UI thread."""
    log_ready = pyqtSignal(str)

class QtLogHandler(logging.Handler):
    """
    Custom logging handler that emits records via a Qt signal.
    """
    def __init__(self):
        super().__init__()
        self.signaler = LogSignaler()

    def emit(self, record):
        msg = self.format(record)
        self.signaler.log_ready.emit(msg)

class LogViewerDialog(QDialog):
    """
    Non-blocking dialog to display application logs in real-time.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Application Logs")
        self.resize(700, 400)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Log Display
        self.log_display = QPlainTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_display.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: 'Courier New', monospace;
                font-size: 11px;
            }
        """)
        layout.addWidget(self.log_display)

        # Toolbar
        btn_layout = QHBoxLayout()
        
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.log_display.clear)
        btn_layout.addWidget(clear_btn)
        
        btn_layout.addStretch()
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.hide)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)

    def append_log(self, text: str):
        """Append log text and auto-scroll to the bottom."""
        self.log_display.appendPlainText(text)
        # Scroll to bottom
        scrollbar = self.log_display.verticalScrollBar()
        if scrollbar is not None:
            scrollbar.setValue(scrollbar.maximum())

    def closeEvent(self, event):
        """Just hide instead of destroying to keep history/connection."""
        self.hide()
        event.ignore()
