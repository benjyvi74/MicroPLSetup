# Standard imports
import logging
import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent.parent
if str(project_root / "src") not in sys.path:
    sys.path.insert(0, str(project_root / "src"))

from micropl.gui.main import main

if __name__ == '__main__':
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('micropl.log')
        ]
    )

    logger = logging.getLogger(__name__)
    logger.info("Starting MicroPL application")

    # Run GUI
    try:
        main()
    except Exception as e:
        logger.error(f"Application crashed: {e}", exc_info=True)
        sys.exit(1)
