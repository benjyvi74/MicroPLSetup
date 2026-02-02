"""
Mock Serial test for FHR640 to verify driver logic.
This script mocks the pyserial interface to test the FHR640 class.
"""

import unittest
from unittest.mock import MagicMock, patch
import time
import sys

# Mock serial BEFORE importing FHR640
mock_serial_mod = MagicMock()
sys.modules["serial"] = mock_serial_mod

from micropl.hardware.fhr640 import FHR640

class TestFHR640Serial(unittest.TestCase):
    def setUp(self):
        self.config = {'port': 'MOCK_COM'}
        self.fhr = FHR640(self.config)
        
        # Setup mock Serial instance
        self.mock_ser = MagicMock()
        mock_serial_mod.Serial.return_value = self.mock_ser
        self.mock_ser.is_open = True
        
        # Helper to queue bytes and return them one by one
        self._read_queue = []
        def mock_read(size=1):
            res = b''
            for _ in range(size):
                if self._read_queue:
                    res += self._read_queue.pop(0)
                else:
                    # Default behaviors if queue empty:
                    # If we just wrote 'E', return 'z'
                    # If we just wrote a standard command, return 'o'
                    last_write = [call.args[0] for call in self.mock_ser.write.call_args_list][-1]
                    if last_write == b'E':
                        res += b'z'
                    elif b'Z453' in last_write:
                        res += b'o' # next read will be status
                    elif last_write.endswith(b'\r'):
                        res += b'o'
                    else:
                        res += b'*' # default ack
            return res
            
        self.mock_ser.read.side_effect = mock_read
        
        def mock_read_until(term):
            res = b''
            while not res.endswith(term):
                chunk = mock_read(1)
                if not chunk: break
                res += chunk
            return res
            
        self.mock_ser.read_until.side_effect = mock_read_until

    def queue_response(self, data: bytes):
        for i in range(len(data)):
            self._read_queue.append(data[i:i+1])

    def test_connect_success(self):
        # Setup sequence responses
        self.queue_response(b'*') # Autobaud
        self.queue_response(b'=') # Intelligent
        self.queue_response(b'*') # Main
        
        self.fhr.connect()
        self.assertTrue(self.fhr.is_connected())

    def test_move_wavelength(self):
        # 1. Connect (Skip startup if 'F')
        self.queue_response(b'F')
        self.fhr.connect()
        
        # 2. Move (Ack 'o', Busy check 'E' -> 'o', 'z')
        self.queue_response(b'o\r') # Command ack
        self.queue_response(b'oz')   # Status check ('o' then 'z')
        
        self.fhr.set_center_wavelength(750)
        self.assertEqual(self.fhr._center_wavelength, 750)

    def test_get_wavelength(self):
        # 1. Connect
        self.queue_response(b'F')
        self.fhr.connect()
        
        # 2. Read (Ack 'o', then value + '\r')
        self.queue_response(b'o633.000\r')
        
        val = self.fhr.get_current_wavelength()
        self.assertEqual(val, 633.0)

    def test_set_grating(self):
        # 1. Connect
        self.queue_response(b'F')
        self.fhr.connect()
        
        # 2. Select (Ack 'o', then Status 'Z453' -> 'o', 'z\r')
        self.queue_response(b'o\r') # Command ack
        self.queue_response(b'oz\r') # Status check (via _send_command)
        
        self.fhr.set_grating(1)
        any_z451 = any(b'Z451' in call.args[0] for call in self.mock_ser.write.call_args_list)
        self.assertTrue(any_z451)

if __name__ == "__main__":
    unittest.main()
