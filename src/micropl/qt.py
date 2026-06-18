import sys
import logging
import platform
import os
import shutil
from pathlib import Path

# --- Mac GUI Fix (Refined Proxy & Environment) ---
if platform.system() == "Darwin" and "MICROPL_QT_FIXED" not in os.environ:
    try:
        import importlib.util
        
        # 1. Locate Qt installation
        spec = importlib.util.find_spec("PyQt6")
        is_pyqt = True
        if not spec:
            spec = importlib.util.find_spec("PySide6")
            is_pyqt = False
            
        if spec and spec.submodule_search_locations:
            base_path = Path(spec.submodule_search_locations[0])
            qt_root = base_path / ("Qt6" if is_pyqt else "Qt")
            plugins_path = qt_root / "plugins"
            lib_path = qt_root / "lib"
            
            if plugins_path.exists():
                sys.stderr.write("Finalizing macOS Qt environment fix...\n")
                
                # Cleanup and create clean proxy only for platforms
                proxy_dir = Path("/tmp/micropl_qt_fix")
                proxy_platforms = proxy_dir / "platforms"
                
                if proxy_dir.exists():
                    shutil.rmtree(proxy_dir, ignore_errors=True)
                proxy_platforms.mkdir(parents=True, exist_ok=True)
                
                # Copy ONLY cocoa for minimal footprint and maximum compatibility
                src_platforms = plugins_path / "platforms"
                if src_platforms.exists():
                    cocoa_plugin = src_platforms / "libqcocoa.dylib"
                    if cocoa_plugin.exists():
                        shutil.copy(cocoa_plugin, proxy_platforms / "libqcocoa.dylib")
                
                # IMPORTANT: Set pointing to the PLATFORMS folder directly for QPA
                # and the PLUGINS folder for general plugin discovery
                os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(proxy_platforms)
                os.environ["QT_PLUGIN_PATH"] = str(plugins_path)
                
                # Set DYLD_FRAMEWORK_PATH for the libraries
                os.environ["DYLD_FRAMEWORK_PATH"] = str(lib_path)
                
                os.environ["MICROPL_QT_FIXED"] = "1"
                
                # Re-execute to ensure DYLD_* takes effect
                sys.stderr.write(f"Redirecting macOS Qt to: {proxy_platforms}\n")
                sys.stderr.flush()
                os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        sys.stderr.write(f"Bridge fix failed: {e}\n")
# -------------------------------------------------------

import typing

if typing.TYPE_CHECKING:
    from PyQt6 import QtWidgets, QtCore, QtGui
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
        QTabWidget, QStatusBar, QMenuBar, QMenu, QPushButton, QLabel, 
        QProgressBar, QGroupBox, QTextEdit, QDoubleSpinBox, QComboBox, 
        QGridLayout, QFrame, QSpinBox, QTableWidget, QTableWidgetItem,
        QHeaderView, QToolBar, QFileDialog, QMessageBox, QSlider, QSplitter,
        QLineEdit, QDialog, QDialogButtonBox, QCheckBox, QStackedWidget,
        QButtonGroup, QPlainTextEdit, QListWidget, QListWidgetItem, QSplashScreen,
        QSizePolicy, QScrollArea, QToolButton
    )
    from PyQt6.QtCore import QTimer, QThread, QObject, pyqtSignal, pyqtSlot, Qt, QSize, QCoreApplication
    from PyQt6.QtGui import QAction, QImage, QPixmap, QIcon
    PYSIDE = False
    PYQT = True
else:
    # Preferred: PyQt6
    try:
        from PyQt6 import QtWidgets, QtCore, QtGui
        from PyQt6.QtWidgets import (
            QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
            QTabWidget, QStatusBar, QMenuBar, QMenu, QPushButton, QLabel, 
            QProgressBar, QGroupBox, QTextEdit, QDoubleSpinBox, QComboBox, 
            QGridLayout, QFrame, QSpinBox, QTableWidget, QTableWidgetItem,
            QHeaderView, QToolBar, QFileDialog, QMessageBox, QSlider, QSplitter,
            QLineEdit, QDialog, QDialogButtonBox, QCheckBox, QStackedWidget,
            QButtonGroup, QPlainTextEdit, QListWidget, QListWidgetItem, QSplashScreen,
            QSizePolicy, QScrollArea, QToolButton
        )
        from PyQt6.QtCore import QTimer, QThread, QObject, pyqtSignal, pyqtSlot, Qt, QSize, QCoreApplication
        from PyQt6.QtGui import QAction, QImage, QPixmap, QIcon
        PYSIDE = False
        PYQT = True
    except ImportError:
        try:
            from PySide6 import QtWidgets, QtCore, QtGui
            from PySide6.QtWidgets import (
                QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                QTabWidget, QStatusBar, QMenuBar, QMenu, QPushButton, QLabel, 
                QProgressBar, QGroupBox, QTextEdit, QDoubleSpinBox, QComboBox, 
                QGridLayout, QFrame, QSpinBox, QTableWidget, QTableWidgetItem,
                QHeaderView, QToolBar, QFileDialog, QMessageBox, QSlider, QSplitter,
                QLineEdit, QDialog, QDialogButtonBox, QCheckBox, QStackedWidget,
                QButtonGroup, QPlainTextEdit, QListWidget, QListWidgetItem, QSplashScreen,
                QSizePolicy, QScrollArea, QToolButton
            )
            from PySide6.QtCore import QTimer, QThread, QObject, Signal as pyqtSignal, Slot as pyqtSlot, Qt, QSize, QCoreApplication
            from PySide6.QtGui import QAction, QImage, QPixmap, QIcon
            PYSIDE = True
            PYQT = False
        except ImportError:
            raise ImportError("No Qt6 binding (PyQt6 or PySide6) found.")

# Post-import safety path enforcement
if platform.system() == "Darwin":
    p = os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH")
    if p:
        QCoreApplication.addLibraryPath(p)
