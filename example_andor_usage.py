"""
Example usage of Andor DU420A-BR-DD iDus camera with pylablib.

This script demonstrates basic camera operations:
- Connection and initialization
- Temperature management
- Single image acquisition
- Continuous acquisition
- ROI configuration
"""

import time
import logging
import numpy as np
from micropl.hardware.factory import create_instrument

# Configure logging to see camera operations
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def example_basic_usage():
    """Basic camera connection and single image acquisition."""
    logger.info("=== Example 1: Basic Usage ===")

    # Create camera instance with configuration
    config = {
        'model': 'DU420A-BR-DD',
        'camera_index': 0,
        'exposure_time': 0.1,
        'temperature': -70,
        'fan_mode': 'on'
    }

    cam = create_instrument('andor_camera', config)

    try:
        # Connect to camera
        cam.connect()

        # Get camera information
        info = cam.get_info()
        logger.info(f"Camera info: {info}")

        # Wait for temperature to stabilize (optional)
        logger.info("Waiting for temperature stabilization...")
        temp = cam.get_temperature()
        logger.info(f"Current temperature: {temp:.1f}°C")

        # Acquire a single image
        logger.info("Acquiring single image...")
        image = cam.acquire_image()
        logger.info(f"Acquired image: shape={image.shape}, dtype={image.dtype}")
        logger.info(f"Image stats: min={image.min()}, max={image.max()}, mean={image.mean():.1f}")

    finally:
        cam.disconnect()


def example_with_context_manager():
    """Using context manager for automatic cleanup."""
    logger.info("=== Example 2: Context Manager ===")

    config = {
        'model': 'DU420A-BR-DD',
        'camera_index': 0,
        'exposure_time': 0.5,
        'temperature': -70,
    }

    # Context manager automatically handles connect/disconnect
    with create_instrument('andor_camera', config) as cam:
        # Set exposure time
        cam.set_exposure(0.5)

        # Acquire image
        image = cam.acquire_image()
        logger.info(f"Acquired image with shape {image.shape}")


def example_roi_configuration():
    """Configure Region of Interest and binning."""
    logger.info("=== Example 3: ROI Configuration ===")

    config = {'model': 'DU420A-BR-DD', 'camera_index': 0}

    with create_instrument('andor_camera', config) as cam:
        # Get full detector size
        info = cam.get_info()
        detector_size = info.get('detector_size')
        logger.info(f"Full detector size: {detector_size}")

        # Set ROI to center quarter of detector with 2x2 binning
        if detector_size:
            width, height = detector_size
            x_start = width // 4
            x_end = 3 * width // 4
            y_start = height // 4
            y_end = 3 * height // 4

            cam.set_roi(x_start, x_end, y_start, y_end, x_bin=2, y_bin=2)
            logger.info(f"ROI set: x=[{x_start}:{x_end}], y=[{y_start}:{y_end}], bin=2x2")

            # Get current ROI
            roi = cam.get_roi()
            logger.info(f"Current ROI: {roi}")

            # Acquire image with ROI
            image = cam.acquire_image()
            logger.info(f"ROI image shape: {image.shape}")

            # Reset to full frame
            cam.set_roi()
            logger.info("ROI reset to full frame")


def example_continuous_acquisition():
    """Continuous acquisition mode."""
    logger.info("=== Example 4: Continuous Acquisition ===")

    config = {
        'model': 'DU420A-BR-DD',
        'camera_index': 0,
        'exposure_time': 0.05,  # 50ms exposure
    }

    with create_instrument('andor_camera', config) as cam:
        # Start continuous acquisition
        cam.start_acquisition()
        logger.info("Continuous acquisition started")

        # Acquire 10 frames
        num_frames = 10
        images = []

        for i in range(num_frames):
            # Wait for frame to be ready
            if cam.wait_for_frame(timeout=2.0):
                # Read oldest unread image
                image = cam.read_oldest_image()
                if image is not None:
                    images.append(image)
                    logger.info(f"Frame {i+1}/{num_frames}: shape={image.shape}, "
                              f"mean={image.mean():.1f}")
            else:
                logger.warning(f"Timeout waiting for frame {i+1}")

        # Stop acquisition
        cam.stop_acquisition()
        logger.info(f"Acquired {len(images)} frames")

        # Calculate average image
        if images:
            avg_image = np.mean(images, axis=0)
            logger.info(f"Average image: mean={avg_image.mean():.1f}, "
                       f"std={avg_image.std():.1f}")


def example_multiple_exposures():
    """Acquire images at different exposure times."""
    logger.info("=== Example 5: Multiple Exposure Times ===")

    config = {'model': 'DU420A-BR-DD', 'camera_index': 0}

    exposure_times = [0.01, 0.05, 0.1, 0.5, 1.0]  # seconds

    with create_instrument('andor_camera', config) as cam:
        for exp_time in exposure_times:
            # Set exposure
            cam.set_exposure(exp_time)

            # Acquire image
            image = cam.acquire_image()

            logger.info(f"Exposure {exp_time}s: mean={image.mean():.1f}, "
                       f"max={image.max()}")


def example_temperature_monitoring():
    """Monitor CCD temperature."""
    logger.info("=== Example 6: Temperature Monitoring ===")

    config = {
        'model': 'DU420A-BR-DD',
        'camera_index': 0,
        'temperature': -70,
        'fan_mode': 'on'
    }

    with create_instrument('andor_camera', config) as cam:
        info = cam.get_info()
        logger.info(f"Target temperature: {info['target_temperature']}°C")

        # Monitor temperature for 30 seconds
        logger.info("Monitoring temperature (30 seconds)...")
        start_time = time.time()

        while time.time() - start_time < 30:
            temp = cam.get_temperature()
            logger.info(f"Current temperature: {temp:.1f}°C")
            time.sleep(5)


def example_readout_modes():
    """Explore available readout/amplifier modes."""
    logger.info("=== Example 7: Readout Modes ===")

    config = {'model': 'DU420A-BR-DD', 'camera_index': 0}

    with create_instrument('andor_camera', config) as cam:
        # Try to set different readout modes
        # Note: Available modes depend on camera model
        try:
            logger.info("Testing readout mode 0...")
            cam.set_readout_mode(0)

            image = cam.acquire_image()
            logger.info(f"Image acquired with mode 0: mean={image.mean():.1f}")

        except Exception as e:
            logger.warning(f"Error with readout mode: {e}")


def example_save_image():
    """Acquire and save image to file."""
    logger.info("=== Example 8: Save Image ===")

    import matplotlib.pyplot as plt

    config = {
        'model': 'DU420A-BR-DD',
        'camera_index': 0,
        'exposure_time': 0.1
    }

    with create_instrument('andor_camera', config) as cam:
        # Acquire image
        image = cam.acquire_image()

        # Save as numpy array
        np.save('andor_image.npy', image)
        logger.info("Image saved as andor_image.npy")

        # Save as PNG with matplotlib
        plt.figure(figsize=(8, 6))
        plt.imshow(image, cmap='viridis', origin='lower')
        plt.colorbar(label='Counts')
        plt.title(f'Andor {cam.model} Image')
        plt.xlabel('X pixel')
        plt.ylabel('Y pixel')
        plt.tight_layout()
        plt.savefig('andor_image.png', dpi=150)
        logger.info("Image saved as andor_image.png")
        plt.close()


if __name__ == '__main__':
    # Run examples
    # Uncomment the examples you want to run

    try:
        # Basic examples
        example_basic_usage()
        # example_with_context_manager()

        # Advanced examples
        # example_roi_configuration()
        # example_continuous_acquisition()
        # example_multiple_exposures()

        # Monitoring and configuration
        # example_temperature_monitoring()
        # example_readout_modes()

        # Save data
        # example_save_image()

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
