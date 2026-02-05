import sys
import os
import platform
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("HardwareCheck")

def check_python():
    print(f"--- Environment Info ---")
    print(f"OS: {platform.system()} {platform.release()}")
    print(f"Python: {sys.version}")
    print(f"Executable: {sys.executable}")
    print("")

def check_pylablib():
    print(f"--- Pylablib Info ---")
    try:
        import pylablib
        print(f"pylablib version: {pylablib.__version__}")
        
        # Check backends
        from pylablib.core.devio import comm_backend
        backends = comm_backend.get_available_backends()
        print(f"Available backends: {backends}")
        
        if 'visa' not in backends:
            print("WARNING: 'visa' backend not found. For Thorlabs PM100, NI VISA is recommended.")
    except ImportError:
        print("ERROR: pylablib not installed.")
    except Exception as e:
        print(f"ERROR checking pylablib: {e}")
    print("")

def list_kinesis_devices():
    print(f"--- Thorlabs Kinesis Devices ---")
    try:
        from pylablib.devices import Thorlabs
        devices = Thorlabs.list_kinesis_devices()
        if not devices:
            print("No Kinesis devices found.")
        for dev in devices:
            print(f"  {dev}")
    except Exception as e:
        print(f"Error listing Kinesis devices: {e}")
    print("")

def list_serial_ports():
    print(f"--- Serial (COM) Ports ---")
    try:
        import serial.tools.list_ports
        ports = serial.tools.list_ports.comports()
        if not ports:
            print("No serial ports found.")
        for port in ports:
            print(f"  {port.device}: {port.description}")
    except ImportError:
        print("ERROR: pyserial not installed.")
    except Exception as e:
        print(f"Error listing serial ports: {e}")
    print("")

def check_andor_sdk():
    print(f"--- Andor SDK Discovery ---")
    if platform.system() != "Windows":
        print("Skipping Andor SDK check (not on Windows).")
        return

    search_dirs = [
        os.path.join(os.environ.get("PROGRAMFILES", "C:\\Program Files"), "Andor SDK"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"), "Andor SDK"),
        os.path.join(os.environ.get("PROGRAMFILES", "C:\\Program Files"), "Andor Solis"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"), "Andor Solis"),
        os.path.join(os.environ.get("PROGRAMFILES", "C:\\Program Files"), "Andor Solis", "Drivers"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"), "Andor Solis", "Drivers"),
        "C:\\Andor SDK",
        "C:\\Andor Solis",
        "C:\\Andor Solis\\Drivers"
    ]
    
    found_any = False
    for path in search_dirs:
        if os.path.exists(path):
            print(f"Found candidate directory: {path}")
            try:
                files = os.listdir(path)
                dlls = [f for f in files if f.lower().endswith(".dll")]
                if dlls:
                    print(f"  Contains {len(dlls)} DLLs (e.g., {', '.join(dlls[:3])}...)")
                    found_any = True
                else:
                    print(f"  No DLLs found in this directory.")
            except Exception as e:
                print(f"  Error reading directory: {e}")
    
    if not found_any:
        print("WARNING: No Andor SDK or Solis directories found in standard locations.")
    print("")

def check_pm100():
    print(f"--- Thorlabs PM100 Check ---")
    try:
        from pylablib.devices import Thorlabs
        print("Thorlabs.PM100 class found.")
    except Exception as e:
        print(f"Error checking PM100: {e}")
    print("")

if __name__ == "__main__":
    check_python()
    check_pylablib()
    list_serial_ports()
    list_kinesis_devices()
    check_andor_sdk()
    check_pm100()
    print("--- End of Report ---")
