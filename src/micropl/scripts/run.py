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

# 1. CRITICAL: Trigger the macOS Qt environment fix before ANYTHING else.
# This may re-execute the script, and we want it to happen as cleanly as possible.
from micropl.qt import QApplication

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

    # 1. IMMEDIATELY create Application and Splash Screen
    # We do this before importing the rest of the app to avoid the 2-3s module import delay
    # 1. Initialize Qt and the Splash Screen immediately
    # We already imported QApplication at the top of the file
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # Modern look
    
    from micropl.gui.splash import MicroPLSplash
    
    import time
    logger.info("Initializing Splash Screen...")
    splash = MicroPLSplash()
    splash.show()
    
    # Force macOS to bring it to the front and map it
    splash.raise_()
    splash.activateWindow()
    
    app.processEvents()
    
    logger.info("Splash Screen shown, starting module load...")
    
    splash.set_progress(5, "Loading Application Framework & Hardware Drivers...")

    from micropl.qt import QTimer
    
    # 2. Wait for the event loop to start, then perform heavy imports
    # By yielding back to the main Qt event loop (app.exec()) between EVERY heavy import,
    # we completely prevent macOS WindowServer from deciding our app is unresponsive.
    _main_window = None
    
    def load_step_1():
        splash.set_progress(10, "Loading Hardware Manager (Pylablib, PySerial, etc)...")
        import micropl.hardware.manager
        QTimer.singleShot(100, load_step_2)
        
    def load_step_2():
        splash.set_progress(15, "Loading Camera Components (Andor SDK)...")
        import micropl.hardware.andor_camera
        QTimer.singleShot(100, load_step_3)
        
    def load_step_3():
        splash.set_progress(20, "Loading Automation UI (NumPy, SciPy)...")
        import micropl.gui.automation_panel
        QTimer.singleShot(100, load_step_4)
        
    def load_step_4():
        splash.set_progress(25, "Loading Measurement UI (PyQtGraph)...")
        import micropl.gui.measurement_panel
        QTimer.singleShot(100, load_step_5)
        
    def load_step_5():
        splash.set_progress(30, "Loading Live View...")
        import micropl.gui.live_view
        QTimer.singleShot(100, load_step_6)
        
    def load_step_6():
        splash.set_progress(35, "Loading Control Panels...")
        import micropl.gui.monochromator_panel
        import micropl.gui.powermeter_panel
        import micropl.gui.polarizer_panel
        import micropl.gui.stage_panel
        QTimer.singleShot(100, load_step_7)
        
    def load_step_7():
        global _main_window
        splash.set_progress(40, "Building Main Window...")
        try:
            from micropl.gui.main import main
            _main_window = main(app, splash)
        except Exception as e:
            logger.error(f"Application crashed during load: {e}", exc_info=True)
            app.quit()
            
    QTimer.singleShot(1000, load_step_1)
    
    # 3. Start the event loop immediately to render the splash screen
    sys.exit(app.exec())
