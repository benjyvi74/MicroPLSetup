"""
Startup splash screen with progress reporting for MicroPL.
"""

from pathlib import Path

from .. import __version__
from ..qt import (
    QApplication, QLabel, QPixmap, QProgressBar,
    QSplashScreen, QVBoxLayout, Qt
)

class MicroPLSplash(QSplashScreen):
    def __init__(self):
        # Create a solid white pixmap for the native splash background
        pixmap = QPixmap(500, 220)
        pixmap.fill(Qt.GlobalColor.white)
        super().__init__(pixmap)
        
        # Ensure it stays on top and behaves like a persistent window (not a transient splash)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        # Main layout for overlay text (QSplashScreen can have a layout)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 10, 30, 20) # Tighter top/left margins for version
        layout.setSpacing(5)
        
        # Version Tag (Top Left)
        self.version_label = QLabel(__version__)
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        # Increased font size to 11px and changed color to dark grey for white background
        self.version_label.setStyleSheet("color: #636e72; font-size: 11px; font-weight: normal; background: transparent; border: none;")
        layout.addWidget(self.version_label)
        
        layout.addSpacing(5)
        
        # Logo / Branding Container
        self.logo_label = QLabel()
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_label.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self.logo_label)
        
        # Check for logo file
        logo_path = Path(__file__).parent / "assets" / "PLC.png"
        
        if logo_path.exists():
            pixmap = QPixmap(str(logo_path))
            if not pixmap.isNull():
                # Scale logo to fit while maintaining aspect ratio
                scaled_logo = pixmap.scaled(400, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.logo_label.setPixmap(scaled_logo)
                has_logo = True
            else:
                has_logo = False
        else:
            has_logo = False

        # Title (Fallback or secondary)
        self.title_label = QLabel("Photolum Control Software")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("color: #2d3436; font-size: 24px; font-weight: bold; background: transparent; border: none;")
        layout.addWidget(self.title_label)
        
        # Subtitle (Fallback or secondary)
        self.subtitle_label = QLabel("Automated Micro-Photoluminescence Platform")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setStyleSheet("color: #636e72; font-size: 13px; background: transparent; border: none;")
        layout.addWidget(self.subtitle_label)
        
        # If we have a logo that contains the title, hide the text labels
        if has_logo:
            self.title_label.hide()
            self.subtitle_label.hide()
            
        layout.addStretch()

        # Status text
        self.status_label = QLabel("Initializing...")
        self.status_label.setStyleSheet("color: #2d3436; font-size: 11px; background: transparent; border: none;")
        layout.addWidget(self.status_label)
        
        # Progress bar
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.setStyleSheet("""
            QProgressBar {
                border: none;
                background-color: #dfe6e9;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background-color: #0984e3;
                border-radius: 2px;
            }
        """)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

    def set_progress(self, value, text=None):
        """Update progress bar and status text."""
        self.progress.setValue(value)
        if text:
            self.status_label.setText(text)
            # Standard QSplashScreen showMessage is redundant but can be used for accessibility
            # self.showMessage(text, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter, QtGui.QColor("#dfe6e9"))
        
        # Force a UI update manually
        self.update()
        QApplication.processEvents()

    def finish(self, main_window):
        """Standard QSplashScreen finish behavior."""
        super().finish(main_window)
