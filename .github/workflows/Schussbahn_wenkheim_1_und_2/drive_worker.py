# drive_worker.py - v2.0 (GPIO-Direktverdrahtung)
import time
import logging
from PyQt5.QtCore import QThread, pyqtSignal
import RPi.GPIO as GPIO
from config_loader import PINS_OUT, PINS_IN

class DriveThread(QThread):
    status_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    drive_time_signal = pyqtSignal(float)

    def __init__(self, mode, parent_app, times):
        super().__init__()
        self.mode = mode
        self.main_app = parent_app
        self.times = times
        self.movement_start_time = time.time()

    def log_and_raise_error(self, message):
        logging.error(message)
        self.error_signal.emit(message)
        # Im Notfall alle Schütze sofort hart abschalten (True = AUS bei deiner Relaiskarte)
        for pin in PINS_OUT.values():
            if pin != PINS_OUT["Licht"]: # Licht anlassen
                GPIO.output(pin, True)

    def check_inputs_during_flight(self):
        """Liest die physischen Pi-Pins aus und prüft Schütze & Motorschutz."""
        motorschutz = GPIO.input(PINS_IN["Motorschutz"])
        endschalter_home = GPIO.input(PINS_IN["Endschalter"])
        schuetz_rechts = GPIO.input(PINS_IN["Feedback_Rechts"])
        schuetz_links = GPIO.input(PINS_IN["Feedback_Links"])
        schuetz_langsam = GPIO.input(PINS_IN["Feedback_Langsam"])
        schuetz_schnell = GPIO.input(PINS_IN["Feedback_Schnell"])

        # Werte für das Live-Diagnosefenster bereitstellen
        self.main_app.latest_inputs = [
            motorschutz, endschalter_home, schuetz_rechts, 
            schuetz_links, schuetz_langsam, schuetz_schnell
        ]
        self.main_app.latest_coils = [
            not GPIO.output(PINS_OUT["Rechtslauf"]), not GPIO.output(PINS_OUT["Linkslauf"]),
            not GPIO.output(PINS_OUT["Langsam"]), not GPIO.output(PINS_OUT["Schnell"])
        ]

        if not motorschutz:
            self.log_and_raise_error("FEHLER: Motorschutzschalter ausgelöst!")
            return False
        if schuetz_rechts and schuetz_links:
            self.log_and_raise_error("FEHLER: Schütz Rechtslauf und Linkslauf aktiv!")
            return False
        if schuetz_langsam and schuetz_schnell:
            self.log_and_raise_error("FEHLER: Schütz Langsam und Schnell aktiv!")
            return False

        # Überwachung: Anlauf-Timeout (wird im Tippbetrieb ignoriert)
        if self.mode not in ["TippVor", "TippRueck"]:
            if schuetz_rechts or schuetz_links:
                max_anlauf_zeit = self.times.get("Anlauf-Überwachung", 2.0)
                if time.time() - self.movement_start_time > max_anlauf_zeit:
                    if endschalter_home:
                        self.log_and_raise_error("FEHLER: Endschalter klemmt / nicht verlassen!")
                        return False
        return True

    def run(self):
        drive_start_timestamp = time.time()
        time_bremse = 0.2
        time_umschalt = 0.05
        time_anschlag = 0.4
        
        try:
            # --- MODUS BESCHUSS (Vorwärts Richtung Kugelfang) ---
            if self.mode == "Beschuss":
                self.status_signal.emit("Unterwegs")
                GPIO.output(PINS_OUT["Rechtslauf"], False) # Einschalten (LOW-aktiv)
                time.sleep(time_bremse)
                GPIO.output(PINS_OUT["Schnell"], False)
                
                start = time.time()
                while time.time() - start < self.times["Beschuss Schnell"]:
                    if not self.check_inputs_during_flight(): return
                    time.sleep(0.05)

                GPIO.output(PINS_OUT["Schnell"], True) # Ausschalten (HIGH)
                time.sleep(time_umschalt)
                GPIO.output(PINS_OUT["Langsam"], False) # Umschalten auf Langsam
                
                start = time.time()
                while time.time() - start < self.times["Beschuss Langsam"]:
                    if not self.check_inputs_during_flight(): return
                    time.sleep(0.05)

                GPIO.output(PINS_OUT["Rechtslauf"], True)
                time.sleep(time_bremse)
                GPIO.output(PINS_OUT["Langsam"], True)

            # --- MODUS WERTUNG (Rückwärts Richtung Schützenstand bis Endschalter) ---
            elif self.mode == "Wertung":
                self.status_signal.emit("Unterwegs")
                GPIO.output(PINS_OUT["Linkslauf"], False)
                time.sleep(time_bremse)
                GPIO.output(PINS_OUT["Schnell"], False)
                
                start = time.time()
                while time.time() - start < self.times["Wertung Schnell"]:
                    if not self.check_inputs_during_flight(): return
                    time.sleep(0.05)

                GPIO.output(PINS_OUT["Schnell"], True)
                time.sleep(time_umschalt)
                GPIO.output(PINS_OUT["Langsam"], False)
                
                watchdog_start = time.time()
                max_allowed_time = self.times.get("Sicherheits-Timeout", 15.0)

                while True:
                    if not self.check_inputs_during_flight(): return
                    if time.time() - watchdog_start > max_allowed_time:
                        self.log_and_raise_error("TIMEOUT: Endschalter nicht rechtzeitig erreicht!")
                        return
                    
                    if GPIO.input(PINS_IN["Endschalter"]): # Endschalter erreicht!
                        break
                    time.sleep(0.05)

                time.sleep(time_anschlag)
                GPIO.output(PINS_OUT["Linkslauf"], True)
                time.sleep(time_bremse)
                GPIO.output(PINS_OUT["Langsam"], True)

            # --- MODUS HOMEFAHRT (Automatische Initialisierung bei Start) ---
            elif self.mode == "HomeFahrt":
                self.status_signal.emit("Home-Fahrt aktiv...")
                GPIO.output(PINS_OUT["Schnell"], True) # Sicherheitshalber aus
                time.sleep(time_umschalt)
                GPIO.output(PINS_OUT["Linkslauf"], False)
                time.sleep(time_bremse)
                GPIO.output(PINS_OUT["Langsam"], False)
                
                watchdog_start = time.time()
                max_allowed_time = self.times.get("Home-Timeout", 25.0)

                while True:
                    if not self.check_inputs_during_flight(): return
                    if time.time() - watchdog_start > max_allowed_time:
                        self.log_and_raise_error("TIMEOUT: Startposition bei Home-Fahrt nicht erreicht!")
                        return
                    if GPIO.input(PINS_IN["Endschalter"]): 
                        break
                    time.sleep(0.05)

                time.sleep(time_anschlag)
                GPIO.output(PINS_OUT["Linkslauf"], True)
                time.sleep(time_bremse)
                GPIO.output(PINS_OUT["Langsam"], True)

            # --- MANUELLER TIPPBETRIEB VORWÄRTS ---
            elif self.mode == "TippVor":
                self.status_signal.emit("Tippbetrieb Vorwärts...")
                GPIO.output(PINS_OUT["Rechtslauf"], False)
                time.sleep(time_bremse)
                GPIO.output(PINS_OUT["Langsam"], False)
                while True:
                    if not self.check_inputs_during_flight(): return
                    time.sleep(0.05)

            # --- MANUELLER TIPPBETRIEB RÜCKWÄRTS ---
            elif self.mode == "TippRueck":
                self.status_signal.emit("Tippbetrieb Rückwärts...")
                GPIO.output(PINS_OUT["Linkslauf"], False)
                time.sleep(time_bremse)
                GPIO.output(PINS_OUT["Langsam"], False)
                while True:
                    if not self.check_inputs_during_flight(): return
                    if GPIO.input(PINS_IN["Endschalter"]): 
                        break
                    time.sleep(0.05)

            actual_duration = time.time() - drive_start_timestamp
            self.drive_time_signal.emit(actual_duration)
            self.finished_signal.emit()

        except Exception as e:
            actual_duration = time.time() - drive_start_timestamp
            self.drive_time_signal.emit(actual_duration)
            self.log_and_raise_error(f"Kritischer Systemfehler im Ablauf-Thread: {e}")
