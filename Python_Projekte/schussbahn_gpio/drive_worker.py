# -*- coding: utf-8 -*-
import time
import logging
from PyQt5.QtCore import QThread, pyqtSignal
from gpiozero import DigitalInputDevice, DigitalOutputDevice

class DriveThread(QThread):
    # Core-Signale zur thread-sicheren Kommunikation mit der Haupt-GUI
    status_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    drive_time_signal = pyqtSignal(float)
    io_update_signal = pyqtSignal(list, list)

    def __init__(self, mode, times):
        super().__init__()
        self.mode = mode
        self.times = times
        self.movement_start_time = time.time()
        self._is_running = True

        # Ausgänge initialisieren (Low-Active: active_high=False zieht den Pin im Idle hoch)
        self.out_rechts = DigitalOutputDevice(26, active_high=False, initial_value=False)
        self.out_links  = DigitalOutputDevice(19, active_high=False, initial_value=False)
        self.out_langsam = DigitalOutputDevice(13, active_high=False, initial_value=False)
        self.out_schnell = DigitalOutputDevice(6,  active_high=False, initial_value=False)
        self.out_licht   = DigitalOutputDevice(23, active_high=False, initial_value=False)

        # Eingänge initialisieren (Mit internem Pull-Up Widerstand)
        self.in_motorschutz = DigitalInputDevice(18, pull_up=True)
        self.in_endschalter = DigitalInputDevice(10, pull_up=True)
        self.in_schuetz_r   = DigitalInputDevice(20, pull_up=True)
        self.in_schuetz_l   = DigitalInputDevice(21, pull_up=True)
        self.in_schuetz_la  = DigitalInputDevice(16, pull_up=True)
        self.in_schuetz_sc  = DigitalInputDevice(12, pull_up=True)

    def stop(self):
        self._is_running = False

    def log_and_raise_error(self, message):
        logging.error(message)
        self.error_signal.emit(message)
        self.all_outputs_off()

    def all_outputs_off(self):
        self.out_rechts.off()
        self.out_links.off()
        self.out_langsam.off()
        self.out_schnell.off()

    def check_inputs_during_flight(self):
        if not self._is_running:
            return False
            
        # Live-Zustände einlesen
        ms = self.in_motorschutz.is_active
        es = self.in_endschalter.is_active
        sr = self.in_schuetz_r.is_active
        sl = self.in_schuetz_l.is_active
        sla = self.in_schuetz_la.is_active
        ssc = self.in_schuetz_sc.is_active

        inputs = [ms, es, sr, sl, sla, ssc]
        coils = [self.out_rechts.is_active, self.out_links.is_active, 
                 self.out_langsam.is_active, self.out_schnell.is_active, 
                 False, False, False, self.out_licht.is_active]

        self.io_update_signal.emit(inputs, coils)

        if not ms:
            self.log_and_raise_error("FEHLER: Motorschutzschalter ausgelöst!")
            return False
        if sr and sl:
            self.log_and_raise_error("FEHLER: Schütz Rechtslauf und Linkslauf aktiv!")
            return False
        if sla and ssc:
            self.log_and_raise_error("FEHLER: Schütz Langsam und Schnell aktiv!")
            return False

        if self.mode not in ["TippVor", "TippRueck"]:
            if sr or sl:
                if time.time() - self.movement_start_time > self.times.get("Anlauf-Überwachung", 2.0):
                    if es:
                        self.log_and_raise_error("FEHLER: Endschalter klemmt / defekt!")
                        return False
        return True

    def run(self):
        drive_start_timestamp = time.time()
        try:
            if self.mode == "Beschuss":
                self.status_signal.emit("Unterwegs")
                self.out_rechts.on()
                time.sleep(0.05)
                self.out_schnell.on()

                start = time.time()
                while time.time() - start < self.times["Beschuss Schnell"] and self._is_running:
                    if not self.check_inputs_during_flight(): return
                    time.sleep(0.05)

                self.out_schnell.off()
                self.out_langsam.on()
                time.sleep(0.1)

                start = time.time()
                while time.time() - start < self.times["Beschuss Langsam"] and self._is_running:
                    if not self.check_inputs_during_flight(): return
                    time.sleep(0.05)

                self.all_outputs_off()

            elif self.mode == "Wertung":
                self.status_signal.emit("Unterwegs")
                self.out_links.on()
                time.sleep(0.05)
                self.out_schnell.on()

                start = time.time()
                while time.time() - start < self.times["Wertung Schnell"] and self._is_running:
                    if not self.check_inputs_during_flight(): return
                    time.sleep(0.05)

                self.out_schnell.off()
                self.out_langsam.on()
                time.sleep(0.1)

                watchdog_start = time.time()
                while self._is_running:
                    if not self.check_inputs_during_flight(): return
                    if time.time() - watchdog_start > self.times.get("Sicherheits-Timeout", 15.0):
                        self.log_and_raise_error("TIMEOUT: Endschalter nicht erreicht!")
                        return
                    if self.in_endschalter.is_active: 
                        break
                    time.sleep(0.05)

                self.all_outputs_off()

            elif self.mode == "HomeFahrt":
                self.status_signal.emit("Home-Fahrt aktiv...")
                self.out_links.on()
                time.sleep(0.05)
                self.out_langsam.on()

                watchdog_start = time.time()
                while self._is_running:
                    if not self.check_inputs_during_flight(): return
                    if time.time() - watchdog_start > self.times.get("Home-Timeout", 25.0):
                        self.log_and_raise_error("TIMEOUT: Startposition nicht erreicht!")
                        return
                    if self.in_endschalter.is_active: 
                        break
                    time.sleep(0.05)

                self.all_outputs_off()

            elif self.mode == "TippVor":
                self.status_signal.emit("Tippbetrieb Vorwärts...")
                self.out_rechts.on()
                time.sleep(0.1)
                self.out_langsam.on()
                while self._is_running:
                    if not self.check_inputs_during_flight(): return
                    time.sleep(0.05)

            elif self.mode == "TippRueck":
                self.status_signal.emit("Tippbetrieb Rückwärts...")
                self.out_links.on()
                time.sleep(0.1)
                self.out_langsam.on()
                while self._is_running:
                    if not self.check_inputs_during_flight(): return
                    if self.in_endschalter.is_active: 
                        break
                    time.sleep(0.05)

            self.all_outputs_off()
            self.drive_time_signal.emit(time.time() - drive_start_timestamp)
            self.finished_signal.emit()

        except Exception as e:
            self.all_outputs_off()
            self.drive_time_signal.emit(time.time() - drive_start_timestamp)
            self.log_and_raise_error(f"Kritischer Systemfehler: {e}")
