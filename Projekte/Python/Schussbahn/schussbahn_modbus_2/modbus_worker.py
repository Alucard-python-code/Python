# modbus_worker.py

import time
from PyQt5.QtCore import QThread, pyqtSignal
from pymodbus.client import ModbusTcpClient

class ModbusWorker(QThread):
    """
    Hintergrund-Thread optimiert für Waveshare POE ETH Relay (B).
    Verarbeitet Einstellungsänderungen dynamisch im laufenden Betrieb.
    """
    data_updated = pyqtSignal(list, list)

    def __init__(self, app_config):
        super().__init__()
        self.config = app_config
        self.running = True
        self.slave_id = 1 
        self.trigger_reconnect = False  # Signalisiert dem Thread einen IP-Wechsel
        
        self.relay_write_list = [False] * 8
        self.inputs = [False] * 8

    def update_outputs(self, new_outputs):
        """Wird von der main.py aufgerufen, um Fahrbefehle oder Licht zu übergeben."""
        self.relay_write_list = list(new_outputs)

    def request_reconnect(self):
        """Erlaubt der main.py, einen sicheren Reconnect im Thread anzufordern."""
        self.trigger_reconnect = True

    def run(self):
        while self.running:
            try:
                # Verbindung herstellen
                client = ModbusTcpClient(
                    host=self.config['ip'], 
                    port=self.config['port'], 
                    framer="rtu", 
                    timeout=2.0
                )
                
                if not client.connect():
                    time.sleep(2)
                    continue
                
                heartbeat_state = False
                last_heartbeat_time = 0
                self.trigger_reconnect = False  # Reset nach erfolgreichem Aufbau
                
                while self.running and not self.trigger_reconnect:
                    current_time = time.time()
                    
                    # ---- 1. HEARTBEAT / BLINKEN AUF CH6 (Adresse 4) ----
                    if current_time - last_heartbeat_time >= 0.5:
                        heartbeat_state = not heartbeat_state
                        client.write_coil(address=4, value=heartbeat_state, device_id=self.slave_id)
                        last_heartbeat_time = current_time
                    
                    # ---- 2. RELAIS SCHREIBEN ----
                    current_relays = list(self.relay_write_list)
                    client.write_coils(address=0, values=current_relays[:4], device_id=self.slave_id)
                    client.write_coil(address=7, value=current_relays[7], device_id=self.slave_id)

                    # ---- 3. HARDWARE-EINGÄNGE LESEN ----
                    rr = client.read_discrete_inputs(address=0, count=8, device_id=self.slave_id)
                    
                    if rr and not rr.isError():
                        self.inputs = rr.bits[:8]
                        current_outputs_for_gui = list(self.relay_write_list)
                        current_outputs_for_gui[4] = heartbeat_state  # Blink-LED CH6 (Index 4)
                        
                        self.data_updated.emit(self.inputs, current_outputs_for_gui)
                    else:
                        raise Exception("Fehlerhafte Antwort vom Modul")
                    
                    time.sleep(0.1)
                    
            except Exception:
                time.sleep(1)
            finally:
                try:
                    client.close()
                except:
                    pass

        # Beim endgültigen Beenden alle Ausgänge abschalten
        try:
            client = ModbusTcpClient(host=self.config['ip'], port=self.config['port'], framer="rtu", timeout=2.0)
            if client.connect():
                client.write_coils(address=0, values=[False]*8, device_id=self.slave_id)
                client.close()
        except:
            pass
