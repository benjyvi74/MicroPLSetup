"""
Hardware integration test for Horiba FHR640 serial connection.
Run this script on the Windows machine with the spectrometer connected via Null-Modem cable.
"""

import logging
import time
import sys
from micropl.hardware.horiba_serial import HoribaSerialMonochromator

# Configure logging to see the communication details
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def run_fhr640_test(port='COM1'):
    config = {
        'port': port,
        'baudrate': 19200,
        'center_wavelength': 500.0
    }
    
    logger.info(f"--- Starting FHR640 Serial Test on {port} ---")
    fhr = HoribaSerialMonochromator(config)
    
    try:
        # 1. Connect and initialize
        logger.info("Connecting to hardware...")
        fhr.connect()
        logger.info("Connection established.")
        
        # 2. Get info
        info = fhr.get_info()
        logger.info(f"Device Info: {info}")
        
        # 3. Read current wavelength
        curr_wl = fhr.get_current_wavelength()
        logger.info(f"Currently at {curr_wl:.3f} nm")
        
        # 4. Small movement test
        target_wl = curr_wl + 5.0
        logger.info(f"Testing movement: Moving to {target_wl:.3f} nm...")
        fhr.set_center_wavelength(target_wl)
        new_wl = fhr.get_current_wavelength()
        logger.info(f"Movement complete. Actual position: {new_wl:.3f} nm")
        
        # 5. Slit test (entrance slit)
        logger.info("Testing slit: Setting entrance slit (0) to 100 steps...")
        fhr.set_slit_width(100, slit_id=0)
        logger.info("Slit set.")

        # 6. Grating test (Optional - be careful if you don't know your grating indices!)
        # logger.info("Testing grating: Selecting grating index 0...")
        # fhr.set_grating(0)
        # logger.info("Grating switch complete.")

        logger.info("\n--- TEST COMPLETED SUCCESSFULLY ---")
        
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
    finally:
        fhr.disconnect()
        logger.info("Disconnected from hardware.")

if __name__ == "__main__":
    # Change 'COM1' to whatever your USB-to-Serial adapter shows up as in Device Manager
    com_port = 'COM1'
    
    if len(sys.argv) > 1:
        com_port = sys.argv[1]
        
    run_fhr640_test(com_port)
