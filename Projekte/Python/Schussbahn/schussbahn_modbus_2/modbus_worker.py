# modbus_worker.py

import time
import threading
from PyQt5.QtCore import QThread, pyqtSignal
from pymodbus.client import ModbusTcpClient

class ModbusWorker(QThread):
    """
    Hintergrund-Thread für das Waveshare POE ETH Relay (B).
    Nutzt deine funktionierenden Original-Befehle im absolut starren 100ms-Takt.
    """
    data_updated = pyqtSignal(list, list)

    def __init__(self, app_config):
        super().__init__()
        self.config = app_config
        self.running = True
        self.slave_id = 1 
        self.trigger_reconnect = False
        
        # Thread-Sicherung
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
                # Verbindung stabil im funktionierenden RTU-over-TCP Modus öffnen
                client = ModbusTcpClient(
                    host=self.config['ip'], 
                    port=self.config['port'], 
                    framer="rtu", 
                    timeout=0.2
                )
                
                if not client.connect():
                    time.sleep(1.0)
                    continue
                
                heartbeat_state = False
                last_heartbeat_time = 0
                self.trigger_reconnect = False
                
                # Haupt-Kommunikationsschleife
                while self.running and not self.trigger_reconnect:
                    cycle_start = time.time()
                    
                    # INNERE SICHERHEITSSCHLEIFE: Fehler trennen NICHT den TCP-Socket!
                    try:
                        # ---- 1. HEARTBEAT / BLINKEN AUF CH6 (Adresse 4) ----
                        if cycle_start - last_heartbeat_time >= 0.5:
                            heartbeat_state = not heartbeat_state
                            client.write_coil(address=4, value=heartbeat_state, device_id=self.slave_id)
                            last_heartbeat_time = cycle_start
                        
                        # ---- 2. RELAIS SCHREIBEN (Deine funktionierenden Sammelbefehle) ----
                        with self.data_lock:
                            current_relays = list(self.relay_write_list)
                        
                        # Schütze CH1-CH4 als Block schreiben
                        client.write_coils(address=0, values=current_relays[:4], device_id=self.slave_id)
                        
                        # KORREKTUR: index [7] hinzugefügt, da write_coil keine Liste akzeptiert!
                        client.write_coil(address=7, value=current_relays[7], device_id=self.slave_id)

                        # ---- 3. HARDWARE-EINGÄNGE LESEN (Deine Original-Abfrage) ----
                        rr = client.read_discrete_inputs(address=0, count=8, device_id=self.slave_id)
                        
                        if rr and not rr.isError():
                            self.inputs = rr.bits[:8]
                            
                            # Blinken für die GUI-LED auf CH6 (Index 4) einspeisen
                            current_outputs_for_gui = list(current_relays)
                            current_outputs_for_gui[4] = heartbeat_state  
                            
                            # Daten flüssig an das PyQt5-Hauptfenster übermitteln
                            self.data_updated.emit(self.inputs, current_outputs_for_gui)
                        else:
                            if hasattr(client, 'framer') and hasattr(client.framer, 'clear'):
                                client.framer.clear()
                                
                    except Exception:
                        if client and hasattr(client, 'framer') and hasattr(client.framer, 'clear'):
                            client.framer.clear()
                    
                    # DYNAMISCHES TIMING: Verhindert, dass der Takt "eiert".
                    # Berechnet die exakte Dauer der Modbus-Befehle und füllt auf genau 100ms auf.
                    elapsed = time.time() - cycle_start
                    sleep_time = max(0.01, 0.1 - elapsed)
                    time.sleep(sleep_time)
                    
            except Exception:
                time.sleep(1.0)
            finally:
                if client:
                    try:
                        client.close()
                    except:
                        pass

        # Beim Schließen der Anwendung alle Ausgänge sicher abwerfen
        try:
            client = ModbusTcpClient(host=self.config['ip'], port=self.config['port'], framer="rtu", timeout=0.5)
            if client.connect():
                client.write_coils(address=0, values=[False]*8, device_id=self.slave_id)
                client.close()
        except:
            pass
