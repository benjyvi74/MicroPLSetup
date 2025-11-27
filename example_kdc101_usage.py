"""
Example usage of the ThorlabsKDC101 driver in the MicroPL project.

This example demonstrates how to:
1. Create and connect to a KDC101 device
2. Home the device
3. Move to specific positions
4. Control TTL output for shutter
5. Properly disconnect
"""

from micropl.hardware.factory import create_instrument
import time


def basic_example():
    """Basic usage example."""
    print("=== Basic KDC101 Example ===\n")

    # Configuration for your KDC101
    config = {
        'serial_number': '27500125',  # Replace with your device serial number
        'kinesis_path': r"C:\Program Files\Thorlabs\Kinesis",  # Default path
        'steps_per_rev': 1919.64186,  # For PRM1-Z8 rotation mount
        'gbox_ratio': 1.0,
        'pitch': 1.0,
    }

    # Create the device using the factory
    kdc = create_instrument('kdc101', config)

    try:
        # Connect to the device
        print("Connecting to KDC101...")
        kdc.connect()
        print("Connected!\n")

        # Get device info
        info = kdc.get_info()
        print(f"Device Info: {info}\n")

        # Home the device
        print("Homing device...")
        kdc.home()
        print("Homing complete!\n")

        # Read current position
        position = kdc.get_position()
        print(f"Current position: {position:.2f}°\n")

        # Move to position 45°
        print("Moving to 45°...")
        kdc.move_to(45.0)
        kdc.wait_for_move()
        print(f"New position: {kdc.get_position():.2f}°\n")

        # Move relative by 90°
        print("Moving relative by 90°...")
        kdc.move_by(90.0)
        kdc.wait_for_move()
        print(f"New position: {kdc.get_position():.2f}°\n")

        # Return to home position
        print("Returning to home (0°)...")
        kdc.move_to(0.0)
        kdc.wait_for_move()
        print(f"Final position: {kdc.get_position():.2f}°\n")

    finally:
        # Always disconnect
        print("Disconnecting...")
        kdc.disconnect()
        print("Done!")


def shutter_control_example():
    """Example using TTL output for shutter control."""
    print("=== Shutter Control Example ===\n")

    config = {
        'serial_number': '27500125',
    }

    kdc = create_instrument('kdc101', config)

    try:
        kdc.connect()
        print("Connected to KDC101\n")

        # Open shutter (TTL high)
        print("Opening shutter (TTL HIGH)...")
        kdc.set_ttl_output(True)
        time.sleep(1)

        # Close shutter (TTL low)
        print("Closing shutter (TTL LOW)...")
        kdc.set_ttl_output(False)
        time.sleep(1)

        print("Shutter control complete!\n")

    finally:
        kdc.disconnect()


def context_manager_example():
    """Example using context manager (recommended)."""
    print("=== Context Manager Example ===\n")

    config = {
        'serial_number': '27500125',
    }

    # Using 'with' statement ensures proper cleanup
    with create_instrument('kdc101', config) as kdc:
        print("Connected via context manager\n")

        kdc.home()
        print("Homed\n")

        kdc.move_to(180.0)
        kdc.wait_for_move()
        print(f"Moved to: {kdc.get_position():.2f}°\n")

        # Device will automatically disconnect when exiting 'with' block
        print("Exiting context manager (auto-disconnect)\n")


def polarization_sweep_example():
    """Example: Sweep polarizer through angles for measurements."""
    print("=== Polarization Sweep Example ===\n")

    config = {
        'serial_number': '27500125',
    }

    with create_instrument('kdc101', config) as kdc:
        kdc.connect()
        kdc.home()

        # Sweep from 0 to 180 degrees in 15-degree steps
        angles = range(0, 181, 15)

        print("Starting polarization sweep...\n")

        for angle in angles:
            # Move to angle
            kdc.move_to(float(angle))
            kdc.wait_for_move()

            # Read position (verify)
            actual_pos = kdc.get_position()

            print(f"Angle: {angle}° (actual: {actual_pos:.2f}°)")

            # Here you would trigger your measurement
            # e.g., acquire spectrum, read power meter, etc.
            time.sleep(0.5)  # Simulate measurement time

        print("\nSweep complete!")


if __name__ == "__main__":
    # Run the example you want to test
    # Uncomment the one you want to run:

    basic_example()
    # shutter_control_example()
    # context_manager_example()
    # polarization_sweep_example()
