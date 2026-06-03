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
    shutter_status_changed = pyqtSignal(bool) # is_connected
    
    stage_x_pos_changed = pyqtSignal(float)
    stage_x_status_changed = pyqtSignal(bool, bool)
    
    stage_y_pos_changed = pyqtSignal(float)
    stage_y_status_changed = pyqtSignal(bool, bool)
    
    pm_power_ready = pyqtSignal(float)
    pm_status_changed = pyqtSignal(bool, str)  # is_connected, status_message
    
    mono_pos_changed = pyqtSignal(float)
    mono_status_changed = pyqtSignal(bool)
    
    spectral_unit_changed = pyqtSignal(str)          # Sync signal for units (nm, meV)
    spectral_display_mode_changed = pyqtSignal(str)  # Sync signal for mode (Pixel, Spectral)
    hw_config_changed = pyqtSignal()                 # Sync signal for hardware selection changes

    def __init__(self, hardware_manager: HardwareManager):
        super().__init__()
        self.hw = hardware_manager
        self._running = True
        
        self._last_kdc_pos = None
        self._last_shutter_open = None
        self._last_stage_x_pos = None
        self._last_stage_y_pos = None
        self._last_pm_power = None
        self._last_mono_pos = None
        self._last_shutter_conn = None

    @pyqtSlot()
    def process(self):
        """Main loop for background polling (Slow devices)."""
        logger.info("Hardware worker process started")
        
        while self._running:
            try:
                self._poll_polarizer()
                self._poll_shutter()  # Dedicated shutter polling
                self._poll_stage()
                self._poll_pm()
                self._poll_mono()
                time.sleep(0.1) # 10 Hz (Serial communication is slow)
            except Exception as e:
                logger.error(f"Error in hardware worker loop: {e}")
                time.sleep(1.0)

    def _poll_polarizer(self):
        """Poll the KDC101 used as a polarizer."""
        kdc = self.hw.polarizer
        if not kdc:
            return
            
        if not kdc._lock.acquire(blocking=False):
            return
            
        try:
            is_conn = kdc.is_connected()
            if is_conn:
                pos = kdc.get_position()
                moving = kdc.is_moving()
                
                if self._last_kdc_pos is None or abs(pos - self._last_kdc_pos) > 0.0005:
                    self.kdc_pos_changed.emit(pos)
                    self._last_kdc_pos = pos
                
                self.kdc_status_changed.emit(True, moving)
            else:
                self.kdc_status_changed.emit(False, False)
                self._last_kdc_pos = None
        except Exception as e:
            logger.error(f"Polarizer KDC101 connection lost: {e}")
            try: kdc.disconnect()
            except: pass
            self.kdc_status_changed.emit(False, False)
        finally:
            kdc._lock.release()

    def _poll_shutter(self):
        """Poll the device currently acting as the system shutter."""
        shutter = self.hw.shutter
        if not shutter:
            return
            
        if not shutter._lock.acquire(blocking=False):
            return
            
        try:
            is_conn = bool(shutter.is_connected())
            if self._last_shutter_conn != is_conn:
                self.shutter_status_changed.emit(is_conn)
                self._last_shutter_conn = is_conn

            if is_conn:
                shutter_open = shutter.get_shutter()
                if self._last_shutter_open != shutter_open:
                    self.shutter_changed.emit(shutter_open)
                    self._last_shutter_open = shutter_open
        except:
            pass
        finally:
            shutter._lock.release()

    def _poll_stage(self):
        """Poll the XY stage motors."""
        # 1. Stage X
        self._poll_generic_motor(
            self.hw.stage_x, 
            self.stage_x_pos_changed, self.stage_x_status_changed,
            '_last_stage_x_pos'
        )
        # 2. Stage Y
        self._poll_generic_motor(
            self.hw.stage_y, 
            self.stage_y_pos_changed, self.stage_y_status_changed,
            '_last_stage_y_pos'
        )

    def _poll_generic_motor(self, motor, signal_pos, signal_status, last_pos_attr):
        """
        Generic polling for any motor instrument.
        
        Implements a state-tracking and error-debouncing mechanism:
        1. Only emits signals to the UI if the position has meaningfully changed (reduces event spam).
        2. Maintains an error counter to ignore transient serial dropouts, only emitting 
           a 'disconnected' signal if the error persists for several cycles.
        """
        if not motor:
            return
            
        if not motor._lock.acquire(blocking=False):
            return
            
        # Error counter attribute name
        err_attr = f"{last_pos_attr}_err_count"
        if not hasattr(self, err_attr):
            setattr(self, err_attr, 0)

        try:
            is_conn = motor.is_connected()
            if is_conn:
                pos = motor.get_position()
                moving = motor.is_moving()
                
                last_pos = getattr(self, last_pos_attr)
                if last_pos is None or abs(pos - last_pos) > 0.0005:
                    signal_pos.emit(pos)
                    setattr(self, last_pos_attr, pos)
                
                signal_status.emit(True, moving)
                setattr(self, err_attr, 0) # Reset error count on success
            else:
                signal_status.emit(False, False)
                setattr(self, last_pos_attr, None)
        except Exception as e:
            err_count = getattr(self, err_attr) + 1
            setattr(self, err_attr, err_count)
            
            # Log as debug unless it persists
            if err_count < 3:
                logger.debug(f"Transient motor polling error ({err_count}): {e}")
            else:
                logger.warning(f"Persistent motor polling error: {e}")
                signal_status.emit(False, False)
                setattr(self, last_pos_attr, None)
        finally:
            motor._lock.release()

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
                                logger.error(f"Thorlabs PM100 connection lost: {e}")
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
        mono = self.hw.mono
        if not mono:
            return
            
        if not mono._lock.acquire(blocking=False):
            return
            
        try:
            is_conn = mono.is_connected()
            if is_conn:
                pos = mono.get_current_wavelength()
                if self._last_mono_pos is None or abs(pos - self._last_mono_pos) > 0.001:
                    self.mono_pos_changed.emit(pos)
                    self._last_mono_pos = pos
                
                # Poll grating as well but maybe less often? 
                # For now just every poll is fine at 10Hz
                try:
                    g_idx = mono.get_grating()
                    self.hw._last_grating_idx = g_idx
                except:
                    pass
                    
                self.mono_status_changed.emit(True)
            else:
                self.mono_status_changed.emit(False)
        except Exception as e:
            logger.error(f"Monochromator connection lost: {e}")
            try:
                mono.disconnect()
            except:
                pass
            self.mono_status_changed.emit(False)
        finally:
            mono._lock.release()

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
        self._temp_interval = 10.0  # Polling temp is slow on SDK2, do it rarely

    @pyqtSlot()
    def process(self):
        logger.info("Camera worker process started")
        while self._running:
            try:
                self._poll_cameras()
                time.sleep(0.01)  # 100 Hz polling
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
                        # 1. Temperature (Rate-limited and only if NOT acquiring for SDK2)
                        if update_temp:
                            # For SDK2 cameras (like iDus), temperature calls can block for >1s
                            # during acquisition. We skip them if live to keep framerate high.
                            is_sdk2 = getattr(cam, '_sdk_version', 2) == 2
                            if not (is_sdk2 and cam.is_acquiring()):
                                try:
                                    temp = cam.get_temperature()
                                    status = cam.get_cooling_status()
                                    self.camera_temp_changed.emit(cam_id, temp, status)
                                except:
                                    pass

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
        self.shutter_status_changed = self.hw_worker.shutter_status_changed
        
        self.stage_x_pos_changed = self.hw_worker.stage_x_pos_changed
        self.stage_x_status_changed = self.hw_worker.stage_x_status_changed
        
        self.stage_y_pos_changed = self.hw_worker.stage_y_pos_changed
        self.stage_y_status_changed = self.hw_worker.stage_y_status_changed
        self.pm_power_ready = self.hw_worker.pm_power_ready
        self.pm_status_changed = self.hw_worker.pm_status_changed
        self.mono_pos_changed = self.hw_worker.mono_pos_changed
        self.mono_status_changed = self.hw_worker.mono_status_changed
        self.spectral_unit_changed = self.hw_worker.spectral_unit_changed
        self.spectral_display_mode_changed = self.hw_worker.spectral_display_mode_changed
        self.hw_config_changed = self.hw_worker.hw_config_changed
        
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
