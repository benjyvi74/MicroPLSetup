import sys
import os
import subprocess

def is_venv():
    return sys.prefix != sys.base_prefix

if sys.platform == "darwin" and is_venv() and "STUFF_REEXECUTED" not in os.environ:
    print("Detected macOS Venv. Attempting re-execution with system Python...")
    
    # Get the venv site-packages
    import site
    venv_site = site.getsitepackages()[0]
    
    # Setup environment
    new_env = os.environ.copy()
    new_env["PYTHONPATH"] = venv_site
    new_env["STUFF_REEXECUTED"] = "1"
    
    # Run using system python
    args = ["/usr/bin/python3"] + sys.argv
    subprocess.run(args, env=new_env)
    sys.exit(0)

print(f"Running on: {sys.executable}")
print(f"Prefix: {sys.prefix}")

try:
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    print("SUCCESS: GUI initialized!")
except ImportError as e:
    print(f"Import error: {e}")
except Exception as e:
    print(f"Error: {e}")
