# -*- coding: utf-8 -*-
import time
import socket
import json
import logging
from PyQt5.QtCore import QThread, pyqtSignal

class DriveThread(QThread):
    status_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    drive_time_signal = pyqtSignal(float)
    io_update_signal = pyqtSignal(list, list)

    def __init__(self, mode, client_dummy, times, ist_referenziert=False):
        super().__init__()
        self.mode = mode
        # client_dummy wird ignoriert, wir nutzen die IPC-Netzwerkschnittstelle
        self.times = times
        self.ist_referenziert = ist_referenziert
        self._is_running = True
        self.latest_inputs = [False] * 8
        self.last_gui_emit = 0 
        
        # Lokaler Zustand für Relais 1-4, den wir an das Backend übergeben
        self.current_relays = [False, False, False, False]
        
        # IPC-Konfiguration für die Verbindung zum Hintergrundprogramm
        self.ipc_host = "127.0.0.1"
        self.ipc_port = 65432

    def communicate_with_backend(self, relays_to_write):
        """Sendet Relais-Zustände an das Backend und holt die 8 Eingänge ab (mit sicheren Retries)."""
        max_retries = 4
        for attempt in range(max_retries):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.15) # Leicht erhöht für stabilere Handshakes
                    s.connect((self.ipc_host, self.ipc_port))
                    
                    payload = {"set_relays": relays_to_write}
                    s.sendall(json.dumps(payload).encode('utf-8'))
                    
                    response = s.recv(1024).decode('utf-8')
                    if not response:
                        raise socket.error("Leere Antwort vom Server")
                        
                    data = json.loads(response)
                    return data.get("inputs", [False] * 8)
                    
            except (socket.error, json.JSONDecodeError) as e:
                # Bei schnellen Abfolgen kurz warten und erneut versuchen
                if attempt < max_retries - 1:
                    time.sleep(0.04) # 40ms Puffer geben, damit sich der Server fängt
                    continue
                else:
                    # Erst nach dem 4. Fehlschlag werfen wir den Fehler
                    raise Exception(f"IPC-Hintergrunddienst nicht erreichbar: {e}")

    def write_hardware_coil(self, kanal, zustand):
        """Setzt den Zustand für ein Relais im lokalen Array und sendet es."""
        if 0 <= kanal <= 3:
            self.current_relays[kanal] = zustand
        try:
            # Sofortiger Sync mit dem Backend und Aktualisierung der Eingänge
            self.latest_inputs = self.communicate_with_backend(self.current_relays)
            return True
        except:
            return False

    def check_inputs_during_flight(self):
        """Prüft den Status der Eingänge während der Fahrt über das Backend."""
        if not self._is_running:
            raise Exception("Thread wurde manuell gestoppt")

        try:
            # Zyklischer Datenaustausch im Fahrtverlauf
            self.latest_inputs = self.communicate_with_backend(self.current_relays)
            
            # Da das Backend die Coils verwaltet, simulieren wir die Coils für die GUI
            # Relais 5 (Index 4) wird als Heartbeat weggelassen, da rein intern
            simulated_coils = self.current_relays + [False, False, False, False]

            # GUI-Drosselung (Schutzfilter für Pi 5 gegen Memory Crashes)
            current_time = time.time() * 1000
            if current_time - self.last_gui_emit > 200:
                self.last_gui_emit = current_time
                self.io_update_signal.emit(self.latest_inputs, simulated_coils)

            if not self.latest_inputs[0]: # Index 0 für den Motorschutz
                raise Exception("Sicherheitskreis unterbrochen (Motorschutz)")

            return True
        except Exception as e:
            raise Exception(f"Sicherheitsabbruch: {str(e)}")

    def run(self):
        start_time = time.time()

        if self.mode == "Beschuss":
            wd_limit = self.times.get("Watchdog Beschuss", 10.0)
        elif self.mode == "Wertung":
            wd_limit = self.times.get("Watchdog Wertung", 10.0)
        else:
            wd_limit = self.times.get("Watchdog HomeFahrt", 20.0)

        try:
            def check_watchdog():
                if (time.time() - start_time) > wd_limit:
                    if self.mode == "HomeFahrt":
                        raise Exception("TIMEOUT_HOMEFAHRT")
                    else:
                        raise Exception(f"WATCHDOG: Timeout bei {self.mode} erreicht ({wd_limit}s)")

            # ====================================================================
            # 1. MODUS: BESCHUSS
            # ====================================================================
            if self.mode == "Beschuss":
                self.write_hardware_coil(0, True)
                time.sleep(0.1)
                self.write_hardware_coil(3, True)

                end_time_schnell = time.time() + self.times["Beschuss Schnell"]
                while time.time() < end_time_schnell:
                    check_watchdog()
                    self.check_inputs_during_flight()
                    time.sleep(0.05)

                self.write_hardware_coil(3, False)
                self.write_hardware_coil(2, True)

                end_time_langsam = time.time() + self.times["Beschuss Langsam"]
                while time.time() < end_time_langsam:
                    check_watchdog()
                    self.check_inputs_during_flight()
                    time.sleep(0.05)

                self.write_hardware_coil(0, False)
                self.write_hardware_coil(2, False)
                # Letzter Sync zum Ausschalten aller Relais im Backend
                self.communicate_with_backend([False, False, False, False])

            # ====================================================================
            # 2. MODUS: WERTUNG
            # ====================================================================
            elif self.mode == "Wertung":
                self.write_hardware_coil(1, True)
                time.sleep(0.1)
                self.write_hardware_coil(3, True)
                self.status_signal.emit("Wertung: Schnellphase")

                end_time_schnell = time.time() + self.times.get("Wertung Schnell", 2.5)
                while time.time() < end_time_schnell:
                    check_watchdog()
                    self.check_inputs_during_flight()

                    if isinstance(self.latest_inputs, list) and len(self.latest_inputs) > 1 and self.latest_inputs[1] == True:
                        break
                    time.sleep(0.05)

                self.write_hardware_coil(3, False)
                self.write_hardware_coil(2, True)
                self.status_signal.emit("Wertung: Langsamphase")

                while self._is_running:
                    check_watchdog()
                    self.check_inputs_during_flight()

                    if isinstance(self.latest_inputs, list) and len(self.latest_inputs) > 1:
                        if self.latest_inputs[1] == True:
                            break
                    time.sleep(0.05)

                self.write_hardware_coil(1, False)
                self.write_hardware_coil(2, False)
                self.communicate_with_backend([False, False, False, False])

            # ====================================================================
            # 3. MODUS: HOMEFAHRT
            # ====================================================================
            elif self.mode == "HomeFahrt":
                self.write_hardware_coil(1, True)
                time.sleep(0.1)
                self.write_hardware_coil(2, True)

                while self._is_running:
                    check_watchdog()
                    self.check_inputs_during_flight()

                    if isinstance(self.latest_inputs, list) and len(self.latest_inputs) > 1:
                        if self.latest_inputs[1] == True:
                            break
                    time.sleep(0.05)

                self.write_hardware_coil(1, False)
                self.write_hardware_coil(2, False)
                self.communicate_with_backend([False, False, False, False])

            self.drive_time_signal.emit(time.time() - start_time)
            self.finished_signal.emit()

        except Exception as e:
            # Im Fehlerfall übergeben wir sofort eine leere Liste, um alle Relais abzuwerfen
            try:
                self.communicate_with_backend([False, False, False, False])
            except:
                pass
            self.error_signal.emit(str(e))

    def stop(self):
        self._is_running = False
