import sys
import time
import random
import serial
from hart_protocol import Unpacker, tools

SIMULATION_MODE = True  
SERIAL_PORT = 'COM3' if sys.platform == 'win32' else '/dev/ttyUSB0'

class HARTModem:
    def __init__(self):
        self.ser = None
        if not SIMULATION_MODE:
            try:
                self.ser = serial.Serial(SERIAL_PORT, baudrate=1200, parity=serial.PARITY_ODD, stopbits=serial.STOPBITS_ONE, timeout=1)
            except Exception as e:
                print(f"Modem-Fehler: {e}")

    def _exchange(self, address, command_number):
        """Send a command and decode the first complete HART response."""
        command = tools.pack_command(address, command_id=command_number)
        self.ser.write(command)
        response = self.ser.read(64)
        if not response:
            return None

        unpacker = Unpacker(on_error="raise")
        unpacker.feed(response)
        return next(unpacker)

    def read_live_pressure(self, address, r_min, r_max):
        """Liest zyklisch den aktuellen Druckwert aus (Command 3)."""
        if SIMULATION_MODE:
            return round(random.uniform(r_min, r_max), 3)
        
        if self.ser:
            try:
                response = self._exchange(address, 3)
                if response:
                    return round(response.primary_variable, 3)
            except Exception:
                pass
        return "ERR-COMM"

    def scan_sensor_hardware(self):
        """Scant den Bus (Command 0 & 15) und liefert die echten Hardware-Specs."""
        if SIMULATION_MODE:
            time.sleep(1.0)
            return {
                "serial": f"SN-RM3051-{random.randint(100000, 999999)}",
                "model": "Rosemount 3051S", "min": 0.0, "max": 10.0, "unit": "bar"
            }
        
        if not self.ser:
            return None
            
        try:
            data_0 = self._exchange(0, 0)
            data_15 = self._exchange(0, 15)
            if not data_0 or not data_15:
                return None
            
            return {
                "serial": str(getattr(data_0, "device_id", "UNKNOWN_SN")),
                "model": f"Emerson Type {getattr(data_0, 'manufacturer_device_type', 'Transmitter')}",
                "min": getattr(data_15, "lower_range_value", 0.0),
                "max": getattr(data_15, "upper_range_value", 10.0),
                "unit": str(getattr(data_15, "primary_variable_units", "bar")),
            }
        except Exception:
            return None

    def send_trim_command(self, address, command_type):
        """Sendet Kalibrierbefehle (43 = Zero Trim, 44 = Span Trim)"""
        if SIMULATION_MODE:
            return True
        if self.ser:
            cmd_num = 43 if command_type == "zero" else 44
            try:
                cmd_bytes = tools.pack_command(address, command_id=cmd_num)
                self.ser.write(cmd_bytes)
                return True
            except Exception:
                return False
        return False
