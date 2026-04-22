"""
Test script to connect to Andor camera and inspect available functions/attributes.
"""

import logging
import sys
import os

# Add src to path if needed
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from micropl.hardware.andor_camera import AndorCamera, discover_cameras

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_camera_functions():
    # 1. Discover
    logger.info("Discovering cameras...")
    available = discover_cameras(force_refresh=True)
    if not available:
        logger.error("No cameras found!")
        return

    cam_id = list(available.keys())[0]
    config = available[cam_id]
    logger.info(f"Targeting camera: {cam_id} ({config['model']})")

    # 2. Connect
    cam = AndorCamera(config)
    try:
        logger.info("Connecting to camera...")
        cam.connect()
        logger.info("Connected successfully.")

        # 3. Check Detector Size
        size = cam.get_detector_size()
        logger.info(f"Detector Size (via our wrapper): {size}")

        # 4. Inspect Pylablib Object
        inner_cam = cam.get_inner_cam()
        if inner_cam:
            logger.info("\n--- Pylablib Camera Object Inspection ---")
            logger.info(f"Object type: {type(inner_cam)}")
            
            # List some key methods
            methods = [m for m in dir(inner_cam) if not m.startswith('_')]
            logger.info(f"Found {len(methods)} public methods/attributes.")
            
            # Group by common prefixes
            getters = [m for m in methods if m.startswith('get_')]
            setters = [m for m in methods if m.startswith('set_')]
            setups = [m for m in methods if m.startswith('setup_')]
            
            logger.info(f"\nGetters ({len(getters)}): {getters[:10]} ...")
            logger.info(f"Setters ({len(setters)}): {setters[:10]} ...")
            logger.info(f"Setups ({len(setups)}): {setups[:10]} ...")

            # Specifically check for detector info in pylablib
            if hasattr(inner_cam, 'get_detector_size'):
                logger.info(f"Direct call inner_cam.get_detector_size(): {inner_cam.get_detector_size()}")
            
            # Detailed list of all methods for the user to see
            logger.info("\nFull method list:")
            for i in range(0, len(methods), 5):
                logger.info(", ".join(methods[i:i+5]))

    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
    finally:
        cam.disconnect()
        logger.info("Disconnected.")

if __name__ == "__main__":
    test_camera_functions()
