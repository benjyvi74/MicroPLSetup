"""
Asynchronous hardware service for de-coupling GUI from USB communication.
"""

import time
import logging
import numpy as np
from typing import Dict, Any, Optional
from ..qt import QObject, QThread, pyqtSignal, pyqtSlot, QTimer
from ..hardware.manager import HardwareManager

logger = logging.getLogger(__name__)

class HardwareWorker(QObject):
    """
    Core engine that runs in the background thread.
    Handles physical hardware polling and command execution.
    """
    # Signals for state changes
    kdc_pos_changed = pyqtSignal(float)
    kdc_status_changed = pyqtSignal(bool, bool)  # is_connected, is_moving
    shutter_changed = pyqtSignal(bool)
    
    pm_power_ready = pyqtSignal(float)
    pm_status_changed = pyqtSignal(bool, str)  # is_connected, status_message
    
    mono_pos_changed = pyqtSignal(float)
    mono_status_changed = pyqtSignal(bool)
    
    spectral_unit_changed = pyqtSignal(str)          # Sync signal for units (nm, meV)
    spectral_display_mode_changed = pyqtSignal(str)  # Sync signal for mode (Pixel, Spectral)

    def __init__(self, hardware_manager: HardwareManager):
        super().__init__()
        self.hw = hardware_manager
        self._running = True
        
        self._last_kdc_pos = None
        self._last_shutter_open = None
        self._last_pm_power = None
        self._last_mono_pos = None

    @pyqtSlot()
    def process(self):
        """Main loop for background polling (Slow devices)."""
        logger.info("Hardware worker process started")
        
        while self._running:
            try:
                self._poll_kdc()
                self._poll_pm()
                self._poll_mono()
                time.sleep(0.01)
            except Exception as e:
                logger.error(f"Error in hardware worker loop: {e}")
                time.sleep(1.0)

    def _poll_kdc(self):
        try:
            kdc = self.hw.kdc101
            if kdc:
                if not kdc._lock.acquire(blocking=False):
                    return
                try:
                    is_conn = kdc.is_connected()
                    if is_conn:
                        pos = kdc.get_position()
                        moving = kdc.is_moving()
                        shutter_open = kdc.get_shutter()
                        
                        if self._last_kdc_pos is None or abs(pos - self._last_kdc_pos) > 0.0005:
                            self.kdc_pos_changed.emit(pos)
                            self._last_kdc_pos = pos
                        
                        if self._last_shutter_open != shutter_open:
                            self.shutter_changed.emit(shutter_open)
                            self._last_shutter_open = shutter_open

                        self.kdc_status_changed.emit(True, moving)
                    else:
                        self.kdc_status_changed.emit(False, False)
                        self._last_shutter_open = None
                        self._last_kdc_pos = None
                finally:
                    kdc._lock.release()
        except Exception as e:
            logger.debug(f"KDC polling error: {e}")

    def _poll_pm(self):
        try:
            pm = self.hw.get_instrument('pm100')
            if pm:
                if not pm._lock.acquire(blocking=False):
                    return
                try:
                    if pm.is_connected():
                        try:
                            p = pm.read_power()
                            if self._last_pm_power is None or abs(p - self._last_pm_power) > abs(p * 0.001) + 1e-12:
                                self.pm_power_ready.emit(p)
                                self._last_pm_power = p
                            self.pm_status_changed.emit(True, "Connected")
                        except Exception as e:
                            err_str = str(e)
                            if "VI_ERROR_TMO" in err_str:
                                self.pm_status_changed.emit(True, "Sensor Disconnected")
                            elif "VI_ERROR_SYSTEM_ERROR" in err_str or "VI_ERROR_CONN_LOST" in err_str:
                                logger.error(f"PM100 connection lost: {e}")
                                pm.disconnect()
                                self.pm_status_changed.emit(False, "Disconnected")
                            else:
                                logger.debug(f"PM read error: {e}")
                                self.pm_status_changed.emit(True, "Connected")
                    else:
                        self.pm_status_changed.emit(False, "Disconnected")
                finally:
                    pm._lock.release()
        except Exception as e:
            logger.debug(f"PM polling error: {e}")

    def _poll_mono(self):
        try:
            mono = self.hw.mono
            if mono:
                if not mono._lock.acquire(blocking=False):
                    return
                try:
                    is_conn = mono.is_connected()
                    if is_conn:
                        pos = mono.get_current_wavelength()
                        if self._last_mono_pos is None or abs(pos - self._last_mono_pos) > 0.001:
                            self.mono_pos_changed.emit(pos)
                            self._last_mono_pos = pos
                        self.mono_status_changed.emit(True)
                    else:
                        self.mono_status_changed.emit(False)
                finally:
                    mono._lock.release()
        except Exception as e:
            logger.debug(f"Mono polling error: {e}")

    def stop(self):
        self._running = False


class CameraWorker(QObject):
    """
    Dedicated worker for high-speed camera polling.
    Runs in a separate thread per all cameras generically.
    """
    # Generic camera signals — carry camera_id so receivers can route correctly
    camera_frame_ready = pyqtSignal(str, np.ndarray)  # camera_id, frame
    camera_temp_changed = pyqtSignal(str, float, str)  # camera_id, temp, status

    def __init__(self, hardware_manager: HardwareManager):
        super().__init__()
        self.hw = hardware_manager
        self._running = True
        self._last_temp_time = 0
        self._temp_interval = 2.0  # Only poll temp every 2 seconds

    @pyqtSlot()
    def process(self):
        logger.info("Camera worker process started")
        while self._running:
            try:
                self._poll_cameras()
                time.sleep(0.001)  # 1ms sleep for maximum frame rate
            except Exception as e:
                logger.error(f"Error in camera worker loop: {e}")
                time.sleep(1.0)

    def _poll_cameras(self):
        now = time.time()
        update_temp = (now - self._last_temp_time) > self._temp_interval
        if update_temp:
            self._last_temp_time = now

        # Iterate over all cameras generically
        for cam_id, cam in self.hw.cameras.items():
            try:
                if cam and cam.is_connected():
                    if not cam._lock.acquire(blocking=False):
                        continue
                    try:
                        # 1. Temperature (rate-limited)
                        if update_temp:
                            temp = cam.get_temperature()
                            status = cam.get_cooling_status()
                            self.camera_temp_changed.emit(cam_id, temp, status)

                        # 2. Frames
                        if cam.is_acquiring():
                            frame = cam.read_newest_image()
                            if frame is not None:
                                self.camera_frame_ready.emit(cam_id, frame)
                    finally:
                        cam._lock.release()
            except Exception:
                pass  # Silently fail single poll to keep loop fast

    def stop(self):
        self._running = False


class HardwareService(QObject):
    """
    Public interface for the hardware service.
    Handles thread lifecycles and signal routing.
    """
    def __init__(self, hardware_manager: HardwareManager):
        super().__init__()
        self.hw = hardware_manager
        
        # Thread 1: General Hardware (Motors, PM, Mono)
        self.hw_thread = QThread()
        self.hw_worker = HardwareWorker(self.hw)
        self.hw_worker.moveToThread(self.hw_thread)
        self.hw_thread.started.connect(self.hw_worker.process)
        
        # Thread 2: Cameras (High Speed)
        self.cam_thread = QThread()
        self.cam_worker = CameraWorker(self.hw)
        self.cam_worker.moveToThread(self.cam_thread)
        self.cam_thread.started.connect(self.cam_worker.process)
        
        # --- Proxy signals: Hardware ---
        self.kdc_pos_changed = self.hw_worker.kdc_pos_changed
        self.kdc_status_changed = self.hw_worker.kdc_status_changed
        self.shutter_changed = self.hw_worker.shutter_changed
        self.pm_power_ready = self.hw_worker.pm_power_ready
        self.pm_status_changed = self.hw_worker.pm_status_changed
        self.mono_pos_changed = self.hw_worker.mono_pos_changed
        self.mono_status_changed = self.hw_worker.mono_status_changed
        self.spectral_unit_changed = self.hw_worker.spectral_unit_changed
        self.spectral_display_mode_changed = self.hw_worker.spectral_display_mode_changed
        
        # --- Proxy signals: Cameras (generic) ---
        self.camera_frame_ready = self.cam_worker.camera_frame_ready  # (camera_id, frame)
        self.camera_temp_changed = self.cam_worker.camera_temp_changed  # (camera_id, temp, status)

    def start(self):
        if not self.hw_thread.isRunning():
            self.hw_thread.start()
        if not self.cam_thread.isRunning():
            self.cam_thread.start()
        logger.info("Hardware services started")

    def stop(self):
        if self.hw_thread.isRunning():
            self.hw_worker.stop()
            self.hw_thread.quit()
            self.hw_thread.wait()
            
        if self.cam_thread.isRunning():
            self.cam_worker.stop()
            self.cam_thread.quit()
            self.cam_thread.wait()
            
        logger.info("Hardware services stopped")
