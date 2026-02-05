import os
import sys
import logging
import time
import numpy as np
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from micropl.hardware.andor_camera import AndorCamera

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("CoolingTest")

def run_cooling_test(camera_index, role_name, target_temp):
    print("\n" + "="*60)
    print(f" TESTING {role_name} (Index {camera_index})")
    print(f" Target Temperature: {target_temp}°C")
    print("="*60)
    
    config = {
        'camera_index': camera_index,
        'sdk_version': 2,
        'temperature': target_temp,
        'fan_mode': 'full'
    }
    
    cam = None
    try:
        print(f"[*] Connecting to {role_name}...")
        cam = AndorCamera(config)
        cam.connect()
        
        info = cam.get_info()
        model = info.get('model', 'Unknown')
        serial = info.get('serial_number', 'N/A')
        print(f"[+] Connected: {model} (S/N: {serial})")
        
        print(f"[*] Engaging Cooling Engine...")
        cam.set_temperature(target_temp)
        # We explicitly verify the thermal state in a loop
        
        print("\nMonitoring Cooling Progression (30 seconds):")
        print(f"{'Time (s)':<10} | {'Temp (°C)':<15} | {'SDK Status':<20}")
        print("-" * 50)
        
        start_time = time.time()
        initial_temp = cam.get_temperature()
        
        for i in range(15): # 30 seconds total, 2s intervals
            current_temp = cam.get_temperature()
            status = cam.get_cooling_status()
            elapsed = time.time() - start_time
            
            print(f"{elapsed:<10.1f} | {current_temp:<15.2f} | {status:<20}")
            
            if i == 0:
                initial_temp = current_temp
                
            time.sleep(2)
            
        final_temp = cam.get_temperature()
        change = initial_temp - final_temp
        
        print("-" * 50)
        if change > 0.5:
            print(f"[SUCCESS] Temperature decreased by {change:.1f}°C in 30s.")
        elif np.isnan(final_temp):
            print("[FAILURE] No numeric temperature reading obtained.")
        else:
            print("[WARNING] Temperature is static. Hardware may be at limit or cooler is struggling.")
            
    except Exception as e:
        print(f"[ERROR] Test failed: {e}")
    finally:
        if cam:
            print(f"[*] Disconnecting...")
            cam.disconnect()
            print("[+] Done.")

if __name__ == "__main__":
    print("ANDOR HARDWARE THERMAL VALIDATION TEST")
    
    # 1. Test Spectrometer (iDus)
    run_cooling_test(1, "Spectrometer", -70)
    
    # 2. Test Visualisation (Luca)
    print("\n" + "-"*30)
    run_cooling_test(0, "Visualisation", -20)
    
    print("\nAll tests concluded.")
