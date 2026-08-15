# modbus_worker.py

import time
import threading
from PyQt5.QtCore import QThread, pyqtSignal
from pymodbus.client import ModbusTcpClient

class ModbusWorker(QThread):
    """
    Hintergrund-Thread optimiert für Waveshare POE ETH Relay (B).
    Schreibt Ausgänge NUR bei echten Änderungen. Verhindert Bus-Überlastung.
    """
    data_updated = pyqtSignal(list, list)

    def __init__(self, app_config):
        super().__init__()
        self.config = app_config
        self.running = True
        self.slave_id = 1 
        self.trigger_reconnect = False
        
        self.data_lock = threading.Lock()
        
        # IO-Listen für die GUI
        self.relay_write_list = [False] * 8
        self.inputs = [False] * 8
        
        # SPIEGEL-LISTE: Speichert den Zustand, der ZULETZT an die Hardware gesendet wurde
        self.last_sent_relays = [False] * 8

    def update_outputs(self, new_outputs):
        """Sichert das Ändern der Ausgänge über das Thread-Lock ab."""
        with self.data_lock:
            self.relay_write_list = list(new_outputs)

    def request_reconnect(self):
        self.trigger_reconnect = True

    def run(self):
        while self.running:
            try:
                # Verbindung im stabilen RTU-over-TCP Modus aufbauen
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
                
                # Beim Verbindungsaufbau einmalig den aktuellen Zustand erzwingen
                with self.data_lock:
                    self.last_sent_relays = list(self.relay_write_list)
                for ch in range(4):
                    client.write_coil(address=ch, value=self.last_sent_relays[ch], device_id=self.slave_id)
                client.write_coil(address=7, value=self.last_sent_relays[7], device_id=self.slave_id)
                
                while self.running and not self.trigger_reconnect:
                    current_time = time.time()
                    
                    # ---- 1. HEARTBEAT / BLINKEN (Exakt alle 0.5s) ----
                    if current_time - last_heartbeat_time >= 0.5:
                        heartbeat_state = not heartbeat_state
                        client.write_coil(address=4, value=heartbeat_state, device_id=self.slave_id)
                        last_heartbeat_time = current_time
                    
                    # ---- 2. ÄNDERUNGS-CHECK FÜR DIE RELAIS ----
                    with self.data_lock:
                        current_relays = list(self.relay_write_list)
                    
                    # Wir vergleichen die Soll-Werte mit dem, was wir zuletzt gesendet haben
                    for ch in range(8):
                        # Wenn sich ein Kanal geändert hat (z.B. Schütz an/aus durch GUI oder FahrtWorker)
                        if current_relays[ch] != self.last_sent_relays[ch]:
                            # Schreibe NUR diesen einen geänderten Kanal auf das Modul
                            client.write_coil(address=ch, value=current_relays[ch], device_id=self.slave_id)
                            # Spiegel-Liste aktualisieren
                            self.last_sent_relays[ch] = current_relays[ch]

                    # ---- 3. HARDWARE-EINGÄNGE LESEN (Standard-Abfrage) ----
                    rr = client.read_discrete_inputs(address=0, count=8, device_id=self.slave_id)
                    
                    if rr and not rr.isError():
                        self.inputs = rr.bits[:8]
                        
                        # Blinken für die GUI-LED auf CH6 (Index 4) visualisieren
                        current_outputs_for_gui = list(current_relays)
                        current_outputs_for_gui[4] = heartbeat_state  
                        
                        self.data_updated.emit(self.inputs, current_outputs_for_gui)
                    else:
                        raise Exception("Fehlerhafte Antwort vom Modul")
                    
                    # Feste Atempause von 100ms für das Netzwerk-Gateway
                    time.sleep(0.1)
                    
            except Exception:
                # Bei Fehlern (z.B. CRC-Fehler oder Verbindungsabbruch) 1 Sekunde warten, dann sauber neu verbinden
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
