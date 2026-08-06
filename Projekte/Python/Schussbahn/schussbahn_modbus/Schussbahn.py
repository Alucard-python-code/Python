#!/usr/bin/python3
# -*- coding: utf-8 -*-

import sys
import os
import logging
import time
from PyQt5.QtWidgets import *
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, QTimer

# NEU: pymodbus für RTU-over-TCP Kommunikation importieren
from pymodbus import FramerType
from pymodbus.client import ModbusTcpClient as ModbusClient

from config_loader import load_settings, load_operating_hours, save_operating_hours, load_error_log, save_error_log, save_settings
from ui_dialogs import SettingsWindow
from drive_worker import DriveThread

# Log-Pfad auflösen
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
        self.reconnect_counter = 0 
        self.wartung_popup_gezeigt = False
        self.ist_referenziert = False

        modbus_ip = self.times.get("Modbus-IP", "192.168.8.203")
        
        # NEU: Client mit FramerType.RTU initialisieren
        self.client = ModbusClient(host=modbus_ip, port=502, timeout=0.5, framer=FramerType.RTU)
        self.client.connect()
        
        self.setFixedSize(1024, 600)
        self.init_ui()

        self.central_monitor_timer = QTimer(self)
        self.central_monitor_timer.timeout.connect(self.cyclic_monitor)

        self.hours_timer = QTimer(self)
        self.hours_timer.timeout.connect(self.track_total_hours)
        self.hours_timer.start(1000) 

        self.blink_status = False
        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self.toggle_blink_text)

        self.startup_safety_check()
    def check_wartung_fällig(self):
        laufzeit = self.times.get("Laufzeit Motor (min)", 0.0)
        intervall = self.times.get("Wartung Interval (min)", 500.0)
        
        if laufzeit >= intervall:
            if not self.is_driving:
                self.status_msg.setText("WARTUNG FÄLLIG!")
                self.status_msg.setStyleSheet("color: #ff0000; background-color: #111111; padding-left: 15px; border-radius: 6px; font-weight: bold;")
            
            if not self.wartung_popup_gezeigt:
                self.wartung_popup_gezeigt = True  
                
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Warning)
                msg.setWindowTitle("Wartungshinweis")
                msg.setText(f"Die Wartung ist fällig!\n\nAktuelle Laufzeit: {int(laufzeit)} min\nIntervall: {int(intervall)} min")
                msg.setStandardButtons(QMessageBox.Ok)
                msg.setStyleSheet("background-color: #2b2b2b; color: white;") 
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
            neue_ip = self.times.get("Modbus-IP", "192.168.8.203")
            self.client.host = neue_ip 

            # NEU: .connect() verwenden
            if not self.client.connect():
                logging.error("System-Reset fehlgeschlagen: Modbus antwortet nicht.")
                return False

            # NEU: .write_coils() mit Slave-ID 1
            self.client.write_coils(0, [False] * 8, device_id=1)

            self.exit_requested = False
            self.ist_referenziert = False  
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
        self.hours_data["fahrzeit_sekunden"] += seconds
        save_operating_hours(self.hours_data) 
        
        neue_minuten = seconds / 60.0
        aktuelle_laufzeit = self.times.get("Laufzeit Motor (min)", 0.0)
        self.times["Laufzeit Motor (min)"] = aktuelle_laufzeit + neue_minuten
        
        save_settings(self.times)
    def handle_thread_io_update(self, inputs, coils):
        self.latest_inputs = inputs
        self.latest_coils = coils

    def startup_safety_check(self):
        try:
            self.client.connect()
        except:
            pass

        # NEU: Verbindung über ein Test-Lesepaket prüfen (Ersetzt .is_open)
        test_read = self.client.read_discrete_inputs(0, 1, device_id=1)
        if test_read.isError():
            self.update_ui_connectivity(False)
            self.handle_system_error("FEHLER: Modbus-Verbindung fehlgeschlagen!")
            return

        self.update_ui_connectivity(True)

        if self.client.write_coils(0, [False] * 8, device_id=1).isError():
            self.handle_system_error("FEHLER: Modbus-Verbindung fehlgeschlagen beim Start!")
            return

        # NEU: Einlesen der Hardware-Eingänge via RTU
        res_inputs = self.client.read_discrete_inputs(0, 8, device_id=1)
        if res_inputs.isError():
            self.handle_system_error("FEHLER: Eingänge konnten nicht gelesen werden!")
            return
        
        inputs = res_inputs.bits
        self.latest_inputs = inputs
        
        if not inputs or len(inputs) < 6:
            self.handle_system_error("FEHLER: Eingänge unvollständig!")
            return

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
                self.client.write_coils(0, [False] * 8, device_id=1)
                time.sleep(0.3) 
                self.start_drive("HomeFahrt")

    def cyclic_monitor(self):
        if self.is_driving: 
            return

        # --- RECONNECT LOGIK VIA RTU-TEST ---
        test_read = self.client.read_discrete_inputs(0, 1, device_id=1)
        if test_read.isError():
            self.client.close()
            time.sleep(0.1)
            self.client.connect()
            
            self.status_msg.setText("FEHLER: Modbus Verbindung verloren! (Reconnect...)")
            self.status_msg.setStyleSheet("color: #ff0000; background-color: #111111; padding: 6px; border: 1px solid red; border-radius: 6px;")
            self.update_ui_connectivity(False)
            self.btn_beschuss.setEnabled(False)
            self.btn_wertung.setEnabled(False)
            return 

        # NEU: Zyklischer Abruf der IO-Zustände (.bits)
        res_inputs = self.client.read_discrete_inputs(0, 8, device_id=1)
        res_coils = self.client.read_coils(0, 8, device_id=1)

        if res_inputs.isError() or res_coils.isError():
            self.status_msg.setText("FEHLER: Modbus Daten ungültig!")
            self.status_msg.setStyleSheet("color: #ff0000; background-color: #111111; padding: 6px; border: 1px solid red; border-radius: 6px;")
            self.btn_beschuss.setEnabled(False)
            self.btn_wertung.setEnabled(False)
            try: self.client.close()
            except: pass
            return

        inputs = res_inputs.bits
        coils = res_coils.bits

        self.update_ui_connectivity(True)
        self.latest_inputs = inputs
        self.latest_coils = coils if coils else [False]*8

        if self.system_fault:
            self.btn_beschuss.setEnabled(False)
            self.btn_wertung.setEnabled(False)
            try: self.client.write_coils(0, [False] * 8, device_id=1)
            except: pass
            return

        if not inputs[0]: 
            self.handle_system_error("FEHLER: Motorschutzschalter ausgelöst!")
            return

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
    def start_drive(self, gewünschter_modus):
        if self.is_driving or self.system_fault:
            return

        if not self.ist_referenziert and gewünschter_modus in ["Beschuss", "Wertung"]:
            effektiver_modus = "HomeFahrt"
        else:
            effektiver_modus = gewünschter_modus

        self.is_driving = True
        self.central_monitor_timer.stop()
        self.start_position_animation(effektiver_modus)

        if effektiver_modus == "HomeFahrt" and not self.ist_referenziert:
            self.status_msg.setText("ACHTUNG: REFERENZFAHRT AKTIV (LANGSAM)!")
            self.blink_timer.start(500)
        else:
            self.blink_timer.stop()
            self.status_msg.setStyleSheet("color: #ffaa00; background-color: #111111; padding: 6px; border-radius: 6px;")
            self.status_msg.setText(f"Modus: {effektiver_modus} läuft...")

        self.drive_thread = DriveThread(
            mode=effektiver_modus, 
            client=self.client, 
            times=self.times, 
            ist_referenziert=self.ist_referenziert
        )

        self.drive_thread.status_signal.connect(self.update_status)
        self.drive_thread.error_signal.connect(self.fahrt_abgebrochen_fehler)
        self.drive_thread.io_update_signal.connect(self.handle_thread_io_update)
        self.drive_thread.drive_time_signal.connect(self.add_drive_time)

        if hasattr(self, 'settings_window') and self.settings_window:
            self.drive_thread.io_update_signal.connect(self.settings_window.update_live_ios_safe)

        if effektiver_modus == "HomeFahrt":
            self.drive_thread.finished_signal.connect(self.home_fahrt_erfolgreich)
        else:
            self.drive_thread.finished_signal.connect(self.drive_finished)

        self.drive_thread.start()

    def set_light(self, state): 
        self.btn_licht_an.setEnabled(False)
        self.btn_licht_aus.setEnabled(False)
        try:
            # NEU: .write_coil() statt .write_single_coil() mit device_id=1
            res = self.client.write_coil(7, state, device_id=1)
            if res.isError():
                raise Exception("Schreibfehler über Modbus RTU Frame")
            QTimer.singleShot(500, lambda: self.update_ui_connectivity(True))
        except Exception as e:
            logging.error(f"Fehler beim Lichtschalten: {e}")
            self.update_ui_connectivity(False)

        QTimer.singleShot(500, lambda: self.btn_licht_an.setEnabled(True))
        QTimer.singleShot(500, lambda: self.btn_licht_aus.setEnabled(True))

    def stop_tipp_mode(self):
        if not self.is_driving: 
            return

        self.stop_position_animation() 

        try:
            if hasattr(self, 'drive_thread') and self.drive_thread and self.drive_thread.isRunning():
                self.drive_thread.stop()
                self.drive_thread.wait()

            # NEU: Alle SPS-Ausgänge nullen mit device_id=1
            self.client.write_coils(0, [False] * 8, device_id=1)
        except Exception as e:
            logging.error(f"Fehler beim Stoppen des Tipp-Modus: {e}")

        self.is_driving = False
        self.central_monitor_timer.start(250)

    def close_program_safely(self):
        self.central_monitor_timer.stop()
        self.hours_timer.stop() 
        self.blink_timer.stop()
        save_operating_hours(self.hours_data)
        if hasattr(self, 'settings_window') and self.settings_window is not None: 
            self.settings_window.close()
        try: 
            self.client.write_coils(0, [False] * 8, device_id=1)
            self.client.close()
        except: 
            pass
        sys.exit(0)
    # ... (Die restlichen UI-Methoden und die Animation bleiben für dieses Fenster unverändert)
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

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape or event.key() == Qt.Key_Q: 
            self.handle_exit()

    def start_tipp_mode(self, direction):
        if self.system_fault or self.is_driving: 
            return
        self.is_driving = True
        self.central_monitor_timer.stop()
        self.drive_thread = DriveThread(mode=direction, client=self.client, times=self.times, ist_referenziert=self.ist_referenziert)
        self.drive_thread.io_update_signal.connect(self.handle_thread_io_update)
        self.drive_thread.drive_time_signal.connect(self.add_drive_time)
        if hasattr(self, 'settings_window') and self.settings_window:
            self.drive_thread.io_update_signal.connect(self.settings_window.update_live_ios_safe)
        self.drive_thread.start()

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
            if elapsed >= total_time: progress_percent = 100; self.animation_timer.stop()
            else: progress_percent = int((elapsed / total_time) * 100)
        elif self.anim_mode in ["Wertung", "HomeFahrt"]:
            estimated_total = self.t_wertung_schnell + 3.0
            if elapsed >= estimated_total: progress_percent = 0; self.animation_timer.stop()
            else: progress_percent = int(100 - ((elapsed / estimated_total) * 100))
            if progress_percent < 0: progress_percent = 0
        elif self.anim_mode == "TippVor":
            progress_percent = self.track_bar.value() + 1
            if progress_percent > 100: progress_percent = 100
        elif self.anim_mode == "TippRueck":
            progress_percent = self.track_bar.value() - 1
            if progress_percent < 0: progress_percent = 0
        self.track_bar.setValue(progress_percent)
        available_width = self.track_bar.width() - 25
        if available_width <= 0: available_width = 750
        target_x = int((progress_percent / 100.0) * available_width)
        self.moving_target.move(target_x, -4)

    def stop_position_animation(self):
        if hasattr(self, 'animation_timer') and self.animation_timer.isActive():
            self.animation_timer.stop()
        try:
            # KORREKTUR: Nutzt das neue device_id Feld und wertet direkt das Listen-Array der Bits aus
            res = self.client.read_discrete_inputs(0, 8, device_id=1)
            if not res.isError() and res.bits:
                if res.bits[1]: # Wenn Wagen physisch wieder am Start-Endschalter (Index 1) steht
                    self.track_bar.setValue(0)
                    self.moving_target.move(0, -3) 
        except:
            pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SchussbahnApp()
    window.show()
    sys.exit(app.exec_())
