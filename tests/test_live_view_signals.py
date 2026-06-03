import sys
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

# Mock pylablib
sys.modules['pylablib'] = MagicMock()
sys.modules['pylablib.devices'] = MagicMock()

from PyQt6.QtWidgets import QApplication
from micropl.gui.main import MainWindow
from micropl.gui.live_view import LiveView
from micropl.gui.measurement_panel import MeasurementPanel

app = QApplication.instance() or QApplication(sys.argv)

class TestLiveViewSignals(unittest.TestCase):
    def setUp(self):
        # Reset singleton
        from micropl.hardware.manager import HardwareManager
        HardwareManager._instance = None
        
        self.main = MainWindow()
        self.live_view = self.main.live_view
        self.measurement_panel = self.main.measurement_panel
        self.hw = self.main.hw

    def tearDown(self):
        if hasattr(self, 'main') and self.main:
            self.main.close()

    def test_heating_sequence_signal_propagation(self):
        x = np.linspace(500, 600, 1024)
        y = np.ones(1024) * 100.0
        label = "step_001_P_1,5mW_t_10s"

        # Check connection
        mock_slot = MagicMock()
        self.live_view.measurement_ready.disconnect()
        self.live_view.measurement_ready.connect(mock_slot)
        
        # Emulate LiveView receiving signal from seq_worker
        self.live_view._on_seq_measurement(x, y, label)
        
        # Verify mock_slot was called
        mock_slot.assert_called_once_with(x, y, label)

    def test_real_on_measurement_ready(self):
        x = np.linspace(500, 600, 1024)
        y = np.random.rand(1024) * 100.0
        label = "step_001_P_1,5mW_t_10s"
        
        # Call the real slot and ensure it does not raise any exceptions
        try:
            self.measurement_panel.on_measurement_ready(x, y, label)
        except Exception as e:
            self.fail(f"on_measurement_ready raised an exception: {e}")
            
        # Verify it was added to history list and history data
        self.assertEqual(self.measurement_panel.history_list.count(), 1)
        self.assertEqual(len(self.measurement_panel._history_data), 1)

    @patch('micropl.gui.automation_panel.acquire_spectrum_synchronized')
    def test_laser_heating_worker_execution(self, mock_acquire):
        mock_acquire.return_value = np.ones(1024)
        
        # Setup mock hardware
        mock_pol = MagicMock()
        mock_pol.is_connected.return_value = True
        mock_pol.is_moving.return_value = False
        
        mock_shutter = MagicMock()
        
        mock_cam = MagicMock()
        mock_cam.is_connected.return_value = True
        mock_cam.get_exposure.return_value = 0.1
        mock_cam.get_info.return_value = {'detector_size': (1024, 256)}
        
        self.hw.instruments['polarizer'] = mock_pol
        self.hw.instruments['shutter'] = mock_shutter
        self.hw.config = {
            'hardware': {
                'shutter': {
                    'linked_id': 'shutter',
                    'channel': 1
                }
            }
        }
        self.hw.get_spectroscopy_camera = MagicMock(return_value=mock_cam)
        
        # Mock calibration points
        self.hw.polarizer_calibration.points = {0.0: 10.0, 0.001: 20.0, 0.002: 30.0}
        self.hw.polarizer_calibration.get_angle_for_power = MagicMock(return_value=15.0)
        
        from micropl.gui.automation_panel import LaserHeatingWorker
        steps = [{'target_w': 0.001, 'duration': 0.1}]
        
        # Test 1: start_index = 0, skip_step_0 = False => should run Step 0
        worker = LaserHeatingWorker(
            self.hw, meas_power_w=0.001, steps=steps, data_dir="/tmp/test_heating",
            metadata={}, skip_step_0=False, start_index=0
        )
        
        # Connect signal to slot
        mock_ready = MagicMock()
        worker.measurement_ready.connect(mock_ready)
        
        with patch('os.makedirs'):
            with patch('micropl.core.data_manager.DataManager.save_spectrum'):
                worker._execute_sequence()
                
        # Verify step 0 and step 1 ready signals were emitted
        # We expect 2 calls: one for step 0 baseline, one for heating step 1
        self.assertEqual(mock_ready.call_count, 2)
        # Verify shutter.set_shutter was called (specifically, to open/close for measurement/heating)
        mock_shutter.set_shutter.assert_any_call(True, channel=self.hw.shutter_channel)
        
        # Test 2: start_index = 1 => should skip Step 0
        worker2 = LaserHeatingWorker(
            self.hw, meas_power_w=0.001, steps=steps, data_dir="/tmp/test_heating",
            metadata={}, skip_step_0=False, start_index=1
        )
        mock_ready2 = MagicMock()
        worker2.measurement_ready.connect(mock_ready2)
        
        with patch('os.makedirs'):
            with patch('micropl.core.data_manager.DataManager.save_spectrum'):
                worker2._execute_sequence()
                
        # We expect 1 call: only heating step 1
        self.assertEqual(mock_ready2.call_count, 1)

    @patch('micropl.gui.automation_panel.acquire_spectrum_synchronized')
    def test_power_series_worker_execution(self, mock_acquire):
        mock_acquire.return_value = np.ones(1024)
        
        # Setup mock hardware
        mock_pol = MagicMock()
        mock_pol.is_connected.return_value = True
        mock_pol.is_moving.return_value = False
        
        mock_shutter = MagicMock()
        
        mock_cam = MagicMock()
        mock_cam.is_connected.return_value = True
        mock_cam.get_exposure.return_value = 0.1
        mock_cam.get_info.return_value = {'detector_size': (1024, 256)}
        
        self.hw.instruments['polarizer'] = mock_pol
        self.hw.instruments['shutter'] = mock_shutter
        self.hw.config = {
            'hardware': {
                'shutter': {
                    'linked_id': 'shutter',
                    'channel': 1
                }
            }
        }
        self.hw.get_spectroscopy_camera = MagicMock(return_value=mock_cam)
        
        # Mock calibration points
        self.hw.polarizer_calibration.points = {0.0: 10.0, 0.001: 20.0, 0.002: 30.0}
        self.hw.polarizer_calibration.get_angle_for_power = MagicMock(return_value=15.0)
        
        from micropl.gui.automation_panel import PowerSeriesWorker
        powers = [0.001, 0.002]
        
        worker = PowerSeriesWorker(
            self.hw, powers_w=powers, data_dir="/tmp/test_powers",
            metadata={}, stabilization_delay=0.1
        )
        
        mock_ready = MagicMock()
        worker.measurement_ready.connect(mock_ready)
        
        with patch('os.makedirs'):
            with patch('micropl.core.data_manager.DataManager.save_spectrum'):
                worker._execute_sequence()
                
        # We expect 2 calls (one for each power step)
        self.assertEqual(mock_ready.call_count, 2)
        mock_shutter.set_shutter.assert_any_call(True, channel=self.hw.shutter_channel)

    @patch('micropl.gui.main.Thread')
    def test_connect_hardware_async(self, mock_thread):
        # Trigger the async connect
        self.main.connect_hardware()
        
        # Verify the menu action is disabled
        self.assertFalse(self.main.connect_action.isEnabled())
        self.assertFalse(self.main.disconnect_action.isEnabled())
        
        # Verify a thread was started
        mock_thread.assert_called_once()
        self.assertTrue(mock_thread.return_value.daemon)

    @patch('micropl.gui.main.Thread')
    def test_connect_hardware_sequence(self, mock_thread):
        # Mock initialize_instrument on hardware manager
        self.hw.initialize_instrument = MagicMock()
        
        # Setup config with enabled devices
        self.hw.config = {
            'hardware': {
                'cameras': [{'id': 'camera_1', 'enabled': True, 'driver': 'andor_camera', 'name': 'iDus'}],
                'monochromators': [{'id': 'mono', 'enabled': True, 'driver': 'horiba_serial', 'name': 'Horiba Mono'}],
                'accessories': [{'id': 'polarizer', 'enabled': True, 'driver': 'kdc101', 'name': 'Polarizer'}]
            }
        }
        
        # Mock instruments
        mock_cam = MagicMock()
        mock_mono = MagicMock()
        mock_acc = MagicMock()
        
        self.hw.get_camera = MagicMock(return_value=mock_cam)
        self.hw.get_instrument = MagicMock(side_effect=lambda name: mock_mono if name == 'mono' else mock_acc)
        self.hw.get_spectroscopy_camera_id = MagicMock(return_value='camera_1')
        self.hw.sync_calibration_with_hardware = MagicMock()
        
        # Mock panels in UI
        mock_cam_card = MagicMock()
        self.live_view.camera_panels = {'camera_1': mock_cam_card}
        
        mock_mono_panel = MagicMock()
        mock_mono_panel.acc_id = 'mono'
        mock_mono_panel.content_widget = MagicMock()
        
        mock_acc_panel = MagicMock()
        mock_acc_panel.acc_id = 'polarizer'
        mock_acc_panel.content_widget = MagicMock()
        
        self.main.equipment_sidebar._wrappers = [mock_mono_panel, mock_acc_panel]
        
        # We need to mock time.sleep so the test runs instantly
        with patch('time.sleep') as mock_sleep:
            self.main.connect_hardware()
            
            # Retrieve target function of the thread
            target_func = mock_thread.call_args[1]['target']
            
            # Execute the target function synchronously in the test
            target_func()
            
            # Process Qt events so the QTimer.singleShot callbacks run
            QApplication.processEvents()
            
        # Verify the devices were connected
        mock_cam.connect.assert_called_once()
        mock_mono.connect.assert_called_once()
        mock_acc.connect.assert_called_once()
        
        # Verify calibration synchronization occurred
        self.hw.sync_calibration_with_hardware.assert_called_once()
        
        # Verify the menu actions were re-enabled
        self.assertTrue(self.main.connect_action.isEnabled())
        self.assertTrue(self.main.disconnect_action.isEnabled())

    def test_map_generation_zero_step_safe(self):
        # Temporarily allow 0 range for step size to simulate intermediate state or user editing
        self.main.automation_panel.map_x_step.setRange(0.0, 100)
        self.main.automation_panel.map_y_step.setRange(0.0, 100)
        
        self.main.automation_panel.map_x_step.setValue(0.0)
        self.main.automation_panel.map_y_step.setValue(0.0)
        
        # This call should not raise ZeroDivisionError and should return safely
        try:
            self.main.automation_panel._on_generate_map()
        except ZeroDivisionError as e:
            self.fail(f"_on_generate_map raised ZeroDivisionError: {e}")

class TestROIOffsetsAndCaching(unittest.TestCase):
    def test_camera_card_roi_offsets(self):
        from micropl.gui.camera_sidebar import CameraCard
        
        # Test 1: Spectroscopy camera (1-based UI)
        spec_cfg = {'name': 'iDus', 'role': 'spectroscopy', 'detector_size': [1024, 256]}
        card_spec = CameraCard('camera_1', spec_cfg)
        
        # Ranges should start from 1
        self.assertEqual(card_spec.x_start.minimum(), 1)
        self.assertEqual(card_spec.y_start.minimum(), 1)
        
        # Set values in UI (e.g. 1 to 1024)
        card_spec.x_start.setValue(1)
        card_spec.x_end.setValue(1024)
        card_spec.y_start.setValue(114)
        card_spec.y_end.setValue(143)
        card_spec.x_bin.setValue(1)
        card_spec.y_bin.setValue(30)
        
        # get_roi should return 0-based exclusive-end
        roi = card_spec.get_roi()
        self.assertEqual(roi, (0, 1024, 113, 143, 1, 30))
        
        # sync_roi with 0-based exclusive-end should set UI spinboxes to 1-based inclusive
        card_spec.sync_roi((0, 1024, 113, 143, 1, 30))
        self.assertEqual(card_spec.x_start.value(), 1)
        self.assertEqual(card_spec.y_start.value(), 114)
        
        # Test 2: Visualisation camera (0-based UI)
        vis_cfg = {'name': 'Luca', 'role': 'visualisation', 'detector_size': [1004, 1002]}
        card_vis = CameraCard('camera_0', vis_cfg)
        
        # Ranges should start from 0
        self.assertEqual(card_vis.x_start.minimum(), 0)
        self.assertEqual(card_vis.y_start.minimum(), 0)
        
        # Set values in UI (e.g. 0 to 1004)
        card_vis.x_start.setValue(0)
        card_vis.x_end.setValue(1004)
        
        # get_roi should return exact same values
        roi_vis = card_vis.get_roi()
        self.assertEqual(roi_vis[0], 0)
        self.assertEqual(roi_vis[1], 1004)

        # Test 3: Apply presets on spectroscopy camera card without triggering hardware
        card_spec.apply_preset("center_spec", trigger_hardware=False)
        self.assertEqual(card_spec.y_start.value(), 114)

        card_spec.apply_preset("slit_image", trigger_hardware=False)
        self.assertEqual(card_spec.y_start.value(), 1)

        # Test 4: Apply presets on visualisation camera card without triggering hardware
        card_vis.apply_preset("image_vis", trigger_hardware=False)
        self.assertEqual(card_vis.y_start.value(), 252)

    def test_andor_camera_fvb_roi_caching(self):
        from micropl.hardware.andor_camera import AndorCamera
        
        # Setup mock underlying camera
        mock_pylab_cam = MagicMock()
        mock_pylab_cam.get_detector_size.return_value = (1024, 256)
        
        # Create AndorCamera wrapper
        cam = AndorCamera({'model': 'DU420_BR,DD', 'role': 'spectroscopy', 'detector_size': [1024, 256]})
        cam._cam = mock_pylab_cam
        cam._connected = True
        
        # Case 1: FVB/Single-track mode (y_bin >= roi_height)
        # We request x_start = 10, x_end = 200, but in FVB/Single-track it should override cached horizontal ROI to full width (0, 1024)
        cam.set_roi(x_start=10, x_end=200, y_start=10, y_end=40, y_bin=30)
        
        roi = cam.get_roi()
        self.assertEqual(roi[0], 0) # Overridden to 0
        self.assertEqual(roi[1], 1024) # Overridden to width
        
        # Case 2: Image mode (y_bin < roi_height)
        # We request x_start = 10, x_end = 200, it should preserve them in cache
        cam.set_roi(x_start=10, x_end=200, y_start=10, y_end=40, y_bin=1)
        
        roi_img = cam.get_roi()
        self.assertEqual(roi_img[0], 10)
        self.assertEqual(roi_img[1], 200)

    def test_andor_camera_single_track_no_redundant_reset(self):
        from micropl.hardware.andor_camera import AndorCamera
        
        class MockCam:
            def get_detector_size(self): return (1024, 256)
            def set_read_mode(self, mode): pass
            def setup_single_track(self, center, height): pass
            
        mock_pylab_cam = MagicMock(spec=MockCam)
        mock_pylab_cam.get_detector_size.return_value = (1024, 256)
        
        cam = AndorCamera({'model': 'DU420_BR,DD', 'role': 'spectroscopy', 'detector_size': [1024, 256]})
        cam._cam = mock_pylab_cam
        cam._connected = True
        cam._sdk_version = 2
        
        # 1. Set readout mode to Single track first time
        cam.set_readout_mode("Single track")
        self.assertEqual(cam._readout_mode, "Single track")
        mock_pylab_cam.set_read_mode.assert_called_once_with("single_track")
        
        # Reset mock
        mock_pylab_cam.set_read_mode.reset_mock()
        
        # 2. Set readout mode to Single track again (should be no-op)
        cam.set_readout_mode("Single track")
        mock_pylab_cam.set_read_mode.assert_not_called()
        
        # 3. Call set_roi with Single track active.
        # It should call set_single_track -> setup_single_track(center, height)
        # without calling set_read_mode("single_track") again since it is already "Single track".
        cam.set_roi(x_start=0, x_end=1024, y_start=113, y_end=143, y_bin=30)
        
        # should have called setup_single_track with center=128, height=30
        mock_pylab_cam.setup_single_track.assert_called_once_with(128, 30)
        # and set_read_mode should not have been called during this set_roi sequence since it was already "Single track"
        mock_pylab_cam.set_read_mode.assert_not_called()

class TestColormapScalingControls(unittest.TestCase):
    def setUp(self):
        # Reset singleton and create MainWindow to test UI integration
        from micropl.hardware.manager import HardwareManager
        HardwareManager._instance = None
        
        self.main = MainWindow()
        self.measurement = self.main.measurement_panel
        
        # Add some mock spatial map points data
        self.measurement._spatial_map_data = [
            {'x': 0.0, 'y': 0.0, 'peak_wavelength': 520.0, 'peak_intensity': 100.0, 'integrated_intensity': 1000.0, 'index': 0},
            {'x': 1.0, 'y': 1.0, 'peak_wavelength': 530.0, 'peak_intensity': 500.0, 'integrated_intensity': 5000.0, 'index': 1},
            {'x': 2.0, 'y': 2.0, 'peak_wavelength': 540.0, 'peak_intensity': 900.0, 'integrated_intensity': 9000.0, 'index': 2}
        ]
        
    def tearDown(self):
        if hasattr(self, 'main') and self.main:
            self.main.close()

    def test_autoscale_updates_spinboxes(self):
        # By default, Auto-scale should be checked and controls disabled
        self.assertTrue(self.measurement.spatial_autoscale_chk.isChecked())
        self.assertFalse(self.measurement.spatial_scale_mode_combo.isEnabled())
        self.assertFalse(self.measurement.spatial_min_spin.isEnabled())
        self.assertFalse(self.measurement.spatial_max_spin.isEnabled())
        
        # Select "Peak Wavelength" metric
        self.measurement.spatial_metric_combo.setCurrentText("Peak Wavelength")
        
        # Trigger update
        self.measurement._update_spatial_map()
        
        # Spinboxes should be updated to min/max of peak_wavelength (520.0 to 540.0)
        self.assertEqual(self.measurement.spatial_min_spin.value(), 520.0)
        self.assertEqual(self.measurement.spatial_max_spin.value(), 540.0)
        self.assertEqual(self.measurement.spatial_center_spin.value(), 530.0)
        self.assertEqual(self.measurement.spatial_range_spin.value(), 10.0)

    def test_manual_min_max_scaling(self):
        # Uncheck auto-scale to enable controls
        self.measurement.spatial_autoscale_chk.setChecked(False)
        self.assertTrue(self.measurement.spatial_min_spin.isEnabled())
        
        # Set manual limits
        self.measurement.spatial_scale_mode_combo.setCurrentText("Min / Max")
        self.measurement.spatial_min_spin.setValue(525.0)
        self.measurement.spatial_max_spin.setValue(535.0)
        
        # Spy on the spatial map's update_points call
        self.measurement.spatial_map.update_points = MagicMock()
        self.measurement._update_spatial_map()
        
        # Verify custom limits were passed to the plot widget
        self.measurement.spatial_map.update_points.assert_called_once_with(
            self.measurement._spatial_map_data,
            -1,
            'peak_wavelength',
            self.measurement._active_colormap,
            auto_scale=False,
            min_val=525.0,
            max_val=535.0
        )

    def test_manual_center_range_scaling(self):
        # Uncheck auto-scale to enable controls
        self.measurement.spatial_autoscale_chk.setChecked(False)
        
        # Set Center / Range mode
        self.measurement.spatial_scale_mode_combo.setCurrentText("Center / Range")
        self.measurement.spatial_center_spin.setValue(530.0)
        self.measurement.spatial_range_spin.setValue(5.0)
        
        # Spy on the spatial map's update_points call
        self.measurement.spatial_map.update_points = MagicMock()
        self.measurement._update_spatial_map()
        
        # Center = 530, Range = 5 => Min = 525, Max = 535
        self.measurement.spatial_map.update_points.assert_called_once_with(
            self.measurement._spatial_map_data,
            -1,
            'peak_wavelength',
            self.measurement._active_colormap,
            auto_scale=False,
            min_val=525.0,
            max_val=535.0
        )

if __name__ == '__main__':
    unittest.main()
