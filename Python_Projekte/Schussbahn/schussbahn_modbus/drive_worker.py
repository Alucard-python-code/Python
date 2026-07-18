# -*- coding: utf-8 -*-
import time
import logging
from PyQt5.QtCore import QThread, pyqtSignal

class DriveThread(QThread):
    status_signal = pyqtSignal(str); finished_signal = pyqtSignal(); error_signal = pyqtSignal(str)
    drive_time_signal = pyqtSignal(float); io_update_signal = pyqtSignal(list, list)

    def __init__(self, mode, client, times, ist_referenziert=False):
        super().__init__()
        self.mode = mode; self.client = client; self.times = times
        self.ist_referenziert = ist_referenziert; self._is_running = True

    def write_hardware_coil(self, kanal, zustand):
        try: return self.client.write_single_coil(kanal, zustand)
        except: return False

    def check_inputs_during_flight(self):
        """
        Prüft den Status der Eingänge während der Fahrt.
        Löst bei Sicherheitsverletzungen oder Kommunikationsfehlern eine 
        Exception aus, um das System in den sicheren Zustand zu versetzen.
        """
        # Prüfen, ob der Thread manuell gestoppt wurde
        if not self._is_running:
            raise Exception("Thread wurde manuell gestoppt")
        
        try:
            # Daten vom Modbus lesen
            inputs = self.client.read_discrete_inputs(0, 8)
            coils = self.client.read_coils(0, 8)
            
            # Überprüfen, ob Daten empfangen wurden
            if inputs and len(inputs) >= 6:
                # UI über den aktuellen Status informieren
                self.io_update_signal.emit(inputs, coils if coils else [False]*8)
                
                # Sicherheits-Check: Motorschutz (Index 0) ist ein Schließer/Öffner-Check
                # Wenn der Eingang "0" ist (ausgelöst), wird die Fahrt sofort abgebrochen
                if not inputs[0]:
                    raise Exception("Sicherheitskreis unterbrochen (Motorschutz)")
                
                return True
            
            # Wenn keine gültigen Daten empfangen wurden, ist die Kommunikation unterbrochen
            raise Exception("Kommunikationsfehler: Ungültige IO-Daten empfangen")
            
        except Exception as e:
            # Jede Exception hier führt dazu, dass der Thread in den 
            # except-Block von 'run' springt und die Schütze abschaltet.
            raise Exception(f"Sicherheitsabbruch: {str(e)}")

    def run(self):
        start_time = time.time()
        # Watchdog Zeit holen (Standard 10.0 Sekunden falls nicht in times)
        wd_limit = self.times.get("Watchdog Beschuss", 10.0) if self.mode == "Beschuss" else self.times.get("Watchdog Wertung", 10.0)

        try:
            # Hilfsfunktion zur Überwachung
            def check_watchdog():
                if (time.time() - start_time) > wd_limit:
                    raise Exception(f"WATCHDOG: Timeout bei {self.mode} erreicht ({wd_limit}s)")

            if self.mode == "Beschuss":
                self.write_hardware_coil(0, True); time.sleep(0.1); self.write_hardware_coil(3, True)
                
                # Schnellphase
                end_time_schnell = time.time() + self.times["Beschuss Schnell"]
                while time.time() < end_time_schnell:
                    check_watchdog()
                    self.check_inputs_during_flight()
                    time.sleep(0.05)
                
                self.write_hardware_coil(3, False); self.write_hardware_coil(2, True)
                
                # Langsamphase
                end_time_langsam = time.time() + self.times["Beschuss Langsam"]
                while time.time() < end_time_langsam:
                    check_watchdog()
                    self.check_inputs_during_flight()
                    time.sleep(0.05)
                
                # Abschalten
                self.write_hardware_coil(0, False); self.write_hardware_coil(2, False)

            elif self.mode == "Wertung":
                self.write_hardware_coil(1, True); time.sleep(0.1); self.write_hardware_coil(3, True)
                
                # Überwachung während der Wertungsfahrt
                while self._is_running:
                    check_watchdog()
                    self.check_inputs_during_flight()
                    # Endschalter-Abfrage (Index 1)
                    if self.client.read_discrete_inputs(0, 8)[1]: 
                        break
                    time.sleep(0.05)
                
                # Abschalten
                self.write_hardware_coil(1, False); self.write_hardware_coil(2, False)

            self.drive_time_signal.emit(time.time() - start_time)
            self.finished_signal.emit()

        except Exception as e:
            # Zentrales Aufräumen im Fehlerfall: Alle Ausgänge sicher ausschalten
            for i in range(8):
                self.write_hardware_coil(i, False)
            self.error_signal.emit(str(e))

    def stop(self):
        self._is_running = False