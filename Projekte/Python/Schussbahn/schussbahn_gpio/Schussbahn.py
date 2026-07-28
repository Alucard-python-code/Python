#!/usr/bin/python3
# -*- coding: utf-8 -*-
import sys
import time
from PyQt5.QtWidgets import *
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QIcon
from gpiozero import DigitalInputDevice, OutputDevice
from config_loader import load_settings, save_settings, add_to_error_log
from ui_dialogs import SettingsWindow
from drive_worker import DriveThread

class SchussbahnApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.times = load_settings()
        self.ist_referenziert = False
        self.is_driving = False
        self.system_fault = False
        
        self.latest_inputs = [False] * 6
        self.latest_coils = [False] * 8

        # Hardware-Initialisierung (Pins für die GPIO-Variante)
        self.in_motorschutz = DigitalInputDevice(18, pull_up=True)
        self.in_endschalter = DigitalInputDevice(23, pull_up=True)
        self.in_schuetz_r   = DigitalInputDevice(24, pull_up=True)
        self.in_schuetz_l   = DigitalInputDevice(25, pull_up=True)
        self.in_schuetz_la  = DigitalInputDevice(16, pull_up=True)
        self.in_schuetz_sc  = DigitalInputDevice(12, pull_up=True)

        self.out_rechts     = OutputDevice(5, active_high=True, initial_value=False)
        self.out_links      = OutputDevice(6, active_high=True, initial_value=False)
        self.out_langsam    = OutputDevice(13, active_high=True, initial_value=False)
        self.out_schnell    = OutputDevice(19, active_high=True, initial_value=False)
        self.out_licht      = OutputDevice(21, active_high=True, initial_value=False)

        self.init_ui()

        # Timer für die permanente E/A-Überwachung im Hintergrund
        self.monitor_timer = QTimer(self)
        self.monitor_timer.timeout.connect(self.check_hardware_monitor)
        self.monitor_timer.start(100)

        # Timer für das blinkende Warn-Label bei der HomeFahrt
        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self.toggle_blink_label)
        self.blink_state = False

    def init_ui(self):
        self.setWindowTitle("Schussbahn Steuerung Wenkheim (GPIO)")
        self.setFixedSize(1024, 600)
        self.setWindowFlags(Qt.FramelessWindowHint)
        
        # HG-Farbe an Modbus angepasst (Dunkles Anthrazit #222)
        self.setStyleSheet("background-color: #222222; color: white; font-family: Arial;")

        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # ÜBERSCHRIFT (Goldgelb wie bei Modbus)
        title = QLabel("SCHUSSBAHN WENKHEIM")
        title.setFont(QFont("Arial", 24, QFont.Bold))
        title.setStyleSheet("color: #FFD700;")
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)

        # STATUS-ANZEIGE / WARN-LABEL
        self.status_msg = QLabel("System bereit. Bitte Referenzfahrt (Home) starten.")
        self.status_msg.setFont(QFont("Arial", 16, QFont.Bold))
        # Style exakt an Modbus angepasst
        self.status_msg.setStyleSheet("color: #ffaa00; background-color: #111111; padding: 15px; border-radius: 6px;")
        self.status_msg.setAlignment(Qt.AlignCenter)
        self.status_msg.setFixedHeight(60)
        main_layout.addWidget(self.status_msg)

        # AKTIONSTASTEN (Layout & Farben identisch zu Modbus)
        grid = QGridLayout()
        grid.setSpacing(15)

        self.btn_home = QPushButton("HOME\n(Referenzfahrt)")
        self.btn_home.setFont(QFont("Arial", 14, QFont.Bold))
        # Blaues Design für die Home-Taste
        self.btn_home.setStyleSheet("background-color: #0055ff; color: white; border-radius: 8px; height: 90px;")
        self.btn_home.clicked.connect(lambda: self.start_drive("HomeFahrt"))
        grid.addWidget(self.btn_home, 0, 0)

        self.btn_beschuss = QPushButton("BESCHUSS\n(Fahrt nach Vorne)")
        self.btn_beschuss.setFont(QFont("Arial", 14, QFont.Bold))
        # Rotes Design für Beschuss-Fahrt
        self.btn_beschuss.setStyleSheet("background-color: #E30613; color: white; border-radius: 8px; height: 90px;")
        self.btn_beschuss.clicked.connect(lambda: self.start_drive("Beschuss"))
        grid.addWidget(self.btn_beschuss, 0, 1)

        self.btn_wertung = QPushButton("WERTUNG\n(Fahrt zum Schützen)")
        self.btn_wertung.setFont(QFont("Arial", 14, QFont.Bold))
        # Grünes Design für Wertungs-Rückfahrt
        self.btn_wertung.setStyleSheet("background-color: #458B00; color: white; border-radius: 8px; height: 90px;")
        self.btn_wertung.clicked.connect(lambda: self.start_drive("Wertung"))
        grid.addWidget(self.btn_wertung, 0, 2)

        # TIPP-BETRIEB STEUERUNG
        tipp_box = QHBoxLayout()
        self.btn_tipp_vor = QPushButton("Tipp Vor ➔")
        self.btn_tipp_vor.setFont(QFont("Arial", 12, QFont.Bold))
        self.btn_tipp_vor.setStyleSheet("background-color: #444; color: white; border-radius: 6px; height: 50px;")
        self.btn_tipp_vor.pressed.connect(lambda: self.start_drive("TippVor"))
        self.btn_tipp_vor.released.connect(self.stop_tipp)

        self.btn_tipp_zurueck = QPushButton("片 Tipp Zurück")
        self.btn_tipp_zurueck.setFont(QFont("Arial", 12, QFont.Bold))
        self.btn_tipp_zurueck.setStyleSheet("background-color: #444; color: white; border-radius: 6px; height: 50px;")
        self.btn_tipp_zurueck.pressed.connect(lambda: self.start_drive("TippRueck"))
        self.btn_tipp_zurueck.released.connect(self.stop_tipp)

        tipp_box.addWidget(self.btn_tipp_zurueck)
        tipp_box.addWidget(self.btn_tipp_vor)
        grid.addLayout(tipp_box, 1, 0, 1, 2)

        # SERVICE / SETUP BUTTON
        self.btn_settings = QPushButton("⚙ Service")
        self.btn_settings.setFont(QFont("Arial", 12, QFont.Bold))
        self.btn_settings.setStyleSheet("background-color: #555555; color: white; border-radius: 6px; height: 50px;")
        self.btn_settings.clicked.connect(self.open_settings)
        grid.addWidget(self.btn_settings, 1, 2)

        main_layout.addLayout(grid)

        # UNTERER STATUSBALKEN (Infotext & Uhrzeit)
        footer = QHBoxLayout()
        self.lbl_info = QLabel("Status: Bereit")
        self.lbl_info.setFont(QFont("Arial", 11))
        self.lbl_info.setStyleSheet("color: #aaa;")
        
        self.lbl_time = QLabel()
        self.lbl_time.setFont(QFont("Arial", 11))
        self.lbl_time.setStyleSheet("color: #aaa;")
        self.update_clock()
        
        footer.addWidget(self.lbl_info)
        footer.addStretch()
        footer.addWidget(self.lbl_time)
        main_layout.addLayout(footer)

        self.setCentralWidget(central_widget)

        # Uhrzeit-Timer starten (sekündliches Update)
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_clock)
        self.clock_timer.start(1000)

    def update_clock(self):
        self.lbl_time.setText(time.strftime("%d.%m.%Y  %H:%M:%S"))
    def check_hardware_monitor(self):
        """ Liest permanent die IO-Zustände aus (wichtig für die LEDs im Service-Menü) """
        if self.is_driving:
            return

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

        if not self.latest_inputs and not self.system_fault:
            self.handle_system_error("FEHLER: Motorschutzschalter im Stillstand ausgelöst!")

        # Wenn der Wagen physikalisch auf dem Endschalter steht, gilt er als referenziert
        if self.latest_inputs and not self.ist_referenziert:
            self.ist_referenziert = True
            if not self.system_fault:
                self.status_msg.setStyleSheet("color: #458B00; background-color: #111111; padding: 15px; border-radius: 6px;")
                self.status_msg.setText("Wagen in Startposition. Bereit für Beschuss.")

    def start_drive(self, gewuenschter_modus):
        if self.is_driving or self.system_fault:
            return

        # Erzwinge HomeFahrt, falls das System unreferenziert ist
        if not self.ist_referenziert and gewuenschter_modus in ["Beschuss", "Wertung"]:
            effektiver_modus = "HomeFahrt"
        else:
            effektiver_modus = gewuenschter_modus

        self.is_driving = True
        self.monitor_timer.stop()

        # Optische Alarmierung und Blink-Takt aktivieren
        if effektiver_modus == "HomeFahrt" and not self.ist_referenziert:
            self.status_msg.setText("ACHTUNG: REFERENZFAHRT AKTIV (LANGSAM)!")
            self.blink_timer.start(500)
        else:
            self.blink_timer.stop()
            # Gelber Statusbalken während der Fahrt (wie bei Modbus)
            self.status_msg.setStyleSheet("color: #ffaa00; background-color: #111111; padding: 15px; border-radius: 6px;")
            self.status_msg.setText(f"Modus: {effektiver_modus} läuft...")

        out_tuple = (self.out_rechts, self.out_links, self.out_langsam, self.out_schnell, self.out_licht)
        in_tuple = (self.in_motorschutz, self.in_endschalter, self.in_schuetz_r, self.in_schuetz_l, self.in_schuetz_la, self.in_schuetz_sc)

        self.thread = DriveThread(effektiver_modus, self.times, self.ist_referenziert, out_tuple, in_tuple)
        self.thread.io_update_signal.connect(self.handle_thread_io_update)
        self.thread.status_signal.connect(self.update_status)
        
        if effektiver_modus == "HomeFahrt":
            self.thread.finished_signal.connect(self.home_fahrt_erfolgreich)
        else:
            self.thread.finished_signal.connect(self.drive_finished)
            
        self.thread.error_signal.connect(self.fahrt_abgebrochen_fehler)
        self.thread.start()

    def toggle_blink_label(self):
        """ Lässt das Label während der unreferenzierten HomeFahrt rot/schwarz blinken """
        self.blink_state = not self.blink_state
        if self.blink_state:
            # Kräftiges Signalrot für die Alarmierung
            self.status_msg.setStyleSheet("color: white; background-color: #E30613; padding: 15px; border-radius: 6px;")
        else:
            self.status_msg.setStyleSheet("color: #E30613; background-color: #111111; padding: 15px; border-radius: 6px;")
    def handle_thread_io_update(self, inputs, coils):
        self.latest_inputs = inputs
        self.latest_coils = coils

    def update_status(self, statustext):
        self.lbl_info.setText(f"Status: {statustext}")

    def drive_finished(self):
        self.is_driving = False
        self.blink_timer.stop()
        # Modbus-konformes Grün für die erfolgreiche Beendigung
        self.status_msg.setStyleSheet("color: #458B00; background-color: #111111; padding: 15px; border-radius: 6px;")
        self.status_msg.setText("Fahrt erfolgreich beendet.")
        self.monitor_timer.start(100)

    def home_fahrt_erfolgreich(self):
        self.ist_referenziert = True
        self.is_driving = False
        self.blink_timer.stop()
        # Sattes Grün für erfolgreiche Referenzierung
        self.status_msg.setStyleSheet("color: #458B00; background-color: #111111; padding: 15px; border-radius: 6px;")
        self.status_msg.setText("Referenzfahrt erfolgreich! System bereit.")
        self.monitor_timer.start(100)

    def stop_tipp(self):
        if hasattr(self, 'thread') and self.thread.isRunning():
            self.thread.stop()

    def fahrt_abgebrochen_fehler(self, error_msg):
        self.blink_timer.stop()
        
        # Interaktiver Watchdog-Rettungsanker bei HomeFahrt-Zeitüberschreitung
        if error_msg == "TIMEOUT_HOMEFAHRT":
            self.is_driving = False
            self.out_rechts.off()
            self.out_links.off()
            self.out_langsam.off()
            self.out_schnell.off()
            
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Question)
            msg.setWindowTitle("Position unbekannt")
            msg.setText("Der Wagen hat den Endschalter im Zeitfenster nicht erreicht.\n\nSoll die HomeFahrt fortgesetzt werden?")
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg.setDefaultButton(QMessageBox.Yes)
            msg.setStyleSheet("background-color: #2b2b2b; color: white; font-size: 14px;")
            
            if msg.exec_() == QMessageBox.Yes:
                self.status_msg.setText("Wiederhole HomeFahrt...")
                self.start_drive("HomeFahrt")
            else:
                self.ist_referenziert = False
                self.handle_system_error("FEHLER: Referenzfahrt durch Benutzer abgebrochen!")
        else:
            self.ist_referenziert = False
            self.handle_system_error(error_msg)

    def handle_system_error(self, message):
        """ Schaltet die App bei schweren Hardwaredefekten in den roten Störungsmodus """
        self.system_fault = True
        self.is_driving = False
        self.blink_timer.stop()
        
        # Roter Alarmbalken (Exakt wie bei der Modbus-Variante)
        self.status_msg.setStyleSheet("color: #ffffff; background-color: #B22222; padding: 15px; border-radius: 6px;")
        self.status_msg.setText(message)
        add_to_error_log(message)
        
        # Hardware komplett abschalten
        self.out_rechts.off()
        self.out_links.off()
        self.out_langsam.off()
        self.out_schnell.off()
        self.monitor_timer.start(100)

    def trigger_system_reset(self):
        """ Quittiert den Fehlerzustand und setzt das System zurück """
        self.system_fault = False
        self.ist_referenziert = False
        self.status_msg.setStyleSheet("color: #ffaa00; background-color: #111111; padding: 15px; border-radius: 6px;")
        self.status_msg.setText("System zurückgesetzt. Bitte HomeFahrt starten.")

    def open_settings(self):
        if not hasattr(self, 'settings_window') or self.settings_window is None:
            self.settings_window = SettingsWindow(self)
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SchussbahnApp()
    window.show()
    sys.exit(app.exec_())
