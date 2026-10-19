import time
import logging
import traceback
from micropl.hardware.horiba_sdk import HoribaSDKMonochromator

# Set logging level for the horiba_sdk module to see the internal logs
logging.basicConfig(level=logging.INFO)

def test_horiba_sdk(target_id: str = "Mono2"):
    print(f"\n=== Horiba iHR320 SDK Diagnostic Tool (Targeting '{target_id}') ===")
    
    # 1. Discover devices
    try:
        print("\n1. Discovering devices...")
        devices = HoribaSDKMonochromator.discover()
        if not devices:
            print("   WARNING: No monochromators found. Check SDK registration and USB connection.")
            return
        for unique_id, model_name in devices:
            print(f"   - Found unique_id '{unique_id}' (Model: '{model_name}')")
    except Exception as e:
        print(f"   ERROR during discovery: {e}")
        print(f"   Traceback:\n{traceback.format_exc()}")
        return

    # 2. Connect
    print(f"\n2. Connecting to device with unique_id='{target_id}'...")
    try:
        # Pass explicit unique_id (default Mono2)
        # Note: force_init=False is recommended to speed up the test if already homed.
        mono = HoribaSDKMonochromator(config={"unique_id": target_id, "force_init": False})
        mono.connect()
        print("   SUCCESS! Connected.")
    except Exception as e:
        print(f"   ERROR during connection: {e}")
        print(f"   Traceback:\n{traceback.format_exc()}")
        return

    # 3. Read info
    print("\n3. Reading current state...")
    try:
        info = mono.get_info()
        print(f"   Info: {info}")
        current_wl = mono.get_current_wavelength()
        print(f"   Current Wavelength: {current_wl:.2f} nm")
        current_grating = mono.get_grating(force_read=True)
        print(f"   Current Grating Index: {current_grating}")
        for i, name in enumerate(["Front Entrance", "Side Entrance", "Front Exit", "Side Exit"]):
            w = mono.get_slit_width(i)
            print(f"   Slit {i} ({name}): {w:.1f} um")
    except Exception as e:
        print(f"   ERROR reading state: {e}")
        print(f"   Traceback:\n{traceback.format_exc()}")

    # 4. Test movements
    print("\n4. Testing hardware movements...")
    try:
        # Wavelength movement
        target_wl = current_wl + 1.0 if current_wl else 500.0
        print(f"\n   --- Moving wavelength from {current_wl:.2f} nm to {target_wl:.2f} nm ---")
        mono.set_center_wavelength(target_wl)
        new_wl = mono.get_current_wavelength()
        print(f"   Reached Wavelength: {new_wl:.2f} nm")
        
        # Test slits
        print("\n   --- Testing Slit Control ---")
        print("   Setting Front Entrance Slit (0) to 150 um...")
        mono.set_slit_width(150.0, 0)
        print(f"   New Slit 0 width: {mono.get_slit_width(0):.1f} um")
        
        # Test mirrors
        print("\n   --- Testing Mirror Control ---")
        print("   Moving entrance mirror to side (lateral)...")
        mono.set_mirror(port="entrance", position="side")
        time.sleep(1) # Pause to let mechanical movement finish fully before next command
        print("   Moving entrance mirror back to front (direct)...")
        mono.set_mirror(port="entrance", position="direct")
        
        # Note on grating: 
        # Grating changes involve physical turret rotation which takes ~15-30s. 
        # You can uncomment this block to test it, but it's slow.
        """
        print("\n   --- Testing Grating Turret ---")
        target_grating = 1 if current_grating == 0 else 0
        print(f"   Changing grating from index {current_grating} to {target_grating}...")
        mono.set_grating(target_grating)
        print(f"   New Grating Index: {mono.get_grating()}")
        """
        
    except Exception as e:
        print(f"   ERROR during hardware movement: {e}")
        print(f"   Traceback:\n{traceback.format_exc()}")

    # 5. Disconnect
    print("\n5. Disconnecting...")
    try:
        mono.disconnect()
        print("   Disconnected successfully.")
    except Exception as e:
        print(f"   ERROR during disconnect: {e}")
        print(f"   Traceback:\n{traceback.format_exc()}")

if __name__ == "__main__":
    import sys
    target_id = sys.argv[1] if len(sys.argv) > 1 else "Mono2"
    test_horiba_sdk(target_id)
