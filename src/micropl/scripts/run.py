"""
Entry point script for running MicroPL application.

Usage:
    python -m micropl.scripts.run
"""

import sys
import logging
from pathlib import Path

# Add parent directory to path if needed
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

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
    main()
