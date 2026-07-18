#!/usr/bin/python3
# -*- coding: utf-8 -*-
import time
from PyQt5.QtCore import QThread, pyqtSignal

class DriveThread(QThread):
    status_signal = pyqtSignal(str)
    drive_time_signal = pyqtSignal(float)
    io_update_signal = pyqtSignal(list, list)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, mode, times, ist_referenziert, out_data, in_data):
        super().__init__()
        self.mode = mode
        self.times = times
        self.ist_referenziert = ist_referenziert
        self._running = True
        
        # Hardware entpacken
        self.out_rechts, self.out_links, self.out_langsam, self.out_schnell, self.out_licht = out_data
        self.in_motorschutz, self.in_endschalter, self.in_schuetz_r, self.in_schuetz_l, \
        self.in_schuetz_la, self.in_schuetz_sc = in_data

    def stop(self):
        self._running = False

    def emit_io_state(self):
        inputs = [
            int(self.in_motorschutz.is_active),
            int(self.in_endschalter.is_active),
            int(self.in_schuetz_r.is_active),
            int(self.in_schuetz_l.is_active),
            int(self.in_schuetz_la.is_active),
            int(self.in_schuetz_sc.is_active)
        ]
        coils = [
            self.out_rechts.is_active,
            self.out_links.is_active,
            self.out_langsam.is_active,
            self.out_schnell.is_active,
            False, False, False,
            self.out_licht.is_active
        ]
        self.io_update_signal.emit(inputs, coils)

    def check_hardware_feedback(self, r=False, l=False, la=False, sc=False):
        self.emit_io_state()
        if not self.in_motorschutz.is_active:
            self.error_signal.emit("FEHLER: Motorschutzschalter ausgelöst!")
            return False
        if r and not self.in_schuetz_r.is_active:
            self.error_signal.emit("FEHLER: Schütz Rechts zieht nicht an!")
            return False
        if l and not self.in_schuetz_l.is_active:
            self.error_signal.emit("FEHLER: Schütz Links zieht nicht an!")
            return False
        if la and not self.in_schuetz_la.is_active:
            self.error_signal.emit("FEHLER: Schütz Langsam zieht nicht an!")
            return False
        if sc and not self.in_schuetz_sc.is_active:
            self.error_signal.emit("FEHLER: Schütz Schnell zieht nicht an!")
            return False
        return True

    def run(self):
        start_time = time.time()
        self.status_signal.emit("Unterwegs")

        try:
            if self.mode == "Beschuss":
                if not self.execute_beschuss(): return
            elif self.mode == "Wertung":
                if not self.execute_wertung(): return
            elif self.mode == "HomeFahrt":
                if not self.execute_homefahrt(): return
            elif self.mode == "TippVor":
                if not self.execute_tipp(vorwaerts=True): return
            elif self.mode == "TippRueck":
                if not self.execute_tipp(vorwaerts=False): return

            duration = time.time() - start_time
            self.drive_time_signal.emit(duration)
            self.status_signal.emit("Fertig")
            self.finished_signal.emit()

        except Exception as e:
            self.all_outputs_off()
            self.error_signal.emit(f"FEHLER: Unerwarteter Thread-Abbruch: {str(e)}")

    def all_outputs_off(self):
        self.out_rechts.off()
        self.out_links.off()
        self.out_langsam.off()
        self.out_schnell.off()

    def sleep_and_check(self, duration):
        steps = int(duration / 0.05)
        for _ in range(max(1, steps)):
            if not self._running:
                return False
            time.sleep(0.05)
            self.emit_io_state()
            if not self.in_motorschutz.is_active:
                self.error_signal.emit("FEHLER: Motorschutzschalter während der Fahrt ausgelöst!")
                return False
        return True

    def execute_beschuss(self):
        # 1. Start Vorwärts Schnell
        self.out_rechts.on()
        self.out_schnell.on()
        time.sleep(0.15)
        if not self.check_hardware_feedback(r=True, sc=True): return False

        if not self.sleep_and_check(self.times.get("Beschuss Schnell", 7.0)): return False

        # 2. Umschalten auf Langsamlauf
        self.out_schnell.off()
        time.sleep(0.1)
        self.out_langsam.on()
        time.sleep(0.15)
        if not self.check_hardware_feedback(r=True, la=True): return False

        if not self.sleep_and_check(self.times.get("Beschuss Langsam", 2.5)): return False

        # 3. Stop vor dem Kugelfang
        self.all_outputs_off()
        if not self.sleep_and_check(self.times.get("Bremszeit Vorwaerts", 0.5)): return False
        if not self.sleep_and_check(self.times.get("Wartezeit Kugelfang", 3.0)): return False
        return True

    def execute_wertung(self):
        # Wenn nicht referenziert, Sicherheits-Fahrt erzwingen
        if not self.ist_referenziert:
            return self.execute_homefahrt()

        self.out_links.on()
        self.out_schnell.on()
        time.sleep(0.15)
        if not self.check_hardware_feedback(l=True, sc=True): return False

        t_schnell = self.times.get("Wertung Schnell", 6.5)
        steps = int(t_schnell / 0.05)
        for _ in range(steps):
            if not self._running: return False
            time.sleep(0.05)
            self.emit_io_state()
            if self.in_endschalter.is_active:
                break
            if not self.in_motorschutz.is_active:
                self.error_signal.emit("FEHLER: Motorschutzschalter während Wertung ausgelöst!")
                return False

        # Bremsphase / Auslauf
        self.all_outputs_off()
        if not self.sleep_and_check(self.times.get("Bremszeit Rueckwaerts", 0.5)): return False

        if not self.in_endschalter.is_active:
            self.error_signal.emit("FEHLER: Endschalter nach Wertungsfahrt nicht erreicht!")
            return False
        return True

    def execute_homefahrt(self):
        # Sicherheitsfahrt: Immer rein Rückwärts Langsam
        self.out_links.on()
        self.out_langsam.on()
        time.sleep(0.15)
        if not self.check_hardware_feedback(l=True, la=True): return False

        timeout_start = time.time()
        while not self.in_endschalter.is_active:
            if not self._running: return False
            time.sleep(0.05)
            self.emit_io_state()
            if not self.in_motorschutz.is_active:
                self.error_signal.emit("FEHLER: Motorschutzschalter während HomeFahrt ausgelöst!")
                return False
            if (time.time() - timeout_start) > 25.0:
                self.error_signal.emit("FEHLER: Zeitüberschreitung (Timeout) bei HomeFahrt!")
                return False

        self.all_outputs_off()
        time.sleep(self.times.get("Bremszeit Rueckwaerts", 0.5))
        return True

    def execute_tipp(self, vorwaerts=True):
        if vorwaerts:
            self.out_rechts.on()
        else:
            self.out_links.on()
        
        self.out_langsam.on()
        time.sleep(0.15)
        
        if vorwaerts:
            if not self.check_hardware_feedback(r=True, la=True): return False
        else:
            if not self.check_hardware_feedback(l=True, la=True): return False

        while self._running:
            time.sleep(0.05)
            self.emit_io_state()
            if not self.in_motorschutz.is_active:
                self.error_signal.emit("FEHLER: Motorschutzschalter während Tippbetrieb ausgelöst!")
                return False
            if not vorwaerts and self.in_endschalter.is_active:
                break

        self.all_outputs_off()
        time.sleep(0.3)
        return True