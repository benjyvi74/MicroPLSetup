# Andor DU420A-BR-DD iDus Camera Driver

Documentation for the Andor iDus camera implementation using pylablib in the MicroPL project.

## Description

The DU420A-BR-DD is an Andor iDus spectroscopy CCD camera, used in this project for:
- Spectral acquisition
- Low-light imaging
- Scientific measurements with thermoelectric cooling

## Prerequisites

### Hardware
- Andor DU420A-BR-DD iDus camera (or compatible iXon, iKon, iStart, iVac, Luca, Newton)
- USB connection to computer
- Andor SDK2 installed

### Software
- **Andor SDK2** (required)
  - Download from: https://andor.oxinst.com/downloads/
  - Install the appropriate SDK for your platform
  - Follow manufacturer installation instructions

- **pylablib-lightweight** with dependencies
  ```bash
  pip install pylablib-lightweight[numba,devio]
  ```

- Python 3.9+

## Architecture

The driver is implemented in `/src/micropl/hardware/andor_camera.py` using:
- **pylablib.devices.Andor.AndorSDK2Camera** for SDK2 interface
- **Abstract Camera interface** from `base.py`
- **Automatic temperature and fan control** during initialization

## Implemented Features

### Connection and Initialization
- ✅ `connect()` - Connect to camera with temperature/fan initialization
- ✅ `disconnect()` - Safe disconnection with cleanup
- ✅ `is_connected()` - Check connection status
- ✅ `get_info()` - Get detailed camera information

### Acquisition
- ✅ `acquire_image()` - Single frame acquisition (snap mode)
- ✅ `start_acquisition()` - Start continuous acquisition
- ✅ `stop_acquisition()` - Stop acquisition and clear buffers
- ✅ `read_oldest_image()` - Read oldest unread frame from buffer
- ✅ `read_multiple_images(n)` - Read multiple frames
- ✅ `wait_for_frame(timeout)` - Wait for frame availability

### Configuration
- ✅ `set_exposure(time)` - Set exposure time
- ✅ `get_exposure()` - Get actual exposure time
- ✅ `set_roi()` - Configure Region of Interest with binning
- ✅ `get_roi()` - Get current ROI settings
- ✅ `set_gain(gain)` - Set amplifier mode (gain)
- ✅ `set_readout_mode(mode)` - Set readout/amplifier mode

### Temperature Control
- ✅ `get_temperature()` - Read current CCD temperature
- ✅ Temperature setpoint configured during initialization
- ✅ Fan mode control ("on"/"off")

### Other
- ✅ Context manager support (`with` statement)
- ✅ Comprehensive error handling and logging
- ✅ Detector size and ROI information

## Configuration

### In `default.yaml`

```yaml
hardware:
  andor_camera:
    model: DU420A-BR-DD  # Camera model
    camera_index: 0  # Camera index (0 = first camera)
    exposure_time: 0.1  # seconds
    temperature: -70  # °C (set during initialization)
    fan_mode: on  # "on" or "off"
    readout_mode: null  # null = default, or specify amplifier mode index
```

### Finding Available Cameras

Use pylablib to list connected cameras:

```python
from pylablib.devices import Andor
num_cameras = Andor.get_cameras_number_SDK2()
print(f"Found {num_cameras} Andor camera(s)")
```

## Usage Examples

### Basic Example

```python
from micropl.hardware.factory import create_instrument

config = {
    'model': 'DU420A-BR-DD',
    'camera_index': 0,
    'exposure_time': 0.1,
    'temperature': -70,
}

cam = create_instrument('andor_camera', config)
cam.connect()

try:
    # Get camera info
    info = cam.get_info()
    print(f"Detector size: {info['detector_size']}")
    print(f"Temperature: {info['current_temperature']:.1f}°C")

    # Acquire single image
    image = cam.acquire_image()
    print(f"Image shape: {image.shape}")
    print(f"Mean counts: {image.mean():.1f}")

finally:
    cam.disconnect()
```

### With Context Manager (Recommended)

```python
with create_instrument('andor_camera', config) as cam:
    # Set exposure
    cam.set_exposure(0.5)

    # Acquire image
    image = cam.acquire_image()
    # Automatic disconnection on exit
```

### Continuous Acquisition

```python
with create_instrument('andor_camera', config) as cam:
    # Start continuous acquisition
    cam.start_acquisition()

    # Acquire 10 frames
    for i in range(10):
        if cam.wait_for_frame(timeout=2.0):
            image = cam.read_oldest_image()
            print(f"Frame {i+1}: mean={image.mean():.1f}")

    # Stop acquisition
    cam.stop_acquisition()
```

### Region of Interest (ROI)

```python
with create_instrument('andor_camera', config) as cam:
    # Get detector size
    width, height = cam.get_info()['detector_size']

    # Set ROI to center quarter with 2x2 binning
    cam.set_roi(
        x_start=width//4,
        x_end=3*width//4,
        y_start=height//4,
        y_end=3*height//4,
        x_bin=2,
        y_bin=2
    )

    # Acquire with ROI
    image = cam.acquire_image()
    print(f"ROI image shape: {image.shape}")

    # Reset to full frame
    cam.set_roi()
```

### Multiple Exposures

```python
with create_instrument('andor_camera', config) as cam:
    exposure_times = [0.01, 0.05, 0.1, 0.5, 1.0]

    for exp_time in exposure_times:
        cam.set_exposure(exp_time)
        image = cam.acquire_image()
        print(f"Exposure {exp_time}s: counts={image.mean():.1f}")
```

More examples in `example_andor_usage.py`.

## Camera Parameters

### DU420A-BR-DD Specifications
- **Sensor**: CCD (front-illuminated or back-thinned)
- **Resolution**: Typically 1024x256 or similar (check with `get_detector_size()`)
- **Cooling**: Thermoelectric cooling to -70°C or lower
- **Interface**: USB 2.0/3.0

Check actual specifications with:
```python
info = cam.get_info()
print(f"Detector size: {info['detector_size']}")
```

## Troubleshooting

### "pylablib not available"
- Install pylablib: `pip install pylablib-lightweight[numba,devio]`
- Restart Python after installation

### "Could not initialize camera" / SDK2 errors
- Verify Andor SDK2 is installed
- Check camera is connected via USB
- Ensure no other software is using the camera
- Try unplugging/replugging the USB cable
- Check camera power supply

### "Camera index not available"
- Use `Andor.get_cameras_number_SDK2()` to check connected cameras
- Verify `camera_index` in configuration (usually 0 for first camera)

### Temperature not reaching setpoint
- Allow sufficient stabilization time (can take 10-30 minutes)
- Check ambient temperature
- Verify fan is working (`fan_mode: on`)
- Monitor with `get_temperature()` periodically

### Images too dark/bright
- Adjust exposure time with `set_exposure()`
- Try different amplifier modes with `set_gain()` or `set_readout_mode()`
- Check experimental setup (light source, alignment)

### Slow acquisition
- Reduce ROI size to increase frame rate
- Use binning to increase speed
- Check readout mode (faster modes may have more noise)

### "Device not connected" errors
- Always call `connect()` before operations
- Use context manager (`with`) for automatic connection management
- Check logs for connection errors

## Known Limitations

1. **Temperature setpoint**
   - Can only be set during initialization
   - Reconnect to change temperature setpoint

2. **Gain control**
   - SDK2 uses amplifier modes instead of traditional gain
   - Available modes depend on camera model

3. **Shutter control**
   - Shutter initially closed for protection
   - Configure shutter mode if needed

4. **Platform compatibility**
   - SDK2 availability depends on platform
   - Check Andor documentation for OS support

## Performance Tips

1. **Use appropriate exposure time**
   - Start with 0.1s and adjust based on signal
   - Longer exposures = more signal but slower acquisition

2. **ROI and binning**
   - Use ROI to reduce readout time
   - Binning improves S/N ratio and speed

3. **Continuous acquisition**
   - More efficient for multiple frames
   - Uses buffering for faster throughput

4. **Temperature stability**
   - Wait for temperature to stabilize before measurements
   - Monitor temperature during long acquisitions

5. **Buffer management**
   - Read frames regularly to avoid buffer overflow
   - Use `read_multiple_images()` for batch reading

## API Methods Summary

| Method | Description |
|--------|-------------|
| `connect()` | Connect to camera |
| `disconnect()` | Disconnect from camera |
| `acquire_image()` | Single frame snap |
| `start_acquisition()` | Start continuous mode |
| `stop_acquisition()` | Stop continuous mode |
| `set_exposure(time)` | Set exposure time (seconds) |
| `set_roi(...)` | Configure ROI and binning |
| `get_roi()` | Get current ROI |
| `set_gain(gain)` | Set amplifier mode |
| `get_temperature()` | Read CCD temperature |
| `read_oldest_image()` | Read from buffer |
| `wait_for_frame(timeout)` | Wait for frame |

## References

- [pylablib Documentation](https://pylablib.readthedocs.io/en/stable/devices/Andor.html)
- [Andor SDK2 Documentation](https://andor.oxinst.com/products/software-development-kit/andor-sdk)
- [DU420 Product Page](https://andor.oxinst.com/products/idu-detector-series)

## Author

Implemented for the MicroPL project using pylablib-lightweight.
