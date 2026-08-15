# modbus_worker.py

import time
import threading
import logging
from PyQt5.QtCore import QThread, pyqtSignal
from pymodbus.client import ModbusTcpClient

class ModbusWorker(QThread):
    """
    Hintergrund-Thread optimiert für Waveshare POE ETH Relay (B).
    Arbeitet rein sequentiell im starren 100ms-Takt, um Pufferüberläufe zu verhindern.
    """
    data_updated = pyqtSignal(list, list)

    def __init__(self, app_config):
        super().__init__()
        self.config = app_config
        self.running = True
        self.slave_id = 1 
        self.trigger_reconnect = False
        
        # Thread-Verriegelung für sicheren Datenaustausch
        self.data_lock = threading.Lock()
        
        self.relay_write_list = [False] * 8
        self.inputs = [False] * 8

    def update_outputs(self, new_outputs):
        """Sichert das Ändern der Ausgänge über das Thread-Lock ab."""
        with self.data_lock:
            self.relay_write_list = list(new_outputs)

    def request_reconnect(self):
        self.trigger_reconnect = True

    def run(self):
        while self.running:
            try:
                # Verbindung exakt wie im funktionierenden Skript aufbauen
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
                self.trigger_reconnect = False
                
                while self.running and not self.trigger_reconnect:
                    current_time = time.time()
                    
                    # ---- 1. HEARTBEAT / BLINKEN (Nur alle 0.5s senden!) ----
                    if current_time - last_heartbeat_time >= 0.5:
                        heartbeat_state = not heartbeat_state
                        client.write_coil(address=4, value=heartbeat_state, device_id=self.slave_id)
                        last_heartbeat_time = current_time
                    
                    # ---- 2. RELAIS SCHREIBEN (Ausgabeliste sicher kopieren) ----
                    with self.data_lock:
                        current_relays = list(self.relay_write_list)
                    
                    # Einzeln schreiben statt Sammelbefehl ist auf den Waveshare-Modulen
                    # oft stabiler, wenn es im Takt läuft
                    for ch in range(4):
                        client.write_coil(address=ch, value=current_relays[ch], device_id=self.slave_id)
                    
                    # Lichtkanal CH8 (Adresse 7) schreiben
                    client.write_coil(address=7, value=current_relays[7], device_id=self.slave_id)

                    # ---- 3. HARDWARE-EINGÄNGE LESEN ----
                    rr = client.read_discrete_inputs(address=0, count=8, device_id=self.slave_id)
                    
                    if rr and not rr.isError():
                        self.inputs = rr.bits[:8]
                        
                        # Blinken für die GUI-LED auf CH6 (Index 4) visualisieren
                        current_outputs_for_gui = list(current_relays)
                        current_outputs_for_gui[4] = heartbeat_state  
                        
                        self.data_updated.emit(self.inputs, current_outputs_for_gui)
                    else:
                        raise Exception("Fehlerhafte Antwort vom Modul")
                    
                    # ZWANGSPAUSE: Genau 100ms warten, damit das Gateway Zeit zum Verarbeiten hat.
                    # Das entspricht exakt deinem funktionierenden Skript!
                    time.sleep(0.1)
                    
            except Exception as e:
                # Bei Fehlern (z.B. Puffer voll) 1 Sekunde warten und Socket neu initialisieren
                time.sleep(1)
            finally:
                try:
                    client.close()
                except:
                    pass

        # Beim Schließen der App alle Ausgänge abwerfen
        try:
            client = ModbusTcpClient(host=self.config['ip'], port=self.config['port'], framer="rtu", timeout=2.0)
            if client.connect():
                for ch in range(8):
                    client.write_coil(address=ch, value=False, device_id=self.slave_id)
                client.close()
        except:
            pass
