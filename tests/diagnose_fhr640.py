"""
Diagnostic script for Horiba FHR640 Serial.
Tries multiple command variants to see what the hardware responds to.
"""
import serial
import time
import sys

def test_port(port, baudrate=19200):
    print(f"--- Opening {port} at {baudrate} baud ---")
    try:
        ser = serial.Serial(port, baudrate, timeout=2.0)
    except Exception as e:
        print(f"Error opening port: {e}")
        return

    def send_raw(cmd_bytes, label):
        print(f"Testing {label}: {cmd_bytes}")
        ser.write(cmd_bytes)
        time.sleep(0.5)
        resp = ser.read_all()
        print(f"  Response: {resp}")
        return resp

    # 1. Check Autobaud
    send_raw(b' ', "Autobaud (<Space>)")
    
    # 2. Try Standard Position Read (Mono 0 and 1)
    send_raw(b'H0\r', "Standard Read Position (H0)")
    send_raw(b'H1\r', "Standard Read Position (H1)")
    
    # 3. Try TRIAX Position Read (Mono 0 and 1)
    send_raw(b'Z62,0\r', "TRIAX Read Position (Z62,0)")
    send_raw(b'Z62,1\r', "TRIAX Read Position (Z62,1)")
    
    # 4. Check Status Commands
    send_raw(b'E', "Busy Check (E)")
    send_raw(b'l', "Accessory Busy Check (lowercase L)")

    # 5. Mirror Swings (Tests)
    print("\n--- Testing Mirrors ---")
    send_raw(b'd0\r', "Entrance Mirror -> Front (d0)")
    send_raw(b'c0\r', "Entrance Mirror -> Side (c0)")
    send_raw(b'f0\r', "Exit Mirror -> Front (f0)")
    send_raw(b'e0\r', "Exit Mirror -> Side (e0)")
    
    ser.close()
    print("--- Done ---")

if __name__ == "__main__":
    port = sys.argv[1] if len(sys.argv) > 1 else 'COM1'
    test_port(port)
