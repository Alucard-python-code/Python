# modbus_worker.py

import time
import threading
from PyQt5.QtCore import QThread, pyqtSignal
from pymodbus.client import ModbusTcpClient

class ModbusWorker(QThread):
    """
    Hochstabiler, industrieller Hintergrund-Thread fuer das Waveshare POE ETH Relay (B).
    Optimiert fuer unterbrechungsfreien 24/7-Dauerbetrieb ohne Bus-Hänger.
    """
    data_updated = pyqtSignal(list, list)

    def __init__(self, app_config):
        super().__init__()
        self.config = app_config
        self.running = True
        self.slave_id = 1 
        self.trigger_reconnect = False
        
        self.data_lock = threading.Lock()
        
        # IO-Listen fuer die GUI und den FahrtWorker
        self.relay_write_list = [False] * 8
        self.inputs = [False] * 8
        
        # Spiegel-Liste zur Vermeidung von Bus-Dauerfeuer
        self.last_sent_relays = [False] * 8

    def update_outputs(self, new_outputs):
        with self.data_lock:
            self.relay_write_list = list(new_outputs)

    def request_reconnect(self):
        self.trigger_reconnect = True

    def run(self):
        while self.running:
            client = None
            try:
                # 1. Verbindung einmalig stabil im RTU-over-TCP Modus aufbauen
                # timeout=0.3s verhindert langes Blockieren bei Paketverlusten
                client = ModbusTcpClient(
                    host=self.config['ip'], 
                    port=self.config['port'], 
                    framer="rtu", 
                    timeout=0.3
                )
                
                if not client.connect():
                    time.sleep(1.0)
                    continue
                
                heartbeat_state = False
                last_heartbeat_time = 0
                self.trigger_reconnect = False
                
                # Initialen Zustand der Relais beim Start einmalig erzwingen
                with self.data_lock:
                    self.last_sent_relays = list(self.relay_write_list)
                for ch in range(4):
                    client.write_coil(address=ch, value=self.last_sent_relays[ch], device_id=self.slave_id)
                client.write_coil(address=7, value=self.last_sent_relays[7], device_id=self.slave_id)
                
                # Haupt-Kommunikationsschleife (Bleibt permanent offen)
                while self.running and not self.trigger_reconnect:
                    loop_start = time.time()
                    
                    try:
                        # ---- A. HEARTBEAT / BLINKEN (Exakt alle 0.5s) ----
                        if loop_start - last_heartbeat_time >= 0.5:
                            heartbeat_state = not heartbeat_state
                            client.write_coil(address=4, value=heartbeat_state, device_id=self.slave_id)
                            last_heartbeat_time = loop_start
                        
                        # ---- B. COILS NUR BEI ECHTER ÄNDERUNG SCHREIBEN ----
                        with self.data_lock:
                            current_relays = list(self.relay_write_list)
                        
                        for ch in range(8):
                            if current_relays[ch] != self.last_sent_relays[ch]:
                                client.write_coil(address=ch, value=current_relays[ch], device_id=self.slave_id)
                                self.last_sent_relays[ch] = current_relays[ch]

                        # ---- C. HARDWARE-EINGÄNGE LESEN ----
                        rr = client.read_discrete_inputs(address=0, count=8, device_id=self.slave_id)
                        
                        if rr and not rr.isError():
                            self.inputs = rr.bits[:8]
                            
                            # Herzschlag-Blinken fuer die GUI-LED CH6 (Index 4) einspeisen
                            current_outputs_for_gui = list(current_relays)
                            current_outputs_for_gui[4] = heartbeat_state  
                            
                            self.data_updated.emit(self.inputs, current_outputs_for_gui)
                        else:
                            # Kleinerer Fehler im Paket: Wir flushen den Puffer, anstatt den Socket zu killen
                            if hasattr(client, 'framer') and hasattr(client.framer, 'clear'):
                                client.framer.clear()
                    
                    except Exception:
                        # Einzelschleifen-Fehler (z.B. CRC-Fehler): Puffer leeren und direkt weiterarbeiten
                        if hasattr(client, 'framer') and hasattr(client.framer, 'clear'):
                            client.framer.clear()
                    
                    # Hochfrequenter Zyklustakt (50ms) gewaehrleistet extrem schnelles Nachholen
                    # von verlorenen Paketen weit unterhalb deines 500ms-Limits
                    time.sleep(0.05)
                    
            except Exception:
                # Schwerer Netzwerkfehler (Kabel ab / IP-Wechsel): 1s Pause fuer harten Reset
                time.sleep(1.0)
            finally:
                if client:
                    try:
                        client.close()
                    except:
                        pass

        # Beim kontrollierten Schliessen der Anwendung alle Relais sicher abwerfen
        try:
            client = ModbusTcpClient(host=self.config['ip'], port=self.config['port'], framer="rtu", timeout=0.5)
            if client.connect():
                for ch in range(8):
                    client.write_coil(address=ch, value=False, device_id=self.slave_id)
                client.close()
        except:
            pass
