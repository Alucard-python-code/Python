# -*- coding: utf-8 -*-
import time
import logging
from config_loader import save_error_log

class SafetyManager:
    def __init__(self, parent_app):
        self.app = parent_app

    def run_startup_check(self):
        """Prüft die Bedingungen beim Systemstart."""
        inputs = self.app.ipc.query_backend(self.app.current_static_relays)

        if not self.app.ipc.connected:
            self.app.update_ui_connectivity(False)
            self.app.status_msg.setText("START-WARNUNG: IPC-Dienst offline! Warte auf Backend...")
            self.app.status_msg.setStyleSheet("color: #ffaa00; background-color: #111111; padding-left: 15px; border-radius: 6px;")
            self.app.btn_beschuss.setEnabled(False)
            self.app.btn_wertung.setEnabled(False)
            self.app.central_monitor_timer.start(250)
            return

        self.app.update_ui_connectivity(True)
        self.app.latest_inputs = inputs

        if not inputs or len(inputs) < 2: 
            self.handle_system_error("FEHLER: Motorschutzschalter ausgelöst (In1=0)!")
        elif any(inputs[2:6]): 
            self.handle_system_error("FEHLER: Schütze nicht in Nullstellung!")
        else:
            if inputs[1]: 
                self.app.status_msg.setText("zur Auswertung bereit")
                self.app.status_msg.setStyleSheet("color: #00ff00; background-color: #111111; padding-left: 15px; border-radius: 6px;")
                self.app.btn_beschuss.setEnabled(True)
                self.app.btn_wertung.setEnabled(False)
                self.app.ist_referenziert = True
                self.app.central_monitor_timer.start(250)
            else: 
                self.app.status_msg.setText("Wagen nicht in Startposition! Bereite Home-Fahrt vor...")
                self.app.status_msg.setStyleSheet("color: #ffaa00; background-color: #111111; padding-left: 15px; border-radius: 6px;")
                time.sleep(0.3) 
                self.app.start_drive("HomeFahrt")

    def handle_system_error(self, message):
        """Sperrt die Anlage hart bei kritischen Fehlern und loggt diese."""
        self.app.animation.stop() 
        self.app.is_driving = False
        self.app.system_fault = True

        timestamp = time.strftime("%d.%m.%Y %H:%M:%S")
        clean_msg = message.replace("FEHLER: ", "")
        self.app.gui_error_list.insert(0, f"[{timestamp}] {clean_msg}")

        if len(self.app.gui_error_list) > 5:
            self.app.gui_error_list.pop()

        save_error_log(self.app.gui_error_list)

        self.app.current_static_relays = [False, False, False, False]
        self.app.ipc.query_backend(self.app.current_static_relays)

        self.app.status_msg.setText(message)
        self.app.status_msg.setStyleSheet("color: #ff0000; background-color: #111111; padding: 6px; border: 1px solid red; border-radius: 6px;")
        self.app.btn_beschuss.setEnabled(False)
        self.app.btn_wertung.setEnabled(False)

        if not self.app.central_monitor_timer.isActive(): 
            self.app.central_monitor_timer.start(250)
