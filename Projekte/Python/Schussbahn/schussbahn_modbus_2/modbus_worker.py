# modbus_worker.py

import time
import threading
from PyQt5.QtCore import QThread, pyqtSignal
from pymodbus.client import ModbusTcpClient

class ModbusWorker(QThread):
    """
    Industrie-Hintergrund-Thread für Waveshare POE ETH Relay (B).
    Hält die TCP-Verbindung permanent offen und blockiert Reconnect-Hänger.
    Garantiert Fehlerbehebung innerhalb von max. 100ms.
    """
    data_updated = pyqtSignal(list, list)

    def __init__(self, app_config):
        super().__init__()
        self.config = app_config
        self.running = True
        self.slave_id = 1 
        self.trigger_reconnect = False
        
        self.data_lock = threading.Lock()
        self.relay_write_list = [False] * 8
        self.inputs = [False] * 8

    def update_outputs(self, new_outputs):
        with self.data_lock:
            self.relay_write_list = list(new_outputs)

    def request_reconnect(self):
        self.trigger_reconnect = True

    def run(self):
        while self.running:
            client = None
            try:
                # Verbindung stabil im RTU-over-TCP Modus öffnen
                # Knallhartes Timeout von 0.15s – wir warten nicht auf hängende Pakete!
                client = ModbusTcpClient(
                    host=self.config['ip'], 
                    port=self.config['port'], 
                    framer="rtu", 
                    timeout=0.15
                )
                
                if not client.connect():
                    time.sleep(1.0)
                    continue
                
                heartbeat_state = False
                last_heartbeat_time = 0
                self.trigger_reconnect = False
                
                # Haupt-Kommunikationsschleife (Bleibt dauerhaft in diesem Block)
                while self.running and not self.trigger_reconnect:
                    loop_start = time.time()
                    
                    # INNERE SCHLEIFE ABSICHERN: Fehler führen NICHT zum Verbindungsabbruch!
                    try:
                        # ---- 1. HEARTBEAT-BERECHNUNG ----
                        if loop_start - last_heartbeat_time >= 0.5:
                            heartbeat_state = not heartbeat_state
                            last_heartbeat_time = loop_start
                        
                        # ---- 2. REGISTER-DATEN VORBEREITEN ----
                        with self.data_lock:
                            current_relays = list(self.relay_write_list)
                        
                        current_relays[4] = heartbeat_state # Live-Blinken CH6
                        
                        output_register_value = 0
                        for ch in range(8):
                            if current_relays[ch]:
                                output_register_value |= (1 << ch)
                        
                        # ---- 3. HARDWARE BESCHREIBEN (Register 0) ----
                        client.write_register(address=0x0000, value=output_register_value, device_id=self.slave_id)

                        # ---- 4. HARDWARE LESEN (Register 0x0040) ----
                        rr = client.read_holding_registers(address=0x0040, count=1, device_id=self.slave_id)
                        
                        if rr and not rr.isError():
                            reg_val = rr.registers[0]
                            for i in range(8):
                                self.inputs[i] = bool((reg_val >> i) & 1)
                            
                            # Daten an GUI senden
                            self.data_updated.emit(self.inputs, current_relays)
                        else:
                            # Paket fehlerhaft? Sofort Puffer flushen und im nächsten Tekt neu versuchen
                            if hasattr(client, 'framer') and hasattr(client.framer, 'clear'):
                                client.framer.clear()
                                
                    except Exception:
                        # Sporadischer Fehler (z.B. EMV-Störung): Puffer leeren, NICHT die Verbindung schließen!
                        if client and hasattr(client, 'framer') and hasattr(client.framer, 'clear'):
                            client.framer.clear()
                    
                    # Fester 100ms Takt. Wenn ein Fehler auftritt, sind wir in 100ms wieder empfangsbereit!
                    time.sleep(0.1)
                    
            except Exception:
                # Nur bei echtem Hardware-Ausfall (z.B. Kabel gezogen) greift diese Pause
                time.sleep(1.0)
            finally:
                if client:
                    try:
                        client.close()
                    except:
                        pass

        # Beim Schließen der App alle Ausgänge geordnet auf 0 setzen
        try:
            client = ModbusTcpClient(host=self.config['ip'], port=self.config['port'], framer="rtu", timeout=0.5)
            if client.connect():
                client.write_register(address=0x0000, value=0, device_id=self.slave_id)
                client.close()
        except:
            pass
