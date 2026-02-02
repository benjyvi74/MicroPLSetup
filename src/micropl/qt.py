"""
Qt compatibility layer to support both PySide6 and PyQt6.
This project uses this layer to resolve macOS-specific crashes with PyQt6 in venvs.
"""

import sys
import logging

logger = logging.getLogger(__name__)

# Preferred: PyQt6 (matches DataTreatment config)
# Fallback: PySide6
try:
    from PyQt6 import QtWidgets, QtCore, QtGui
    from PyQt6.QtCore import pyqtSignal, pyqtSlot, Qt
    from PyQt6.QtGui import QAction
    PYSIDE = False
    PYQT = True
except ImportError:
    try:
        from PySide6 import QtWidgets, QtCore, QtGui
        from PySide6.QtCore import Signal as pyqtSignal, Slot as pyqtSlot, Qt
        from PySide6.QtGui import QAction
        PYSIDE = True
        PYQT = False
    except ImportError:
        raise ImportError("No Qt6 binding (PyQt6 or PySide6) found.")

# Export common classes to the top level for convenience
if PYSIDE:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
        QTabWidget, QStatusBar, QMenuBar, QMenu, QPushButton, QLabel, 
        QProgressBar, QGroupBox, QTextEdit, QDoubleSpinBox, QComboBox, 
        QGridLayout, QFrame, QSpinBox, QTableWidget, QTableWidgetItem,
        QHeaderView, QToolBar, QFileDialog, QMessageBox, QSlider, QSplitter,
        QLineEdit, QDialog, QDialogButtonBox, QCheckBox, QStackedWidget
    )
    from PySide6.QtCore import QTimer, Signal as pyqtSignal, Slot as pyqtSlot, Qt
    from PySide6.QtGui import QAction, QImage, QPixmap
else:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
        QTabWidget, QStatusBar, QMenuBar, QMenu, QPushButton, QLabel, 
        QProgressBar, QGroupBox, QTextEdit, QDoubleSpinBox, QComboBox, 
        QGridLayout, QFrame, QSpinBox, QTableWidget, QTableWidgetItem,
        QHeaderView, QToolBar, QFileDialog, QMessageBox, QSlider, QSplitter,
        QLineEdit, QDialog, QDialogButtonBox, QCheckBox, QStackedWidget
    )
    from PyQt6.QtCore import QTimer, pyqtSignal, pyqtSlot, Qt
    from PyQt6.QtGui import QAction, QImage, QPixmap

# Manual top-level exports for common usage (redundant but helpful for some IDEs)
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
QMenu = QtWidgets.QMenu
QDialog = QtWidgets.QDialog
QDialogButtonBox = QtWidgets.QDialogButtonBox
QCheckBox = QtWidgets.QCheckBox
QSpinBox = QtWidgets.QSpinBox
QStackedWidget = QtWidgets.QStackedWidget
