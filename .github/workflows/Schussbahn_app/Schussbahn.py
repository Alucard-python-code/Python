#!/usr/bin/python3
# -*- coding: utf-8 -*-

import sys
import os
import logging
import time
from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QLabel, QGridLayout, QVBoxLayout, QHBoxLayout, QProgressBar
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, QTimer
from pyModbusTCP.client import ModbusClient

from config_loader import load_settings, load_operating_hours, save_operating_hours, load_error_log, save_error_log
from ui_dialogs import SettingsWindow
from drive_worker import DriveThread

# 1. UNIVERSAL-FINDER für den Hauptordner
try:
    import __main__
    if hasattr(__main__, '__file__'):
        SCRIPT_DIR = os.path.dirname(os.path.abspath(__main__.__file__))
    else:
        SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except Exception:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 2. Log-Datei absolut an diesen Ordner binden (LÖSCHT den Fehler "neben dem Ordner")
LOG_FILE = os.path.join(SCRIPT_DIR, "schussbahn_error.log")

# 3. Logging-System initialisieren
logging.basicConfig(filename=LOG_FILE, level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')

class SchussbahnApp(QWidget):
    def __init__(self):
        super().__init__()
        self.times = load_settings()
        self.hours_data = load_operating_hours() 
        self.autosave_counter = 0
        
        self.exit_requested = False
        self.is_driving = False
        self.system_fault = False  # NEU: Flag für aktiven Systemfehler
        self.latest_inputs = []
        self.latest_coils = []
        self.gui_error_list = load_error_log()  
        
        # Fest konfiguriert auf Ihr Modul und Port 4196
        modbus_ip = self.times.get("Modbus-IP", "192.168.8.203")
        self.client = ModbusClient(host=modbus_ip, port=4196, timeout=2.0, auto_open=True, auto_close=True)
        self.init_ui()
        
        self.monitor_timer = QTimer(self)
        self.monitor_timer.timeout.connect(self.cyclic_monitor)
        
        # 2. HIER den hours_timer initialisieren (VOR dem Safety-Check!)
        self.hours_timer = QTimer(self)
        self.hours_timer.timeout.connect(self.track_total_hours)
        self.hours_timer.start(1000) # Läuft jede Sekunde
        
        # 3. ERST JETZT den Safety-Check ausführen
        self.startup_safety_check()

    # NEU: Methode zum Zurücksetzen der Modbus-Verbindung
    # NEU: Genereller System-Reset für Verbindung und Logik
    def general_system_reset(self):
        try:
            # 1. Fahr-Modus zurücksetzen und Timer stoppen
            self.is_driving = False
            self.system_fault = False
            self.monitor_timer.stop()
            
            # 2. Alte Verbindung schließen
            self.client.close()
            time.sleep(0.1)
            
            # KORREKTUR: Einstellungen neu laden und die IP-Adresse im Client aktualisieren
            self.times = load_settings()  # Lädt das Dictionary inklusive der neuen IP frisch in self.times
            neue_ip = self.times.get("Modbus-IP", "192.168.8.203")
            
            self.client.host = neue_ip    # Schreibt die neue IP direkt in das Client-Objekt
            
            if not self.client.open():
                logging.error("System-Reset fehlgeschlagen: Modbus antwortet nicht.")
                return False
                
            # 4. Alle Ausgänge hart abschalten (Coils auf False)
            self.client.unit_id = 1
            self.client.write_multiple_coils(0, [False] * 8)
            
            # 5. Internen Status zurücksetzen und Sicherheitscheck neu ausführen
            self.exit_requested = False
            self.startup_safety_check() # Startet auch den zyklischen Monitor neu
            return True
        except Exception as e:
            logging.error(f"Kritischer Fehler beim generellen System-Reset: {e}")
            return False



    def track_total_hours(self):
        self.hours_data["gesamt_sekunden"] += 1.0
        self.autosave_counter += 1
        
        # Jede Minute (60 Sekunden) remanent auf die SD-Karte schreiben
        if self.autosave_counter >= 60:
            save_operating_hours(self.hours_data)
            self.autosave_counter = 0

    # NEU: Funktion addiert die reine Fahrzeit aus dem Thread
    def add_drive_time(self, seconds):
        self.hours_data["fahrzeit_sekunden"] += seconds
        save_operating_hours(self.hours_data) # Fahrzeiten sofort mitsichern

    def init_ui(self):
        self.setStyleSheet("background-color: #2b2b2b; color: #ffffff;")
        
        # 1. Haupt-Layout erstellen
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # 2. Raster für die riesigen Touch-Buttons
        grid_layout = QGridLayout()
        grid_layout.setSpacing(10)
        
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
        
        button_font = QFont("Arial", 26, QFont.Bold)
        for btn, row, col in buttons:
            btn.setFont(button_font)
            btn.setMinimumHeight(540) 
            grid_layout.addWidget(btn, row, col)
            
        main_layout.addLayout(grid_layout, stretch=75)
        
        # ====================================================================
        # 3. POSITIONS-MONITOR (VOLLE BREITE, KRAFTVOLLE SCHRIFT & MASSIVER BALKEN)
        # ====================================================================
        position_container = QWidget()
        position_container.setFixedHeight(120) # Etwas höher für die massive Optik
        position_container.setStyleSheet("background-color: #1a1a1a; border-radius: 8px; border: 1px solid #444444;")
        
        # Zurück auf die volle Breite (direktes Layout im Container)
        track_layout = QHBoxLayout(position_container)
        track_layout.setContentsMargins(20, 0, 20, 0)
        track_layout.setSpacing(15)
        
        # NEU: Schriftart doppelt so hoch gestaltet (Größe 22)
        lbl_home = QLabel("Stand")
        lbl_home.setFont(QFont("Arial", 22, QFont.Bold)); lbl_home.setStyleSheet("color: #00ffcc; border: none;")
        
        # NEU: Balkenhöhe (Breite) perfekt an die Symbol-Proportionen angepasst (48 Pixel)
        self.track_bar = QProgressBar()
        self.track_bar.setRange(0, 100)
        self.track_bar.setValue(0)
        self.track_bar.setTextVisible(False)
        self.track_bar.setFixedHeight(65) 
        self.track_bar.setStyleSheet("""
            QProgressBar { background-color: #252525; border-radius: 6px; border: 1px solid #444444; }
            QProgressBar::chunk { background-color: #113322; border-radius: 5px; } 
        """)
        
        # Das Zielscheiben-Symbol wird perfekt in den massiven Balken zentriert
        self.moving_target = QLabel("🎯", self.track_bar)
        self.moving_target.setFont(QFont("Arial", 32)) # Riesige, fette Scheibe
        self.moving_target.setStyleSheet("border: none; background: transparent;")
        self.moving_target.move(0, -3) # Perfekte Höhen-Zentrierung im 48px Balken
        
        # NEU: Auch hier Schriftart doppelt so hoch (Größe 22)
        lbl_end = QLabel("Kugelfang")
        lbl_end.setFont(QFont("Arial", 22, QFont.Bold)); lbl_end.setStyleSheet("color: #ffaa00; border: none;")
        
        # Elemente in die volle Breite des Layouts einfügen
        track_layout.addWidget(lbl_home)
        track_layout.addWidget(self.track_bar, stretch=1) # stretch=1 zwingt den Balken auf die volle Breite
        track_layout.addWidget(lbl_end)
        
        main_layout.addWidget(position_container, stretch=15)
        # ====================================================================
        
        # 4. STATUSZEILE (Bombensicher gelöst)
        status_layout = QHBoxLayout()
        status_title = QLabel("Status: ")
        status_title.setFont(QFont("Arial", 24, QFont.Bold)); status_title.setFixedWidth(240); status_title.setFixedHeight(120)
        status_layout.addWidget(status_title)
        
        self.status_msg = QLabel("Initialisierung...")
        self.status_msg.setFont(QFont("Arial", 24, QFont.Bold)); self.status_msg.setFixedHeight(120)
        self.status_msg.setStyleSheet("color: #00ff00; background-color: #111111; padding-left: 20px; border-radius: 8px;")
        status_layout.addWidget(self.status_msg)
        
        main_layout.addLayout(status_layout, stretch=10)
        
        self.setLayout(main_layout)
        
        # 5. Event-Verknüpfungen
        self.btn_beschuss.clicked.connect(lambda: self.start_drive("Beschuss"))
        self.btn_wertung.clicked.connect(lambda: self.start_drive("Wertung"))
        self.btn_licht_an.clicked.connect(lambda: self.set_light(True))
        self.btn_licht_aus.clicked.connect(lambda: self.set_light(False))
        self.btn_einstellungen.clicked.connect(self.open_settings)
        self.btn_exit.clicked.connect(self.handle_exit)
        self.showFullScreen()

        
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
        if not inputs[0]: self.handle_system_error("FEHLER: Motorschutzschalter ausgelöst (In1=0)!")
        elif any(inputs[2:6]): self.handle_system_error("FEHLER: Schütze nicht in Nullstellung!")
        else:
            if inputs[1]:  # In2 = True: Wagen steht bereits perfekt in der Startposition
                self.status_msg.setText("zur Auswertung bereit")
                self.status_msg.setStyleSheet("color: #00ff00; background-color: #111111; padding-left: 20px; border-radius: 8px;")
                self.btn_beschuss.setEnabled(True); self.btn_wertung.setEnabled(False)
                self.monitor_timer.start(250)
            else:          # In2 = False: Wagen steht irgendwo auf der Bahn -> Automatische Home-Fahrt!
                self.status_msg.setText("Wagen nicht in Startposition! Bereite Home-Fahrt vor...")
                self.status_msg.setStyleSheet("color: #ffaa00; background-color: #111111; padding-left: 20px; border-radius: 8px;")
                
                # ZWANGSPAUSE: Wir schalten noch einmal ALLES ab (Sicherheits-Löschung)
                self.client.write_multiple_coils(0, [False] * 8)
                
                # Dem Modbus-Modul und den Schützen Zeit geben physisch abzufallen (0.3 Sekunden)
                time.sleep(0.3) 
                
                # Erst JETZT, wenn alles garantiert AUS ist, den Fahr-Thread starten
                self.start_drive("HomeFahrt")


    def cyclic_monitor(self):
        if self.is_driving: return
        
        inputs = self.client.read_discrete_inputs(0, 8)
        coils = self.client.read_coils(0, 8)
        
        # 1. Verbindung prüfen
        if not inputs or len(inputs) < 6:
            self.status_msg.setText("FEHLER: Modbus Verbindung verloren!")
            self.status_msg.setStyleSheet("color: #ff0000; background-color: #111111; padding: 8px; border: 2px solid red; border-radius: 8px;")
            self.btn_beschuss.setEnabled(False); self.btn_wertung.setEnabled(False)
            return
            
        # Live-Daten für das Einstellungsfenster sichern
        self.latest_inputs = inputs
        self.latest_coils = coils if coils else [False]*8
        
        # 2. Wenn das System im Fehler-Modus ist: Keine Fahrt erlauben, Ausgänge sperren
        if self.system_fault:
            self.btn_beschuss.setEnabled(False)
            self.btn_wertung.setEnabled(False)
            try:
                # Dauerhafter Schutz: Ausgänge im Fehlerfall jede 250ms auf False zwingen
                self.client.write_multiple_coils(0, [False] * 8)
            except:
                pass
            return  # Monitor-Durchlauf hier abbrechen, damit der Fehler stehen bleibt
            
        # 3. Normaler Betrieb (wenn kein Fehler vorliegt)
        if not inputs[0]: 
            self.handle_system_error("FEHLER: Motorschutzschalter ausgelöst!")
            return
            
        if inputs[1]:
            self.status_msg.setText("zur Auswertung bereit")
            self.status_msg.setStyleSheet("color: #00ff00; background-color: #111111; padding: 8px; border-radius: 8px;")
            self.btn_beschuss.setEnabled(True); self.btn_wertung.setEnabled(False)
        else:
            self.status_msg.setText("Bahn frei? / Beschuss bereit")
            self.status_msg.setStyleSheet("color: #ffff00; background-color: #111111; padding: 8px; border-radius: 8px;")
            self.btn_beschuss.setEnabled(False); self.btn_wertung.setEnabled(True)


    def start_drive(self, mode):
        self.is_driving = True; self.monitor_timer.stop()
        self.btn_beschuss.setEnabled(False); self.btn_wertung.setEnabled(False); self.btn_einstellungen.setEnabled(True)
        self.client.main_app_ref = self
        self.thread = DriveThread(mode, self.client, self.times)
        self.thread.start_fast = time.time()
        self.thread.status_signal.connect(self.update_status)
        self.thread.error_signal.connect(self.handle_system_error)
        self.thread.finished_signal.connect(self.drive_finished)
        self.thread.drive_time_signal.connect(self.add_drive_time)
        self.thread.start()
        # NEU: Grafik-Animation zeitgleich mit dem Motor starten!
        self.start_position_animation(mode)

    def update_status(self, text):
        self.status_msg.setText(text)
        if text == "Unterwegs":
            self.status_msg.setStyleSheet("color: #ffaa00; background-color: #111111; padding: 8px; border-radius: 8px;")

    def drive_finished(self):
        self.stop_position_animation()  # NEU
        self.is_driving = False
        if self.exit_requested: self.close_program_safely()
        else: self.monitor_timer.start(250)

    def handle_system_error(self, message):
        self.stop_position_animation()  # NEU
        self.is_driving = False
        self.system_fault = True
        
        # Fehler mit Zeitstempel in das GUI-Logbuch eintragen
        timestamp = time.strftime("%d.%m.%Y %H:%M:%S")
        clean_msg = message.replace("FEHLER: ", "")
        self.gui_error_list.insert(0, f"[{timestamp}] {clean_msg}")
        
        if len(self.gui_error_list) > 5:
            self.gui_error_list.pop() # Nur die neuesten 5 behalten
            
        # NEU: Fehlerliste sofort ausfallsicher auf die SD-Karte schreiben
        save_error_log(self.gui_error_list)
            
        try: self.client.write_multiple_coils(0, [False] * 8)
        except: pass
            
        self.status_msg.setText(message)
        self.status_msg.setStyleSheet("color: #ff0000; background-color: #111111; padding: 8px; border: 2px solid red; border-radius: 8px;")
        self.btn_beschuss.setEnabled(False); self.btn_wertung.setEnabled(False)
        if not self.monitor_timer.isActive(): self.monitor_timer.start(250)


    def set_light(self, state): 
        # NEU: Schützt das Lichtrelais vor schnellem Flattern
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
        self.settings_window.show(); self.settings_window.raise_(); self.settings_window.activateWindow()
        
    def handle_exit(self):
        if self.is_driving: 
            self.exit_requested = True
            self.status_msg.setText("Exit angefordert. Letzte Fahrt wird beendet...")
        else: 
            self.close_program_safely()
            
    def close_program_safely(self):
        self.monitor_timer.stop()
        self.hours_timer.stop() # NEU
        save_operating_hours(self.hours_data) # NEU: Beim regulären Beenden sichern
        if hasattr(self, 'settings_window') and self.settings_window is not None: self.settings_window.close()
        try: self.client.write_multiple_coils(0, [False] * 8); self.client.close()
        except: pass
        sys.exit(0)
        
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape or event.key() == Qt.Key_Q: self.handle_exit()

    # NEU: Startet den Tippbetrieb aus dem Einstellungsfenster heraus
    def start_tipp_mode(self, direction):
        if self.system_fault or self.is_driving: return
        self.is_driving = True
        self.monitor_timer.stop()
        self.client.main_app_ref = self
        self.thread = DriveThread(direction, self.client, self.times)
        self.thread.drive_time_signal.connect(self.add_drive_time)
        self.thread.start()

    # NEU: Stoppt den Tippbetrieb sofort beim Loslassen des Touch-Buttons
    def stop_tipp_mode(self):
        if not self.is_driving: return
        self.stop_position_animation()  # NEU
        try:
            # Thread beenden und Ausgänge sofort auf False zwingen
            if hasattr(self, 'thread') and self.thread.isRunning():
                self.thread.terminate() # Tipp-Dauerschleife hart abbrechen
                self.thread.wait()
            self.client.write_multiple_coils(0, [False] * 8)
        except:
            pass
        self.is_driving = False
        self.monitor_timer.start(250)

    # NEU: Methode zum vollständigen Löschen des remanenten Logbuchs
    def clear_gui_error_log(self):
        self.gui_error_list = []
        from config_loader import save_error_log
        save_error_log(self.gui_error_list)
        
    def start_position_animation(self, mode):
        self.anim_mode = mode
        self.anim_start_time = time.time()
        
        # Fahrtzeiten dynamisch laden
        self.t_beschuss_schnell = self.times.get("Beschuss Schnell", 3.0)
        self.t_beschuss_langsam = self.times.get("Beschuss Langsam", 2.0)
        self.t_wertung_schnell = self.times.get("Wertung Schnell", 2.5)
        
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.process_target_movement)
        self.animation_timer.start(30)

    def process_target_movement(self):
        elapsed = time.time() - self.anim_start_time
        progress_percent = 0
        
        # --- MODUS BESCHUSS (Wandert nach rechts) ---
        if self.anim_mode == "Beschuss":
            total_time = self.t_beschuss_schnell + self.t_beschuss_langsam
            if elapsed >= total_time:
                progress_percent = 100
                self.animation_timer.stop()
            else:
                progress_percent = int((elapsed / total_time) * 100)
                
        # --- MODUS WERTUNG / HOME-FAHRT (Wandert nach links) ---
        elif self.anim_mode in ["Wertung", "HomeFahrt"]:
            estimated_total = self.t_wertung_schnell + 3.0
            if elapsed >= estimated_total:
                progress_percent = 0
                self.animation_timer.stop()
            else:
                progress_percent = int(100 - ((elapsed / estimated_total) * 100))
                if progress_percent < 0: progress_percent = 0

        # --- MODUS MANUELLER TIPPBETRIEB ---
        elif self.anim_mode == "TippVor":
            progress_percent = self.track_bar.value() + 1
            if progress_percent > 100: progress_percent = 100
        elif self.anim_mode == "TippRueck":
            progress_percent = self.track_bar.value() - 1
            if progress_percent < 0: progress_percent = 0

        # 1. Den Fortschrittsbalken im Hintergrund füllen
        self.track_bar.setValue(progress_percent)
        
        # 2. POSITIONIERUNG DIREKT AUF DER SCHIENE
        # Die maximale Fahrbreite innerhalb des Balkens ermitteln
        available_width = self.track_bar.width() - 42
        if available_width <= 0: 
            available_width = 800
            
        # Da wir im Balken liegen, ist 0% exakt x=0! Kein Offset-Raten mehr nötig.
        target_x = int((progress_percent / 100.0) * available_width)
        
        # Das Symbol auf der Schiene verschieben (Y-Wert bleibt zentriert bei -2)
        self.moving_target.move(target_x, -15)

    def stop_position_animation(self):
        if hasattr(self, 'animation_timer') and self.animation_timer.isActive():
            self.animation_timer.stop()
        inputs = self.client.read_discrete_inputs(0, 8)
        if inputs and len(inputs) >= 2 and inputs[1]:  # In2 aktiv = Am Stand
            self.track_bar.setValue(0)
            # KORREKTUR: Auch beim Stoppen fest auf -16 setzen
            self.moving_target.move(0, -15) 


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SchussbahnApp()
    window.show()
    sys.exit(app.exec_())
