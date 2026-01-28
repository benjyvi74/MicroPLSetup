"""
Test script for hardware drivers using pylablib.
This script attempts to connect to the KDC101, Andor Camera, and PM100.
"""

import logging
import sys
import time
from micropl.hardware.kdc101 import ThorlabsKDC101
from micropl.hardware.andor_camera import AndorCamera
from micropl.hardware.pm100 import PM100

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_kdc101():
    logger.info("Testing KDC101...")
    try:
        # Initialize
        kdc = ThorlabsKDC101(config={'serial_number': '27500125'})
        logger.info(f"Initialized KDC101 with SN: {kdc.serial_number}")
        
        # Connect
        kdc.connect()
        logger.info("Connected to KDC101")
        
        # Get info
        info = kdc.get_info()
        logger.info(f"Device Info: {info}")
        
        # Move
        current_pos = kdc.get_position()
        logger.info(f"Current Position: {current_pos}")
        
        target = current_pos + 10
        logger.info(f"Moving to {target}...")
        kdc.move_to(target)
        kdc.wait_for_move()
        
        new_pos = kdc.get_position()
        logger.info(f"New Position: {new_pos}")
        
        kdc.disconnect()
        logger.info("Disconnected from KDC101")
        
    except Exception as e:
        logger.error(f"KDC101 Test Failed: {e}")

def test_andor(sdk_version=2):
    logger.info(f"\nTesting Andor Camera (SDK{sdk_version})...")
    try:
        # Initialize
        cam = AndorCamera(config={'model': 'DU420A-BR-DD', 'exposure_time': 0.05, 'sdk_version': sdk_version})
        logger.info(f"Initialized Andor Camera (SDK{sdk_version}): {cam.model}")
        
        # Connect
        cam.connect()
        logger.info("Connected to Andor Camera")
        
        # Get info
        info = cam.get_info()
        logger.info(f"Camera Info: {info}")
        
        # Acquire image
        img = cam.acquire_image()
        logger.info(f"Acquired image with shape: {img.shape}, mean: {img.mean()}")
        
        cam.disconnect()
        logger.info("Disconnected from Andor Camera")
        
    except Exception as e:
        logger.error(f"Andor Camera (SDK{sdk_version}) Test Failed: {e}")

def test_pm100():
    logger.info("\nTesting PM100 Power Meter...")
    try:
        # Replace with your actual VISA address on Windows
        visa_address = 'USB0::0x1313::0x807B::400000::INSTR'
        pm = PM100(config={'port': visa_address, 'wavelength': 532})
        logger.info(f"Initialized PM100 at {visa_address}")

        # Connect
        pm.connect()
        logger.info("Connected to PM100")

        # Get info
        info = pm.get_info()
        logger.info(f"Power Meter Info: {info}")

        # Read power
        power = pm.read_power()
        logger.info(f"Current Power: {power:.6e} W")

        # Change wavelength
        pm.set_wavelength(633)
        logger.info(f"New Wavelength: {pm.get_wavelength()} nm")

        pm.disconnect()
        logger.info("Disconnected from PM100")

    except Exception as e:
        logger.error(f"PM100 Test Failed: {e}")

if __name__ == "__main__":
    logger.info("Starting Hardware Tests (pylablib)")
    
    # These tests will likely fail on Mac due to missing DLLs/hardware
    # but we can check if they fail gracefully or for the expected reasons.
    
    test_kdc101()
    test_andor(sdk_version=2)
    test_andor(sdk_version=3)
    test_pm100()
    
    logger.info("\nTests Completed")

