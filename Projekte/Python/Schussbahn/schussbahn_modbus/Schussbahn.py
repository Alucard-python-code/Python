#!/usr/bin/python3
# -*- coding: utf-8 -*-

import sys
import os
import time
from PyQt5.QtWidgets import QApplication, QWidget, QMessageBox
from PyQt5.QtCore import QTimer, Qt

# --- Modul-Importe der neuen Architektur ---
from config_loader import load_settings, load_operating_hours, save_operating_hours, save_settings
from ui_dialogs import SettingsWindow
from drive_worker import DriveThread
from ipc_client import IpcClient
from time_tracker import TimeTracker
from safety_manager import SafetyManager
from progress_animator import ProgressAnimator
from ui_components import setup_app_ui

class SchussbahnApp(QWidget):
    def __init__(self):
        super().__init__()
        
        # 1. Konfiguration laden
        self.times = load_settings()
        self.hours_data = load_operating_hours() 
        
        # 2. Submodule instanziieren
        self.ipc = IpcClient(host="127.0.0.1", port=65432)
        self.tracker = TimeTracker(self)
        self.safety = SafetyManager(self)
        self.animation = ProgressAnimator(self)

        # 3. Zustandsvariablen
        self.exit_requested = False
        self.is_driving = False
        self.system_fault = False
        self.ist_referenziert = False
        
        self.latest_inputs = [False] * 8
        self.latest_coils = [False] * 8
        self.current_static_relays = [False, False, False, False]
        self.gui_error_list = []
        self.wartung_popup_gezeigt = False
        self.blink_status = False

        # 4. UI bauen & Timer starten
        setup_app_ui(self)
        self._bind_signals()
        
        self.central_monitor_timer = QTimer(self)
        self.central_monitor_timer.timeout.connect(self.cyclic_monitor)

        self.hours_timer = QTimer(self)
        self.hours_timer.timeout.connect(self.tracker.track_total_hours)
        self.hours_timer.start(1000) 

        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self.toggle_blink_text)

        # 5. Ersten Hardware-Check durchführen
        self.safety.run_startup_check()

    def _bind_signals(self):
        self.btn_beschuss.clicked.connect(lambda: self.start_drive("Beschuss"))
        self.btn_wertung.clicked.connect(lambda: self.start_drive("Wertung"))
        self.btn_licht_an.clicked.connect(lambda: self.set_light(True))
        self.btn_licht_aus.clicked.connect(lambda: self.set_light(False))
        self.btn_einstellungen.clicked.connect(self.open_settings)
        self.btn_exit.clicked.connect(self.handle_exit)
        self.showFullScreen()

    def cyclic_monitor(self):
        if self.is_driving: 
            return

        inputs = self.ipc.query_backend(self.current_static_relays)

        if not self.ipc.connected:
            self.status_msg.setText("FEHLER: IPC-Verbindung zum Modbus-Dienst verloren!")
            self.status_msg.setStyleSheet("color: #ffaa00; background-color: #111111; padding: 6px; border: 1px solid #ffaa00; border-radius: 6px; font-weight: bold;")
            self.update_ui_connectivity(False)
            self.btn_beschuss.setEnabled(False)
            self.btn_wertung.setEnabled(False)
            return

        self.update_ui_connectivity(True)
        self.latest_inputs = inputs
        self.latest_coils = self.current_static_relays + [False]*4

        if self.system_fault:
            return

        if not inputs or len(inputs) < 2: 
            self.safety.handle_system_error("FEHLER: Motorschutzschalter ausgelöst!")
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

        effektiver_modus = "HomeFahrt" if (not self.ist_referenziert and gewünschter_modus in ["Beschuss", "Wertung"]) else gewünschter_modus

        self.is_driving = True
        self.central_monitor_timer.stop()
        self.animation.start(effektiver_modus)

        if effektiver_modus == "HomeFahrt" and not self.ist_referenziert:
            self.status_msg.setText("ACHTUNG: REFERENZFAHRT AKTIV (LANGSAM)!")
            self.blink_timer.start(500)
        else:
            self.blink_timer.stop()
            self.status_msg.setStyleSheet("color: #ffaa00; background-color: #111111; padding: 6px; border-radius: 6px;")
            self.status_msg.setText(f"Modus: {effektiver_modus} läuft...")

        try:
            # WICHTIG: client_dummy=None wird übergeben. 
            self.drive_thread = DriveThread(mode=effektiver_modus, client_dummy=None, times=self.times, ist_referenziert=self.ist_referenziert)
            self.drive_thread.status_signal.connect(self.update_status)
            self.drive_thread.error_signal.connect(self.fahrt_abgebrochen_fehler)
            self.drive_thread.io_update_signal.connect(self.handle_thread_io_update)
            self.drive_thread.drive_time_signal.connect(self.tracker.add_drive_time)

            if hasattr(self, 'settings_window') and self.settings_window:
                self.drive_thread.io_update_signal.connect(self.settings_window.update_live_ios_safe)

            # Verwende hier NUR noch den sicheren Funktionstext ohne direkte Verknüpfung von unvollständigen Callbacks
            if effektiver_modus == "HomeFahrt":
                self.drive_thread.finished_signal.connect(self.home_fahrt_erfolgreich)
            else:
                self.drive_thread.finished_signal.connect(self.drive_finished)
                
            self.drive_thread.start()
        except Exception as thread_error:
            print(f"Kritischer Fehler beim Thread-Start: {thread_error}")
            self.is_driving = False
            self.safety.handle_system_error(f"FEHLER: Thread-Start fehlgeschlagen! {thread_error}")


    def home_fahrt_erfolgreich(self):
        self.blink_timer.stop()
        self.ist_referenziert = True
        self.status_msg.setStyleSheet("color: #00ff00; background-color: #111111; padding-left: 15px; border-radius: 6px;")
        self.status_msg.setText("zur Auswertung bereit")
        # Rufe die Beendigung sauber auf:
        self.animation.stop()
        self.is_driving = False
        if self.exit_requested: 
            self.close_program_safely()
        else: 
            self.central_monitor_timer.start(250)

    def fahrt_abgebrochen_fehler(self, error_msg):
        self.blink_timer.stop()
        if error_msg == "TIMEOUT_HOMEFAHRT":
            self.is_driving = False
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Question)
            msg.setWindowTitle("Position unbekannt")
            msg.setText("Der Wagen hat den Endschalter im Zeitfenster nicht erreicht.\n\nSoll die HomeFahrt wiederholt werden?")
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg.setStyleSheet("background-color: #2b2b2b; color: white; font-size: 14px;")

            if msg.exec_() == QMessageBox.Yes:
                self.start_drive("HomeFahrt")
            else:
                self.ist_referenziert = False
                self.safety.handle_system_error("FEHLER: Referenzfahrt abgebrochen (Zeitüberschreitung)!")
        else:
            self.ist_referenziert = False
            self.safety.handle_system_error(error_msg)

    def set_light(self, state): 
        self.btn_licht_an.setEnabled(False)
        self.btn_licht_aus.setEnabled(False)
        
        # Relais 4 für das Backend (wird in drive_worker.py an Index 3 geführt)
        self.current_static_relays = state
        self.ipc.query_backend(self.current_static_relays)
        
        QTimer.singleShot(300, lambda: self.btn_licht_an.setEnabled(True))
        QTimer.singleShot(300, lambda: self.btn_licht_aus.setEnabled(True))

    def update_ui_connectivity(self, is_connected):
        self.btn_licht_an.setEnabled(is_connected)
        self.btn_licht_aus.setEnabled(is_connected)

    def toggle_blink_text(self):
        self.status_msg.setStyleSheet(f"color: {'#ff0000' if self.blink_status else 'transparent'}; background-color: #111111; padding-left: 15px; border-radius: 6px; font-weight: bold;")
        self.blink_status = not self.blink_status

    def handle_thread_io_update(self, inputs, coils):
        self.latest_inputs = inputs
        self.latest_coils = coils

    def update_status(self, text):
        if not self.blink_timer.isActive(): self.status_msg.setText(text)

    def drive_finished(self):
        self.animation.stop()
        self.is_driving = False
        if self.exit_requested: self.close_program_safely()
        else: self.central_monitor_timer.start(250)

    def open_settings(self):
        if not hasattr(self, 'settings_window') or self.settings_window is None:
            self.settings_window = SettingsWindow(self)
        self.settings_window.show()

    def handle_exit(self):
        if self.is_driving: 
            self.exit_requested = True
            self.status_msg.setText("Exit angefordert. Letzte Fahrt wird beendet...")
        else: 
            self.close_program_safely()

    def close_program_safely(self):
        self.central_monitor_timer.stop()
        self.hours_timer.stop()
        save_operating_hours(self.hours_data)
        try: self.ipc.query_backend([False, False, False, False])
        except: pass
        sys.exit(0)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SchussbahnApp()
    window.show()
    sys.exit(app.exec_())
