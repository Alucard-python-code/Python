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
        self.movement_start_time = time.time()
        self._is_running = True 
        
        try:
            self.client.timeout = 0.5
            self.client.auto_open = True
        except:
            pass

    def stop(self):
        self._is_running = False

    def log_and_raise_error(self, message):
        logging.error(message)
        self.error_signal.emit(message)
        try:
            self.client.write_multiple_coils(0, [False] * 8)
        except:
            pass

    def write_hardware_coil(self, logischer_kanal, zustand):
        """ Übersetzt Software-Steuerbefehle dynamisch in reale Hardware-Kanäle """
        reales_relais = logischer_kanal
        inv_dir = self.times.get("Invertiere-Drehrichtung", False)
        inv_speed = self.times.get("Invertiere-Geschwindigkeit", False)

        # 1. Richtungstausch (0 <-> 1)
        if inv_dir:
            if reales_relais == 0: reales_relais = 1
            elif reales_relais == 1: reales_relais = 0

        # 2. Geschwindigkeitstausch (2 <-> 3)
        if inv_speed:
            if reales_relais == 2: reales_relais = 3
            elif reales_relais == 3: reales_relais = 2

        try:
            return self.client.write_single_coil(reales_relais, zustand)
        except Exception as e:
            logging.error(f"Fehler beim Modbus-Relais-Schreiben ({reales_relais}): {e}")
            return False

    def check_inputs_during_flight(self):
        if not self._is_running:
            return False
        try:
            if hasattr(self.client, 'is_open') and not self.client.is_open():
                self.client.open()
        except:
            pass

        inputs = None
        coils = [False] * 8
        try:
            inputs = self.client.read_discrete_inputs(0, 8)
            if not inputs or len(inputs) < 6:
                time.sleep(0.05)
                if hasattr(self.client, 'open'): self.client.open()
                inputs = self.client.read_discrete_inputs(0, 8)
                
            if inputs and len(inputs) >= 6:
                read_coils = self.client.read_coils(0, 8)
                if read_coils: coils = read_coils
        except Exception as e:
            inputs = None

        if not inputs or len(inputs) < 6:
            self.log_and_raise_error("Modbus-Verbindung verloren!")
            return False

        self.io_update_signal.emit(inputs, coils)

        motorschutz = inputs[0]
        endschalter_home = inputs[1]
        schuetz_rechts = inputs[2]
        schuetz_links = inputs[3]
        schuetz_langsam = inputs[4]
        schuetz_schnell = inputs[5]

        if not motorschutz:
            self.log_and_raise_error("FEHLER: Motorschutzschalter ausgelöst!")
            return False

        if self.mode == "HomeFahrt" and not self.ist_referenziert and schuetz_schnell:
            self.log_and_raise_error("FEHLER: Unerwarteter Schnelllauf bei unreferenzierter Home-Fahrt!")
            return False

        if schuetz_rechts and schuetz_links:
            self.log_and_raise_error("FEHLER: Schütz Rechtslauf und Linkslauf aktiv!")
            return False
        if schuetz_langsam and schuetz_schnell:
            self.log_and_raise_error("FEHLER: Schütz Langsam und Schnell aktiv!")
            return False

        if self.mode not in ["TippVor", "TippRueck"]:
            if self.mode == "HomeFahrt" and not self.ist_referenziert:
                return True
                
            if schuetz_rechts or schuetz_links:
                max_anlauf_zeit = self.times.get("Anlauf-Überwachung", 2.0)
                if time.time() - self.movement_start_time > max_anlauf_zeit:
                    if endschalter_home:
                        self.log_and_raise_error("FEHLER: Endschalter klemmt / defekt!")
                        return False
        return True

    def run(self):
        if hasattr(self, 'times') and "Modbus-IP" in self.times:
            self.client.host = self.times["Modbus-IP"]
            
        drive_start_timestamp = time.time()
        try:
            if self.mode == "Beschuss":
                self.status_signal.emit("Unterwegs")
                self.write_hardware_coil(0, True)
                time.sleep(0.05)
                self.write_hardware_coil(3, True)
                time.sleep(0.1)
                
                start = time.time()
                while time.time() - start < self.times["Beschuss Schnell"] and self._is_running:
                    if not self.check_inputs_during_flight(): return
                    time.sleep(0.05)
                    
                self.write_hardware_coil(3, False)
                self.write_hardware_coil(2, True)
                time.sleep(0.1)
                
                start = time.time()
                while time.time() - start < self.times["Beschuss Langsam"] and self._is_running:
                    if not self.check_inputs_during_flight(): return
                    time.sleep(0.05)
                    
                self.write_hardware_coil(0, False)
                time.sleep(0.05)
                self.write_hardware_coil(2, False)

            elif self.mode == "Wertung":
                self.status_signal.emit("Unterwegs")
                self.write_hardware_coil(1, True)
                time.sleep(0.05)
                self.write_hardware_coil(3, True)
                time.sleep(0.1)
                
                start = time.time()
                while time.time() - start < self.times["Wertung Schnell"] and self._is_running:
                    if not self.check_inputs_during_flight(): return
                    time.sleep(0.05)
                    
                self.write_hardware_coil(3, False)
                self.write_hardware_coil(2, True)
                time.sleep(0.1)
                
                watchdog_start = time.time()
                max_allowed_time = self.times.get("Sicherheits-Timeout", 15.0)
                while self._is_running:
                    if not self.check_inputs_during_flight(): return
                    if time.time() - watchdog_start > max_allowed_time:
                        self.log_and_raise_error("TIMEOUT: Endschalter nicht erreicht!")
                        return
                    inputs = self.client.read_discrete_inputs(0, 8)
                    if inputs and inputs[1]: break
                    time.sleep(0.05)
                    
                self.write_hardware_coil(1, False)
                time.sleep(0.05)
                self.write_hardware_coil(2, False)

            elif self.mode == "HomeFahrt":
                if not self.ist_referenziert:
                    self.status_signal.emit("Sicherheits-Homefahrt (Langsam)...")
                    self.write_hardware_coil(3, False) 
                    time.sleep(0.05)
                    self.write_hardware_coil(1, True)
                    time.sleep(0.1)
                    self.write_hardware_coil(2, True)
                    max_allowed_time = self.times.get("Home-Timeout", 25.0) * 1.5
                else:
                    self.status_signal.emit("Normale Home-Fahrt...")
                    self.write_hardware_coil(3, True)
                    time.sleep(0.05)
                    self.write_hardware_coil(1, True)
                    time.sleep(0.1)
                    self.write_hardware_coil(2, True)
                    max_allowed_time = self.times.get("Home-Timeout", 25.0)
                
                time.sleep(0.05)
                watchdog_start = time.time()
                
                while self._is_running:
                    if not self.check_inputs_during_flight(): return
                    if time.time() - watchdog_start > max_allowed_time:
                        self.log_and_raise_error("TIMEOUT: Startposition bei Home-Fahrt nicht erreicht!")
                        return
                    inputs = self.client.read_discrete_inputs(0, 8)
                    if inputs and inputs[1]: break
                    time.sleep(0.05)
                    
                self.write_hardware_coil(1, False)
                time.sleep(0.05)
                self.write_hardware_coil(2, False)
                time.sleep(0.05)
                self.write_hardware_coil(3, False)

            elif self.mode == "TippVor":
                self.status_signal.emit("Tippbetrieb Vorwärts...")
                self.write_hardware_coil(0, True)
                time.sleep(0.1)
                self.write_hardware_coil(2, True)
                while self._is_running:
                    if not self.check_inputs_during_flight(): return
                    time.sleep(0.05)

            elif self.mode == "TippRueck":
                self.status_signal.emit("Tippbetrieb Rückwärts...")
                self.write_hardware_coil(1, True)
                time.sleep(0.1)
                self.write_hardware_coil(2, True)
                while self._is_running:
                    if not self.check_inputs_during_flight(): return
                    inputs = self.client.read_discrete_inputs(0, 8)
                    if inputs and inputs[1]: break
                    time.sleep(0.05)

            actual_duration = time.time() - drive_start_timestamp
            self.drive_time_signal.emit(actual_duration)
            self.finished_signal.emit()
            
        except Exception as e:
            actual_duration = time.time() - drive_start_timestamp
            self.drive_time_signal.emit(actual_duration)
            self.log_and_raise_error(f"Kritischer Systemfehler im Ablauf-Thread: {e}")