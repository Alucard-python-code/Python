#!/usr/bin/python3
# -*- coding: utf-8 -*-

import sys
import os
import logging
import time
from PyQt5.QtWidgets import (QApplication, QWidget, QPushButton, QLabel, QGridLayout, 
                             QVBoxLayout, QHBoxLayout, QProgressBar, QSizePolicy)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, QTimer
from pyModbusTCP.client import ModbusClient

from config_loader import load_settings, load_operating_hours, save_operating_hours, load_error_log, save_error_log
from ui_dialogs import SettingsWindow
from drive_worker import DriveThread

try:
    import __main__
    if hasattr(__main__, '__file__'):
        SCRIPT_DIR = os.path.dirname(os.path.abspath(__main__.__file__))
    else:
        SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except Exception:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

LOG_FILE = os.path.join(SCRIPT_DIR, "schussbahn_error.log")
logging.basicConfig(filename=LOG_FILE, level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')

class SchussbahnApp(QWidget):
    def __init__(self):
        super().__init__()
        self.times = load_settings()
        self.hours_data = load_operating_hours() 
        self.autosave_counter = 0

        self.exit_requested = False
        self.is_driving = False
        self.system_fault = False 
        self.latest_inputs = []
        self.latest_coils = []
        self.gui_error_list = load_error_log() 

        modbus_ip = self.times.get("Modbus-IP", "192.168.8.203")
        self.client = ModbusClient(host=modbus_ip, port=4196, timeout=2.0, auto_open=True, auto_close=True)
        
        # UI-Fixierung für exakt 1024x600 px
        self.setFixedSize(1024, 600)
        self.init_ui()

        self.monitor_timer = QTimer(self)
        self.monitor_timer.timeout.connect(self.cyclic_monitor)

        self.hours_timer = QTimer(self)
        self.hours_timer.timeout.connect(self.track_total_hours)
        self.hours_timer.start(1000) 

        self.startup_safety_check()

    def general_system_reset(self):
        try:
            self.is_driving = False
            self.system_fault = False
            self.monitor_timer.stop()
            self.client.close()
            time.sleep(0.1)

            self.times = load_settings() 
            neue_ip = self.times.get("Modbus-IP", "192.168.8.203")
            self.client.host = neue_ip 

            if not self.client.open():
                logging.error("System-Reset fehlgeschlagen: Modbus antwortet nicht.")
                return False

            self.client.unit_id = 1
            self.client.write_multiple_coils(0, [False] * 8)

            self.exit_requested = False
            self.startup_safety_check() 
            return True
        except Exception as e:
            logging.error(f"Kritischer Fehler beim generellen System-Reset: {e}")
            return False

    def track_total_hours(self):
        self.hours_data["gesamt_sekunden"] += 1.0
        self.autosave_counter += 1
        if self.autosave_counter >= 60:
            save_operating_hours(self.hours_data)
            self.autosave_counter = 0

    def add_drive_time(self, seconds):
        self.hours_data["fahrzeit_sekunden"] += seconds
        save_operating_hours(self.hours_data) 

    def init_ui(self):
        self.setStyleSheet("background-color: #2b2b2b; color: #ffffff;")
        self.setWindowFlags(Qt.FramelessWindowHint)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        grid_layout = QGridLayout()
        grid_layout.setSpacing(8)

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

        button_font = QFont("Arial", 18, QFont.Bold)
        for btn, row, col in buttons:
            btn.setFont(button_font)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            
            # FARB-ANPASSUNG: Exakt dasselbe Design wie die "Ändern"-Buttons
            if btn == self.btn_exit:
                # Der Exit-Button bekommt ein dezentes Rot, bleibt aber im selben Stil
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #552222;
                        color: #ffaaaa;
                        border: 1px solid #774444;
                        border-radius: 4px;
                    }
                    QPushButton:pressed {
                        background-color: #773333;
                    }
                    QPushButton:disabled {
                        background-color: #221111;
                        color: #553333;
                        border: 1px solid #332222;
                    }
                """)
            else:
                # Alle Standard-Buttons erhalten das originale dunkle Grau
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #444444;
                        color: white;
                        border: 1px solid #555555;
                        border-radius: 4px;
                    }
                    QPushButton:pressed {
                        background-color: #666666;
                    }
                    QPushButton:disabled {
                        background-color: #222222;
                        color: #666666;
                        border: 1px solid #333333;
                    }
                """)
                
            grid_layout.addWidget(btn, row, col)

        main_layout.addLayout(grid_layout, stretch=60)

        # Positions-Monitor flacher dimensioniert für 600px Begrenzung
        position_container = QWidget()
        position_container.setFixedHeight(75) 
        position_container.setStyleSheet("background-color: #1a1a1a; border-radius: 6px; border: 1px solid #444444;")

        track_layout = QHBoxLayout(position_container)
        track_layout.setContentsMargins(15, 0, 15, 0)
        track_layout.setSpacing(10)

        lbl_home = QLabel("Stand")
        lbl_home.setFont(QFont("Arial", 14, QFont.Bold)) 
        lbl_home.setStyleSheet("color: #00ffcc; border: none;")

        self.track_bar = QProgressBar()
        self.track_bar.setRange(0, 100)
        self.track_bar.setValue(0)
        self.track_bar.setTextVisible(False)
        self.track_bar.setFixedHeight(35) 
        self.track_bar.setStyleSheet("""
            QProgressBar { background-color: #252525; border-radius: 4px; border: 1px solid #444444; }
            QProgressBar::chunk { background-color: #113322; border-radius: 3px; } 
        """)

        self.moving_target = QLabel("🎯", self.track_bar)
        self.moving_target.setFont(QFont("Arial", 20)) 
        self.moving_target.setStyleSheet("border: none; background: transparent;")
        self.moving_target.move(0, -3) 

        lbl_end = QLabel("Kugelfang")
        lbl_end.setFont(QFont("Arial", 14, QFont.Bold))
        lbl_end.setStyleSheet("color: #ffaa00; border: none;")

        track_layout.addWidget(lbl_home)
        track_layout.addWidget(self.track_bar, stretch=1)
        track_layout.addWidget(lbl_end)

        main_layout.addWidget(position_container, stretch=20)

        status_layout = QHBoxLayout()
        status_title = QLabel("Status: ")
        status_title.setFont(QFont("Arial", 16, QFont.Bold))
        status_title.setFixedWidth(120)
        status_title.setFixedHeight(50) 
        status_layout.addWidget(status_title)

        self.status_msg = QLabel("Initialisierung...")
        self.status_msg.setFont(QFont("Arial", 16, QFont.Bold))
        self.status_msg.setFixedHeight(50)
        self.status_msg.setStyleSheet("color: #00ff00; background-color: #111111; padding-left: 15px; border-radius: 6px;")
        status_layout.addWidget(self.status_msg)

        main_layout.addLayout(status_layout, stretch=20)
        self.setLayout(main_layout)

        self.btn_beschuss.clicked.connect(lambda: self.start_drive("Beschuss"))
        self.btn_wertung.clicked.connect(lambda: self.start_drive("Wertung"))
        self.btn_licht_an.clicked.connect(lambda: self.set_light(True))
        self.btn_licht_aus.clicked.connect(lambda: self.set_light(False))
        self.btn_einstellungen.clicked.connect(self.open_settings)
        self.btn_exit.clicked.connect(self.handle_exit)
        self.showFullScreen()

    def handle_thread_io_update(self, inputs, coils):
        """ Thread-sicheres Signal-Callback-Verfahren """
        self.latest_inputs = inputs
        self.latest_coils = coils

    def startup_safety_check(self):
        if not self.client.is_open: self.client.open()
        self.client.unit_id = 1
        if not self.client.write_multiple_coils(0, [False] * 8):
            self.handle_system_error("FEHLER: Modbus-Verbindung fehlgeschlagen beim Start!")
            return

        inputs = self.client.read_discrete_inputs(0, 8)
        if not inputs or len(inputs) < 6:
            self.handle_system_error("FEHLER: Eingänge konnten nicht gelesen werden!")
            return

        self.latest_inputs = inputs
        if not inputs: 
            self.handle_system_error("FEHLER: Motorschutzschalter ausgelöst (In1=0)!")
        elif any(inputs[2:6]): 
            self.handle_system_error("FEHLER: Schütze nicht in Nullstellung!")
        else:
            if inputs: 
                self.status_msg.setText("zur Auswertung bereit")
                self.status_msg.setStyleSheet("color: #00ff00; background-color: #111111; padding-left: 15px; border-radius: 6px;")
                self.btn_beschuss.setEnabled(True); self.btn_wertung.setEnabled(False)
                self.monitor_timer.start(250)
            else: 
                self.status_msg.setText("Wagen nicht in Startposition! Bereite Home-Fahrt vor...")
                self.status_msg.setStyleSheet("color: #ffaa00; background-color: #111111; padding-left: 15px; border-radius: 6px;")
                self.client.write_multiple_coils(0, [False] * 8)
                time.sleep(0.3) 
                self.start_drive("HomeFahrt")

    def cyclic_monitor(self):
        if self.is_driving: return

        inputs = self.client.read_discrete_inputs(0, 8)
        coils = self.client.read_coils(0, 8)

        if not inputs or len(inputs) < 6:
            self.status_msg.setText("FEHLER: Modbus Verbindung verloren!")
            self.status_msg.setStyleSheet("color: #ff0000; background-color: #111111; padding: 6px; border: 1px solid red; border-radius: 6px;")
            self.btn_beschuss.setEnabled(False); self.btn_wertung.setEnabled(False)
            return

        self.latest_inputs = inputs
        self.latest_coils = coils if coils else [False]*8

        if self.system_fault:
            self.btn_beschuss.setEnabled(False)
            self.btn_wertung.setEnabled(False)
            try: self.client.write_multiple_coils(0, [False] * 8)
            except: pass
            return 

        if not inputs[0]: 
            self.handle_system_error("FEHLER: Motorschutzschalter ausgelöst!")
            return

        if inputs[1]:  # In2 = True: Wagen steht am Stand / Startposition
            self.status_msg.setText("zur Auswertung bereit")
            self.status_msg.setStyleSheet("color: #00ff00; background-color: #111111; padding: 6px; border-radius: 6px;")
            self.btn_beschuss.setEnabled(True)
            self.btn_wertung.setEnabled(False)
        else:          # In2 = False: Bahn ist frei für die Wertung
            self.status_msg.setText("Bahn frei? / Beschuss bereit")
            self.status_msg.setStyleSheet("color: #ffff00; background-color: #111111; padding: 6px; border-radius: 6px;")
            self.btn_beschuss.setEnabled(False)
            self.btn_wertung.setEnabled(True)

    def start_drive(self, mode):
        self.is_driving = True
        self.monitor_timer.stop()
        self.btn_beschuss.setEnabled(False)
        self.btn_wertung.setEnabled(False)
        self.btn_einstellungen.setEnabled(True)
        
        self.thread = DriveThread(mode, self.client, self.times)
        # Thread-sichere Verbindung der Signale (Verhindert GUI-Abstürze)
        self.thread.io_update_signal.connect(self.handle_thread_io_update)
        self.thread.status_signal.connect(self.update_status)
        self.thread.error_signal.connect(self.handle_system_error)
        self.thread.finished_signal.connect(self.drive_finished)
        self.thread.drive_time_signal.connect(self.add_drive_time)
        self.thread.start()
        
        # Grafik-Animation zeitgleich mit dem Motor starten
        self.start_position_animation(mode)

    def update_status(self, text):
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
        self.is_driving = False
        self.system_fault = True

        # Fehler mit Zeitstempel in das GUI-Logbuch eintragen
        timestamp = time.strftime("%d.%m.%Y %H:%M:%S")
        clean_msg = message.replace("FEHLER: ", "")
        self.gui_error_list.insert(0, f"[{timestamp}] {clean_msg}")

        if len(self.gui_error_list) > 5:
            self.gui_error_list.pop() # Nur die neuesten 5 Vorfälle behalten

        # Fehlerliste sofort ausfallsicher auf die SD-Karte schreiben
        save_error_log(self.gui_error_list)

        try: 
            self.client.write_multiple_coils(0, [False] * 8)
        except: 
            pass

        self.status_msg.setText(message)
        self.status_msg.setStyleSheet("color: #ff0000; background-color: #111111; padding: 6px; border: 1px solid red; border-radius: 6px;")
        self.btn_beschuss.setEnabled(False)
        self.btn_wertung.setEnabled(False)
        
        if not self.monitor_timer.isActive(): 
            self.monitor_timer.start(250)

    def set_light(self, state): 
        # Schützt das Lichtrelais vor schnellem Flattern (Hardware-Schonung)
        self.btn_licht_an.setEnabled(False)
        self.btn_licht_aus.setEnabled(False)
        try:
            self.client.write_single_coil(7, state)
        except Exception as e:
            logging.error(f"Fehler beim Lichtschalten: {e}")
            
        # Nach 500 Millisekunden die Licht-Buttons automatisch wieder freigeben
        QTimer.singleShot(500, lambda: self.btn_licht_an.setEnabled(True))
        QTimer.singleShot(500, lambda: self.btn_licht_aus.setEnabled(True))

    def open_settings(self):
        if not hasattr(self, 'settings_window') or self.settings_window is None:
            self.settings_window = SettingsWindow(self)
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def handle_exit(self):
        if self.is_driving: 
            self.exit_requested = True
            self.status_msg.setText("Exit angefordert. Letzte Fahrt wird beendet...")
        else: 
            self.close_program_safely()

    def close_program_safely(self):
        self.monitor_timer.stop()
        self.hours_timer.stop() 
        save_operating_hours(self.hours_data) # Beim regulären Beenden remanent sichern
        if hasattr(self, 'settings_window') and self.settings_window is not None: 
            self.settings_window.close()
        try: 
            self.client.write_multiple_coils(0, [False] * 8)
            self.client.close()
        except: 
            pass
        sys.exit(0)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape or event.key() == Qt.Key_Q: 
            self.handle_exit()

    def start_tipp_mode(self, direction):
        if self.system_fault or self.is_driving: 
            return
        self.is_driving = True
        self.monitor_timer.stop()
        self.thread = DriveThread(direction, self.client, self.times)
        self.thread.io_update_signal.connect(self.handle_thread_io_update)
        self.thread.drive_time_signal.connect(self.add_drive_time)
        self.thread.start()

    def stop_tipp_mode(self):
        if not self.is_driving: 
            return
        self.stop_position_animation() 
        try:
            if hasattr(self, 'thread') and self.thread.isRunning():
                self.thread.stop() # Setzt das sichere boolsche Flag im Thread (kein terminate)
                self.thread.wait()
            self.client.write_multiple_coils(0, [False] * 8)
        except:
            pass
        self.is_driving = False
        self.monitor_timer.start(250)

    def clear_gui_error_log(self):
        self.gui_error_list = []
        save_error_log(self.gui_error_list)

    def start_position_animation(self, mode):
        self.anim_mode = mode
        self.anim_start_time = time.time()
        
        # Fahrtzeiten dynamisch aus den Settings laden
        self.t_beschuss_schnell = self.times.get("Beschuss Schnell", 3.0)
        self.t_beschuss_langsam = self.times.get("Beschuss Langsam", 2.0)
        self.t_wertung_schnell = self.times.get("Wertung Schnell", 2.5)

        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.process_target_movement)
        self.animation_timer.start(30)
    def process_target_movement(self):
        elapsed = time.time() - self.anim_start_time
        progress_percent = 0

        # --- MODUS BESCHUSS (Wandert nach rechts zum Kugelfang) ---
        if self.anim_mode == "Beschuss":
            total_time = self.t_beschuss_schnell + self.t_beschuss_langsam
            if elapsed >= total_time:
                progress_percent = 100
                self.animation_timer.stop()
            else:
                progress_percent = int((elapsed / total_time) * 100)

        # --- MODUS WERTUNG / HOME-FAHRT (Wandert nach links zum Stand) ---
        elif self.anim_mode in ["Wertung", "HomeFahrt"]:
            estimated_total = self.t_wertung_schnell + 3.0
            if elapsed >= estimated_total:
                progress_percent = 0
                self.animation_timer.stop()
            else:
                progress_percent = int(100 - ((elapsed / estimated_total) * 100))
                if progress_percent < 0: 
                    progress_percent = 0

        # --- MODUS MANUELLER TIPPBETRIEB (Schrittweise Bewegung) ---
        elif self.anim_mode == "TippVor":
            progress_percent = self.track_bar.value() + 1
            if progress_percent > 100: 
                progress_percent = 100
        elif self.anim_mode == "TippRueck":
            progress_percent = self.track_bar.value() - 1
            if progress_percent < 0: 
                progress_percent = 0

        # 1. Den Fortschrittsbalken im Hintergrund füllen
        self.track_bar.setValue(progress_percent)

        # 2. POSITIONIERUNG DIREKT AUF DER SCHIENE (Optimiert für 1024x600)
        available_width = self.track_bar.width() - 25
        if available_width <= 0: 
            available_width = 750

        # Prozentuale Position in Pixel-Koordinaten umrechnen
        target_x = int((progress_percent / 100.0) * available_width)

        # Das Symbol auf der Schiene verschieben (Y-Wert perfekt zentriert bei -4px)
        self.moving_target.move(target_x, -4)

    def stop_position_animation(self):
        if hasattr(self, 'animation_timer') and self.animation_timer.isActive():
            self.animation_timer.stop()
        try:
            inputs = self.client.read_discrete_inputs(0, 8)
            if inputs and len(inputs) >= 2 and inputs[1]:  # In2 aktiv = Wagen steht am Stand
                self.track_bar.setValue(0)
                self.moving_target.move(0, -3) 
        except:
            pass

# ====================================================================
# HAUPT-EINSTIEGSPUNKT DES PROGRAMMS
# ====================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SchussbahnApp()
    window.show()
    sys.exit(app.exec_())
