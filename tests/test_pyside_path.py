import os
import sys
import shutil
from pathlib import Path

# --- Mac GUI Fix (Self-Re-Executing with os.execv) ---
if sys.platform == "darwin" and "MICROPL_FIXED" not in os.environ:
    try:
        import importlib.util
        spec = importlib.util.find_spec("PySide6")
        if spec and spec.submodule_search_locations:
            pyside_path = Path(spec.submodule_search_locations[0])
            qdir = pyside_path / "Qt" / "plugins"
            
            if qdir.exists() and (" " in str(qdir) or " " in sys.executable):
                print(f"Space detected in path. Attempting clean re-execution fix...")
                
                proxy_dir = Path("/tmp/qtplugins_clean")
                proxy_platforms = proxy_dir / "platforms"
                
                if proxy_dir.exists():
                    shutil.rmtree(proxy_dir, ignore_errors=True)
                proxy_platforms.mkdir(parents=True, exist_ok=True)
                
                # Copy ALL plugins in the platforms folder
                platforms_path = qdir / "platforms"
                for item in platforms_path.glob("*.dylib"):
                    shutil.copy2(item, proxy_platforms / item.name)
                
                # Setup environment for re-execution
                os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(proxy_platforms)
                os.environ["MICROPL_FIXED"] = "1"
                os.environ["QT_DEBUG_PLUGINS"] = "1"
                
                # RE-EXECUTE (replaces current process)
                print(f"Execv-ing with QT_QPA_PLATFORM_PLUGIN_PATH={proxy_platforms}")
                sys.stdout.flush()
                os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        print(f"Fix failed: {e}")
# ----------------------------------------

try:
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    print("SUCCESS: Plugin loaded and App initialized!")
except Exception as e:
    print(f"FINAL FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
