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
        if not self._is_running:
            raise Exception("Thread wurde manuell gestoppt")

        try:
            inputs = self.client.read_discrete_inputs(0, 8)
            coils = self.client.read_coils(0, 8)

            if inputs and len(inputs) >= 6:
                self.io_update_signal.emit(inputs, coils if coils else [False]*8)

                if not inputs[0]:
                    raise Exception("Sicherheitskreis unterbrochen (Motorschutz)")
                return True

            raise Exception("Kommunikationsfehler: Ungültige IO-Daten empfangen")
        except Exception as e:
            raise Exception(f"{str(e)}")

    def run(self):
        start_time = time.time()
        
        # Watchdog-Zeiten zuweisen
        if self.mode == "Beschuss":
            wd_limit = self.times.get("Watchdog Beschuss", 10.0)
        elif self.mode == "Wertung":
            wd_limit = self.times.get("Watchdog Wertung", 10.0)
        else:
            wd_limit = self.times.get("Watchdog HomeFahrt", 20.0) # Einstellbarer oder fester Standard-Wert

        try:
            def check_watchdog():
                if (time.time() - start_time) > wd_limit:
                    if self.mode == "HomeFahrt":
                        # Spezieller Text für das Abfragefenster in der GUI
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
                self.write_hardware_coil(1, True); time.sleep(0.1); self.write_hardware_coil(3, True)

                while self._is_running:
                    check_watchdog()
                    self.check_inputs_during_flight()
                    
                    inputs = self.client.read_discrete_inputs(0, 8)
                    if inputs and inputs[1]: 
                        break
                    time.sleep(0.05)

                self.write_hardware_coil(1, False); self.write_hardware_coil(3, False)

            # ====================================================================
            # 3. MODUS: HOMEFAHRT
            # ====================================================================
            elif self.mode == "HomeFahrt":
                self.write_hardware_coil(1, True); time.sleep(0.1); self.write_hardware_coil(2, True)

                while self._is_running:
                    check_watchdog()
                    self.check_inputs_during_flight()
                    
                    inputs = self.client.read_discrete_inputs(0, 8)
                    if inputs and inputs[1]: 
                        break
                    time.sleep(0.05)

                self.write_hardware_coil(1, False); self.write_hardware_coil(2, False)

            self.drive_time_signal.emit(time.time() - start_time)
            self.finished_signal.emit()

        except Exception as e:
            # Im Fehlerfall sofort alle Ausgänge abschalten
            for i in range(8):
                self.write_hardware_coil(i, False)
            self.error_signal.emit(str(e))

    def stop(self):
        self._is_running = False
