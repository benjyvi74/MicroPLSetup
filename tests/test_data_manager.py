import unittest
import tempfile
from pathlib import Path
import numpy as np
from datetime import datetime

from micropl.core.data_manager import DataManager
from micropl.core.measurement import MeasurementResult

class TestDataManagerLaserCapitalization(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dm = DataManager(data_root=self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_save_and_load_laser_capitalization(self):
        # 1. Create a measurement result with lowercase keys
        metadata = {
            'Timestamp': datetime.now().isoformat(),
            'laser': {
                'Wavelength (nm)': 750.0,
                'Mode': 'CW',
                'Excitation Power (W)': 1e-5
            },
            'step': {
                'Step Type': 'Laser Heating Cycle',
                'Sequence Step Number': 1,
                'Heating Power (W)': 0.001,
                'Heating Duration (s)': 10.0
            },
            'camera': {
                'spec_camera': {
                    'Model': 'DU420_BR,DD',
                    'Exposure (ms)': 1000.0
                }
            },
            'monochromator': {
                'Model': 'FHR640',
                'Wavelength (nm)': 879.32
            },
            'Objective': '40x'
        }
        
        result = MeasurementResult(
            timestamp=datetime.now(),
            integration_time=1.0,
            wavelengths=np.linspace(700, 800, 10),
            intensities=np.ones(10) * 100,
            metadata=metadata
        )
        
        # Save it
        filepath = Path(self.temp_dir.name) / "test_spectrum.csv"
        self.dm.save_spectrum(result, filepath)
        
        # 2. Check the raw file contents to ensure capitalized sections are written
        with open(filepath, 'r') as f:
            content = f.read()
            self.assertIn("# Laser:", content)
            self.assertIn("# Step:", content)
            self.assertIn("# Camera:", content)
            self.assertIn("# Monochromator:", content)
            self.assertNotIn("# laser:", content)
            self.assertNotIn("# step:", content)
            self.assertNotIn("# camera:", content)
            self.assertNotIn("# monochromator:", content)
            
        # 3. Load the spectrum back and verify the loaded metadata dictionary contains capitalized keys
        loaded = self.dm.load_spectrum(filepath)
        self.assertIn("Laser", loaded.metadata)
        self.assertIn("Step", loaded.metadata)
        self.assertIn("Camera", loaded.metadata)
        self.assertIn("Monochromator", loaded.metadata)
        self.assertNotIn("laser", loaded.metadata)
        self.assertNotIn("step", loaded.metadata)
        self.assertNotIn("camera", loaded.metadata)
        self.assertNotIn("monochromator", loaded.metadata)
        
        # Check values
        self.assertEqual(float(loaded.metadata['Laser']['Wavelength (nm)']), 750.0)
        self.assertEqual(loaded.metadata['Laser']['Mode'], 'CW')
        self.assertEqual(loaded.metadata['Step']['Step Type'], 'Laser Heating Cycle')
        self.assertEqual(loaded.metadata['Monochromator']['Model'], 'FHR640')
        self.assertEqual(loaded.metadata['Camera']['spec_camera']['Model'], 'DU420_BR,DD')

if __name__ == '__main__':
    unittest.main()
