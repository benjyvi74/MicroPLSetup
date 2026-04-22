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

logger = logging.getLogger(__name__)

# Preferred: PyQt6
try:
    from PyQt6 import QtWidgets, QtCore, QtGui
    from PyQt6.QtCore import pyqtSignal, pyqtSlot, Qt, QCoreApplication
    from PyQt6.QtGui import QAction
    PYSIDE = False
    PYQT = True
except ImportError:
    try:
        from PySide6 import QtWidgets, QtCore, QtGui
        from PySide6.QtCore import Signal as pyqtSignal, Slot as pyqtSlot, Qt, QCoreApplication
        from PySide6.QtGui import QAction
        PYSIDE = True
        PYQT = False
    except ImportError:
        raise ImportError("No Qt6 binding (PyQt6 or PySide6) found.")

# Post-import safety path enforcement
if platform.system() == "Darwin":
    p = os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH")
    if p:
        QCoreApplication.addLibraryPath(p)

# Export common classes
if PYSIDE:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
        QTabWidget, QStatusBar, QMenuBar, QMenu, QPushButton, QLabel, 
        QProgressBar, QGroupBox, QTextEdit, QDoubleSpinBox, QComboBox, 
        QGridLayout, QFrame, QSpinBox, QTableWidget, QTableWidgetItem,
        QHeaderView, QToolBar, QFileDialog, QMessageBox, QSlider, QSplitter,
        QLineEdit, QDialog, QDialogButtonBox, QCheckBox, QStackedWidget,
        QButtonGroup, QPlainTextEdit, QListWidget, QListWidgetItem, QSplashScreen,
        QScrollArea
    )
    from PySide6.QtCore import QTimer, QThread, QObject, Signal as pyqtSignal, Slot as pyqtSlot, Qt
    from PySide6.QtGui import QAction, QImage, QPixmap
else:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
        QTabWidget, QStatusBar, QMenuBar, QMenu, QPushButton, QLabel, 
        QProgressBar, QGroupBox, QTextEdit, QDoubleSpinBox, QComboBox, 
        QGridLayout, QFrame, QSpinBox, QTableWidget, QTableWidgetItem,
        QHeaderView, QToolBar, QFileDialog, QMessageBox, QSlider, QSplitter,
        QLineEdit, QDialog, QDialogButtonBox, QCheckBox, QStackedWidget,
        QButtonGroup, QPlainTextEdit, QListWidget, QListWidgetItem, QSplashScreen,
        QScrollArea
    )
    from PyQt6.QtCore import QTimer, QThread, QObject, pyqtSignal, pyqtSlot, Qt
    from PyQt6.QtGui import QAction, QImage, QPixmap

# Manual exports
QApplication = QtWidgets.QApplication
QMainWindow = QtWidgets.QMainWindow
QWidget = QtWidgets.QWidget
QVBoxLayout = QtWidgets.QVBoxLayout
QHBoxLayout = QtWidgets.QHBoxLayout
QTabWidget = QtWidgets.QTabWidget
QStatusBar = QtWidgets.QStatusBar
QMenuBar = QtWidgets.QMenuBar
QMenu = QtWidgets.QMenu
QPushButton = QtWidgets.QPushButton
QLabel = QtWidgets.QLabel
QProgressBar = QtWidgets.QProgressBar
QGroupBox = QtWidgets.QGroupBox
QTextEdit = QtWidgets.QTextEdit
QDoubleSpinBox = QtWidgets.QDoubleSpinBox
QComboBox = QtWidgets.QComboBox
QGridLayout = QtWidgets.QGridLayout
QFrame = QtWidgets.QFrame
QTimer = QtCore.QTimer
QSpinBox = QtWidgets.QSpinBox
QTableWidget = QtWidgets.QTableWidget
QTableWidgetItem = QtWidgets.QTableWidgetItem
QHeaderView = QtWidgets.QHeaderView
QToolBar = QtWidgets.QToolBar
QFileDialog = QtWidgets.QFileDialog
QMessageBox = QtWidgets.QMessageBox
QSlider = QtWidgets.QSlider
QImage = QtGui.QImage
QPixmap = QtGui.QPixmap
QLineEdit = QtWidgets.QLineEdit
QDialog = QtWidgets.QDialog
QDialogButtonBox = QtWidgets.QDialogButtonBox
QCheckBox = QtWidgets.QCheckBox
QStackedWidget = QtWidgets.QStackedWidget
QButtonGroup = QtWidgets.QButtonGroup
QPlainTextEdit = QtWidgets.QPlainTextEdit
QSplitter = QtWidgets.QSplitter
QThread = QtCore.QThread
QObject = QtCore.QObject
QListWidget = QtWidgets.QListWidget
QListWidgetItem = QtWidgets.QListWidgetItem
QSplashScreen = QtWidgets.QSplashScreen
QSizePolicy = QtWidgets.QSizePolicy
QScrollArea = QtWidgets.QScrollArea
