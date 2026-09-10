import sys
import time
import random
import serial

try:
    from hart_protocol import encdec
except ImportError:
    # Falls das Paket auf dem Test-PC/Codespace eine andere Struktur hat,
    # definieren wir einen leeren Dummy, damit die Simulation fehlerfrei startet.
    class DummyEncDec:
        def encode_command(self, *args, **kwargs): return b''
        def decode_response(self, *args, **kwargs): return {}
    encdec = DummyEncDec()

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

    def read_live_pressure(self, address, r_min, r_max):
        """Liest zyklisch den aktuellen Druckwert aus (Command 3)."""
        if SIMULATION_MODE:
            return round(random.uniform(r_min, r_max), 3)
        
        if self.ser:
            try:
                cmd_3 = encdec.encode_command(address=address, command_number=3)
                self.ser.write(cmd_3)
                response = self.ser.read(30)
                if response:
                    unpacked_data = encdec.decode_response(response)
                    return round(unpacked_data.get('primary_value', 0.0), 3)
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
            cmd_0 = encdec.encode_command(address=0, command_number=0)
            self.ser.write(cmd_0)
            data_0 = encdec.decode_response(self.ser.read(30))
            
            cmd_15 = encdec.encode_command(address=0, command_number=15)
            self.ser.write(cmd_15)
            data_15 = encdec.decode_response(self.ser.read(30))
            
            return {
                "serial": str(data_0.get('device_id', 'UNKNOWN_SN')),
                "model": f"Emerson Type {data_0.get('device_type', 'Transmitter')}",
                "min": data_15.get('lower_range_value', 0.0),
                "max": data_15.get('upper_range_value', 10.0),
                "unit": data_15.get('range_unit', 'bar')
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
                cmd_bytes = encdec.encode_command(address=address, command_number=cmd_num)
                self.ser.write(cmd_bytes)
                return True
            except Exception:
                return False
        return False
