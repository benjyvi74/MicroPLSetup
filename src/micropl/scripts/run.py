# Standard imports
import logging
import os
import sys
from pathlib import Path

# Ensure project root / src is in sys.path for both initial run and re-execution
script_path = Path(__file__).resolve()
# path: src/micropl/scripts/run.py -> Parent1: scripts, Parent2: micropl, Parent3: src, Parent4: Root
project_root = script_path.parent.parent.parent.parent
src_path = str(project_root / "src")

if src_path not in sys.path:
    sys.path.insert(0, src_path)

# Ensure it's and in PYTHONPATH for child processes (re-execution)
os.environ["PYTHONPATH"] = src_path + os.pathsep + os.environ.get("PYTHONPATH", "")

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
