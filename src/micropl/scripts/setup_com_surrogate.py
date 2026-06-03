import sys
import os

try:
    import winreg
except ImportError:
    print("This script must be run on Windows.")
    sys.exit(1)

def setup_surrogate(prog_id):
    try:
        # Find CLSID from ProgID (in 32-bit registry view)
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id + r"\CLSID", 0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as key:
            clsid, _ = winreg.QueryValueEx(key, "")
            print(f"[{prog_id}] Found CLSID: {clsid}")
            
        # 1. Add 'AppID' value to the CLSID key in the 32-bit registry
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}", 0, winreg.KEY_ALL_ACCESS | winreg.KEY_WOW64_32KEY) as key:
            winreg.SetValueEx(key, "AppID", 0, winreg.REG_SZ, clsid)
            print(f"[{prog_id}] Added AppID to CLSID registry key.")
            
        # 2. Create the AppID key in the 32-bit registry with an empty 'DllSurrogate' value
        # An empty string tells Windows to use the default 'dllhost.exe'
        with winreg.CreateKeyEx(winreg.HKEY_CLASSES_ROOT, rf"AppID\{clsid}", 0, winreg.KEY_ALL_ACCESS | winreg.KEY_WOW64_32KEY) as key:
            winreg.SetValueEx(key, "DllSurrogate", 0, winreg.REG_SZ, "")
            print(f"[{prog_id}] Created AppID key with DllSurrogate in 32-bit registry.")
            
        # 3. Create the AppID key in the 64-bit registry (so 64-bit Python finds the surrogate hook)
        with winreg.CreateKeyEx(winreg.HKEY_CLASSES_ROOT, rf"AppID\{clsid}", 0, winreg.KEY_ALL_ACCESS | winreg.KEY_WOW64_64KEY) as key:
            winreg.SetValueEx(key, "DllSurrogate", 0, winreg.REG_SZ, "")
            print(f"[{prog_id}] Created AppID key with DllSurrogate in 64-bit registry.")
            
        print(f"SUCCESS: COM Surrogate fully configured for {prog_id}.\n")
        
    except PermissionError:
        print(f"FAILED: Permission denied. You must run this script as an Administrator!\n")
    except Exception as e:
        print(f"FAILED to configure {prog_id}: {e}\n")

if __name__ == "__main__":
    print("=== Jobin Yvon 64-bit COM Surrogate Setup ===")
    print("This script configures Windows to run the 32-bit HORIBA SDK")
    print("inside a dllhost.exe surrogate so that 64-bit Python can use it.\n")
    
    # We must configure the surrogate for both the Monochromator class and the Browser component
    setup_surrogate("JYMono.Monochromator")
    setup_surrogate("JYConfigBrowserComponent.JYConfigBrowerInterface")
    
    print("Setup complete. If there were no errors, you can now use 64-bit Python.")
