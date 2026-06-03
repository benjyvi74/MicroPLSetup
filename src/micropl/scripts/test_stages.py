
import time
import logging
from pylablib.devices import Thorlabs

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_kdc101_connectivity():
    print("\n=== Thorlabs KDC101 Diagnostic Tool ===")
    
    # 1. List all detected devices
    try:
        devices = Thorlabs.list_kinesis_devices()
        print(f"\n1. Detected Kinesis Devices: {devices}")
        if not devices:
            print("   WARNING: No Thorlabs Kinesis devices detected. Check USB/Power.")
    except Exception as e:
        print(f"   ERROR listing devices: {e}")

    # 2. Test specific serial numbers from config
    target_serials = ["27271950", "27272895"]
    
    for sn in target_serials:
        print(f"\n--- Testing SN: {sn} ---")
        try:
            # Try to connect with 'stage' scaling
            print(f"Connecting to {sn}...")
            dev = Thorlabs.KinesisMotor(sn, scale="stage")
            
            # Read position
            pos = dev.get_position()
            print(f"   SUCCESS! Connected to {sn}")
            print(f"   Current Position: {pos}")
            
            # Close
            dev.close()
            print(f"   Closed {sn}")
        except Exception as e:
            print(f"   FAILED to connect to {sn}: {e}")

if __name__ == "__main__":
    test_kdc101_connectivity()
