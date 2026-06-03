import sys
import os
import logging

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

try:
    from micropl.hardware.andor_camera import discover_cameras, AndorCamera
except ImportError as e:
    print(f"Error: Could not import AndorCamera. Make sure you are running from the correct directory: {e}")
    sys.exit(1)

# Disable redundant logging
logging.getLogger("micropl").setLevel(logging.WARNING)

def detailed_discovery():
    print("="*60)
    print(" ANDOR CAMERA DISCOVERY TOOL ")
    print("="*60)
    
    # Use the driver's own discovery function (module level)
    try:
        available_cameras = discover_cameras(force_refresh=True)
    except Exception as e:
        print(f"Discovery failed: {e}")
        return

    if not available_cameras:
        print("\nNo cameras found. Please check connections and power.")
        return

    print(f"\nFound {len(available_cameras)} camera(s).")

    for conn_id, info in available_cameras.items():
        print(f"\n--- Camera Connection: {conn_id} ---")
        print(f"  Reported Model:  {info.get('model', 'Unknown')}")
        print(f"  Head Model:      {info.get('head_model', 'Unknown')}")
        print(f"  Serial Number:   {info.get('serial_number', 'Unknown')}")
        print(f"  SDK Version:     {info.get('sdk_version', 'Unknown')}")
        print(f"  Camera Index:    {info.get('camera_index', 'Unknown')}")
        
        # Try to connect and get more details
        try:
            cam = AndorCamera(info)
            cam.connect()
            
            if cam.is_connected():
                # Actual sensor size
                w, h = cam.get_detector_size()
                print(f"  Actual Sensor:   {w} x {h}")
                
                # Temperature
                try:
                    t = cam.get_temperature()
                    s = cam.get_cooling_status()
                    print(f"  Temp/Status:     {t} °C ({s})")
                except:
                    pass
                
                # Speeds (SDK2)
                if info.get('sdk_version') == 2:
                    try:
                        vss = cam.get_vss_speeds()
                        print(f"  VSS periods:     {vss} us")
                        hss = cam.get_hss_speeds()
                        print(f"  HSS freqs:       {hss} MHz")
                    except:
                        pass
                
                cam.disconnect()
            else:
                print("  [Could not connect for deeper query]")
        except Exception as e:
            print(f"  [Error during deep query: {e}]")

    print("\n" + "="*60)
    print("Discovery complete.")
    print("="*60)

if __name__ == "__main__":
    detailed_discovery()
