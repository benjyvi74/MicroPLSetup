"""
Test script for hardware drivers using pylablib.
This script attempts to connect to the KDC101 and Andor Camera.
"""

import logging
import sys
import time
from micropl.hardware.kdc101 import ThorlabsKDC101
from micropl.hardware.andor_camera import AndorCamera

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
        
        # Home
        # kdc.home() # Commented out to avoid long wait if not needed for basic test
        
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

def test_andor():
    logger.info("\nTesting Andor Camera...")
    try:
        # Initialize
        cam = AndorCamera(config={'model': 'DU420A-BR-DD', 'exposure_time': 0.05})
        logger.info(f"Initialized Andor Camera: {cam.model}")
        
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
        logger.error(f"Andor Camera Test Failed: {e}")

if __name__ == "__main__":
    logger.info("Starting Hardware Tests (pylablib)")
    
    test_kdc101()
    test_andor()
    
    logger.info("Tests Completed")
