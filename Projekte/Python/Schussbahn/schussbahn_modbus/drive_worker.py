# -*- coding: utf-8 -*-
import time
import logging
from PyQt5.QtCore import QThread, pyqtSignal

class DriveThread(QThread):
    status_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    drive_time_signal = pyqtSignal(float)
    io_update_signal = pyqtSignal(list, list)

    def __init__(self, mode, client, times, ist_referenziert=False):
        super().__init__()
        self.mode = mode
        self.client = client
        self.times = times
        self.ist_referenziert = ist_referenziert
        self._is_running = True
        self.latest_inputs = [] # Speicher für die zyklischen Schleifen

    def write_hardware_coil(self, kanal, zustand):
        try:
            # KORREKTUR: .write_coil() mit nackter Kanaladresse vorne und device_id=1
            res = self.client.write_coil(kanal, value=zustand, device_id=1)
            return not res.isError()
        except:
            return False

    def check_inputs_during_flight(self):
        """
        Prüft den Status der Eingänge während der Fahrt.
        """
        if not self._is_running:
            raise Exception("Thread wurde manuell gestoppt")

        try:
            res_inputs = self.client.read_discrete_inputs(0, count=8, device_id=1)
            time.sleep(0.04) # Schutzpause für den Pi 5 / Waveshare Puffer
            res_coils = self.client.read_coils(0, count=8, device_id=1)

            if res_inputs.isError() or res_coils.isError():
                raise Exception("Kommunikationsfehler: Fehlerantwort von Modbus")

            # REPARATUR FÜR DEN PI 5: 
            # Wir zwingen die Modbus-Bits in eine echte, feste Standard-Python-Liste [True, False, ...].
            # Das verhindert jegliche Zugriffsfehler (IndexError/TypeError) in den Schleifen!
            inputs = list(res_inputs.bits) if res_inputs.bits else [False]*8
            coils = list(res_coils.bits) if res_coils.bits else [False]*8

            if len(inputs) >= 6:
                self.latest_inputs = inputs # Speichert die saubere Liste im Thread
                self.io_update_signal.emit(inputs, coils)

                # Sicherheits-Check: Motorschutz (Index 0)
                if not inputs[0]:
                    raise Exception("Sicherheitskreis unterbrochen (Motorschutz)")

                return True

            raise Exception("Kommunikationsfehler: Ungültige IO-Daten")

        except Exception as e:
            raise Exception(f"Sicherheitsabbruch: {str(e)}")



    def run(self):
        start_time = time.time()
        
        # Watchdog-Zeiten zuweisen
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
                self.write_hardware_coil(0, True); time.sleep(0.1); self.write_hardware_coil(3, True)

                end_time_schnell = time.time() + self.times["Beschuss Schnell"]
                while time.time() < end_time_schnell:
                    check_watchdog()
                    self.check_inputs_during_flight()
                    time.sleep(0.05)

                self.write_hardware_coil(3, False); self.write_hardware_coil(2, True)

                end_time_langsam = time.time() + self.times["Beschuss Langsam"]
                while time.time() < end_time_langsam:
                    check_watchdog()
                    self.check_inputs_during_flight()
                    time.sleep(0.05)

                self.write_hardware_coil(0, False); self.write_hardware_coil(2, False)

            # ====================================================================
            # 2. MODUS: WERTUNG
            # ====================================================================
            elif self.mode == "Wertung":
                # Phase 1: Links-Lauf (1) und Schnell (3) einschalten
                self.write_hardware_coil(1, True)
                time.sleep(0.1)
                self.write_hardware_coil(3, True)
                self.status_signal.emit("Wertung: Schnellphase")

                # Schnellphase läuft exakt so lange, wie in "Wertung Schnell" definiert
                end_time_schnell = time.time() + self.times.get("Wertung Schnell", 2.5)
                while time.time() < end_time_schnell:
                    check_watchdog()
                    self.check_inputs_during_flight()
                    
                    # Sicherheitsnetz: Falls der Endschalter (Index 1) schon in der 
                    # Schnellphase getroffen wird, sofort abbrechen
                    if self.latest_inputs and self.latest_inputs[1]:
                        break
                    time.sleep(0.05)

                # Phase 2: Schnell (3) ausschalten und Langsam (2) einschalten
                self.write_hardware_coil(3, False)
                self.write_hardware_coil(2, True)
                self.status_signal.emit("Wertung: Langsamphase")

                # Langsamphase läuft nun so lange, bis der Endschalter (Index 1) schaltet
                while self._is_running:
                    check_watchdog()
                    self.check_inputs_during_flight()
                    
                    # Endschalter-Abfrage (Index 1) – stoppt die Fahrt im Ziel
                    if self.latest_inputs and self.latest_inputs[1]: 
                        break
                    time.sleep(0.05)

                # Nach dem Verlassen der Schleife (Endschalter erreicht): Alles sicher abschalten
                self.write_hardware_coil(1, False)
                self.write_hardware_coil(2, False)

            # ====================================================================
            # 3. MODUS: HOMEFAHRT
            # ====================================================================
            elif self.mode == "HomeFahrt":
                self.write_hardware_coil(1, True); time.sleep(0.1); self.write_hardware_coil(2, True)

                while self._is_running:
                    check_watchdog()
                    self.check_inputs_during_flight()
                    
                    if self.latest_inputs and self.latest_inputs[1]: 
                        break
                    time.sleep(0.05)

                self.write_hardware_coil(1, False); self.write_hardware_coil(2, False)

            self.drive_time_signal.emit(time.time() - start_time)
            self.finished_signal.emit()

        except Exception as e:
            # Im Fehlerfall sofort alle Ausgänge abschalten
            for i in range(8):
                self.write_hardware_coil(i, False)
                time.sleep(0.04)
            self.error_signal.emit(str(e))

    def stop(self):
        self._is_running = False
