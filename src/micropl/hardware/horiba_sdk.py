"""
Horiba iHR320 Monochromator driver via the Jobin Yvon Windows COM/ActiveX SDK.

Requirements (Windows only):
  - pip install pywin32
  - Run RegHJY.bat and RegHJY_SDK.bat as Administrator from the Jobin Yvon SDK folder.
  - Optionally run JYUSBSpectrometerConfig.exe to configure the device unique_id.
"""

import logging
import time
import threading
from typing import Dict, Any, Optional, Tuple
import numpy as np

try:
    import pythoncom
    import win32com.client
    import pywintypes
    _COM_AVAILABLE = True
except ImportError:
    _COM_AVAILABLE = False


def _format_com_error(exc: Exception) -> str:
    """Extract descriptive text from a Windows COM error if possible."""
    if _COM_AVAILABLE and isinstance(exc, pywintypes.com_error):
        try:
            hresult, msg, excepinfo, argerror = exc.args
            desc = excepinfo[2] if excepinfo and len(excepinfo) > 2 else msg
            return f"{desc} (HRESULT: {hex(hresult) if isinstance(hresult, int) else hresult})"
        except Exception:
            return str(exc)
    return str(exc)


from .base import Spectrometer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SDK constants (from jyAllMonos.ini + C++/VB example analysis)
# ---------------------------------------------------------------------------
_FRONT_ENTRANCE  = 0
_SIDE_ENTRANCE   = 1
_FRONT_EXIT      = 2
_SIDE_EXIT       = 3

_ENTRANCE_MIRROR = 0
_EXIT_MIRROR     = 1

_MIRROR_FRONT    = 0   # Axial
_MIRROR_SIDE     = 1   # Lateral

# COM ProgIDs — note: "Brower" (not "Browser") is the correct, original SDK typo
_MONO_PROGID    = "JYMono.Monochromator"
_BROWSER_PROGID = "JYConfigBrowserComponent.JYConfigBrowerInterface"


# ---------------------------------------------------------------------------
# COM event sink
# ---------------------------------------------------------------------------

class _MonoEventSink:
    """
    COM event sink for JYMono.Monochromator asynchronous events.
    The SDK fires OnInitialized when homing is complete (can take ~2 min).
    """

    # Class-level shared event so DispatchWithEvents can reach it
    _initialized_event: threading.Event = threading.Event()
    _critical_error: Optional[int] = None

    def OnInitialized(self, status, eventInfo):
        logger.info(f"iHR320: OnInitialized event (status={status})")
        _MonoEventSink._initialized_event.set()

    def OnUpdate(self, updateType, eventInfo):
        pass

    def OnOperationStatus(self, status, eventInfo):
        pass

    def OnCriticalError(self, status, eventInfo):
        logger.error(f"iHR320: Critical hardware error (status={status})")
        _MonoEventSink._critical_error = status
        _MonoEventSink._initialized_event.set()   # unblock connect() wait


# ---------------------------------------------------------------------------
# Driver class
# ---------------------------------------------------------------------------

class HoribaSDKMonochromator(Spectrometer):
    """
    Driver for Horiba iHR320 Monochromator via the Jobin Yvon Windows COM/ActiveX SDK.

    This driver wraps the JYMono.Monochromator COM object (JYMono.dll) and provides
    the same public interface as HoribaSerialMonochromator so the rest of the
    application works identically regardless of which monochromator is active.

    The SDK handles the USB protocol internally — no manual USB programming needed.

    Setup on Windows:
        1. Run RegHJY.bat and RegHJY_SDK.bat as Administrator.
        2. Connect the iHR320 via USB and power it on.
        3. (Optional) Run JYUSBSpectrometerConfig.exe to verify device config.
        4. Set driver: "horiba_sdk" and enabled: true in default.yaml.

    Configuration keys (default.yaml):
        unique_id   : str  — SDK device ID (e.g. "Mono1"). Auto-discovered if omitted.
        force_init  : bool — Force full re-homing even if already initialized. Default False.
        init_timeout_s : float — Seconds to wait for homing. Default 120.
        center_wavelength : float — Starting wavelength in nm. Default 500.
        grating_idx : int  — Starting grating index (0, 1, or 2). Default 0.
        gratings    : list — Grating densities in l/mm, e.g. [600, 1200, 1200].
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._unique_id        = self.config.get('unique_id', None)
        self._center_wavelength = self.config.get('center_wavelength', 500.0)
        self._grating_idx      = self.config.get('grating_idx', 0)
        self.grating_densities = self.config.get('gratings', [600, 1200, 1200])
        self._force_init       = self.config.get('force_init', False)
        self._init_timeout     = self.config.get('init_timeout_s', 120.0)

        self._mono = None
        self._use_events       = True
        self._lock = threading.RLock()

    # -----------------------------------------------------------------------
    # Discovery helper
    # -----------------------------------------------------------------------

    @staticmethod
    def discover() -> list:
        """
        List all monochromators registered with the Jobin Yvon SDK.

        Returns:
            List of (name, unique_id) tuples, e.g. [("IHR 320", "Mono1")].

        Raises:
            RuntimeError: If pywin32 is not installed or SDK not registered.
        """
        if not _COM_AVAILABLE:
            raise RuntimeError("pywin32 is not installed. Run: pip install pywin32")

        results = []
        try:
            pythoncom.CoInitialize()
            browser = win32com.client.Dispatch(_BROWSER_PROGID)
            browser.Load()
            name, mono_id = browser.GetFirstMono()
            while name or mono_id:
                results.append((str(name), str(mono_id)))
                name, mono_id = browser.GetNextMono()
        except Exception as exc:
            raise RuntimeError(
                f"SDK discovery failed. Are RegHJY.bat / RegHJY_SDK.bat registered? "
                f"Details: {_format_com_error(exc)}"
            ) from exc

        logger.info(f"iHR320: Discovered {len(results)} monochromator(s): {results}")
        return results

    # -----------------------------------------------------------------------
    # Connection
    # -----------------------------------------------------------------------

    def connect(self) -> None:
        """
        Connect to the iHR320, open USB communications and initialize (home) motors.

        If no unique_id is configured, the first available device is auto-discovered.
        Initialization homes all motors and may take up to 2 minutes — this is normal.
        """
        if self._connected:
            return

        if not _COM_AVAILABLE:
            raise RuntimeError(
                "pywin32 is not installed. Run: pip install pywin32\n"
                "The Jobin Yvon SDK also requires RegHJY.bat and RegHJY_SDK.bat "
                "to be run as Administrator on Windows."
            )

        with self._lock:
            pythoncom.CoInitialize()

            # Auto-discover unique_id if not configured
            if not self._unique_id:
                logger.info("iHR320: No unique_id configured — auto-discovering...")
                devices = self.discover()
                if not devices:
                    raise RuntimeError(
                        "iHR320: No monochromators found by the SDK. "
                        "Ensure the device is plugged in and the SDK is registered."
                    )
                self._unique_id = devices[0][1]
                logger.info(f"iHR320: Auto-selected unique_id='{self._unique_id}'")

            # Reset the class-level event before connecting
            _MonoEventSink._initialized_event.clear()
            _MonoEventSink._critical_error = None

            # Create COM object
            logger.info(f"iHR320: Creating COM object for unique_id='{self._unique_id}'")
            try:
                # Attempt in-process 32-bit dispatch with events
                self._mono = win32com.client.DispatchWithEvents(_MONO_PROGID, _MonoEventSink)
                self._use_events = True
                logger.info("iHR320: COM object created with event support.")
            except Exception as exc:
                # Fallback to standard Dispatch (e.g. for DCOM / COM+ out-of-process surrogate)
                logger.info(
                    f"iHR320: DispatchWithEvents failed ({exc}). "
                    "Falling back to standard Dispatch (no events)..."
                )
                try:
                    self._mono = win32com.client.Dispatch(_MONO_PROGID)
                    self._use_events = False
                except Exception as inner_exc:
                    raise RuntimeError(
                        f"iHR320: Failed to instantiate COM object '{_MONO_PROGID}'. "
                        f"Is the SDK properly registered? Details: {_format_com_error(inner_exc)}"
                    ) from inner_exc

            # Bind device config and open USB
            try:
                self._mono.Uniqueid = self._unique_id
                self._mono.Load()
            except Exception as exc:
                self._mono = None
                raise RuntimeError(
                    f"iHR320: Failed to load configuration for unique_id '{self._unique_id}'. "
                    f"Did you run JYUSBSpectrometerConfig.exe? Details: {_format_com_error(exc)}"
                ) from exc

            logger.info("iHR320: Opening USB communications...")
            try:
                self._mono.OpenCommunications()
            except Exception as exc:
                self._mono = None
                raise RuntimeError(
                    f"iHR320: Failed to open USB communications. "
                    f"Is the device connected via USB and powered on? Details: {_format_com_error(exc)}"
                ) from exc

            # Initialize (homes all motors asynchronously)
            logger.info(
                f"iHR320: Initializing (force_init={self._force_init}). "
                "This homes all motors and may take up to 2 minutes..."
            )
            self._mono.Initialize(self._force_init, False)

            if self._use_events:
                # Pump COM messages while waiting for the OnInitialized event
                start = time.time()
                while not _MonoEventSink._initialized_event.is_set():
                    pythoncom.PumpWaitingMessages()
                    time.sleep(0.05)
                    if time.time() - start > self._init_timeout:
                        raise TimeoutError(
                            f"iHR320: Initialization timed out after {self._init_timeout}s."
                        )

                if _MonoEventSink._critical_error is not None:
                    raise RuntimeError(
                        f"iHR320: Critical error during initialization "
                        f"(status={_MonoEventSink._critical_error})"
                    )
            else:
                # Polling fallback: wait 2 seconds for motor homing to start,
                # then poll IsBusy() until idle.
                logger.info("iHR320: Polling motor busy state for initialization...")
                time.sleep(2.0)
                start = time.time()
                while True:
                    try:
                        busy = bool(self._mono.IsBusy())
                    except Exception as e:
                        logger.warning(f"iHR320: Error reading busy state: {e}")
                        busy = True

                    if not busy:
                        logger.info("iHR320: Monochromator is idle. Homing complete.")
                        break

                    if time.time() - start > self._init_timeout:
                        raise TimeoutError(
                            f"iHR320: Initialization timed out after {self._init_timeout}s."
                        )
                    time.sleep(0.5)

            self._connected = True

            # Sync cached state from hardware
            try:
                self._center_wavelength = self.get_current_wavelength()
                self._grating_idx = self.get_grating(force_read=True)
                logger.info(
                    f"iHR320: Connected. Wavelength={self._center_wavelength:.2f} nm, "
                    f"Grating index={self._grating_idx}"
                )
            except Exception as e:
                logger.warning(
                    f"iHR320: Connected, but failed to sync initial hardware state: {e}. "
                    "Proceeding with default configuration."
                )
                self._center_wavelength = self.config.get('center_wavelength', 920.0)
                self._grating_idx = self.config.get('grating_idx', 0)

    def disconnect(self) -> None:
        """Close USB communications with the device."""
        with self._lock:
            if self._mono is not None:
                try:
                    self._mono.CloseCommunications()
                    logger.info("iHR320: Disconnected.")
                except Exception as exc:
                    logger.warning(f"iHR320: Error during disconnect: {exc}")
                finally:
                    self._mono = None
            self._connected = False

    def is_connected(self) -> bool:
        """Return True if the device is connected and initialized."""
        return self._connected and self._mono is not None

    # -----------------------------------------------------------------------
    # Status
    # -----------------------------------------------------------------------

    def is_busy(self) -> bool:
        """Return True if a motor is currently moving."""
        if not self.is_connected():
            return False
        with self._lock:
            try:
                return bool(self._mono.IsBusy())
            except Exception:
                return False

    def wait_until_ready(self, timeout: float = 60.0) -> None:
        """Block until all motors are idle, pumping COM messages while waiting."""
        start = time.time()
        while self.is_busy():
            pythoncom.PumpWaitingMessages()
            time.sleep(0.05)
            if time.time() - start > timeout:
                raise TimeoutError("iHR320: Motor movement timed out.")

    # -----------------------------------------------------------------------
    # Wavelength
    # -----------------------------------------------------------------------

    def set_center_wavelength(self, wavelength: float) -> None:
        """
        Move to an absolute wavelength position (nm).

        Args:
            wavelength: Target wavelength in nanometers.
        """
        if not self.is_connected():
            raise RuntimeError("iHR320: Device not connected.")
        logger.info(f"iHR320: Moving to {wavelength:.3f} nm")
        with self._lock:
            self._mono.MovetoWavelength(float(wavelength))
        self.wait_until_ready()
        self._center_wavelength = wavelength
        logger.info(f"iHR320: Reached {wavelength:.3f} nm")

    def get_current_wavelength(self) -> float:
        """Read the current wavelength position from hardware."""
        if not self.is_connected():
            return self._center_wavelength
        with self._lock:
            val = float(self._mono.GetCurrentWavelength())
        self._center_wavelength = val
        return val

    def set_spectral_position(self, value: float, unit: str = "nm") -> None:
        """
        Set spectrometer position in nm, meV, or cm⁻¹.

        Args:
            value: Position value in the given unit.
            unit : 'nm', 'meV', or 'cm⁻¹'.
        """
        unit = unit.lower().strip()
        if unit == "nm":
            target_nm = value
        elif unit == "mev":
            target_nm = 1_239_841.93 / value
        elif unit in ("cm⁻¹", "cm-1"):
            target_nm = 10_000_000.0 / value
        else:
            raise ValueError(f"Unsupported unit: '{unit}'. Use 'nm', 'meV', or 'cm⁻¹'.")
        logger.info(f"iHR320: set_spectral_position {value} {unit} → {target_nm:.3f} nm")
        self.set_center_wavelength(target_nm)

    def calibrate(self, wavelength: float) -> None:
        """
        Software-level calibration: record a known wavelength as the current position.

        Note: The Jobin Yvon SDK does not expose a direct hardware calibration command
        equivalent to the Z60 serial command. This method stores the offset in memory
        for the current session only. For hardware-persistent calibration, use the
        JYUSBSpectrometerConfig.exe utility.

        Args:
            wavelength: The known physical wavelength (nm) at the current position.
        """
        logger.warning(
            f"iHR320: calibrate() stores a session-only wavelength offset to {wavelength} nm. "
            "For persistent calibration, use JYUSBSpectrometerConfig.exe."
        )
        self._center_wavelength = wavelength

    # -----------------------------------------------------------------------
    # Grating
    # -----------------------------------------------------------------------

    def set_grating(self, index: int) -> None:
        """
        Select grating by turret index (0, 1, or 2).

        Args:
            index: Grating turret position index.
        """
        if not self.is_connected():
            raise RuntimeError("iHR320: Device not connected.")
        logger.info(f"iHR320: Switching to grating index {index}")
        with self._lock:
            self._mono.MovetoTurret(index)
        # Turret movement can be slow — use a longer timeout
        self.wait_until_ready(timeout=120.0)
        self._grating_idx = index
        logger.info(f"iHR320: Grating index {index} selected.")

    def get_grating(self, force_read: bool = False) -> int:
        """
        Return the current grating turret index (0, 1, or 2).

        Args:
            force_read: If True, queries hardware; otherwise returns cached value.
        """
        if not force_read:
            return self._grating_idx
        if not self.is_connected():
            return self._grating_idx
        with self._lock:
            current_density, all_densities = self._mono.GetCurrentGrating()
        try:
            idx = list(all_densities).index(current_density)
        except ValueError:
            idx = self._grating_idx
        self._grating_idx = idx
        return idx

    # -----------------------------------------------------------------------
    # Slits
    # -----------------------------------------------------------------------

    def set_slit_width(self, width_um: float, slit_id: int = 0) -> None:
        """
        Set slit width in micrometers.

        Args:
            width_um : Target slit width in µm.
            slit_id  : 0=Front Entrance, 1=Side Entrance, 2=Front Exit, 3=Side Exit.
        """
        if not self.is_connected():
            raise RuntimeError("iHR320: Device not connected.")
        logger.info(f"iHR320: Setting slit {slit_id} to {width_um:.1f} µm")
        with self._lock:
            self._mono.MovetoSlitWidth(slit_id, float(width_um))
        self.wait_until_ready()

    def get_slit_width(self, slit_id: int = 0) -> float:
        """
        Read slit width in micrometers.

        Args:
            slit_id: 0=Front Entrance, 1=Side Entrance, 2=Front Exit, 3=Side Exit.
        """
        if not self.is_connected():
            return 0.0
        with self._lock:
            return float(self._mono.GetCurrentSlitWidth(slit_id))

    # -----------------------------------------------------------------------
    # Mirrors
    # -----------------------------------------------------------------------

    def set_mirror(self, port: str = "entrance", position: str = "direct") -> None:
        """
        Move an entrance or exit mirror to axial (front) or lateral (side) position.

        Args:
            port    : 'entrance' or 'exit'.
            position: 'direct' / 'front' / 'axial'  →  axial port.
                      'side' / 'lateral'             →  lateral port.
        """
        if not self.is_connected():
            raise RuntimeError("iHR320: Device not connected.")

        port = port.lower().strip()
        pos  = position.lower().strip()

        mirror_id  = _ENTRANCE_MIRROR if "entrance" in port else _EXIT_MIRROR
        mirror_pos = _MIRROR_FRONT if pos in ("direct", "front", "axial") else _MIRROR_SIDE

        logger.info(f"iHR320: Moving {port} mirror to {position}")
        with self._lock:
            self._mono.MovetoMirrorPosition(mirror_id, mirror_pos)
        self.wait_until_ready()

    # -----------------------------------------------------------------------
    # Spectrum (not applicable — camera handles acquisition)
    # -----------------------------------------------------------------------

    def acquire_spectrum(self) -> Tuple[np.ndarray, np.ndarray]:
        raise NotImplementedError(
            "Use AndorCamera for acquisition. The iHR320 is for wavelength control only."
        )

    # -----------------------------------------------------------------------
    # Info
    # -----------------------------------------------------------------------

    def get_info(self) -> Dict[str, Any]:
        """Return a dictionary of current device state."""
        return {
            'model':      'Horiba iHR320 (SDK)',
            'unique_id':  self._unique_id,
            'connected':  self.is_connected(),
            'wavelength': self._center_wavelength,
            'grating':    self._grating_idx,
        }
