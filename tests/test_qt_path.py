import os
import sys

# Try to find PyQt6
try:
    import PyQt6
    base_path = os.path.dirname(PyQt6.__file__)
    plugins_path = os.path.join(base_path, "Qt6", "plugins")
    platforms_path = os.path.join(plugins_path, "platforms")
    
    print(f"Base: {base_path}")
    print(f"Plugins path exists: {os.path.exists(plugins_path)}")
    print(f"Platforms path exists: {os.path.exists(platforms_path)}")
    
    # Try setting the environment variable to the platforms folder itself
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = platforms_path
    
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    print("SUCCESS: Plugin loaded!")
except Exception as e:
    print(f"FAILED: {e}")
    import traceback
    traceback.print_exc()
