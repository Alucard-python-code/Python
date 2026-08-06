#!/usr/bin/python3
# -*- coding: utf-8 -*-

import sys
import os
import logging
import time
from PyQt5.QtWidgets import*
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, QTimer
from pymodbus import FramerType
from pymodbus.client import ModbusTcpClient as ModbusClient # funktioniert nur mit raspi

from config_loader import load_settings, load_operating_hours, save_operating_hours, load_error_log, save_error_log, save_settings
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
        self.reconnect_counter = 0 # Neuer Zähler in __init__
        self.wartung_popup_gezeigt = False

        # Nach dem Einschalten der App steht der Schlitten irgendwo -> noch nicht referenziert!
        self.ist_referenziert = False

        modbus_ip = self.times.get("Modbus-IP", "192.168.8.250")
        # Port auf 502 standardisiert bzw. deinen ursprünglichen Zustand beibehalten, Timeout kurz gehalten
        self.client = ModbusClient(host=modbus_ip, port=502, timeout=0.5, framer=FramerType.RTU)
        self.client.connect()
        
        # UI-Fixierung für exakt 1024x600 px
        self.setFixedSize(1024, 600)
        self.init_ui()

        # Zyklischer Monitor für Stillstand
        self.central_monitor_timer = QTimer(self)
        self.central_monitor_timer.timeout.connect(self.cyclic_monitor)

        self.hours_timer = QTimer(self)
        self.hours_timer.timeout.connect(self.track_total_hours)
        self.hours_timer.start(1000) 

        # Timer für die rot blinkende Statusanzeige während der Referenzfahrt
        self.blink_status = False
        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self.toggle_blink_text)

        self.startup_safety_check()

    def check_wartung_fällig(self):
        laufzeit = self.times.get("Laufzeit Motor (min)", 0.0)
        intervall = self.times.get("Wartung Intervall (min)", 500.0)
        
        if laufzeit >= intervall:
            # UI-Anzeige im Status-Label
            if not self.is_driving:
                self.status_msg.setText("WARTUNG FÄLLIG!")
                self.status_msg.setStyleSheet("color: #ff0000; background-color: #111111; padding-left: 15px; border-radius: 6px; font-weight: bold;")
            
            # Popup nur einmal zeigen, wenn es noch nicht gezeigt wurde
            if not self.wartung_popup_gezeigt:
                self.wartung_popup_gezeigt = True  # Flag setzen
                
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Warning)
                msg.setWindowTitle("Wartungshinweis")
                msg.setText(f"Die Wartung ist fällig!\n\nAktuelle Laufzeit: {int(laufzeit)} min\nIntervall: {int(intervall)} min")
                msg.setStandardButtons(QMessageBox.Ok)
                msg.setStyleSheet("background-color: #2b2b2b; color: white;") # Dark-Mode Optik
                msg.exec_()

    def general_system_reset(self):
        """ Führt den globalen System-Reset aus und setzt den Referenzstatus zurück """
        try:
            self.blink_timer.stop()
            self.is_driving = False
            self.system_fault = False
            self.central_monitor_timer.stop()
            self.client.close()
            time.sleep(0.1)

            self.times = load_settings() 
            neue_ip = self.times.get("Modbus-IP", "192.168.8.250")
            self.client.host = neue_ip 

            if not self.client.connect():
                logging.error("System-Reset fehlgeschlagen: Modbus antwortet nicht.")
                return False

            self.client.write_coils(0, [False] * 8, device_id=1)

            self.exit_requested = False
            self.ist_referenziert = False  # Löscht den Referenzstatus -> Zwingt nächste Fahrt zu Langsamlauf
            self.startup_safety_check()
            logging.info("System-Reset durchgeführt. Modus HomeFahrt wird ausgeführt.")
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
        # Bestehende Logik für Betriebsstunden
        self.hours_data["fahrzeit_sekunden"] += seconds
        save_operating_hours(self.hours_data) 
        
        # NEU: Laufzeit für Wartung in Minuten addieren
        # seconds / 60 ergibt Minuten
        neue_minuten = seconds / 60.0
        aktuelle_laufzeit = self.times.get("Laufzeit Motor (min)", 0.0)
        self.times["Laufzeit Motor (min)"] = aktuelle_laufzeit + neue_minuten
        
        # Speichere die aktualisierten Zeiten in der Einstellungs-JSON
        save_settings(self.times)

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
            
            if btn == self.btn_exit:
                btn.setStyleSheet("""
                    QPushButton { background-color: #552222; color: #ffaaaa; border: 1px solid #774444; border-radius: 4px; }
                    QPushButton:pressed { background-color: #773333; }
                    QPushButton:disabled { background-color: #221111; color: #553333; border: 1px solid #332222; }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton { background-color: #444444; color: white; border: 1px solid #555555; border-radius: 4px; }
                    QPushButton:pressed { background-color: #666666; }
                    QPushButton:disabled { background-color: #222222; color: #666666; border: 1px solid #333333; }
                """)
                
            grid_layout.addWidget(btn, row, col)

        main_layout.addLayout(grid_layout, stretch=60)

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

    def toggle_blink_text(self):
        """ Lässt das Statuslabel während der Referenzfahrt rot blinken """
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
        # NEU: Try-Block schützt vor dem Einfrieren der GUI bei Netzwerkproblemen
        try:
            if not self.client.connected: 
                self.client.connect()
        except Exception as e:
            self.update_ui_connectivity(False)
            self.handle_system_error(f"FEHLER: Modbus-Verbindungsfehler! {e}")
            return

        # Prüfen, ob die Verbindung wirklich steht
        if not self.client.connected:
            self.update_ui_connectivity(False)
            self.handle_system_error("FEHLER: Modbus-Verbindung fehlgeschlagen!")
            return

        self.update_ui_connectivity(True)

        # Ausgänge nullen mit device_id=1
        res_coils = self.client.write_coils(address=0, value=[False] * 8, device_id=1)
        if res_coils.isError():
            self.handle_system_error("FEHLER: Modbus-Verbindung fehlgeschlagen beim Start!")
            return

        # Eingänge lesen mit device_id=1
        res_inputs = self.client.read_discrete_inputs(address=0, count=8, device_id=1)
        if res_inputs.isError():
            self.handle_system_error("FEHLER: Eingänge konnten nicht gelesen werden!")
            return
        
        inputs = res_inputs.bits
        self.latest_inputs = inputs
        
        if not inputs[0]: 
            self.handle_system_error("FEHLER: Motorschutzschalter ausgelöst (In1=0)!")
        elif any(inputs[2:6]): 
            self.handle_system_error("FEHLER: Schütze nicht in Nullstellung!")
        else:
            if inputs[1]: 
                self.status_msg.setText("zur Auswertung bereit")
                self.status_msg.setStyleSheet("color: #00ff00; background-color: #111111; padding-left: 15px; border-radius: 6px;")
                self.btn_beschuss.setEnabled(True)
                self.btn_wertung.setEnabled(False)
                self.ist_referenziert = True
                self.central_monitor_timer.start(250)
            else: 
                self.status_msg.setText("Wagen nicht in Startposition! Bereite Home-Fahrt vor...")
                self.status_msg.setStyleSheet("color: #ffaa00; background-color: #111111; padding-left: 15px; border-radius: 6px;")
                self.client.write_multiple_coils(address=0, value=[False] * 8, device_id=1)
                time.sleep(0.3) 
                self.start_drive("HomeFahrt")

    def cyclic_monitor(self):
        if self.is_driving: 
            return

        # NEU: .connected statt .is_open
        if not self.client.connected:
            try:
                self.client.connect()
            except:
                pass
            
            self.status_msg.setText("FEHLER: Modbus Verbindung verloren! (Reconnect...)")
            self.status_msg.setStyleSheet("color: #ff0000; background-color: #111111; padding: 6px; border: 1px solid red; border-radius: 6px;")
            self.update_ui_connectivity(False)
            self.btn_beschuss.setEnabled(False)
            self.btn_wertung.setEnabled(False)
            return 

        # NEU: Zyklischer Abruf via pymodbus mit device_id=1
        res_inputs = self.client.read_discrete_inputs(address=0, count=8, device_id=1)
        res_coils = self.client.read_coils(address=0, count=8, device_id=1)

        # Prüfen, ob das Waveshare-Board fehlerhafte Daten geliefert hat
        if res_inputs.isError() or res_coils.isError():
            self.status_msg.setText("FEHLER: Modbus Daten ungültig!")
            self.status_msg.setStyleSheet("color: #ff0000; background-color: #111111; padding: 6px; border: 1px solid red; border-radius: 6px;")
            self.btn_beschuss.setEnabled(False)
            self.btn_wertung.setEnabled(False)
            return

        # NEU: Daten aus dem .bits Feld extrahieren
        inputs = res_inputs.bits
        coils = res_coils.bits

        self.update_ui_connectivity(True)
        self.latest_inputs = inputs
        self.latest_coils = coils if coils else [False]*8
        
        # ... (Ab hier bleibt deine restliche Logik im cyclic_monitor unverändert)


        # Systemfehler-Prüfung
        if self.system_fault:
            self.btn_beschuss.setEnabled(False)
            self.btn_wertung.setEnabled(False)
            try: self.client.write_multiple_coils(address=0, value=[False] * 8, device_id=1)
            except: pass
            return 

        # Hardware-Status-Prüfung
        if not inputs[0]: 
            self.handle_system_error("FEHLER: Motorschutzschalter ausgelöst!")
            return

        # UI-Update je nach Status
        if inputs[1]: 
            self.status_msg.setText("zur Auswertung bereit")
            self.status_msg.setStyleSheet("color: #00ff00; background-color: #111111; padding: 6px; border-radius: 6px;")
            self.btn_beschuss.setEnabled(True)
            self.btn_wertung.setEnabled(False)
        else: 
            self.status_msg.setText("Bahn frei? / Beschuss bereit")
            self.status_msg.setStyleSheet("color: #ffff00; background-color: #111111; padding: 6px; border-radius: 6px;")
            self.btn_beschuss.setEnabled(False)
            self.btn_wertung.setEnabled(True)

    def update_ui_connectivity(self, is_connected):
        """Aktiviert/Deaktiviert die Licht-Buttons basierend auf dem Verbindungsstatus."""
        self.btn_licht_an.setEnabled(is_connected)
        self.btn_licht_aus.setEnabled(is_connected)
        
        # Optional: Visuelles Feedback, damit der User sieht, warum sie grau sind
        opacity = 1.0 if is_connected else 0.3
        self.btn_licht_an.setGraphicsEffect(QGraphicsOpacityEffect(opacity=opacity)) # Falls gewünscht

    def start_drive(self, gewünschter_modus):
        """ Startet den Fahr-Thread und erzwingt bei Bedarf die langsame, rot blinkende HomeFahrt """
        if self.is_driving or self.system_fault:
            return

        # Abfangen von Schnell-Modi, wenn das System seine Position nicht kennt
        if not self.ist_referenziert and gewünschter_modus in ["Beschuss", "Wertung"]:
            effektiver_modus = "HomeFahrt"
        else:
            effektiver_modus = gewünschter_modus

        self.is_driving = True
        self.central_monitor_timer.stop()
        self.start_position_animation(effektiver_modus)

        # Optische Alarmierung und Blink-Takt aktivieren
        if effektiver_modus == "HomeFahrt" and not self.ist_referenziert:
            self.status_msg.setText("ACHTUNG: REFERENZFAHRT AKTIV (LANGSAM)!")
            self.blink_timer.start(500)
        else:
            self.blink_timer.stop()
            self.status_msg.setStyleSheet("color: #ffaa00; background-color: #111111; padding: 6px; border-radius: 6px;")
            self.status_msg.setText(f"Modus: {effektiver_modus} läuft...")

        # Thread-Instanziierung
        self.drive_thread = DriveThread(
            mode=effektiver_modus, 
            client=self.client, 
            times=self.times, 
            ist_referenziert=self.ist_referenziert
        )
        
        # Signalverknüpfungen
        self.drive_thread.status_signal.connect(self.update_status)
        self.drive_thread.error_signal.connect(self.fahrt_abgebrochen_fehler)
        self.drive_thread.io_update_signal.connect(self.handle_thread_io_update)
        self.drive_thread.drive_time_signal.connect(self.add_drive_time)
        
        # HIER EINBINDEN: Live-Daten für die Einstellungs-Ansicht
        if hasattr(self, 'settings_window') and self.settings_window:
            self.drive_thread.io_update_signal.connect(self.settings_window.update_live_ios_safe)
            
        if effektiver_modus == "HomeFahrt":
            self.drive_thread.finished_signal.connect(self.home_fahrt_erfolgreich)
        else:
            self.drive_thread.finished_signal.connect(self.drive_finished)

        self.drive_thread.start()

    def home_fahrt_erfolgreich(self):
        """ Erfolgs-Callback nach Erreichen des Endschalters """
        self.blink_timer.stop()
        self.ist_referenziert = True
        self.status_msg.setStyleSheet("color: #00ff00; background-color: #111111; padding-left: 15px; border-radius: 6px;")
        self.status_msg.setText("zur Auswertung bereit")
        self.drive_finished()

    def fahrt_abgebrochen_fehler(self, error_msg):
        """ Stoppt die optischen Effekte und prüft auf HomeFahrt-Wiederholung """
        self.blink_timer.stop()
        
        # Falls es ein HomeFahrt-Timeout war: Frage den Benutzer interaktiv
        if error_msg == "TIMEOUT_HOMEFAHRT":
            self.is_driving = False
            
            # Schickes, dunkles Abfrage-Popup erzeugen
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Question)
            msg.setWindowTitle("Position unbekannt")
            msg.setText("Der Wagen hat den Endschalter im Zeitfenster nicht erreicht.\n\nSoll die HomeFahrt wiederholt werden?")
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg.setDefaultButton(QMessageBox.Yes)
            msg.setStyleSheet("background-color: #2b2b2b; color: white; font-size: 14px;")
            
            if msg.exec_() == QMessageBox.Yes:
                # Benutzer will wiederholen -> Starte erneuten Versuch
                self.status_msg.setText("Wiederhole HomeFahrt...")
                self.start_drive("HomeFahrt")
            else:
                # Benutzer drückt Nein -> Jetzt erst echtes System-Fault setzen
                self.ist_referenziert = False
                self.handle_system_error("FEHLER: Referenzfahrt abgebrochen (Zeitüberschreitung)!")
        
        else:
            # Jeder andere Hardware-Fehler (z.B. Motorschutzschalter) sperrt sofort hart
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
            self.central_monitor_timer.start(250)

    def handle_system_error(self, message):
        self.stop_position_animation() 
        self.is_driving = False
        self.system_fault = True

        timestamp = time.strftime("%d.%m.%Y %H:%M:%S")
        clean_msg = message.replace("FEHLER: ", "")
        self.gui_error_list.insert(0, f"[{timestamp}] {clean_msg}")

        if len(self.gui_error_list) > 5:
            self.gui_error_list.pop()

        save_error_log(self.gui_error_list)

        try: 
            self.client.write_multiple_coils(0, [False] * 8)
        except: 
            pass

        self.status_msg.setText(message)
        self.status_msg.setStyleSheet("color: #ff0000; background-color: #111111; padding: 6px; border: 1px solid red; border-radius: 6px;")
        self.btn_beschuss.setEnabled(False)
        self.btn_wertung.setEnabled(False)
        
        if not self.central_monitor_timer.isActive(): 
            self.central_monitor_timer.start(250)

    def set_light(self, state): 
        self.btn_licht_an.setEnabled(False)
        self.btn_licht_aus.setEnabled(False)
        try:
            if not self.client.is_open:
                raise Exception("Keine Verbindung")
            self.client.write_single_coil(address=7, value=state, device_id=1)
            # Nach Erfolg wieder freigeben
            QTimer.singleShot(500, lambda: self.update_ui_connectivity(True))
        except Exception as e:
            logging.error(f"Fehler beim Lichtschalten: {e}")
            self.update_ui_connectivity(False)
            
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
        self.central_monitor_timer.stop()
        self.hours_timer.stop() 
        self.blink_timer.stop()
        save_operating_hours(self.hours_data)
        if hasattr(self, 'settings_window') and self.settings_window is not None: 
            self.settings_window.close()
        try: 
            self.client.write_multiple_coils(address=0, value=[False] * 8, device_id=1)
            self.client.close()
        except: 
            pass
        sys.exit(0)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape or event.key() == Qt.Key_Q: 
            self.handle_exit()

    def start_tipp_mode(self, direction):
        """ Startet den Tipp-Betrieb (manuelle Fahrt) """
        if self.system_fault or self.is_driving: 
            return
        
        self.is_driving = True
        self.central_monitor_timer.stop()
        
        # Konsistente Nutzung von self.drive_thread
        self.drive_thread = DriveThread(
            mode=direction, 
            client=self.client, 
            times=self.times, 
            ist_referenziert=self.ist_referenziert
        )
        
        self.drive_thread.io_update_signal.connect(self.handle_thread_io_update)
        self.drive_thread.drive_time_signal.connect(self.add_drive_time)
        
        # Optional: Auch hier das Einstellungs-Fenster live aktualisieren, falls offen
        if hasattr(self, 'settings_window') and self.settings_window:
            self.drive_thread.io_update_signal.connect(self.settings_window.update_live_ios_safe)
            
        self.drive_thread.start()

    def stop_tipp_mode(self):
        """ Stoppt den Tipp-Betrieb sicher """
        if not self.is_driving: 
            return
            
        self.stop_position_animation() 
        
        try:
            # Überprüfung der korrekten Thread-Variable
            if hasattr(self, 'drive_thread') and self.drive_thread and self.drive_thread.isRunning():
                self.drive_thread.stop()
                self.drive_thread.wait()
            
            # SPS-Ausgänge auf Null setzen
            self.client.write_multiple_coils(address=0, value=[False] * 8, device_id=1)
        except Exception as e:
            logging.error(f"Fehler beim Stoppen des Tipp-Modus: {e}")
            
        self.is_driving = False
        self.central_monitor_timer.start(250)

    def start_position_animation(self, mode):
        self.anim_mode = mode
        self.anim_start_time = time.time()
        
        self.t_beschuss_schnell = self.times.get("Beschuss Schnell", 3.0)
        self.t_beschuss_langsam = self.times.get("Beschuss Langsam", 2.0)
        self.t_wertung_schnell = self.times.get("Wertung Schnell", 2.5)

        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.process_target_movement)
        self.animation_timer.start(30)

    def process_target_movement(self):
        elapsed = time.time() - self.anim_start_time
        progress_percent = 0

        if self.anim_mode == "Beschuss":
            total_time = self.t_beschuss_schnell + self.t_beschuss_langsam
            if elapsed >= total_time:
                progress_percent = 100
                self.animation_timer.stop()
            else:
                progress_percent = int((elapsed / total_time) * 100)

        elif self.anim_mode in ["Wertung", "HomeFahrt"]:
            estimated_total = self.t_wertung_schnell + 3.0
            if elapsed >= estimated_total:
                progress_percent = 0
                self.animation_timer.stop()
            else:
                progress_percent = int(100 - ((elapsed / estimated_total) * 100))
                if progress_percent < 0: 
                    progress_percent = 0

        elif self.anim_mode == "TippVor":
            progress_percent = self.track_bar.value() + 1
            if progress_percent > 100: 
                progress_percent = 100
        elif self.anim_mode == "TippRueck":
            progress_percent = self.track_bar.value() - 1
            if progress_percent < 0: 
                progress_percent = 0

        self.track_bar.setValue(progress_percent)

        available_width = self.track_bar.width() - 25
        if available_width <= 0: 
            available_width = 750

        target_x = int((progress_percent / 100.0) * available_width)
        self.moving_target.move(target_x, -4)

    def stop_position_animation(self):
        if hasattr(self, 'animation_timer') and self.animation_timer.isActive():
            self.animation_timer.stop()
        try:
            inputs = self.client.read_discrete_inputs(address=0, count=8, device_id=1)
            if inputs and len(inputs) >= 2 and inputs[1]:
                self.track_bar.setValue(0)
                self.moving_target.move(0, -3) 
        except:
            pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SchussbahnApp()
    window.show()
    sys.exit(app.exec_())