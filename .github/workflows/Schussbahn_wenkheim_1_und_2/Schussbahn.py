# Schussbahn.py - v2.0 (GPIO-Direktverdrahtung)
import sys
import os
import logging
import time
from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QLabel, QGridLayout, QVBoxLayout, QHBoxLayout, QProgressBar
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, QTimer
import RPi.GPIO as GPIO

from config_loader import load_settings, load_operating_hours, save_operating_hours, load_error_log, save_error_log, PINS_OUT, PINS_IN
from ui_dialogs import SettingsWindow
from drive_worker import DriveThread

try:
    import __main__
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__main__.__file__)) if hasattr(__main__, '__file__') else os.path.dirname(os.path.abspath(__file__))
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
        self.latest_inputs = [False] * 6
        self.latest_coils = [False] * 4
        self.gui_error_list = load_error_log() 

        # Physische GPIOs auf dem Pi initialisieren
        self.init_hardware_gpios()
        self.init_ui()

        self.monitor_timer = QTimer(self)
        self.monitor_timer.timeout.connect(self.cyclic_monitor)
        
        self.hours_timer = QTimer(self)
        self.hours_timer.timeout.connect(self.track_total_hours)
        self.hours_timer.start(1000) 

        self.startup_safety_check()

    def init_hardware_gpios(self):
        """Konfiguriert die GPIO-Pins des Raspberry Pi."""
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        
        # Ausgänge festlegen (Auf HIGH setzen, da Relais-Karte LOW-aktiv ist)
        for pin in PINS_OUT.values():
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, True) # Hart ausschalten bei Start
            
        # Eingänge festlegen mit internem Pull-Up Widerstand
        for pin in PINS_IN.values():
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def general_system_reset(self):
        try:
            self.is_driving = False
            self.system_fault = False
            self.monitor_timer.stop()
            
            # Alle Motorschütze hart wegschalten (True = AUS)
            for key, pin in PINS_OUT.items():
                if key != "Licht": GPIO.output(pin, True)
                
            self.times = load_settings()
            self.exit_requested = False
            self.startup_safety_check()
            return True
        except Exception as e:
            logging.error(f"Fehler Reset: {e}")
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
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

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
            btn.setMinimumHeight(240) # Angepasst für gängige Touchscreens
            grid_layout.addWidget(btn, row, col)

        main_layout.addLayout(grid_layout, stretch=75)

        # Positions-Balken
        position_container = QWidget()
        position_container.setFixedHeight(120)
        position_container.setStyleSheet("background-color: #1a1a1a; border-radius: 8px; border: 1px solid #444444;")
        track_layout = QHBoxLayout(position_container)
        track_layout.setContentsMargins(20, 0, 20, 0)
        track_layout.setSpacing(15)

        lbl_home = QLabel("Stand")
        lbl_home.setFont(QFont("Arial", 22, QFont.Bold))
        lbl_home.setStyleSheet("color: #00ffcc; border: none;")

        self.track_bar = QProgressBar()
        self.track_bar.setRange(0, 100)
        self.track_bar.setValue(0)
        self.track_bar.setTextVisible(False)
        self.track_bar.setFixedHeight(65) 
        self.track_bar.setStyleSheet("QProgressBar { background-color: #252525; border-radius: 6px; border: 1px solid #444444; } QProgressBar::chunk { background-color: #113322; border-radius: 5px; }")

        self.moving_target = QLabel("🎯", self.track_bar)
        self.moving_target.setFont(QFont("Arial", 32))
        self.moving_target.setStyleSheet("border: none; background: transparent;")
        self.moving_target.move(0, 5)

        lbl_end = QLabel("Kugelfang")
        lbl_end.setFont(QFont("Arial", 22, QFont.Bold))
        lbl_end.setStyleSheet("color: #ffaa00; border: none;")

        track_layout.addWidget(lbl_home)
        track_layout.addWidget(self.track_bar, stretch=1)
        track_layout.addWidget(lbl_end)
        main_layout.addWidget(position_container, stretch=15)

        # Statuszeile
        status_layout = QHBoxLayout()
        status_title = QLabel("Status: ")
        status_title.setFont(QFont("Arial", 24, QFont.Bold))
        status_title.setFixedWidth(160)
        status_layout.addWidget(status_title)

        self.status_msg = QLabel("Initialisierung...")
        self.status_msg.setFont(QFont("Arial", 24, QFont.Bold))
        self.status_msg.setStyleSheet("color: #00ff00; background-color: #111111; padding-left: 20px; border-radius: 8px;")
        status_layout.addWidget(self.status_msg)
        main_layout.addLayout(status_layout, stretch=10)

        self.setLayout(main_layout)

        self.btn_beschuss.clicked.connect(lambda: self.start_drive("Beschuss"))
        self.btn_wertung.clicked.connect(lambda: self.start_drive("Wertung"))
        self.btn_licht_an.clicked.connect(lambda: self.set_light(True))
        self.btn_licht_aus.clicked.connect(lambda: self.set_light(False))
        self.btn_einstellungen.clicked.connect(self.open_settings)
        self.btn_exit.clicked.connect(self.handle_exit)
        self.showFullScreen()

    def startup_safety_check(self):
        # Alle Schütze wegschalten bei Boot
        for pin in PINS_OUT.values():
            if pin != PINS_OUT["Licht"]: GPIO.output(pin, True)
            
        motorschutz = GPIO.input(PINS_IN["Motorschutz"])
        endschalter_home = GPIO.input(PINS_IN["Endschalter"])
        
        self.latest_inputs = [
            motorschutz, endschalter_home, GPIO.input(PINS_IN["Feedback_Rechts"]),
            GPIO.input(PINS_IN["Feedback_Links"]), GPIO.input(PINS_IN["Feedback_Langsam"]), GPIO.input(PINS_IN["Feedback_Schnell"])
        ]

        if not motorschutz:
            self.handle_system_error("FEHLER: Motorschutzschalter ausgelöst (In1=0)!")
            return

        # Prüfen ob Schütze frei sind (LOW-aktiv Rückmeldung)
        if any([not GPIO.input(PINS_IN["Feedback_Rechts"]), not GPIO.input(PINS_IN["Feedback_Links"]), 
                not GPIO.input(PINS_IN["Feedback_Langsam"]), not GPIO.input(PINS_IN["Feedback_Schnell"])]):
            self.handle_system_error("FEHLER: Schütze nicht in Nullstellung!")
            return

        if endschalter_home: # Endschalter bedient (Wagen steht am Stand)
            self.status_msg.setText("zur Auswertung bereit")
            self.status_msg.setStyleSheet("color: #00ff00; background-color: #111111; padding-left: 20px; border-radius: 8px;")
            self.btn_beschuss.setEnabled(True)
            self.btn_wertung.setEnabled(False)
            self.monitor_timer.start(250)
        else:
            self.status_msg.setText("Wagen nicht in Startposition! Bereite Home-Fahrt vor...")
            self.status_msg.setStyleSheet("color: #ffaa00; background-color: #111111; padding-left: 20px; border-radius: 8px;")
            time.sleep(0.3) 
            self.start_drive("HomeFahrt")

    def cyclic_monitor(self):
        if self.is_driving: return

        motorschutz = GPIO.input(PINS_IN["Motorschutz"])
        endschalter_home = GPIO.input(PINS_IN["Endschalter"])
        
        self.latest_inputs = [
            motorschutz, endschalter_home, GPIO.input(PINS_IN["Feedback_Rechts"]),
            GPIO.input(PINS_IN["Feedback_Links"]), GPIO.input(PINS_IN["Feedback_Langsam"]), GPIO.input(PINS_IN["Feedback_Schnell"])
        ]

        if self.system_fault:
            for pin in PINS_OUT.values():
                if pin != PINS_OUT["Licht"]: GPIO.output(pin, True)
            return

        if not motorschutz: 
            self.handle_system_error("FEHLER: Motorschutzschalter ausgelöst!")
            return

        if endschalter_home:
            self.status_msg.setText("zur Auswertung bereit")
            self.status_msg.setStyleSheet("color: #00ff00; background-color: #111111; padding: 8px; border-radius: 8px;")
            self.btn_beschuss.setEnabled(True)
            self.btn_wertung.setEnabled(False)
        else:
            self.status_msg.setText("Bahn frei? / Beschuss bereit")
            self.status_msg.setStyleSheet("color: #ffff00; background-color: #111111; padding: 8px; border-radius: 8px;")
            self.btn_beschuss.setEnabled(False)
            self.btn_wertung.setEnabled(True)

    def start_drive(self, mode):
        self.is_driving = True
        self.monitor_timer.stop()
        self.btn_beschuss.setEnabled(False)
        self.btn_wertung.setEnabled(False)
        self.thread = DriveThread(mode, self, self.times)
        self.thread.status_signal.connect(self.update_status)
        self.thread.error_signal.connect(self.handle_system_error)
        self.thread.finished_signal.connect(self.drive_finished)
        self.thread.drive_time_signal.connect(self.add_drive_time)
        self.thread.start()
        self.start_position_animation(mode)

    def update_status(self, text):
        self.status_msg.setText(text)
        if text == "Unterwegs":
            self.status_msg.setStyleSheet("color: #ffaa00; background-color: #111111; padding: 8px; border-radius: 8px;")

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
        timestamp = time.strftime("%d.%m.%Y %H:%M:%S")
        clean_msg = message.replace("FEHLER: ", "")
        self.gui_error_list.insert(0, f"({timestamp}) {clean_msg}")
        if len(self.gui_error_list) > 5: 
            self.gui_error_list.pop()
        save_error_log(self.gui_error_list)
        
        for pin in PINS_OUT.values():
            if pin != PINS_OUT["Licht"]: 
                GPIO.output(pin, True)
                
        self.status_msg.setText(message)
        self.status_msg.setStyleSheet("color: #ff0000; background-color: #111111; padding: 8px; border: 2px solid red; border-radius: 8px;")
        self.btn_beschuss.setEnabled(False)
        self.btn_wertung.setEnabled(False)
        if not self.monitor_timer.isActive(): 
            self.monitor_timer.start(250)

    def set_light(self, state):
        self.btn_licht_an.setEnabled(False)
        self.btn_licht_aus.setEnabled(False)
        # Relaiskarte schaltet das Licht bei False (LOW) EIN!
        GPIO.output(PINS_OUT["Licht"], not state)
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
        save_operating_hours(self.hours_data)
        if hasattr(self, 'settings_window') and self.settings_window is not None:
            self.settings_window.close()
        for pin in PINS_OUT.values(): 
            GPIO.output(pin, True) # Alles aus
        GPIO.cleanup()
        sys.exit(0)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape or event.key() == Qt.Key_Q: 
            self.handle_exit()

    def start_tipp_mode(self, direction):
        if self.system_fault or self.is_driving: 
            return
        self.is_driving = True
        self.monitor_timer.stop()
        self.thread = DriveThread(direction, self, self.times)
        self.thread.drive_time_signal.connect(self.add_drive_time)
        self.thread.start()

    def stop_tipp_mode(self):
        if not self.is_driving: 
            return
        self.stop_position_animation()
        try:
            if hasattr(self, 'thread') and self.thread.isRunning():
                self.thread.terminate()
                self.thread.wait()
            for pin in PINS_OUT.values():
                if pin != PINS_OUT["Licht"]: 
                    GPIO.output(pin, True)
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
            progress_percent = 100 if elapsed >= total_time else int((elapsed / total_time) * 100)
        elif self.anim_mode in ("Wertung", "HomeFahrt"):
            estimated_total = self.t_wertung_schnell + 3.0
            progress_percent = 0 if elapsed >= estimated_total else int(100 - ((elapsed / estimated_total) * 100))
            if progress_percent < 0: 
                progress_percent = 0
        elif self.anim_mode == "TippVor":
            progress_percent = min(self.track_bar.value() + 1, 100)
        elif self.anim_mode == "TippRueck":
            progress_percent = max(self.track_bar.value() - 1, 0)
            
        self.track_bar.setValue(progress_percent)
        available_width = max(self.track_bar.width() - 42, 800)
        target_x = int((progress_percent / 100.0) * available_width)
        self.moving_target.move(target_x, 5)

    def stop_position_animation(self):
        if hasattr(self, 'animation_timer') and self.animation_timer.isActive():
            self.animation_timer.stop()
        if GPIO.input(PINS_IN["Endschalter"]):
            self.track_bar.setValue(0)
            self.moving_target.move(0, 5)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SchussbahnApp()
    window.show()
    sys.exit(app.exec_())