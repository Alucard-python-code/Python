#!/usr/bin/python3
# -*- coding: utf-8 -*-
import sys, os, logging, time
from PyQt5.QtWidgets import *
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, QTimer
from gpiozero import DigitalInputDevice, DigitalOutputDevice
from config_loader import load_settings, load_operating_hours, save_operating_hours, load_error_log, save_error_log
from ui_dialogs import SettingsWindow
from drive_worker import DriveThread

class SchussbahnApp(QWidget):
    def __init__(self):
        super().__init__()
        self.times = load_settings()
        self.hours_data = load_operating_hours()
        self.autosave_counter = 0
        self.exit_requested = False
        self.is_driving = False
        self.system_fault = False
        self.gui_error_list = load_error_log()
        self.ist_referenziert = False
        self.blink_status = False

        # Hardware-Objekte zentral
        self.out_rechts = DigitalOutputDevice(26, active_high=False, initial_value=False)
        self.out_links  = DigitalOutputDevice(19, active_high=False, initial_value=False)
        self.out_langsam = DigitalOutputDevice(13, active_high=False, initial_value=False)
        self.out_schnell = DigitalOutputDevice(6,  active_high=False, initial_value=False)
        self.out_licht   = DigitalOutputDevice(23, active_high=False, initial_value=False)

        self.in_motorschutz = DigitalInputDevice(18, pull_up=True)
        self.in_endschalter = DigitalInputDevice(10, pull_up=True)
        self.in_schuetz_r   = DigitalInputDevice(20, pull_up=True)
        self.in_schuetz_l   = DigitalInputDevice(21, pull_up=True)
        self.in_schuetz_la  = DigitalInputDevice(16, pull_up=True)
        self.in_schuetz_sc  = DigitalInputDevice(12, pull_up=True)

        self.setFixedSize(1024, 600)
        self.init_ui()
        
        # ALLE TIMER HIER EINMALIG INITIALISIEREN
        self.monitor_timer = QTimer(self)
        self.monitor_timer.timeout.connect(self.cyclic_monitor)
        self.monitor_timer.start(250)
        
        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self.toggle_blink_text)
        
        self.hours_timer = QTimer(self)
        self.hours_timer.timeout.connect(self.track_total_hours)
        self.hours_timer.start(1000)
        
        self.startup_safety_check()

    def all_outputs_off(self):
        for dev in [self.out_rechts, self.out_links, self.out_langsam, self.out_schnell]:
            dev.off()

    def init_ui(self):
        self.setStyleSheet("background-color: #2b2b2b; color: #ffffff;")
        self.setWindowFlags(Qt.FramelessWindowHint)
        main_layout = QVBoxLayout()
        grid_layout = QGridLayout()

        self.btn_beschuss = QPushButton("Beschuss")
        self.btn_licht_an = QPushButton("Licht an")
        self.btn_einstellungen = QPushButton("Einstellungen")
        self.btn_wertung = QPushButton("Wertung")
        self.btn_licht_aus = QPushButton("Licht aus")
        self.btn_exit = QPushButton("Exit")

        buttons = [
            (self.btn_beschuss, 0, 0), (self.btn_licht_an, 0, 1), (self.btn_einstellungen, 0, 2),
            (self.btn_wertung, 1, 0), (self.btn_licht_aus, 1, 1), (self.btn_exit, 1, 2)
        ]

        for btn, row, col in buttons:
            btn.setFont(QFont("Arial", 18, QFont.Bold))
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            grid_layout.addWidget(btn, row, col)

        main_layout.addLayout(grid_layout)

        self.track_bar = QProgressBar()
        self.track_bar.setRange(0, 100)
        self.track_bar.setValue(0)
        self.track_bar.setTextVisible(False)
        main_layout.addWidget(self.track_bar)

        self.moving_target = QLabel("🎯", self)
        self.moving_target.setFixedSize(30, 30)
        self.moving_target.setFont(QFont("Arial", 20))
        self.moving_target.setStyleSheet("background-color: transparent; border: none;")
        self.moving_target.hide()
        
        self.status_msg = QLabel("Initialisierung...")
        self.status_msg.setStyleSheet("color: #00ff00; background-color: #111111; padding: 15px; border-radius: 6px;")
        main_layout.addWidget(self.status_msg)
        self.setLayout(main_layout)

        self.btn_beschuss.clicked.connect(lambda: self.start_drive("Beschuss"))
        self.btn_wertung.clicked.connect(lambda: self.start_drive("Wertung"))
        self.btn_exit.clicked.connect(self.handle_exit)
        self.btn_einstellungen.clicked.connect(self.open_settings)
        self.showFullScreen()

        QTimer.singleShot(100, self.align_target_to_start)

    def align_target_to_start(self):
        try:
            bar_geo = self.track_bar.geometry()
            target_y = bar_geo.y() + (bar_geo.height() - self.moving_target.height()) // 2
            self.moving_target.move(bar_geo.x(), target_y)
            self.moving_target.raise_()
            self.moving_target.show()
        except:
            pass

    def toggle_blink_text(self):
        if self.blink_status:
            self.status_msg.setStyleSheet("color: #ff0000; background-color: #111111; padding-left: 15px; border-radius: 6px; font-weight: bold;")
            self.blink_status = False
        else:
            self.status_msg.setStyleSheet("color: transparent; background-color: #111111; padding-left: 15px; border-radius: 6px; font-weight: bold;")
            self.blink_status = True

    def handle_thread_io_update(self, inputs, coils):
        self.latest_inputs = inputs
        self.latest_coils = coils

    def startup_safety_check(self):
        if not self.in_motorschutz.is_active: 
            self.handle_system_error("FEHLER: Motorschutzschalter ausgelöst (In1=0)!")
            return
        if self.in_schuetz_r.is_active or self.in_schuetz_l.is_active or self.in_schuetz_la.is_active or self.in_schuetz_sc.is_active:
            self.handle_system_error("FEHLER: Schütze nicht in Nullstellung!")
            return

        if self.in_endschalter.is_active: 
            self.status_msg.setText("zur Auswertung bereit")
            self.status_msg.setStyleSheet("color: #00ff00; background-color: #111111; padding-left: 15px; border-radius: 6px;")
            self.btn_beschuss.setEnabled(True)
            self.btn_wertung.setEnabled(False)
            self.ist_referenziert = True
            self.monitor_timer.start(250)
        else:
            self.status_msg.setText("Wagen nicht in Startposition! Bereite Home-Fahrt vor...")
            self.status_msg.setStyleSheet("color: #ffaa00; background-color: #111111; padding-left: 15px; border-radius: 6px;")
            self.start_drive("HomeFahrt")

    def cyclic_monitor(self):
        if self.is_driving: return

        ms = self.in_motorschutz.is_active
        es = self.in_endschalter.is_active

    # GPIO Status abfragen
        self.latest_inputs = [
            int(self.in_motorschutz.is_active),
            int(self.in_endschalter.is_active),
            int(self.in_schuetz_r.is_active),
            int(self.in_schuetz_l.is_active),
            int(self.in_schuetz_la.is_active),
            int(self.in_schuetz_sc.is_active)
        ]
        self.latest_coils = [
            self.out_rechts.is_active,
            self.out_links.is_active,
            self.out_langsam.is_active,
            self.out_schnell.is_active,
            False, False, False, 
            self.out_licht.is_active
    ]

        if self.system_fault:
            self.btn_beschuss.setEnabled(False); self.btn_wertung.setEnabled(False)
            return

        if not ms: 
            self.handle_system_error("FEHLER: Motorschutzschalter ausgelöst!")
            return

        if es:
            self.status_msg.setText("zur Auswertung bereit")
            self.status_msg.setStyleSheet("color: #00ff00; background-color: #111111; padding: 6px; border-radius: 6px;")
            self.btn_beschuss.setEnabled(True); self.btn_wertung.setEnabled(False)
        else:
            self.status_msg.setText("Bahn frei? / Beschuss bereit")
            self.status_msg.setStyleSheet("color: #ffff00; background-color: #111111; padding: 6px; border-radius: 6px;")
            self.btn_beschuss.setEnabled(False); self.btn_wertung.setEnabled(True)

    def general_system_reset(self):
        try:
            self.blink_timer.stop()
            self.is_driving = False; self.system_fault = False
            self.monitor_timer.stop()
            self.all_outputs_off()

            self.times = load_settings() 
            self.exit_requested = False
            self.ist_referenziert = False 
            self.startup_safety_check() 
            return True
        except Exception as e:
            logging.error(f"Fehler beim System-Reset: {e}")
            return False

    # In SchussbahnApp (main.py) hinzufügen:
    def trigger_system_reset(self):
        logging.info("System-Reset durch Einstellungen angefordert.")
        self.general_system_reset()
        # Optional: Den User kurz informieren
        QMessageBox.information(self, "System", "Konfiguration übernommen. System wurde neu initialisiert.")

    def track_total_hours(self):
        self.hours_data["gesamt_sekunden"] += 1.0
        self.autosave_counter += 1
        if self.autosave_counter >= 60:
            save_operating_hours(self.hours_data)
            self.autosave_counter = 0

    def add_drive_time(self, seconds):
        self.hours_data["fahrzeit_sekunden"] += seconds
        save_operating_hours(self.hours_data) 

    def start_drive(self, modus):
        if self.is_driving or self.system_fault: return
        effektiver_modus = "HomeFahrt" if not self.ist_referenziert and modus in ["Beschuss", "Wertung"] else modus
        
        self.is_driving = True
        self.monitor_timer.stop()
        
        out_tuple = (self.out_rechts, self.out_links, self.out_langsam, self.out_schnell, self.out_licht)
        in_tuple = (self.in_motorschutz, self.in_endschalter, self.in_schuetz_r, self.in_schuetz_l, 
                    self.in_schuetz_la, self.in_schuetz_sc)
        
        self.thread = DriveThread(effektiver_modus, self.times, self.ist_referenziert, out_tuple, in_tuple)
        self.thread.io_update_signal.connect(self.handle_thread_io_update)
        self.thread.status_signal.connect(self.update_status)
        self.thread.finished_signal.connect(self.drive_finished)
        self.thread.error_signal.connect(self.handle_system_error)
        self.thread.start()
        
        # Optional: UI-Feedback geben
        print(f"Starte Modus: {effektiver_modus}")

    def home_fahrt_erfolgreich(self):
        self.blink_timer.stop()
        self.ist_referenziert = True
        self.status_msg.setStyleSheet("color: #00ff00; background-color: #111111; padding-left: 15px; border-radius: 6px;")
        self.status_msg.setText("zur Auswertung bereit")
        self.drive_finished()

    def closeEvent(self, event):
        if hasattr(self, 'thread') and self.thread.isRunning():
            self.thread.stop()
            self.thread.wait() # Warten, bis der Thread sicher gestoppt ist
        event.accept()

    def fahrt_abgebrochen_fehler(self, error_msg):
        self.blink_timer.stop()
        self.ist_referenziert = False
        self.handle_system_error(error_msg)

    def update_status(self, text):
        if not self.blink_timer.isActive():
            self.status_msg.setText(text)
            if text == "Unterwegs":
                self.status_msg.setStyleSheet("color: #ffaa00; background-color: #111111; padding: 6px; border-radius: 6px;")

    def drive_finished(self):
        self.stop_position_animation() 
        self.is_driving = False
        if self.exit_requested: 
            self.close_program_safely()
        else: 
            self.monitor_timer.start(250)

    def handle_system_error(self, message):
        self.stop_position_animation() 
        self.is_driving = False; self.system_fault = True

        timestamp = time.strftime("%d.%m.%Y %H:%M:%S")
        clean_msg = message.replace("FEHLER: ", "")
        self.gui_error_list.insert(0, f"[{timestamp}] {clean_msg}")
        if len(self.gui_error_list) > 5: 
            self.gui_error_list.pop() 

        save_error_log(self.gui_error_list)
        self.all_outputs_off()

        self.status_msg.setText(message)
        self.status_msg.setStyleSheet("color: #ff0000; background-color: #111111; padding: 6px; border: 1px solid red; border-radius: 6px;")
        self.btn_beschuss.setEnabled(False); self.btn_wertung.setEnabled(False)
        if not self.monitor_timer.isActive(): 
            self.monitor_timer.start(250)

    def set_light(self, state): 
        self.btn_licht_an.setEnabled(False); self.btn_licht_aus.setEnabled(False)
        try:
            if state: self.out_licht.on()
            else: self.out_licht.off()
        except Exception as e: 
            logging.error(f"Fehler beim Lichtschalten: {e}")
        QTimer.singleShot(500, lambda: self.btn_licht_an.setEnabled(True))
        QTimer.singleShot(500, lambda: self.btn_licht_aus.setEnabled(True))

    def open_settings(self):
        if not hasattr(self, 'settings_window') or self.settings_window is None:
            self.settings_window = SettingsWindow(self)
        self.settings_window.show(); self.settings_window.raise_(); self.settings_window.activateWindow()

    def handle_exit(self):
        if self.is_driving: 
            self.exit_requested = True
            self.status_msg.setText("Exit angefordert. Letzte Fahrt wird beendet...")
        else: 
            self.close_program_safely()

    def close_program_safely(self):
        self.monitor_timer.stop(); self.hours_timer.stop(); self.blink_timer.stop()
        save_operating_hours(self.hours_data) 
        if hasattr(self, 'settings_window') and self.settings_window is not None: 
            self.settings_window.close()
        try: 
            self.all_outputs_off()
            self.out_licht.off()
        except: pass
        sys.exit(0)

    def start_tipp_mode(self, direction):
        if self.system_fault or self.is_driving: return
        self.is_driving = True; self.monitor_timer.stop()
        
        # WICHTIG: Hier müssen die Tupel genau wie in start_drive definiert sein!
        out_tuple = (self.out_rechts, self.out_links, self.out_langsam, self.out_schnell, self.out_licht)
        in_tuple = (self.in_motorschutz, self.in_endschalter, self.in_schuetz_r, self.in_schuetz_l, 
                    self.in_schuetz_la, self.in_schuetz_sc)
        
        self.thread = DriveThread(direction, self.times, self.ist_referenziert, out_tuple, in_tuple)
        self.thread.io_update_signal.connect(self.handle_thread_io_update)
        self.thread.start()

    def stop_tipp_mode(self):
        if not self.is_driving: return
        self.stop_position_animation() 
        try:
            if hasattr(self, 'thread') and self.thread.isRunning():
                self.thread.stop(); self.thread.wait()
            self.all_outputs_off()
        except: pass
        self.is_driving = False; self.monitor_timer.start(250)

    def start_position_animation(self, mode):
        self.anim_mode = mode; self.anim_start_time = time.time()
        self.t_beschuss_schnell = self.times.get("Beschuss Schnell", 7.0)
        self.t_beschuss_langsam = self.times.get("Beschuss Langsam", 2.5)
        self.t_wertung_schnell = self.times.get("Wertung Schnell", 6.5)

        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.process_target_movement)
        self.animation_timer.start(30)

    def process_target_movement(self):
        elapsed = time.time() - self.anim_start_time
        progress_percent = 0

        if self.anim_mode == "Beschuss":
            total_time = self.t_beschuss_schnell + self.t_beschuss_langsam
            if elapsed >= total_time: progress_percent = 100; self.animation_timer.stop()
            else: progress_percent = int((elapsed / total_time) * 100)

        elif self.anim_mode in ["Wertung", "HomeFahrt"]:
            estimated_total = self.t_wertung_schnell + 3.0
            if elapsed >= estimated_total: progress_percent = 0; self.animation_timer.stop()
            else:
                progress_percent = int(100 - ((elapsed / estimated_total) * 100))
                if progress_percent < 0: progress_percent = 0

        elif self.anim_mode == "TippVor":
            progress_percent = self.track_bar.value() + 1
            if progress_percent > 100: progress_percent = 100
        elif self.anim_mode == "TippRueck":
            progress_percent = self.track_bar.value() - 1
            if progress_percent < 0: progress_percent = 0

        self.track_bar.setValue(progress_percent)

        bar_geo = self.track_bar.geometry()
        available_width = bar_geo.width() - 25
        if available_width <= 0: available_width = 750

        target_x = bar_geo.x() + int((progress_percent / 100.0) * available_width)
        target_y = bar_geo.y() + (bar_geo.height() - self.moving_target.height()) // 2

        self.moving_target.move(target_x, target_y)
        self.moving_target.raise_(); self.moving_target.show()

    def stop_position_animation(self):
        if hasattr(self, 'animation_timer') and self.animation_timer.isActive():
            self.animation_timer.stop()
        try:
            if self.in_endschalter.is_active:
                self.track_bar.setValue(0)
                bar_geo = self.track_bar.geometry()
                target_y = bar_geo.y() + (bar_geo.height() - self.moving_target.height()) // 2
                self.moving_target.move(bar_geo.x(), target_y)
        except: pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SchussbahnApp()
    window.show()
    sys.exit(app.exec_())