# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import QApplication, QWidget, QDialog, QVBoxLayout, QLineEdit, QGridLayout, QPushButton, QHBoxLayout, QLabel, QFrame, QTextEdit, QMessageBox
from PyQt5.QtGui import QFont, QTextCursor
from PyQt5.QtCore import Qt, QTimer
from config_loader import load_settings, save_settings
import time

class NumpadDialog(QDialog):
    def __init__(self, parent=None, title="", initial_value="", is_password=False):
        super().__init__(parent)
        self.is_password_mode = is_password 
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        self.setModal(True)
        self.init_ui(initial_value, is_password)

    def init_ui(self, initial_value, is_password):
        layout = QVBoxLayout()
        self.display = QLineEdit(initial_value)
        self.display.setFont(QFont("Arial", 20))
        self.display.setAlignment(Qt.AlignRight)
        self.display.setReadOnly(True)

        if is_password:
            self.display.setEchoMode(QLineEdit.Password)

        layout.addWidget(self.display)

        grid = QGridLayout()
        buttons = [
            ('7', 0, 0), ('8', 0, 1), ('9', 0, 2),
            ('4', 1, 0), ('5', 1, 1), ('6', 1, 2),
            ('1', 2, 0), ('2', 2, 1), ('3', 2, 2),
            ('0', 3, 0), ('.', 3, 1), ('C', 3, 2)
        ]
        for text, row, col in buttons:
            btn = QPushButton(text)
            btn.setFont(QFont("Arial", 18))
            btn.setFixedSize(65, 65)
            btn.clicked.connect(self.num_pressed)
            grid.addWidget(btn, row, col)

        layout.addLayout(grid)
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setFont(QFont("Arial", 14))
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.setFont(QFont("Arial", 14))
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def num_pressed(self):
        btn = self.sender()
        text = btn.text()
        current = self.display.text()

        if text == 'C': 
            self.display.clear()
            return

        if self.is_password_mode and len(current) >= 4:
            if not current.startswith('9'):
                return
            elif len(current) >= 9:
                return

        if text == '.':
            if "IP" in self.windowTitle():
                if current.count('.') < 3:
                    if not current.endswith('.'):
                        self.display.setText(current + '.')
            else:
                if '.' not in current: 
                    self.display.setText(current + '.')
        else: 
            self.display.setText(current + text)

    def accept(self):
        current_len = len(self.display.text())
        if self.is_password_mode:
            if current_len < 4:
                QMessageBox.warning(self, "Fehler", "Die PIN muss exakt 4-stellig sein!")
                return
            if current_len > 4 and not self.display.text().startswith('9'):
                QMessageBox.warning(self, "Fehler", "Die PIN muss exakt 4-stellig sein!")
                return
        super().accept()

    def get_value(self):
        try: return float(self.display.text())
        except ValueError: return 0.0

    def get_raw_text(self):
        return self.display.text()


class SettingsWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__()
        self.setWindowTitle("Einstellungen & Diagnose")
        self.resize(950, 600)
        self.setStyleSheet("background-color: #2b2b2b; color: #ffffff;")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)

        self.main_app = parent
        self.settings = load_settings()
        self.change_buttons = []
        self.init_ui()

        self.io_timer = QTimer(self)
        self.io_timer.timeout.connect(self.update_live_ios)
        self.io_timer.start(250)

    def init_ui(self):
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(25)

        left_layout = QVBoxLayout()
        times_title = QLabel("Zeiteinstellungen")
        times_title.setFont(QFont("Arial", 14, QFont.Bold))
        left_layout.addWidget(times_title)

        grid_times = QGridLayout()
        grid_times.setSpacing(8)
        self.inputs = {}
        row = 0
        for key, val in self.settings.items():
            if key == "Service-PIN" or key == "Modbus-IP": # IP überspringen, da GPIO-Variante
                continue

            if key == "Wartungsintervall" or key == "Wartungsintervall-Stunden":
                lbl = QLabel(f"{key} (h):")
            else:
                lbl = QLabel(f"{key} (s):")

            lbl.setFont(QFont("Arial", 11))
            grid_times.addWidget(lbl, row, 0)

            le = QLineEdit(str(val))
            le.setFont(QFont("Arial", 11, QFont.Bold))
            le.setReadOnly(True)
            le.setStyleSheet("background-color: #111111; color: #ffffff; padding: 4px;")
            grid_times.addWidget(le, row, 1)

            btn = QPushButton("Ändern")
            btn.setFont(QFont("Arial", 10))
            btn.setMinimumHeight(30)
            btn.clicked.connect(lambda checked, k=key, e=le: self.open_numpad(k, e))
            grid_times.addWidget(btn, row, 2)

            self.change_buttons.append(btn)
            self.inputs[key] = le
            row += 1

        left_layout.addLayout(grid_times)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setStyleSheet("background-color: #555555; margin-top: 5px; margin-bottom: 5px;")
        left_layout.addWidget(sep1)

        hours_title = QLabel("Betriebsstunden & Wartung")
        hours_title.setFont(QFont("Arial", 14, QFont.Bold))
        hours_title.setStyleSheet("color: #00ffcc;")
        left_layout.addWidget(hours_title)

        grid_hours = QGridLayout()
        self.lbl_gesamt_text = QLabel("Gesamtbetriebszeit:")
        self.lbl_gesamt_text.setFont(QFont("Arial", 11))
        self.lbl_gesamt_val = QLabel("0.0 h")
        self.lbl_gesamt_val.setFont(QFont("Arial", 11, QFont.Bold))
        self.lbl_gesamt_val.setStyleSheet("color: #ffffff; background-color: #111111; padding: 4px; border-radius: 3px;")

        self.lbl_fahrt_text = QLabel("Reine Fahrzeit:")
        self.lbl_fahrt_text.setFont(QFont("Arial", 11))
        self.lbl_fahrt_val = QLabel("0.0 h")
        self.lbl_fahrt_val.setFont(QFont("Arial", 11, QFont.Bold))
        self.lbl_fahrt_val.setStyleSheet("color: #ffaa00; background-color: #111111; padding: 4px; border-radius: 3px;")

        grid_hours.addWidget(self.lbl_gesamt_text, 0, 0)
        grid_hours.addWidget(self.lbl_gesamt_val, 0, 1)
        grid_hours.addWidget(self.lbl_fahrt_text, 1, 0)
        grid_hours.addWidget(self.lbl_fahrt_val, 1, 1)
        left_layout.addLayout(grid_hours)

        self.btn_reset_fahrt = QPushButton("Fahrzeit nach Wartung zurücksetzen")
        self.btn_reset_fahrt.setFont(QFont("Arial", 10, QFont.Bold))
        self.btn_reset_fahrt.setStyleSheet("background-color: #444444; color: white; border-radius: 3px; padding: 4px; margin-top: 3px;")
        self.btn_reset_fahrt.clicked.connect(self.protected_fahrzeit_reset)
        left_layout.addWidget(self.btn_reset_fahrt)

        self.btn_change_pin = QPushButton("Service-PIN ändern")
        self.btn_change_pin.setFont(QFont("Arial", 10, QFont.Bold))
        self.btn_change_pin.setStyleSheet("background-color: #334433; color: #aaffaa; border: 1px solid #557755; border-radius: 3px; padding: 4px; margin-top: 3px;")
        self.btn_change_pin.clicked.connect(self.open_pin_change_dialog)
        left_layout.addWidget(self.btn_change_pin) 

        left_layout.addStretch()

        self.save_status_lbl = QLabel("")
        self.save_status_lbl.setFont(QFont("Arial", 11, QFont.Bold))
        self.save_status_lbl.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(self.save_status_lbl)

        self.save_btn = QPushButton("Zeiten Speichern")
        self.save_btn.setFont(QFont("Arial", 12, QFont.Bold))
        self.save_btn.setMinimumHeight(40)
        self.save_btn.setStyleSheet("background-color: #0055ff; color: white; border-radius: 5px;")
        self.save_btn.clicked.connect(self.save_clicked)
        left_layout.addWidget(self.save_btn)
        main_layout.addLayout(left_layout, stretch=45)

        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setStyleSheet("background-color: #555555;")
        main_layout.addWidget(line)

        right_layout = QVBoxLayout()
        io_title = QLabel("Physische I/O Zustände (Live)")
        io_title.setFont(QFont("Arial", 14, QFont.Bold))
        right_layout.addWidget(io_title)

        grid_ios = QGridLayout()
        grid_ios.setSpacing(6)

        self.input_labels_def = [
            "In1: Motorschutzschalter", "In2: Endschalter (Startposition)",
            "In3: Rückmeldung Schütz Rechts", "In4: Rückmeldung Schütz Links",
            "In5: Rückmeldung Schütz Langsam", "In6: Rückmeldung Schütz Schnell"
        ]
        self.output_labels_def = {
            0: "Ch1: Ausgang Rechtslauf", 1: "Ch2: Ausgang Linkslauf",
            2: "Ch3: Ausgang Langsam", 3: "Ch4: Ausgang Schnell", 7: "Ch8: Ausgang Licht"
        }

        self.input_leds, self.output_leds = {}, {}
        io_row = 0
        lbl_in_header = QLabel("EINGÄNGE:")
        lbl_in_header.setStyleSheet("color: #00ffcc; font-weight: bold;")
        grid_ios.addWidget(lbl_in_header, io_row, 0, 1, 2)
        io_row += 1

        for i in range(6):
            led = QLabel(); led.setFixedSize(18, 18); self.set_led_state(led, False)
            lbl_name = QLabel(self.input_labels_def[i])
            grid_ios.addWidget(led, io_row, 0)
            grid_ios.addWidget(lbl_name, io_row, 1)
            self.input_leds[i] = led
            io_row += 1

        grid_ios.setRowMinimumHeight(io_row, 10)
        io_row += 1
        lbl_out_header = QLabel("AUSGÄNGE:")
        lbl_out_header.setStyleSheet("color: #ffaa00; font-weight: bold;")
        grid_ios.addWidget(lbl_out_header, io_row, 0, 1, 2)
        io_row += 1

        for idx, name in self.output_labels_def.items():
            led = QLabel()
            led.setFixedSize(18, 18)
            self.set_led_state(led, False)
            lbl_name = QLabel(name)
            grid_ios.addWidget(led, io_row, 0)
            grid_ios.addWidget(lbl_name, io_row, 1)
            self.output_leds[idx] = led
            io_row += 1

        right_layout.addLayout(grid_ios)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("background-color: #555555; margin-top: 5px; margin-bottom: 5px;")
        right_layout.addWidget(sep2)

        tipp_title = QLabel("Manueller Einrichtbetrieb (Tippen & Halten)")
        tipp_title.setFont(QFont("Arial", 12, QFont.Bold))
        right_layout.addWidget(tipp_title)

        tipp_btn_layout = QHBoxLayout()
        self.btn_tipp_rueck = QPushButton("◀ RÜCKWÄRTS (Langsam)")
        self.btn_tipp_vor = QPushButton("VORWÄRTS (Langsam) ▶")
        self.btn_tipp_rueck.setMinimumHeight(40)
        self.btn_tipp_vor.setMinimumHeight(40)
        self.btn_tipp_rueck.setStyleSheet("background-color: #333333; color: white; border: 1px solid #777777;")
        self.btn_tipp_vor.setStyleSheet("background-color: #333333; color: white; border: 1px solid #777777;")

        self.btn_tipp_vor.pressed.connect(lambda: self.main_app.start_tipp_mode("TippVor"))
        self.btn_tipp_vor.released.connect(self.main_app.stop_tipp_mode)
        self.btn_tipp_rueck.pressed.connect(lambda: self.main_app.start_tipp_mode("TippRueck"))
        self.btn_tipp_rueck.released.connect(self.main_app.stop_tipp_mode)

        tipp_btn_layout.addWidget(self.btn_tipp_rueck)
        tipp_btn_layout.addWidget(self.btn_tipp_vor)
        right_layout.addLayout(tipp_btn_layout)

        log_title = QLabel("Fehler-Logbuch (Letzte 5 Vorfälle)")
        log_title.setFont(QFont("Arial", 12, QFont.Bold))
        log_title.setStyleSheet("color: #ff5555; margin-top: 5px;")
        right_layout.addWidget(log_title)

        self.error_log_view = QTextEdit()
        self.error_log_view.setReadOnly(True)
        self.error_log_view.setFixedHeight(100)
        self.error_log_view.setStyleSheet("background-color: #1a1a1a; color: #ff8888; font-family: monospace; font-size: 11px;")
        right_layout.addWidget(self.error_log_view)

        self.btn_clear_log = QPushButton("Logbuch unwiderruflich löschen")
        self.btn_clear_log.setFont(QFont("Arial", 10, QFont.Bold))
        self.btn_clear_log.setStyleSheet("background-color: #552222; color: #ffaaaa; border: 1px solid #aa5555; padding: 3px; margin-top: 2px;")
        self.btn_clear_log.clicked.connect(self.protected_log_clear)
        right_layout.addWidget(self.btn_clear_log)

        right_layout.addStretch()

        self.btn_system_reset = QPushButton("Generellen System-Reset ausführen")
        self.btn_system_reset.setFont(QFont("Arial", 11, QFont.Bold))
        self.btn_system_reset.setMinimumHeight(35)
        self.btn_system_reset.setStyleSheet("background-color: #ffaa00; color: #111111; font-weight: bold; border-radius: 5px;")
        self.btn_system_reset.clicked.connect(self.trigger_system_reset)
        right_layout.addWidget(self.btn_system_reset)

        close_btn = QPushButton("Schließen")
        close_btn.setMinimumHeight(30)
        close_btn.clicked.connect(self.close)
        right_layout.addWidget(close_btn)
        main_layout.addLayout(right_layout, stretch=55)

        self.setLayout(main_layout)

    def set_led_state(self, led_widget, active):
        if active: 
            led_widget.setStyleSheet("border-radius: 9px; border: 1px solid #111111; background-color: qradialgradient(cx:0.3, cy:0.3, radius:1.0, fx:0.3, fy:0.3, stop:0 #80ff80, stop:1 #009900);")
        else: 
            led_widget.setStyleSheet("border-radius: 9px; border: 1px solid #222222; background-color: qradialgradient(cx:0.3, cy:0.3, radius:1.0, fx:0.3, fy:0.3, stop:0 #555555, stop:1 #222222);")

    def update_live_ios(self):
        if self.main_app.is_driving:
            self.save_btn.setEnabled(False)
            self.btn_reset_fahrt.setEnabled(False)
            self.btn_clear_log.setEnabled(False)
            self.btn_change_pin.setEnabled(False)
            for btn in self.change_buttons: 
                btn.setEnabled(False)
        else:
            self.save_btn.setEnabled(True)
            self.btn_reset_fahrt.setEnabled(True)
            self.btn_clear_log.setEnabled(True)
            self.btn_change_pin.setEnabled(True)
            for btn in self.change_buttons: 
                btn.setEnabled(True)

        inputs = self.main_app.latest_inputs
        coils = self.main_app.latest_coils
        
        if inputs and len(inputs) >= 6:
            for i in range(6): 
                self.set_led_state(self.input_leds[i], inputs[i])
                
        if coils and len(coils) >= 4:
            self.set_led_state(self.output_leds[0], coils[0]) # Rechtslauf
            self.set_led_state(self.output_leds[1], coils[1]) # Linkslauf
            self.set_led_state(self.output_leds[2], coils[2]) # Langsam
            self.set_led_state(self.output_leds[3], coils[3]) # Schnell

        if hasattr(self.main_app, 'hours_data'):
            gesamt_stunden = self.main_app.hours_data["gesamt_sekunden"] / 3600.0
            fahr_stunden = self.main_app.hours_data["fahrzeit_sekunden"] / 3600.0
            self.lbl_gesamt_val.setText(f"{gesamt_stunden:.2f} h")
            
            max_wartung_stunden = self.settings.get("Wartungsintervall", 50.0)
            if fahr_stunden >= max_wartung_stunden:
                self.lbl_fahrt_val.setText(f"{fahr_stunden:.2f} h - WARTUNG FÄLLIG!")
                self.lbl_fahrt_val.setStyleSheet("color: #ff0000; background-color: #111111; padding: 4px; border: 1px solid red; border-radius: 3px; font-weight: bold;")
            else:
                self.lbl_fahrt_val.setText(f"{fahr_stunden:.2f} h")
                self.lbl_fahrt_val.setStyleSheet("color: #ffaa00; background-color: #111111; padding: 4px; border-radius: 3px;")

        if hasattr(self.main_app, 'gui_error_list'):
            self.error_log_view.setPlainText("\n".join(self.main_app.gui_error_list))

    def open_numpad(self, key, line_edit_widget):
        dialog = NumpadDialog(self, title=f"{key} ändern", initial_value=line_edit_widget.text(), is_password=False)
        if dialog.exec_() == QDialog.Accepted:
            new_val = dialog.get_value()
            line_edit_widget.setText(f"{new_val:.1f}")
            self.settings[key] = new_val

    def save_clicked(self):
        try:
            save_settings(self.settings)
            self.main_app.times = self.settings.copy()
            self.save_status_lbl.setText("Erfolgreich gespeichert!")
            self.save_status_lbl.setStyleSheet("color: #00ff00;")
            QTimer.singleShot(3000, lambda: self.save_status_lbl.setText(""))
        except:
            self.save_status_lbl.setText("Fehler beim Speichern!")
            self.save_status_lbl.setStyleSheet("color: #ff0000;")

    PUK_NOTFALL_NUMMER = 987654321

    def protected_fahrzeit_reset(self):
        dialog = NumpadDialog(self, title="Service-PIN eingeben", initial_value="", is_password=True)
        if dialog.exec_() == QDialog.Accepted:
            try:
                eingabe = int(dialog.get_value())
                aktuelle_pin = int(self.settings.get("Service-PIN", 1234))
                if eingabe == aktuelle_pin or eingabe == self.PUK_NOTFALL_NUMMER:
                    self.main_app.hours_data["fahrzeit_sekunden"] = 0.0
                    from config_loader import save_operating_hours
                    save_operating_hours(self.main_app.hours_data)
                    self.save_status_lbl.setText("Fahrzeit auf Null gesetzt!")
                    self.save_status_lbl.setStyleSheet("color: #00ff00;")
                    QTimer.singleShot(3000, lambda: self.save_status_lbl.setText(""))
                else:
                    self.save_status_lbl.setText("FALSCHE PIN!")
                    self.save_status_lbl.setStyleSheet("color: #ff0000;")
                    QTimer.singleShot(3000, lambda: self.save_status_lbl.setText(""))
            except: 
                pass

    def protected_log_clear(self):
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setWindowTitle("Achtung: Logbuch leeren")
        msg_box.setText("Möchten Sie das Fehler-Logbuch leeren?")
        yes_btn = msg_box.addButton("Ja, löschen", QMessageBox.YesRole)
        no_btn = msg_box.addButton("Abbrechen", QMessageBox.NoRole)
        msg_box.exec_()
        if msg_box.clickedButton() == no_btn: 
            return

        dialog = NumpadDialog(self, title="Service-PIN eingeben", initial_value="", is_password=True)
        if dialog.exec_() == QDialog.Accepted:
            try:
                eingabe = int(dialog.get_value())
                aktuelle_pin = int(self.settings.get("Service-PIN", 1234))
                if eingabe == aktuelle_pin or eingabe == self.PUK_NOTFALL_NUMMER:
                    self.main_app.clear_gui_error_log()
                    self.save_status_lbl.setText("Erfolgreich gelöscht!")
                    self.save_status_lbl.setStyleSheet("color: #00ff00;")
                else:
                    self.save_status_lbl.setText("FALSCHE PIN!")
                    self.save_status_lbl.setStyleSheet("color: #ff0000;")
                # (Fortsetzung der übergeordneten Logik)
                QTimer.singleShot(3000, lambda: self.save_status_lbl.setText(""))
            except: 
                pass

    def open_pin_change_dialog(self):
        dialog = NumpadDialog(self, title="Alte PIN eingeben", initial_value="", is_password=True)
        if dialog.exec_() == QDialog.Accepted:
            try:
                eingabe = int(dialog.get_value())
                aktuelle_pin = int(self.settings.get("Service-PIN", 1234))
                
                if eingabe == aktuelle_pin or eingabe == self.PUK_NOTFALL_NUMMER:
                    new_pin_dialog = NumpadDialog(self, title="Neue 4 Ziffern eingeben", initial_value="", is_password=True)
                    if new_pin_dialog.exec_() == QDialog.Accepted:
                        # KORREKTUR: Zuweisung an Dictionary-Key statt Funktionsaufruf-Syntax
                        self.settings["Service-PIN"] = int(new_pin_dialog.get_value())
                        save_settings(self.settings)
                        self.save_status_lbl.setText("PIN geändert!")
                        self.save_status_lbl.setStyleSheet("color: #00ff00;")
                else:
                    self.save_status_lbl.setText("Fehlgeschlagen!")
                    self.save_status_lbl.setStyleSheet("color: #ff0000;")
                    
                QTimer.singleShot(3000, lambda: self.save_status_lbl.setText(""))
            except: 
                pass

    def trigger_system_reset(self):
        self.btn_system_reset.setEnabled(False)
        self.btn_system_reset.setText("Reset läuft...")
        QApplication.processEvents()
        if self.main_app.general_system_reset():
            self.btn_system_reset.setText("Reset erfolgreich!")
            self.btn_system_reset.setStyleSheet("background-color: #00ff00; color: #111111;")
        QTimer.singleShot(3000, self.reset_system_button_style)

    def reset_system_button_style(self):
        self.btn_system_reset.setEnabled(True)
        self.btn_system_reset.setText("Generellen System-Reset ausführen")
        self.btn_system_reset.setStyleSheet("background-color: #ffaa00; color: #111111; font-weight: bold; border-radius: 5px;")

    def closeEvent(self, event):
        self.io_timer.stop()
        event.accept()
