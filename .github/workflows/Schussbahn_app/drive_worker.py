# -*- coding: utf-8 -*-
import time
import logging
from PyQt5.QtCore import QThread, pyqtSignal

class DriveThread(QThread):
    status_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    drive_time_signal = pyqtSignal(float)

    def __init__(self, mode, client, times):
        super().__init__()
        self.mode = mode
        self.client = client
        self.times = times
        self.movement_start_time = time.time()

    def log_and_raise_error(self, message):
        logging.error(message)
        self.error_signal.emit(message)
        try:
            self.client.write_multiple_coils(0, [False] * 8)
        except:
            pass

    def check_inputs_during_flight(self):
        inputs = self.client.read_discrete_inputs(0, 8)
        if not inputs or len(inputs) < 6:
            self.log_and_raise_error("Modbus-Verbindung verloren!")
            return False
            
        if hasattr(self.client, 'main_app_ref'):
            self.client.main_app_ref.latest_inputs = inputs
            try:
                coils = self.client.read_coils(0, 8)
                if coils:
                    self.client.main_app_ref.latest_coils = coils
            except:
                pass

        motorschutz = inputs[0]
        endschalter_home = inputs[1]       # In2: Endschalter Startposition
        schuetz_rechts = inputs[2]         # In3: Schütz Rückmeldung Rechtslauf
        schuetz_links = inputs[3]          # In4: Schütz Rückmeldung Linkslauf
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
            
        # ====================================================================
        # ÜBERWACHUNG: ENDSCHALTER KLEMMT / ANLAUF-TIMEOUT
        # ====================================================================
        # NEU: Diese zeitliche Prüfung wird im Einrichtbetrieb (Tippbetrieb) komplett IGNORIERT!
        if self.mode not in ["TippVor", "TippRueck"]:
            if schuetz_rechts or schuetz_links:
                max_anlauf_zeit = self.times.get("Anlauf-Überwachung", 2.0)
                
                if time.time() - self.movement_start_time > max_anlauf_zeit:
                    if endschalter_home:
                        self.log_and_raise_error("FEHLER: Endschalter klemmt / defekt (nicht verlassen)!")
                        return False
        # ====================================================================
        
        return True

    def run(self):
        # NEU: Vor dem allerersten Befehl die IP-Adresse aus den aktuellen Settings erzwingen!
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
                while time.time() - start < self.times["Beschuss Schnell"]:
                    if not self.check_inputs_during_flight(): return
                    time.sleep(0.05)
                
                self.client.write_single_coil(3, False)
                self.client.write_single_coil(2, True)
                time.sleep(0.1)
                
                start = time.time()
                while time.time() - start < self.times["Beschuss Langsam"]:
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
                while time.time() - start < self.times["Wertung Schnell"]:
                    if not self.check_inputs_during_flight(): return
                    time.sleep(0.05)
                
                self.client.write_single_coil(3, False)
                self.client.write_single_coil(2, True)
                time.sleep(0.1)
                
                watchdog_start = time.time()
                max_allowed_time = self.times.get("Sicherheits-Timeout", 15.0)  
                
                while True:
                    if not self.check_inputs_during_flight(): return
                    if time.time() - watchdog_start > max_allowed_time:
                        self.log_and_raise_error("TIMEOUT: Endschalter nicht rechtzeitig erreicht!")
                        return
                        
                    inputs = self.client.read_discrete_inputs(0, 8)
                    if inputs and inputs[1]:  # In2: Endschalter erreicht
                        break
                    time.sleep(0.05)
                    
                self.client.write_single_coil(1, False)
                time.sleep(0.05)
                self.client.write_single_coil(2, False)

            elif self.mode == "HomeFahrt":
                self.status_signal.emit("Home-Fahrt aktiv...")
                
                # SICHERHEITS-SCHRITT: Schnelllauf (Ch4 / Coil 3) SOFORT als Erstes hart abschalten
                self.client.write_single_coil(3, False)
                time.sleep(0.05) # Kurz warten, damit das Schnelllauf-Schütz sicher abfällt
                
                # Jetzt erst Richtung Linkslauf (Ch2 / Coil 1) einschalten
                self.client.write_single_coil(1, True)
                
                # Mechanische Pause für das Richtungsschütz (wichtig!)
                time.sleep(0.1) 
                
                # Jetzt exklusiv AUSGANG LANGSAM (Ch3 / Coil 2) einschalten
                self.client.write_single_coil(2, True)
                time.sleep(0.05)
                
                watchdog_start = time.time()
                # ... ab hier läuft dein normaler "while True" Code der HomeFahrt weiter ...

                # NEU: Lädt das spezifische Home-Timeout. Falls nicht vorhanden, greifen 25.0s Schutzzeit.
                max_allowed_time = self.times.get("Home-Timeout", 25.0)
                
                while True:
                    if not self.check_inputs_during_flight(): return
                    
                    # Prüfung auf das eigene, längere Home-Timeout
                    if time.time() - watchdog_start > max_allowed_time:
                        self.log_and_raise_error("TIMEOUT: Startposition bei Home-Fahrt nicht erreicht!")
                        return
                        
                    inputs = self.client.read_discrete_inputs(0, 8)
                    if inputs and inputs[1]:  # In2: Startposition erreicht
                        break
                    time.sleep(0.05)
                    
                self.client.write_single_coil(1, False)
                time.sleep(0.05)
                self.client.write_single_coil(2, False)

            # ========================================================
            # NEU: MANUELLER TIPPBETRIEB VORWÄRTS (LANGSAM)
            # ========================================================
            elif self.mode == "TippVor":
                self.status_signal.emit("Tippbetrieb Vorwärts...")
                self.client.write_single_coil(0, True)   # Rechtslauf (Ch1) an
                time.sleep(0.1)
                self.client.write_single_coil(2, True)   # Langsam (Ch3) an
                
                while True:
                    if not self.check_inputs_during_flight(): return
                    time.sleep(0.05) # Läuft endlos, bis die Haupt-App den Thread stoppt

            # ========================================================
            # NEU: MANUELLER TIPPBETRIEB RÜCKWÄRTS (LANGSAM)
            # ========================================================
            elif self.mode == "TippRueck":
                self.status_signal.emit("Tippbetrieb Rückwärts...")
                self.client.write_single_coil(1, True)   # Linkslauf (Ch2) an
                time.sleep(0.1)
                self.client.write_single_coil(2, True)   # Langsam (Ch3) an
                
                while True:
                    if not self.check_inputs_during_flight(): return
                    # Da wir rückwärts fahren, stoppen wir auch hier beim Endschalter In2
                    inputs = self.client.read_discrete_inputs(0, 8)
                    if inputs and inputs[1]: 
                        break
                    time.sleep(0.05)

                
            # Fahrzeit-Signal senden
            actual_duration = time.time() - drive_start_timestamp
            self.drive_time_signal.emit(actual_duration)
            self.finished_signal.emit()
            
        except Exception as e:
            actual_duration = time.time() - drive_start_timestamp
            self.drive_time_signal.emit(actual_duration)
            self.log_and_raise_error(f"Kritischer Systemfehler im Ablauf-Thread: {e}")
