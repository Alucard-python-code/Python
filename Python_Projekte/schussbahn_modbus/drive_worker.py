<<<<<<< HEAD
# -*- coding: utf-8 -*-
import time
import logging
from PyQt5.QtCore import QThread, pyqtSignal

class DriveThread(QThread):
    # Core-Signale zur thread-sicheren Kommunikation mit der Haupt-GUI
    status_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    drive_time_signal = pyqtSignal(float)
    io_update_signal = pyqtSignal(list, list) # Sendet Inputs und Coils gesammelt an GUI

    def __init__(self, mode, client, times):
        super().__init__()
        self.mode = mode
        self.client = client
        self.times = times
        self.movement_start_time = time.time()
        self._is_running = True # Sicheres Flag für Thread-Beendigung

    def stop(self):
        """ Beendet den Thread kontrolliert ohne Absturzrisiko """
        self._is_running = False

    def log_and_raise_error(self, message):
        logging.error(message)
        self.error_signal.emit(message)
        try:
            self.client.write_multiple_coils(0, [False] * 8)
        except:
            pass

    def check_inputs_during_flight(self):
        if not self._is_running:
            return False
            
        inputs = self.client.read_discrete_inputs(0, 8)
        if not inputs or len(inputs) < 6:
            self.log_and_raise_error("Modbus-Verbindung verloren!")
            return False

        coils = [False] * 8
        try:
            read_coils = self.client.read_coils(0, 8)
            if read_coils:
                coils = read_coils
        except:
            pass

        # Thread-sicheres Senden der Zustände an die Haupt-App
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
        if schuetz_rechts and schuetz_links:
            self.log_and_raise_error("FEHLER: Schütz Rechtslauf und Linkslauf aktiv!")
            return False
        if schuetz_langsam and schuetz_schnell:
            self.log_and_raise_error("FEHLER: Schütz Langsam und Schnell aktiv!")
            return False

        if self.mode not in ["TippVor", "TippRueck"]:
            if schuetz_rechts or schuetz_links:
                max_anlauf_zeit = self.times.get("Anlauf-Überwachung", 2.0)
                if time.time() - self.movement_start_time > max_anlauf_zeit:
                    if endschalter_home:
                        self.log_and_raise_error("FEHLER: Endschalter klemmt / defekt (nicht verlassen)!")
                        return False
        return True

    def run(self):
        if hasattr(self, 'times') and "Modbus-IP" in self.times:
            self.client.host = self.times["Modbus-IP"]
        drive_start_timestamp = time.time()
        
        try:
            if self.mode == "Beschuss":
                self.status_signal.emit("Unterwegs")
                self.client.write_single_coil(0, True)
                time.sleep(0.05)
                self.client.write_single_coil(3, True)
                time.sleep(0.1)

                start = time.time()
                while time.time() - start < self.times["Beschuss Schnell"] and self._is_running:
                    if not self.check_inputs_during_flight(): return
                    time.sleep(0.05)

                self.client.write_single_coil(3, False)
                self.client.write_single_coil(2, True)
                time.sleep(0.1)

                start = time.time()
                while time.time() - start < self.times["Beschuss Langsam"] and self._is_running:
                    if not self.check_inputs_during_flight(): return
                    time.sleep(0.05)

                self.client.write_single_coil(0, False)
                time.sleep(0.05)
                self.client.write_single_coil(2, False)

            elif self.mode == "Wertung":
                self.status_signal.emit("Unterwegs")
                self.client.write_single_coil(1, True)
                time.sleep(0.05)
                self.client.write_single_coil(3, True)
                time.sleep(0.1)

                start = time.time()
                while time.time() - start < self.times["Wertung Schnell"] and self._is_running:
                    if not self.check_inputs_during_flight(): return
                    time.sleep(0.05)

                self.client.write_single_coil(3, False)
                self.client.write_single_coil(2, True)
                time.sleep(0.1)

                watchdog_start = time.time()
                max_allowed_time = self.times.get("Sicherheits-Timeout", 15.0) 

                while self._is_running:
                    if not self.check_inputs_during_flight(): return
                    if time.time() - watchdog_start > max_allowed_time:
                        self.log_and_raise_error("TIMEOUT: Endschalter nicht rechtzeitig erreicht!")
                        return
                    inputs = self.client.read_discrete_inputs(0, 8)
                    if inputs and inputs[1]: 
                        break
                    time.sleep(0.05)

                self.client.write_single_coil(1, False)
                time.sleep(0.05)
                self.client.write_single_coil(2, False)

            elif self.mode == "HomeFahrt":
                self.status_signal.emit("Home-Fahrt aktiv...")
                self.client.write_single_coil(3, False)
                time.sleep(0.05)
                self.client.write_single_coil(1, True)
                time.sleep(0.1) 
                self.client.write_single_coil(2, True)
                time.sleep(0.05)

                watchdog_start = time.time()
                max_allowed_time = self.times.get("Home-Timeout", 25.0)

                while self._is_running:
                    if not self.check_inputs_during_flight(): return
                    if time.time() - watchdog_start > max_allowed_time:
                        self.log_and_raise_error("TIMEOUT: Startposition bei Home-Fahrt nicht erreicht!")
                        return
                    inputs = self.client.read_discrete_inputs(0, 8)
                    if inputs and inputs[1]: 
                        break
                    time.sleep(0.05)

                self.client.write_single_coil(1, False)
                time.sleep(0.05)
                self.client.write_single_coil(2, False)

            elif self.mode == "TippVor":
                self.status_signal.emit("Tippbetrieb Vorwärts...")
                self.client.write_single_coil(0, True)
                time.sleep(0.1)
                self.client.write_single_coil(2, True)
                while self._is_running:
                    if not self.check_inputs_during_flight(): return
                    time.sleep(0.05)

            elif self.mode == "TippRueck":
                self.status_signal.emit("Tippbetrieb Rückwärts...")
                self.client.write_single_coil(1, True)
                time.sleep(0.1)
                self.client.write_single_coil(2, True)
                while self._is_running:
                    if not self.check_inputs_during_flight(): return
                    inputs = self.client.read_discrete_inputs(0, 8)
                    if inputs and inputs[1]: 
                        break
                    time.sleep(0.05)

            actual_duration = time.time() - drive_start_timestamp
            self.drive_time_signal.emit(actual_duration)
            self.finished_signal.emit()

        except Exception as e:
            actual_duration = time.time() - drive_start_timestamp
            self.drive_time_signal.emit(actual_duration)
            self.log_and_raise_error(f"Kritischer Systemfehler im Ablauf-Thread: {e}")
=======
# -*- coding: utf-8 -*-
import time
import logging
from PyQt5.QtCore import QThread, pyqtSignal

class DriveThread(QThread):
    # Core-Signale zur thread-sicheren Kommunikation mit der Haupt-GUI
    status_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    drive_time_signal = pyqtSignal(float)
    io_update_signal = pyqtSignal(list, list) # Sendet Inputs und Coils gesammelt an GUI

    def __init__(self, mode, client, times):
        super().__init__()
        self.mode = mode
        self.client = client
        self.times = times
        self.movement_start_time = time.time()
        self._is_running = True # Sicheres Flag für Thread-Beendigung

    def stop(self):
        """ Beendet den Thread kontrolliert ohne Absturzrisiko """
        self._is_running = False

    def log_and_raise_error(self, message):
        logging.error(message)
        self.error_signal.emit(message)
        try:
            self.client.write_multiple_coils(0, [False] * 8)
        except:
            pass

    def check_inputs_during_flight(self):
        if not self._is_running:
            return False
            
        inputs = self.client.read_discrete_inputs(0, 8)
        if not inputs or len(inputs) < 6:
            self.log_and_raise_error("Modbus-Verbindung verloren!")
            return False

        coils = [False] * 8
        try:
            read_coils = self.client.read_coils(0, 8)
            if read_coils:
                coils = read_coils
        except:
            pass

        # Thread-sicheres Senden der Zustände an die Haupt-App
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
        if schuetz_rechts and schuetz_links:
            self.log_and_raise_error("FEHLER: Schütz Rechtslauf und Linkslauf aktiv!")
            return False
        if schuetz_langsam and schuetz_schnell:
            self.log_and_raise_error("FEHLER: Schütz Langsam und Schnell aktiv!")
            return False

        if self.mode not in ["TippVor", "TippRueck"]:
            if schuetz_rechts or schuetz_links:
                max_anlauf_zeit = self.times.get("Anlauf-Überwachung", 2.0)
                if time.time() - self.movement_start_time > max_anlauf_zeit:
                    if endschalter_home:
                        self.log_and_raise_error("FEHLER: Endschalter klemmt / defekt (nicht verlassen)!")
                        return False
        return True

    def run(self):
        if hasattr(self, 'times') and "Modbus-IP" in self.times:
            self.client.host = self.times["Modbus-IP"]
        drive_start_timestamp = time.time()
        
        try:
            if self.mode == "Beschuss":
                self.status_signal.emit("Unterwegs")
                self.client.write_single_coil(0, True)
                time.sleep(0.05)
                self.client.write_single_coil(3, True)
                time.sleep(0.1)

                start = time.time()
                while time.time() - start < self.times["Beschuss Schnell"] and self._is_running:
                    if not self.check_inputs_during_flight(): return
                    time.sleep(0.05)

                self.client.write_single_coil(3, False)
                self.client.write_single_coil(2, True)
                time.sleep(0.1)

                start = time.time()
                while time.time() - start < self.times["Beschuss Langsam"] and self._is_running:
                    if not self.check_inputs_during_flight(): return
                    time.sleep(0.05)

                self.client.write_single_coil(0, False)
                time.sleep(0.05)
                self.client.write_single_coil(2, False)

            elif self.mode == "Wertung":
                self.status_signal.emit("Unterwegs")
                self.client.write_single_coil(1, True)
                time.sleep(0.05)
                self.client.write_single_coil(3, True)
                time.sleep(0.1)

                start = time.time()
                while time.time() - start < self.times["Wertung Schnell"] and self._is_running:
                    if not self.check_inputs_during_flight(): return
                    time.sleep(0.05)

                self.client.write_single_coil(3, False)
                self.client.write_single_coil(2, True)
                time.sleep(0.1)

                watchdog_start = time.time()
                max_allowed_time = self.times.get("Sicherheits-Timeout", 15.0) 

                while self._is_running:
                    if not self.check_inputs_during_flight(): return
                    if time.time() - watchdog_start > max_allowed_time:
                        self.log_and_raise_error("TIMEOUT: Endschalter nicht rechtzeitig erreicht!")
                        return
                    inputs = self.client.read_discrete_inputs(0, 8)
                    if inputs and inputs[1]: 
                        break
                    time.sleep(0.05)

                self.client.write_single_coil(1, False)
                time.sleep(0.05)
                self.client.write_single_coil(2, False)

            elif self.mode == "HomeFahrt":
                self.status_signal.emit("Home-Fahrt aktiv...")
                self.client.write_single_coil(3, False)
                time.sleep(0.05)
                self.client.write_single_coil(1, True)
                time.sleep(0.1) 
                self.client.write_single_coil(2, True)
                time.sleep(0.05)

                watchdog_start = time.time()
                max_allowed_time = self.times.get("Home-Timeout", 25.0)

                while self._is_running:
                    if not self.check_inputs_during_flight(): return
                    if time.time() - watchdog_start > max_allowed_time:
                        self.log_and_raise_error("TIMEOUT: Startposition bei Home-Fahrt nicht erreicht!")
                        return
                    inputs = self.client.read_discrete_inputs(0, 8)
                    if inputs and inputs[1]: 
                        break
                    time.sleep(0.05)

                self.client.write_single_coil(1, False)
                time.sleep(0.05)
                self.client.write_single_coil(2, False)

            elif self.mode == "TippVor":
                self.status_signal.emit("Tippbetrieb Vorwärts...")
                self.client.write_single_coil(0, True)
                time.sleep(0.1)
                self.client.write_single_coil(2, True)
                while self._is_running:
                    if not self.check_inputs_during_flight(): return
                    time.sleep(0.05)

            elif self.mode == "TippRueck":
                self.status_signal.emit("Tippbetrieb Rückwärts...")
                self.client.write_single_coil(1, True)
                time.sleep(0.1)
                self.client.write_single_coil(2, True)
                while self._is_running:
                    if not self.check_inputs_during_flight(): return
                    inputs = self.client.read_discrete_inputs(0, 8)
                    if inputs and inputs[1]: 
                        break
                    time.sleep(0.05)

            actual_duration = time.time() - drive_start_timestamp
            self.drive_time_signal.emit(actual_duration)
            self.finished_signal.emit()

        except Exception as e:
            actual_duration = time.time() - drive_start_timestamp
            self.drive_time_signal.emit(actual_duration)
            self.log_and_raise_error(f"Kritischer Systemfehler im Ablauf-Thread: {e}")
>>>>>>> aea6e0f3cc44f05c8b75f9cd480e934127c702a5
