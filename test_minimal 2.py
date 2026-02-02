
import sys
from PySide6 import QtWidgets, QtCore
from PySide6.QtCore import QLibraryInfo

print(f"PluginsPath: {QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)}")
print(f"LibraryPaths before app: {QtCore.QCoreApplication.libraryPaths()}")

# Force add the path we know exists
known_path = "/Users/benjy/Desktop/PhD/0-Code/MicroPLSetup/.venv/lib/python3.11/site-packages/PySide6/Qt/plugins"
QtCore.QCoreApplication.addLibraryPath(known_path)

print(f"LibraryPaths after add: {QtCore.QCoreApplication.libraryPaths()}")

try:
    app = QtWidgets.QApplication(sys.argv)
    print("QApplication created successfully!")
except Exception as e:
    print(f"Failed to create QApplication: {e}")
    sys.exit(1)
