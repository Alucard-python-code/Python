# -*- coding: utf-8 -*-
import time
import logging
from PyQt5.QtCore import QTimer

class ProgressAnimator:
    def __init__(self, parent_app):
        self.app = parent_app
        self.timer = None
        self.mode = ""
        self.start_time = 0

    def start(self, mode):
        self.mode = mode
        self.start_time = time.time()

        self.t_beschuss_schnell = self.app.times.get("Beschuss Schnell", 3.0)
        self.t_beschuss_langsam = self.app.times.get("Beschuss Langsam", 2.0)
        self.t_wertung_schnell = self.app.times.get("Wertung Schnell", 2.5)

        self.timer = QTimer(self.app)
        self.timer.timeout.connect(self._process_movement)
        self.timer.start(30)

    def _process_movement(self):
        elapsed = time.time() - self.start_time
        progress_percent = 0

        if self.mode == "Beschuss":
            total_time = self.t_beschuss_schnell + self.t_beschuss_langsam
            if elapsed >= total_time:
                progress_percent = 100
                self.timer.stop()
            else:
                progress_percent = int((elapsed / total_time) * 100)

        elif self.mode in ["Wertung", "HomeFahrt"]:
            estimated_total = self.t_wertung_schnell + 3.0
            if elapsed >= estimated_total:
                progress_percent = 0
                self.timer.stop()
            else:
                progress_percent = int(100 - ((elapsed / estimated_total) * 100))
                if progress_percent < 0: 
                    progress_percent = 0

        elif self.mode == "TippVor":
            progress_percent = self.app.track_bar.value() + 1
            if progress_percent > 100: progress_percent = 100
        elif self.mode == "TippRueck":
            progress_percent = self.app.track_bar.value() - 1
            if progress_percent < 0: progress_percent = 0

        self.app.track_bar.setValue(progress_percent)
        available_width = self.app.track_bar.width() - 25
        if available_width <= 0: available_width = 750

        target_x = int((progress_percent / 100.0) * available_width)
        self.app.moving_target.move(target_x, -4)

    def stop(self):
        if self.timer and self.timer.isActive():
            self.timer.stop()
        try:
            inputs = self.app.ipc.query_backend(self.app.current_static_relays)
            if inputs and len(inputs) > 1:
                if inputs[1]:
                    self.app.track_bar.setValue(0)
                    self.app.moving_target.move(0, -3) 
        except Exception as e:
            logging.error(f"Fehler beim Stoppen der Animation: {e}")
