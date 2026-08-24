# main.py

import sys
import time
from PyQt5.QtWidgets import QApplication, QInputDialog, QDialog, QLineEdit, QVBoxLayout, QLabel, QPushButton
from PyQt5.QtCore import Qt

# Eigene Module importieren
from config import INPUT_ENDSCHALTER, OUTPUT_RECHTS, OUTPUT_LINKS, OUTPUT_LANGSAM, OUTPUT_SCHNELL, OUTPUT_LICHT
from gui_base import Ui_SchlittenSteuerung
from settings_dialog import SettingsDialog
from control_logic import SchlittenLogik, FahrtWorker

class SchlittenApp(Ui_SchlittenSteuerung):
    def __init__(self):
        super().__init__()
        
        # Logik-Modul instanziieren
        self.logik = SchlittenLogik()
        
        # UI aus gui_base.py initialisieren
        self.setup_ui()
        self.lbl_bahn_titel.setText(self.logik.config.get('bahn_titel', 'Bahn 1'))
        self.init_signals()

        # IO-Zustände an die GUI-LEDs weiterleiten
        self.logik.worker.data_updated.connect(self.update_gui_leds)

    def init_signals(self):
        """Verknüpft die GUI-Buttons mit den jeweiligen Aktionen."""
        self.btn_beschuss.clicked.connect(self.handle_beschuss)
        self.btn_auswertung.clicked.connect(self.handle_auswertung)
        self.btn_licht_an.clicked.connect(lambda: self.logik.write_output_direct(OUTPUT_LICHT, True))
        self.btn_licht_aus.clicked.connect(lambda: self.logik.write_output_direct(OUTPUT_LICHT, False))
        self.btn_settings.clicked.connect(self.check_pin_and_open_settings)
        self.btn_exit.clicked.connect(self.close)

    def set_led_state(self, label, state):
        color = "#00FF00" if state else "#1A331A"
        label.setStyleSheet(f"""
            QLabel {{
                background-color: {color};
                border-radius: 7px;
                min-width: 14px;
                min-height: 14px;
                max-width: 14px;
                max-height: 14px;
                border: 1px solid #333333;
            }}
        """)

    def update_gui_leds(self, inputs, outputs):
        """Aktualisiert die farbigen LEDs auf der rechten Seite."""
        # 8 Eingänge aktualisieren
        for i in range(len(inputs)):
            if i < len(self.in_leds):
                self.set_led_state(self.in_leds[i], inputs[i])
        
        # 9 Ausgänge (inklusive Heartbeat an Index 8) aktualisieren
        for i in range(len(outputs)):
            if i < len(self.out_leds):
                self.set_led_state(self.out_leds[i], outputs[i])


    def show_watchdog_alarm(self, fahrt_name):
        """Öffnet das rote Alarmfenster bei einer Watchdog-Überschreitung."""
        alarm = QDialog(self)
        alarm.setWindowTitle("WATCHDOG ALARM")
        alarm.setFixedSize(350, 140)
        alarm.setStyleSheet("background-color: #2d0000; color: #ff3333; border: 2px solid #ff3333;")
        
        vbox = QVBoxLayout(alarm)
        lbl = QLabel(f"CRITICAL ERROR:\nWatchdog-Zeit für '{fahrt_name}' überschritten!\n\nAntrieb wurde zwangsabgeschaltet.")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("font-weight: bold; font-size: 12px; border: none;")
        vbox.addWidget(lbl)
        
        btn = QPushButton("Fehler Quittieren")
        btn.setStyleSheet("background-color: #ff3333; color: white; font-weight: bold; padding: 6px;")
        btn.clicked.connect(alarm.accept)
        vbox.addWidget(btn)
        
        alarm.exec_()

    def handle_fahrt_ergebnis(self, erfolg, fahrt_name):
        """Wird aufgerufen, sobald ein Fahrsegment beendet wurde (Erfolg oder Alarm)."""
        if not erfolg:
            self.show_watchdog_alarm(fahrt_name)

    def check_home_position(self, callback_funktion):
        """Überprüft die Home-Position. Falls nicht dort, wird Homing erzwungen."""
        if not self.logik.inputs[INPUT_ENDSCHALTER]:
            dialog = QDialog(self)
            dialog.setWindowTitle("Homing erforderlich")
            dialog.setFixedSize(300, 120)
            dialog.setStyleSheet("background-color: #1e1e1e; color: white;")
            
            vbox = QVBoxLayout(dialog)
            lbl = QLabel("Schlitten nicht auf Endschalter!\nLangsam zur Home-Position fahren?")
            lbl.setAlignment(Qt.AlignCenter)
            vbox.addWidget(lbl)
            
            btn = QPushButton("Bestätigen")
            btn.setStyleSheet("background-color: #1f5eff; padding: 6px; font-weight: bold; color: white;")
            
            def starte_homing():
                dialog.accept()
                wd = self.logik.config['wd_homing']
                
                self.h1 = FahrtWorker(self.logik, OUTPUT_LINKS, OUTPUT_LANGSAM, stop_am_endschalter=True, watchdog_limit=wd, fahrt_name="Homing / Referenzfahrt")
                
                def homing_beendet(erfolg, name):
                    if erfolg:
                        self.logik.homing_done = True
                        info = QDialog(self)
                        info.setWindowTitle("Bereit")
                        info.setFixedSize(250, 100)
                        info.setStyleSheet("background-color: #1e1e1e; color: white;")
                        ivbox = QVBoxLayout(info)
                        ilbl = QLabel("Referenzfahrt abgeschlossen.\nSystem ist jetzt bereit!")
                        ilbl.setAlignment(Qt.AlignCenter)
                        ibtn = QPushButton("OK")
                        ibtn.setStyleSheet("background-color: #2e7d32; padding: 4px; color: white;")
                        ibtn.clicked.connect(info.accept)
                        ivbox.addWidget(ilbl)
                        ivbox.addWidget(ibtn)
                        info.exec_()
                    else:
                        self.show_watchdog_alarm(name)

                self.h1.fahrt_beendet.connect(homing_beendet)
                self.h1.start()

            btn.clicked.connect(starte_homing)
            vbox.addWidget(btn)
            dialog.exec_()
        else:
            self.logik.homing_done = True
            callback_funktion()

    def handle_beschuss(self):
        def ablauf():
            wd = self.logik.config['wd_beschuss']
            self.p1 = FahrtWorker(self.logik, OUTPUT_RECHTS, OUTPUT_SCHNELL, dauer=self.logik.config['b_schnell'], watchdog_limit=wd, fahrt_name="Beschuss")
            
            def starte_phase_2(erfolg, name):
                if erfolg:
                    self.p2 = FahrtWorker(self.logik, OUTPUT_RECHTS, OUTPUT_LANGSAM, dauer=self.logik.config['b_langsam'], watchdog_limit=wd, fahrt_name="Beschuss")
                    self.p2.fahrt_beendet.connect(self.handle_fahrt_ergebnis)
                    self.p2.start()
                else:
                    self.show_watchdog_alarm(name)

            self.p1.fahrt_beendet.connect(starte_phase_2)
            self.p1.start()

        self.check_home_position(ablauf)

    def handle_auswertung(self):
        if not self.logik.homing_done:
            warning_dialog = QDialog(self)
            warning_dialog.setWindowTitle("Sicherheitssperre")
            warning_dialog.setFixedSize(320, 130)
            warning_dialog.setStyleSheet("background-color: #1e1e1e; color: white; border: 1px solid #d32f2f;")
            
            vbox = QVBoxLayout(warning_dialog)
            lbl = QLabel("WARNUNG: Keine Referenzfahrt bekannt!\nAuswertung blockiert.\nBitte zuerst 'Beschuss' für Homing nutzen.")
            lbl.setAlignment(Qt.AlignCenter)
            vbox.addWidget(lbl)
            
            btn = QPushButton("Verstanden")
            btn.setStyleSheet("background-color: #d32f2f; padding: 6px; font-weight: bold; color: white;")
            btn.clicked.connect(warning_dialog.accept)
            vbox.addWidget(btn)
            warning_dialog.exec_()
            return

        if self.logik.inputs[INPUT_ENDSCHALTER]:
            return
        
        wd = self.logik.config['wd_auswertung']
        self.a1 = FahrtWorker(self.logik, OUTPUT_LINKS, OUTPUT_SCHNELL, dauer=self.logik.config['a_schnell'], watchdog_limit=wd, fahrt_name="Auswertung")
        
        def starte_auswertung_phase_2(erfolg, name):
            if erfolg:
                self.a2 = FahrtWorker(self.logik, OUTPUT_LINKS, OUTPUT_LANGSAM, stop_am_endschalter=True, watchdog_limit=wd, fahrt_name="Auswertung")
                self.a2.fahrt_beendet.connect(self.handle_fahrt_ergebnis)
                self.a2.start()
            else:
                self.show_watchdog_alarm(name)

        self.a1.fahrt_beendet.connect(starte_auswertung_phase_2)
        self.a1.start()

    def check_pin_and_open_settings(self):
        pin_input, ok = QInputDialog.getText(self, "PIN-Eingabe", "Bitte 4-stelligen PIN eingeben:", QLineEdit.Password)
        if ok and pin_input == self.logik.config['pin']:
            dlg = SettingsDialog(self, self.logik.config)
            if dlg.exec_() == QDialog.Accepted:
                self.lbl_bahn_titel.setText(self.logik.config.get('bahn_titel', 'Bahn 1'))
                self.logik.worker.request_reconnect()

    def closeEvent(self, event):
        self.logik.shutdown()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = SchlittenApp()
    window.showFullScreen()
    sys.exit(app.exec_())
