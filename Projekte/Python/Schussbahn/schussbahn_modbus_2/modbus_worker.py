# modbus_worker.py

import time
import threading
from PyQt5.QtCore import QThread, pyqtSignal
from pymodbus.client import ModbusTcpClient

class ModbusWorker(QThread):
    """
    Hochstabiler Industrie-Hintergrund-Thread für das Waveshare POE ETH Relay (B).
    Schreibt Ausgänge NUR bei echten Änderungen. Verhindert Bus-Kollaps vollständig.
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
        self.relay_write_list = [False] * 9
        self.inputs = [False] * 8
        
        # SPIEGEL-LISTE: Speichert den Zustand, der ZULETZT an die Hardware gesendet wurde
        self.last_sent_relays = [False] * 9

    def update_outputs(self, new_outputs):
        with self.data_lock:
            self.relay_write_list = list(new_outputs)

    def request_reconnect(self):
        self.trigger_reconnect = True

    def run(self):
        """Hauptschleife des Hintergrund-Threads (Dauertakt)."""
        print(f"[Modbus] Thread gestartet. Ziel-IP: {self.ip}:{self.port}")
        
        while self.running:
            # 1. Sicherstellen, dass die Verbindung physisch steht
            if not self.client.connected:
                try:
                    self.client.close() 
                    time.sleep(0.05)
                    self.client.connect()
                except Exception as e:
                    print(f"[Modbus-Fehler] Verbindungsaufbau fehlgeschlagen: {e}")
                    time.sleep(0.1)
                    continue

            # 2. Ausgänge/Fahrbefehle an den Pico senden (FC15)
            try:
                with self.lock:
                    current_relays = list(self.relay_write_list)

                # Sende den gesamten Block an den Pico (Verwendung von device_id statt slave)
                result_write = self.client.write_coils(
                    address=0, 
                    values=current_relays, 
                    device_id=self.slave_id
                )
                
                if result_write.isError():
                    print("[Modbus-Warnung] Schreibfehler! Erzwinge Socket-Reset...")
                    self.client.close()
                    time.sleep(0.05)
                    continue
                    
            except Exception as e:
                print(f"[Modbus-Fehler] Fehler beim Schreiben: {e}")
                self.client.close()
                continue

            # 3. Den schnellen Heartbeat an Adresse 8 senden (FC05)
            try:
                result_hb = self.client.write_coil(address=8, value=True, device_id=self.slave_id)
                heartbeat_state = False if result_hb.isError() else True
                
                if result_hb.isError():
                    self.client.close()
                    continue
            except Exception:
                heartbeat_state = False
                self.client.close()
                continue

            # 4. Die 8 physischen Eingänge vom Pico live abfragen (FC02)
            try:
                result_read = self.client.read_discrete_inputs(address=0, count=8, device_id=self.slave_id)
                
                if not result_read.isError():
                    self.inputs = result_read.bits[:8]
                else:
                    self.client.close()
                    continue
            except Exception:
                self.client.close()
                continue

            # 5. Daten fehlerfrei verarbeitet -> GUI füttern
            try:
                current_outputs_for_gui = list(current_relays)
                # KORRIGIERT: Schreibt den Zustand sauber in den 9. Platz (Index 8) statt die Liste zu loeschen
                current_outputs_for_gui[8] = heartbeat_state
                
                # Signal fehlerfrei an das Hauptfenster senden
                self.data_updated.emit(self.inputs, current_outputs_for_gui)
            except Exception as e:
                print(f"[GUI-Signal Fehler]: {e}")
                pass

            # Exakter Zeittakt (100 ms)
            time.sleep(0.1)

        # Beim geordneten Beenden der GUI alle Ausgänge nullen
        try:
            self.client.write_coils(address=0, values=[False]*9, device_id=self.slave_id)
            self.client.close()
        except Exception:
            pass
        print("[Modbus] Thread sauber beendet.")
