<<<<<<< HEAD
# -*- coding: utf-8 -*-
import logging
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLineEdit, QGridLayout, QPushButton, QHBoxLayout, QLabel, QFrame, QTextEdit, QMessageBox, QWidget, QApplication
from PyQt5.QtGui import QFont, QTextCursor
from PyQt5.QtCore import Qt, QTimer
from config_loader import load_settings, save_settings

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
        layout.setContentsMargins(10, 10, 10, 10)
        
        self.display = QLineEdit(initial_value)
        self.display.setFont(QFont("Arial", 16))
        self.display.setAlignment(Qt.AlignRight)
        self.display.setReadOnly(True)

        if is_password:
            self.display.setEchoMode(QLineEdit.Password)

        layout.addWidget(self.display)
        grid = QGridLayout()
        grid.setSpacing(5)
        buttons = [
            ('7', 0, 0), ('8', 0, 1), ('9', 0, 2),
            ('4', 1, 0), ('5', 1, 1), ('6', 1, 2),
            ('1', 2, 0), ('2', 2, 1), ('3', 2, 2),
            ('0', 3, 0), ('.', 3, 1), ('C', 3, 2)
        ]
        for text, row, col in buttons:
            btn = QPushButton(text)
            btn.setFont(QFont("Arial", 14, QFont.Bold))
            btn.setFixedSize(55, 55) 
            btn.clicked.connect(self.num_pressed)
            grid.addWidget(btn, row, col)

        layout.addLayout(grid)
        
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setFont(QFont("Arial", 12))
        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.setFont(QFont("Arial", 12))
        ok_btn.clicked.connect(self.accept)
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
            if not current.startswith('9'): return
            elif len(current) >= 9: return

        if text == '.':
            if "IP" in self.windowTitle():
                if current.count('.') < 3 and not current.endswith('.'):
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
        self.setFixedSize(920, 520) 
        self.setStyleSheet("background-color: #2b2b2b; color: #ffffff;")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)

        self.main_app = parent
        self.client = parent.client
        self.settings = load_settings()
        self.change_buttons = []
        self.init_ui()

        self.io_timer = QTimer(self)
        self.io_timer.timeout.connect(self.update_live_ios)
        self.io_timer.start(250)

    def init_ui(self):
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(15)

        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(5, 5, 5, 5)
        left_layout.setSpacing(2) 

        times_title = QLabel("Zeiteinstellungen")
        times_title.setFont(QFont("Arial", 11, QFont.Bold))
        times_title.setFixedHeight(20)
        left_layout.addWidget(times_title)

        grid_times = QGridLayout()
        grid_times.setSpacing(2) 
        grid_times.setContentsMargins(0, 0, 0, 0)
        
        self.inputs = {}
        row = 0
        for key, val in self.settings.items():
            if key == "Service-PIN": continue

            if key == "Modbus-IP":
                lbl = QLabel(f"{key}:")
            elif key in ["Wartungsintervall", "Wartungsintervall-Stunden"]:
                lbl = QLabel(f"{key} (h):")
            else:
                lbl = QLabel(f"{key} (s):")

            lbl.setFont(QFont("Arial", 9)) 
            lbl.setFixedHeight(24)
            lbl.setStyleSheet("margin: 0px; padding: 0px;")
            grid_times.addWidget(lbl, row, 0)
            le = QLineEdit(str(val))
            le.setFont(QFont("Arial", 9, QFont.Bold)) 
            le.setReadOnly(True)
            le.setFixedWidth(125) 
            le.setFixedHeight(24) 
            le.setStyleSheet("""
                background-color: #111111; color: #ffffff; padding: 0px 5px; margin: 0px;
                border: 1px solid #444444; border-radius: 3px;
            """)
            grid_times.addWidget(le, row, 1)

            btn = QPushButton("Ändern")
            btn.setFont(QFont("Arial", 8, QFont.Bold))
            btn.setFixedSize(60, 24) 
            btn.setStyleSheet("""
                QPushButton { background-color: #444444; color: white; margin: 0px; padding: 0px; border: 1px solid #555555; border-radius: 3px; }
                QPushButton:pressed { background-color: #666666; }
            """)
            btn.clicked.connect(lambda checked, k=key, e=le: self.open_numpad(k, e))
            grid_times.addWidget(btn, row, 2)

            self.change_buttons.append(btn)
            self.inputs[key] = le
            row += 1

        left_layout.addLayout(grid_times)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setFixedHeight(2)
        sep1.setStyleSheet("background-color: #444444; margin: 2px 0px;")
        left_layout.addWidget(sep1)

        hours_title = QLabel("Betriebsstunden & Wartung")
        hours_title.setFont(QFont("Arial", 11, QFont.Bold))
        hours_title.setStyleSheet("color: #00ffcc;")
        hours_title.setFixedHeight(20)
        left_layout.addWidget(hours_title)

        grid_hours = QGridLayout()
        grid_hours.setSpacing(2)
        grid_hours.setContentsMargins(0, 0, 0, 0)
        
        self.lbl_gesamt_text = QLabel("Gesamtbetriebszeit:")
        self.lbl_gesamt_text.setFont(QFont("Arial", 9))
        self.lbl_gesamt_text.setFixedHeight(24)
        
        self.lbl_gesamt_val = QLabel("0.0 h")
        self.lbl_gesamt_val.setFont(QFont("Arial", 9, QFont.Bold))
        self.lbl_gesamt_val.setFixedSize(70, 24)
        self.lbl_gesamt_val.setStyleSheet("color: #ffffff; background-color: #111111; padding: 2px 4px; border-radius: 2px;")

        self.lbl_fahrt_text = QLabel("Reine Fahrzeit:")
        self.lbl_fahrt_text.setFont(QFont("Arial", 9))
        self.lbl_fahrt_text.setFixedHeight(24)
        
        self.lbl_fahrt_val = QLabel("0.0 h")
        self.lbl_fahrt_val.setFont(QFont("Arial", 9, QFont.Bold))
        self.lbl_fahrt_val.setFixedSize(70, 24)
        self.lbl_fahrt_val.setStyleSheet("color: #ffaa00; background-color: #111111; padding: 2px 4px; border-radius: 2px;")

        grid_hours.addWidget(self.lbl_gesamt_text, 0, 0)
        grid_hours.addWidget(self.lbl_gesamt_val, 0, 1)
        grid_hours.addWidget(self.lbl_fahrt_text, 1, 0)
        grid_hours.addWidget(self.lbl_fahrt_val, 1, 1)
        left_layout.addLayout(grid_hours)

        self.btn_reset_fahrt = QPushButton("Fahrzeit nach Wartung zurücksetzen")
        self.btn_reset_fahrt.setFont(QFont("Arial", 9, QFont.Bold))
        self.btn_reset_fahrt.setFixedHeight(24) 
        self.btn_reset_fahrt.setStyleSheet("background-color: #444444; color: white; border-radius: 3px; border: 1px solid #555555;")
        self.btn_reset_fahrt.clicked.connect(self.protected_fahrzeit_reset)
        left_layout.addWidget(self.btn_reset_fahrt)

        self.btn_change_pin = QPushButton("Service-PIN ändern")
        self.btn_change_pin.setFont(QFont("Arial", 9, QFont.Bold))
        self.btn_change_pin.setFixedHeight(24) 
        self.btn_change_pin.setStyleSheet("background-color: #334433; color: #aaffaa; border: 1px solid #557755; border-radius: 3px;")
        self.btn_change_pin.clicked.connect(self.open_pin_change_dialog)
        left_layout.addWidget(self.btn_change_pin) 

        self.btn_change_ip = QPushButton("Modbus IP-Adresse ändern")
        self.btn_change_ip.setFont(QFont("Arial", 9, QFont.Bold))
        self.btn_change_ip.setFixedHeight(24) 
        self.btn_change_ip.setStyleSheet("background-color: #333344; color: #ffaaff; border: 1px solid #555577; border-radius: 3px;")
        self.btn_change_ip.clicked.connect(self.open_ip_change_dialog)
        left_layout.addWidget(self.btn_change_ip)

        left_layout.addStretch(1)

        self.save_status_lbl = QLabel("")
        self.save_status_lbl.setFont(QFont("Arial", 9, QFont.Bold))
        self.save_status_lbl.setAlignment(Qt.AlignCenter)
        self.save_status_lbl.setFixedHeight(18)
        left_layout.addWidget(self.save_status_lbl)

        self.save_btn = QPushButton("Zeiten Speichern")
        self.save_btn.setFont(QFont("Arial", 10, QFont.Bold))
        self.save_btn.setFixedHeight(30) 
        self.save_btn.setStyleSheet("background-color: #0055ff; color: white; border-radius: 4px;")
        self.save_btn.clicked.connect(self.save_clicked)
        left_layout.addWidget(self.save_btn)
        
        main_layout.addLayout(left_layout, stretch=45)

        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setStyleSheet("background-color: #555555;")
        main_layout.addWidget(line)

        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(5, 5, 5, 5)
        right_layout.setSpacing(2) 

        io_title = QLabel("Physische I/O Zustände (Live)")
        io_title.setFont(QFont("Arial", 11, QFont.Bold))
        io_title.setFixedHeight(20)
        right_layout.addWidget(io_title)

        grid_ios = QGridLayout()
        grid_ios.setSpacing(2) 
        grid_ios.setContentsMargins(0, 0, 0, 0)

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
        lbl_in_header.setFont(QFont("Arial", 9, QFont.Bold))
        lbl_in_header.setStyleSheet("color: #00ffcc; margin-top: 2px;")
        lbl_in_header.setFixedHeight(18)
        grid_ios.addWidget(lbl_in_header, io_row, 0, 1, 2)
        io_row += 1

        for i in range(6):
            led = QLabel()
            led.setFixedSize(14, 14)
            self.set_led_state(led, False)
            
            lbl_name = QLabel(self.input_labels_def[i])
            lbl_name.setFont(QFont("Arial", 9))
            lbl_name.setFixedHeight(24) 
            lbl_name.setStyleSheet("margin: 0px; padding: 0px;")
            
            grid_ios.addWidget(led, io_row, 0, Qt.AlignVCenter)
            grid_ios.addWidget(lbl_name, io_row, 1, Qt.AlignVCenter)
            self.input_leds[i] = led
            io_row += 1

        lbl_out_header = QLabel("AUSGÄNGE:")
        lbl_out_header.setFont(QFont("Arial", 9, QFont.Bold))
        lbl_out_header.setStyleSheet("color: #ffaa00; margin-top: 4px;")
        lbl_out_header.setFixedHeight(18)
        grid_ios.addWidget(lbl_out_header, io_row, 0, 1, 2)
        io_row += 1

        for idx, name in self.output_labels_def.items():
            led = QLabel()
            led.setFixedSize(14, 14)
            self.set_led_state(led, False)
            
            lbl_name = QLabel(name)
            lbl_name.setFont(QFont("Arial", 9))
            lbl_name.setFixedHeight(24) 
            lbl_name.setStyleSheet("margin: 0px; padding: 0px;")
            
            grid_ios.addWidget(led, io_row, 0, Qt.AlignVCenter)
            grid_ios.addWidget(lbl_name, io_row, 1, Qt.AlignVCenter)
            self.output_leds[idx] = led
            io_row += 1

        right_layout.addLayout(grid_ios)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setFixedHeight(2)
        sep2.setStyleSheet("background-color: #444444; margin: 2px 0px;")
        right_layout.addWidget(sep2)

        tipp_title = QLabel("Manueller Einrichtbetrieb")
        tipp_title.setFont(QFont("Arial", 11, QFont.Bold))
        tipp_title.setFixedHeight(20)
        right_layout.addWidget(tipp_title)

        tipp_btn_layout = QHBoxLayout()
        self.btn_tipp_rueck = QPushButton("◀ RÜCKWÄRTS")
        self.btn_tipp_vor = QPushButton("VORWÄRTS ▶")
        self.btn_tipp_rueck.setFixedHeight(28)
        self.btn_tipp_vor.setFixedHeight(28)
        self.btn_tipp_rueck.setFont(QFont("Arial", 9, QFont.Bold))
        self.btn_tipp_vor.setFont(QFont("Arial", 9, QFont.Bold))
        self.btn_tipp_rueck.setStyleSheet("background-color: #444444; color: white; border: 1px solid #555555; border-radius: 3px;")
        self.btn_tipp_vor.setStyleSheet("background-color: #444444; color: white; border: 1px solid #555555; border-radius: 3px;")

        self.btn_tipp_vor.pressed.connect(lambda: self.main_app.start_tipp_mode("TippVor"))
        self.btn_tipp_vor.released.connect(self.main_app.stop_tipp_mode)
        self.btn_tipp_rueck.pressed.connect(lambda: self.main_app.start_tipp_mode("TippRueck"))
        self.btn_tipp_rueck.released.connect(self.main_app.stop_tipp_mode)

        tipp_btn_layout.addWidget(self.btn_tipp_rueck)
        tipp_btn_layout.addWidget(self.btn_tipp_vor)
        right_layout.addLayout(tipp_btn_layout)

        self.error_log_view = QTextEdit()
        self.error_log_view.setReadOnly(True)
        self.error_log_view.setFixedHeight(55) 
        self.error_log_view.setStyleSheet("background-color: #1a1a1a; color: #ff8888; font-family: monospace; font-size: 10px; border: 1px solid #444444; border-radius: 3px;")
        right_layout.addWidget(self.error_log_view)

        self.btn_clear_log = QPushButton("Logbuch leeren")
        self.btn_clear_log.setFont(QFont("Arial", 9, QFont.Bold))
        self.btn_clear_log.setFixedHeight(24)
        self.btn_clear_log.setStyleSheet("""
            QPushButton { background-color: #4a1515; color: #ff0000; padding: 0px; border: 1px solid #7a2525; border-radius: 3px; }
            QPushButton:pressed { background-color: #6a1f1f; color: #ff3333; }
            QPushButton:disabled { background-color: #221111; color: #441111; border: 1px solid #331111; }
        """)
        self.btn_clear_log.clicked.connect(self.protected_log_clear)
        right_layout.addWidget(self.btn_clear_log)

        right_layout.addStretch(1)

        self.btn_system_reset = QPushButton("Generellen System-Reset ausführen")
        self.btn_system_reset.setFont(QFont("Arial", 10, QFont.Bold))
        self.btn_system_reset.setFixedHeight(30)
        self.btn_system_reset.setStyleSheet("background-color: #ffaa00; color: #111111; border-radius: 4px;")
        self.btn_system_reset.clicked.connect(self.trigger_system_reset)
        right_layout.addWidget(self.btn_system_reset)

        close_btn = QPushButton("Schließen")
        close_btn.setFont(QFont("Arial", 9, QFont.Bold))
        close_btn.setFixedHeight(24)
        close_btn.setStyleSheet("""
            QPushButton { background-color: #444444; color: white; margin: 0px; padding: 0px; border: 1px solid #555555; border-radius: 3px; }
            QPushButton:pressed { background-color: #666666; }
        """)
        close_btn.clicked.connect(self.close)
        right_layout.addWidget(close_btn)
        
        main_layout.addLayout(right_layout, stretch=55)
        self.setLayout(main_layout)

    def set_led_state(self, led_widget, active):
        if active: led_widget.setStyleSheet("border-radius: 7px; border: 1px solid #111111; background-color: qradialgradient(cx:0.3, cy:0.3, radius:1.0, fx:0.3, fy:0.3, stop:0 #80ff80, stop:1 #009900);")
        else: led_widget.setStyleSheet("border-radius: 7px; border: 1px solid #222222; background-color: qradialgradient(cx:0.3, cy:0.3, radius:1.0, fx:0.3, fy:0.3, stop:0 #555555, stop:1 #222222);")

    def update_live_ios(self):
        if self.main_app.is_driving:
            self.save_btn.setEnabled(False)
            self.btn_reset_fahrt.setEnabled(False)
            self.btn_clear_log.setEnabled(False)
            self.btn_change_pin.setEnabled(False)
            self.btn_change_ip.setEnabled(False)
            for btn in self.change_buttons: btn.setEnabled(False)
        else:
            self.save_btn.setEnabled(True)
            self.btn_reset_fahrt.setEnabled(True)
            self.btn_clear_log.setEnabled(True)
            self.btn_change_pin.setEnabled(True)
            self.btn_change_ip.setEnabled(True)
            for btn in self.change_buttons: btn.setEnabled(True)

        inputs = self.main_app.latest_inputs
        coils = self.main_app.latest_coils
        if inputs and len(inputs) >= 6:
            for i in range(6): self.set_led_state(self.input_leds[i], inputs[i])
        if coils and len(coils) >= 8:
            for idx in self.output_labels_def.keys(): self.set_led_state(self.output_leds[idx], coils[idx])

        if hasattr(self.main_app, 'hours_data'):
            gesamt_stunden = self.main_app.hours_data["gesamt_sekunden"] / 3600.0
            fahr_stunden = self.main_app.hours_data["fahrzeit_sekunden"] / 3600.0
            self.lbl_gesamt_val.setText(f"{gesamt_stunden:.2f} h")

            max_wartung_stunden = self.settings.get("Wartungsintervall", self.settings.get("Wartungsintervall-Stunden", 50.0))
            if fahr_stunden >= max_wartung_stunden:
                self.lbl_fahrt_val.setText(f"{fahr_stunden:.2f} h - WARTUNG!")
                self.lbl_fahrt_val.setStyleSheet("color: #ff0000; background-color: #111111; padding: 2px; border: 1px solid red; border-radius: 2px; font-weight: bold;")
            else:
                self.lbl_fahrt_val.setText(f"{fahr_stunden:.2f} h")
                self.lbl_fahrt_val.setStyleSheet("color: #ffaa00; background-color: #111111; padding: 2px; border-radius: 2px;")

        if hasattr(self.main_app, 'gui_error_list'):
            self.error_log_view.setPlainText("\n".join(self.main_app.gui_error_list))
            self.error_log_view.moveCursor(QTextCursor.Start)

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
        except Exception as e:
            self.save_status_lbl.setText("Fehler beim Speichern!")
            self.save_status_lbl.setStyleSheet("color: #ff0000;")

######################################
######################################
    PUK_NOTFALL_NUMMER = 987654321
######################################
######################################

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
                    self.save_status_lbl.setText("Fahrzeit zurückgesetzt!")
                    self.save_status_lbl.setStyleSheet("color: #00ff00;")
                    QTimer.singleShot(3000, lambda: self.save_status_lbl.setText(""))
                else:
                    self.save_status_lbl.setText("FALSCHE PIN!")
                    self.save_status_lbl.setStyleSheet("color: #ff0000;")
                    QTimer.singleShot(3000, lambda: self.save_status_lbl.setText(""))
            except ValueError: pass

    def protected_log_clear(self):
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setWindowTitle("Logbuch leeren")
        msg_box.setText("Möchten Sie das Fehler-Logbuch leeren?")
        yes_btn = msg_box.addButton("Ja, löschen", QMessageBox.YesRole)
        no_btn = msg_box.addButton("Abbrechen", QMessageBox.NoRole)
        msg_box.setDefaultButton(no_btn)
        msg_box.setStyleSheet("background-color: #2b2b2b; color: white;")
        msg_box.exec_()

        if msg_box.clickedButton() == no_btn: return

        dialog = NumpadDialog(self, title="Service-PIN eingeben", initial_value="", is_password=True)
        if dialog.exec_() == QDialog.Accepted:
            try:
                eingabe = int(dialog.get_value())
                aktuelle_pin = int(self.settings.get("Service-PIN", 1234))

                if eingabe == aktuelle_pin or eingabe == self.PUK_NOTFALL_NUMMER:
                    self.main_app.clear_gui_error_log()
                    self.save_status_lbl.setText("Logbuch gelöscht!")
                    self.save_status_lbl.setStyleSheet("color: #00ff00;")
                    QTimer.singleShot(3000, lambda: self.save_status_lbl.setText(""))
                else:
                    self.save_status_lbl.setText("FALSCHE PIN! Abbruch.")
                    self.save_status_lbl.setStyleSheet("color: #ff0000;")
                    QTimer.singleShot(3000, lambda: self.save_status_lbl.setText(""))
            except ValueError: pass

    def open_pin_change_dialog(self):
        dialog = NumpadDialog(self, title="Alte PIN oder PUK eingeben", initial_value="", is_password=True)
        if dialog.exec_() == QDialog.Accepted:
            try:
                eingabe = int(dialog.get_value())
                aktuelle_pin = int(self.settings.get("Service-PIN", 1234))

                if eingabe == aktuelle_pin or eingabe == self.PUK_NOTFALL_NUMMER:
                    new_pin_dialog = NumpadDialog(self, title="EXAKT 4 Ziffern eingeben", initial_value="", is_password=True)
                    if new_pin_dialog.exec_() == QDialog.Accepted:
                        neue_pin = int(new_pin_dialog.get_value())
                        self.settings["Service-PIN"] = neue_pin
                        save_settings(self.settings)
                        self.save_status_lbl.setText("PIN geändert!")
                        self.save_status_lbl.setStyleSheet("color: #00ff00;")
                        QTimer.singleShot(3000, lambda: self.save_status_lbl.setText(""))
                else:
                    self.save_status_lbl.setText("Fehlgeschlagen!")
                    self.save_status_lbl.setStyleSheet("color: #ff0000;")
                    QTimer.singleShot(3000, lambda: self.save_status_lbl.setText(""))
            except ValueError: pass

    def trigger_system_reset(self):
        self.btn_system_reset.setEnabled(False)
        self.btn_system_reset.setText("Führe System-Reset aus...")
        QApplication.processEvents() 
        if self.main_app.general_system_reset():
            self.btn_system_reset.setText("System zurückgesetzt!")
            self.btn_system_reset.setStyleSheet("background-color: #00ff00; color: #111111;")
        else:
            self.btn_system_reset.setText("Reset FEHLGESCHLAGEN!")
            self.btn_system_reset.setStyleSheet("background-color: #ff0000; color: #ffffff;")
        QTimer.singleShot(3000, self.trigger_system_reset_style_reset)

    def trigger_system_reset_style_reset(self):
        self.btn_system_reset.setEnabled(True)
        self.btn_system_reset.setText("Generellen System-Reset ausführen")
        self.btn_system_reset.setStyleSheet("background-color: #ffaa00; color: #111111; font-weight: bold; border-radius: 4px;")

    def open_ip_change_dialog(self):
        aktuelle_ip = self.settings.get("Modbus-IP", "192.168.8.203")
        dialog = NumpadDialog(self, title="Neue IP-Adresse eingeben", initial_value=aktuelle_ip, is_password=False)

        if dialog.exec_() == QDialog.Accepted:
            neue_ip = dialog.get_raw_text()
            if neue_ip.count('.') == 3 and len(neue_ip) >= 7:
                self.settings["Modbus-IP"] = neue_ip
                save_settings(self.settings)
                self.main_app.times["Modbus-IP"] = neue_ip
                self.save_status_lbl.setText("IP geändert! Reset nötig.")
                self.save_status_lbl.setStyleSheet("color: #00ff00;")
                QTimer.singleShot(4000, lambda: self.save_status_lbl.setText(""))
            else:
                self.save_status_lbl.setText("FEHLER: Ungültiges IP-Format!")
                self.save_status_lbl.setStyleSheet("color: #ff0000;")
                QTimer.singleShot(4000, lambda: self.save_status_lbl.setText(""))

    def closeEvent(self, event):
        self.io_timer.stop()
        event.accept()

=======
# -*- coding: utf-8 -*-
import logging
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLineEdit, QGridLayout, QPushButton, QHBoxLayout, QLabel, QFrame, QTextEdit, QMessageBox, QWidget, QApplication
from PyQt5.QtGui import QFont, QTextCursor
from PyQt5.QtCore import Qt, QTimer
from config_loader import load_settings, save_settings

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
        layout.setContentsMargins(10, 10, 10, 10)
        
        self.display = QLineEdit(initial_value)
        self.display.setFont(QFont("Arial", 16))
        self.display.setAlignment(Qt.AlignRight)
        self.display.setReadOnly(True)

        if is_password:
            self.display.setEchoMode(QLineEdit.Password)

        layout.addWidget(self.display)
        grid = QGridLayout()
        grid.setSpacing(5)
        buttons = [
            ('7', 0, 0), ('8', 0, 1), ('9', 0, 2),
            ('4', 1, 0), ('5', 1, 1), ('6', 1, 2),
            ('1', 2, 0), ('2', 2, 1), ('3', 2, 2),
            ('0', 3, 0), ('.', 3, 1), ('C', 3, 2)
        ]
        for text, row, col in buttons:
            btn = QPushButton(text)
            btn.setFont(QFont("Arial", 14, QFont.Bold))
            btn.setFixedSize(55, 55) 
            btn.clicked.connect(self.num_pressed)
            grid.addWidget(btn, row, col)

        layout.addLayout(grid)
        
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setFont(QFont("Arial", 12))
        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.setFont(QFont("Arial", 12))
        ok_btn.clicked.connect(self.accept)
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
            if not current.startswith('9'): return
            elif len(current) >= 9: return

        if text == '.':
            if "IP" in self.windowTitle():
                if current.count('.') < 3 and not current.endswith('.'):
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
        self.setFixedSize(920, 520) 
        self.setStyleSheet("background-color: #2b2b2b; color: #ffffff;")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)

        self.main_app = parent
        self.client = parent.client
        self.settings = load_settings()
        self.change_buttons = []
        self.init_ui()

        self.io_timer = QTimer(self)
        self.io_timer.timeout.connect(self.update_live_ios)
        self.io_timer.start(250)

    def init_ui(self):
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(15)

        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(5, 5, 5, 5)
        left_layout.setSpacing(2) 

        times_title = QLabel("Zeiteinstellungen")
        times_title.setFont(QFont("Arial", 11, QFont.Bold))
        times_title.setFixedHeight(20)
        left_layout.addWidget(times_title)

        grid_times = QGridLayout()
        grid_times.setSpacing(2) 
        grid_times.setContentsMargins(0, 0, 0, 0)
        
        self.inputs = {}
        row = 0
        for key, val in self.settings.items():
            if key == "Service-PIN": continue

            if key == "Modbus-IP":
                lbl = QLabel(f"{key}:")
            elif key in ["Wartungsintervall", "Wartungsintervall-Stunden"]:
                lbl = QLabel(f"{key} (h):")
            else:
                lbl = QLabel(f"{key} (s):")

            lbl.setFont(QFont("Arial", 9)) 
            lbl.setFixedHeight(24)
            lbl.setStyleSheet("margin: 0px; padding: 0px;")
            grid_times.addWidget(lbl, row, 0)
            le = QLineEdit(str(val))
            le.setFont(QFont("Arial", 9, QFont.Bold)) 
            le.setReadOnly(True)
            le.setFixedWidth(125) 
            le.setFixedHeight(24) 
            le.setStyleSheet("""
                background-color: #111111; color: #ffffff; padding: 0px 5px; margin: 0px;
                border: 1px solid #444444; border-radius: 3px;
            """)
            grid_times.addWidget(le, row, 1)

            btn = QPushButton("Ändern")
            btn.setFont(QFont("Arial", 8, QFont.Bold))
            btn.setFixedSize(60, 24) 
            btn.setStyleSheet("""
                QPushButton { background-color: #444444; color: white; margin: 0px; padding: 0px; border: 1px solid #555555; border-radius: 3px; }
                QPushButton:pressed { background-color: #666666; }
            """)
            btn.clicked.connect(lambda checked, k=key, e=le: self.open_numpad(k, e))
            grid_times.addWidget(btn, row, 2)

            self.change_buttons.append(btn)
            self.inputs[key] = le
            row += 1

        left_layout.addLayout(grid_times)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setFixedHeight(2)
        sep1.setStyleSheet("background-color: #444444; margin: 2px 0px;")
        left_layout.addWidget(sep1)

        hours_title = QLabel("Betriebsstunden & Wartung")
        hours_title.setFont(QFont("Arial", 11, QFont.Bold))
        hours_title.setStyleSheet("color: #00ffcc;")
        hours_title.setFixedHeight(20)
        left_layout.addWidget(hours_title)

        grid_hours = QGridLayout()
        grid_hours.setSpacing(2)
        grid_hours.setContentsMargins(0, 0, 0, 0)
        
        self.lbl_gesamt_text = QLabel("Gesamtbetriebszeit:")
        self.lbl_gesamt_text.setFont(QFont("Arial", 9))
        self.lbl_gesamt_text.setFixedHeight(24)
        
        self.lbl_gesamt_val = QLabel("0.0 h")
        self.lbl_gesamt_val.setFont(QFont("Arial", 9, QFont.Bold))
        self.lbl_gesamt_val.setFixedSize(70, 24)
        self.lbl_gesamt_val.setStyleSheet("color: #ffffff; background-color: #111111; padding: 2px 4px; border-radius: 2px;")

        self.lbl_fahrt_text = QLabel("Reine Fahrzeit:")
        self.lbl_fahrt_text.setFont(QFont("Arial", 9))
        self.lbl_fahrt_text.setFixedHeight(24)
        
        self.lbl_fahrt_val = QLabel("0.0 h")
        self.lbl_fahrt_val.setFont(QFont("Arial", 9, QFont.Bold))
        self.lbl_fahrt_val.setFixedSize(70, 24)
        self.lbl_fahrt_val.setStyleSheet("color: #ffaa00; background-color: #111111; padding: 2px 4px; border-radius: 2px;")

        grid_hours.addWidget(self.lbl_gesamt_text, 0, 0)
        grid_hours.addWidget(self.lbl_gesamt_val, 0, 1)
        grid_hours.addWidget(self.lbl_fahrt_text, 1, 0)
        grid_hours.addWidget(self.lbl_fahrt_val, 1, 1)
        left_layout.addLayout(grid_hours)

        self.btn_reset_fahrt = QPushButton("Fahrzeit nach Wartung zurücksetzen")
        self.btn_reset_fahrt.setFont(QFont("Arial", 9, QFont.Bold))
        self.btn_reset_fahrt.setFixedHeight(24) 
        self.btn_reset_fahrt.setStyleSheet("background-color: #444444; color: white; border-radius: 3px; border: 1px solid #555555;")
        self.btn_reset_fahrt.clicked.connect(self.protected_fahrzeit_reset)
        left_layout.addWidget(self.btn_reset_fahrt)

        self.btn_change_pin = QPushButton("Service-PIN ändern")
        self.btn_change_pin.setFont(QFont("Arial", 9, QFont.Bold))
        self.btn_change_pin.setFixedHeight(24) 
        self.btn_change_pin.setStyleSheet("background-color: #334433; color: #aaffaa; border: 1px solid #557755; border-radius: 3px;")
        self.btn_change_pin.clicked.connect(self.open_pin_change_dialog)
        left_layout.addWidget(self.btn_change_pin) 

        self.btn_change_ip = QPushButton("Modbus IP-Adresse ändern")
        self.btn_change_ip.setFont(QFont("Arial", 9, QFont.Bold))
        self.btn_change_ip.setFixedHeight(24) 
        self.btn_change_ip.setStyleSheet("background-color: #333344; color: #ffaaff; border: 1px solid #555577; border-radius: 3px;")
        self.btn_change_ip.clicked.connect(self.open_ip_change_dialog)
        left_layout.addWidget(self.btn_change_ip)

        left_layout.addStretch(1)

        self.save_status_lbl = QLabel("")
        self.save_status_lbl.setFont(QFont("Arial", 9, QFont.Bold))
        self.save_status_lbl.setAlignment(Qt.AlignCenter)
        self.save_status_lbl.setFixedHeight(18)
        left_layout.addWidget(self.save_status_lbl)

        self.save_btn = QPushButton("Zeiten Speichern")
        self.save_btn.setFont(QFont("Arial", 10, QFont.Bold))
        self.save_btn.setFixedHeight(30) 
        self.save_btn.setStyleSheet("background-color: #0055ff; color: white; border-radius: 4px;")
        self.save_btn.clicked.connect(self.save_clicked)
        left_layout.addWidget(self.save_btn)
        
        main_layout.addLayout(left_layout, stretch=45)

        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setStyleSheet("background-color: #555555;")
        main_layout.addWidget(line)

        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(5, 5, 5, 5)
        right_layout.setSpacing(2) 

        io_title = QLabel("Physische I/O Zustände (Live)")
        io_title.setFont(QFont("Arial", 11, QFont.Bold))
        io_title.setFixedHeight(20)
        right_layout.addWidget(io_title)

        grid_ios = QGridLayout()
        grid_ios.setSpacing(2) 
        grid_ios.setContentsMargins(0, 0, 0, 0)

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
        lbl_in_header.setFont(QFont("Arial", 9, QFont.Bold))
        lbl_in_header.setStyleSheet("color: #00ffcc; margin-top: 2px;")
        lbl_in_header.setFixedHeight(18)
        grid_ios.addWidget(lbl_in_header, io_row, 0, 1, 2)
        io_row += 1

        for i in range(6):
            led = QLabel()
            led.setFixedSize(14, 14)
            self.set_led_state(led, False)
            
            lbl_name = QLabel(self.input_labels_def[i])
            lbl_name.setFont(QFont("Arial", 9))
            lbl_name.setFixedHeight(24) 
            lbl_name.setStyleSheet("margin: 0px; padding: 0px;")
            
            grid_ios.addWidget(led, io_row, 0, Qt.AlignVCenter)
            grid_ios.addWidget(lbl_name, io_row, 1, Qt.AlignVCenter)
            self.input_leds[i] = led
            io_row += 1

        lbl_out_header = QLabel("AUSGÄNGE:")
        lbl_out_header.setFont(QFont("Arial", 9, QFont.Bold))
        lbl_out_header.setStyleSheet("color: #ffaa00; margin-top: 4px;")
        lbl_out_header.setFixedHeight(18)
        grid_ios.addWidget(lbl_out_header, io_row, 0, 1, 2)
        io_row += 1

        for idx, name in self.output_labels_def.items():
            led = QLabel()
            led.setFixedSize(14, 14)
            self.set_led_state(led, False)
            
            lbl_name = QLabel(name)
            lbl_name.setFont(QFont("Arial", 9))
            lbl_name.setFixedHeight(24) 
            lbl_name.setStyleSheet("margin: 0px; padding: 0px;")
            
            grid_ios.addWidget(led, io_row, 0, Qt.AlignVCenter)
            grid_ios.addWidget(lbl_name, io_row, 1, Qt.AlignVCenter)
            self.output_leds[idx] = led
            io_row += 1

        right_layout.addLayout(grid_ios)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setFixedHeight(2)
        sep2.setStyleSheet("background-color: #444444; margin: 2px 0px;")
        right_layout.addWidget(sep2)

        tipp_title = QLabel("Manueller Einrichtbetrieb")
        tipp_title.setFont(QFont("Arial", 11, QFont.Bold))
        tipp_title.setFixedHeight(20)
        right_layout.addWidget(tipp_title)

        tipp_btn_layout = QHBoxLayout()
        self.btn_tipp_rueck = QPushButton("◀ RÜCKWÄRTS")
        self.btn_tipp_vor = QPushButton("VORWÄRTS ▶")
        self.btn_tipp_rueck.setFixedHeight(28)
        self.btn_tipp_vor.setFixedHeight(28)
        self.btn_tipp_rueck.setFont(QFont("Arial", 9, QFont.Bold))
        self.btn_tipp_vor.setFont(QFont("Arial", 9, QFont.Bold))
        self.btn_tipp_rueck.setStyleSheet("background-color: #444444; color: white; border: 1px solid #555555; border-radius: 3px;")
        self.btn_tipp_vor.setStyleSheet("background-color: #444444; color: white; border: 1px solid #555555; border-radius: 3px;")

        self.btn_tipp_vor.pressed.connect(lambda: self.main_app.start_tipp_mode("TippVor"))
        self.btn_tipp_vor.released.connect(self.main_app.stop_tipp_mode)
        self.btn_tipp_rueck.pressed.connect(lambda: self.main_app.start_tipp_mode("TippRueck"))
        self.btn_tipp_rueck.released.connect(self.main_app.stop_tipp_mode)

        tipp_btn_layout.addWidget(self.btn_tipp_rueck)
        tipp_btn_layout.addWidget(self.btn_tipp_vor)
        right_layout.addLayout(tipp_btn_layout)

        self.error_log_view = QTextEdit()
        self.error_log_view.setReadOnly(True)
        self.error_log_view.setFixedHeight(55) 
        self.error_log_view.setStyleSheet("background-color: #1a1a1a; color: #ff8888; font-family: monospace; font-size: 10px; border: 1px solid #444444; border-radius: 3px;")
        right_layout.addWidget(self.error_log_view)

        self.btn_clear_log = QPushButton("Logbuch leeren")
        self.btn_clear_log.setFont(QFont("Arial", 9, QFont.Bold))
        self.btn_clear_log.setFixedHeight(24)
        self.btn_clear_log.setStyleSheet("""
            QPushButton { background-color: #4a1515; color: #ff0000; padding: 0px; border: 1px solid #7a2525; border-radius: 3px; }
            QPushButton:pressed { background-color: #6a1f1f; color: #ff3333; }
            QPushButton:disabled { background-color: #221111; color: #441111; border: 1px solid #331111; }
        """)
        self.btn_clear_log.clicked.connect(self.protected_log_clear)
        right_layout.addWidget(self.btn_clear_log)

        right_layout.addStretch(1)

        self.btn_system_reset = QPushButton("Generellen System-Reset ausführen")
        self.btn_system_reset.setFont(QFont("Arial", 10, QFont.Bold))
        self.btn_system_reset.setFixedHeight(30)
        self.btn_system_reset.setStyleSheet("background-color: #ffaa00; color: #111111; border-radius: 4px;")
        self.btn_system_reset.clicked.connect(self.trigger_system_reset)
        right_layout.addWidget(self.btn_system_reset)

        close_btn = QPushButton("Schließen")
        close_btn.setFont(QFont("Arial", 9, QFont.Bold))
        close_btn.setFixedHeight(24)
        close_btn.setStyleSheet("""
            QPushButton { background-color: #444444; color: white; margin: 0px; padding: 0px; border: 1px solid #555555; border-radius: 3px; }
            QPushButton:pressed { background-color: #666666; }
        """)
        close_btn.clicked.connect(self.close)
        right_layout.addWidget(close_btn)
        
        main_layout.addLayout(right_layout, stretch=55)
        self.setLayout(main_layout)

    def set_led_state(self, led_widget, active):
        if active: led_widget.setStyleSheet("border-radius: 7px; border: 1px solid #111111; background-color: qradialgradient(cx:0.3, cy:0.3, radius:1.0, fx:0.3, fy:0.3, stop:0 #80ff80, stop:1 #009900);")
        else: led_widget.setStyleSheet("border-radius: 7px; border: 1px solid #222222; background-color: qradialgradient(cx:0.3, cy:0.3, radius:1.0, fx:0.3, fy:0.3, stop:0 #555555, stop:1 #222222);")

    def update_live_ios(self):
        if self.main_app.is_driving:
            self.save_btn.setEnabled(False)
            self.btn_reset_fahrt.setEnabled(False)
            self.btn_clear_log.setEnabled(False)
            self.btn_change_pin.setEnabled(False)
            self.btn_change_ip.setEnabled(False)
            for btn in self.change_buttons: btn.setEnabled(False)
        else:
            self.save_btn.setEnabled(True)
            self.btn_reset_fahrt.setEnabled(True)
            self.btn_clear_log.setEnabled(True)
            self.btn_change_pin.setEnabled(True)
            self.btn_change_ip.setEnabled(True)
            for btn in self.change_buttons: btn.setEnabled(True)

        inputs = self.main_app.latest_inputs
        coils = self.main_app.latest_coils
        if inputs and len(inputs) >= 6:
            for i in range(6): self.set_led_state(self.input_leds[i], inputs[i])
        if coils and len(coils) >= 8:
            for idx in self.output_labels_def.keys(): self.set_led_state(self.output_leds[idx], coils[idx])

        if hasattr(self.main_app, 'hours_data'):
            gesamt_stunden = self.main_app.hours_data["gesamt_sekunden"] / 3600.0
            fahr_stunden = self.main_app.hours_data["fahrzeit_sekunden"] / 3600.0
            self.lbl_gesamt_val.setText(f"{gesamt_stunden:.2f} h")

            max_wartung_stunden = self.settings.get("Wartungsintervall", self.settings.get("Wartungsintervall-Stunden", 50.0))
            if fahr_stunden >= max_wartung_stunden:
                self.lbl_fahrt_val.setText(f"{fahr_stunden:.2f} h - WARTUNG!")
                self.lbl_fahrt_val.setStyleSheet("color: #ff0000; background-color: #111111; padding: 2px; border: 1px solid red; border-radius: 2px; font-weight: bold;")
            else:
                self.lbl_fahrt_val.setText(f"{fahr_stunden:.2f} h")
                self.lbl_fahrt_val.setStyleSheet("color: #ffaa00; background-color: #111111; padding: 2px; border-radius: 2px;")

        if hasattr(self.main_app, 'gui_error_list'):
            self.error_log_view.setPlainText("\n".join(self.main_app.gui_error_list))
            self.error_log_view.moveCursor(QTextCursor.Start)

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
        except Exception as e:
            self.save_status_lbl.setText("Fehler beim Speichern!")
            self.save_status_lbl.setStyleSheet("color: #ff0000;")

######################################
######################################
    PUK_NOTFALL_NUMMER = 987654321
######################################
######################################

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
                    self.save_status_lbl.setText("Fahrzeit zurückgesetzt!")
                    self.save_status_lbl.setStyleSheet("color: #00ff00;")
                    QTimer.singleShot(3000, lambda: self.save_status_lbl.setText(""))
                else:
                    self.save_status_lbl.setText("FALSCHE PIN!")
                    self.save_status_lbl.setStyleSheet("color: #ff0000;")
                    QTimer.singleShot(3000, lambda: self.save_status_lbl.setText(""))
            except ValueError: pass

    def protected_log_clear(self):
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setWindowTitle("Logbuch leeren")
        msg_box.setText("Möchten Sie das Fehler-Logbuch leeren?")
        yes_btn = msg_box.addButton("Ja, löschen", QMessageBox.YesRole)
        no_btn = msg_box.addButton("Abbrechen", QMessageBox.NoRole)
        msg_box.setDefaultButton(no_btn)
        msg_box.setStyleSheet("background-color: #2b2b2b; color: white;")
        msg_box.exec_()

        if msg_box.clickedButton() == no_btn: return

        dialog = NumpadDialog(self, title="Service-PIN eingeben", initial_value="", is_password=True)
        if dialog.exec_() == QDialog.Accepted:
            try:
                eingabe = int(dialog.get_value())
                aktuelle_pin = int(self.settings.get("Service-PIN", 1234))

                if eingabe == aktuelle_pin or eingabe == self.PUK_NOTFALL_NUMMER:
                    self.main_app.clear_gui_error_log()
                    self.save_status_lbl.setText("Logbuch gelöscht!")
                    self.save_status_lbl.setStyleSheet("color: #00ff00;")
                    QTimer.singleShot(3000, lambda: self.save_status_lbl.setText(""))
                else:
                    self.save_status_lbl.setText("FALSCHE PIN! Abbruch.")
                    self.save_status_lbl.setStyleSheet("color: #ff0000;")
                    QTimer.singleShot(3000, lambda: self.save_status_lbl.setText(""))
            except ValueError: pass

    def open_pin_change_dialog(self):
        dialog = NumpadDialog(self, title="Alte PIN oder PUK eingeben", initial_value="", is_password=True)
        if dialog.exec_() == QDialog.Accepted:
            try:
                eingabe = int(dialog.get_value())
                aktuelle_pin = int(self.settings.get("Service-PIN", 1234))

                if eingabe == aktuelle_pin or eingabe == self.PUK_NOTFALL_NUMMER:
                    new_pin_dialog = NumpadDialog(self, title="EXAKT 4 Ziffern eingeben", initial_value="", is_password=True)
                    if new_pin_dialog.exec_() == QDialog.Accepted:
                        neue_pin = int(new_pin_dialog.get_value())
                        self.settings["Service-PIN"] = neue_pin
                        save_settings(self.settings)
                        self.save_status_lbl.setText("PIN geändert!")
                        self.save_status_lbl.setStyleSheet("color: #00ff00;")
                        QTimer.singleShot(3000, lambda: self.save_status_lbl.setText(""))
                else:
                    self.save_status_lbl.setText("Fehlgeschlagen!")
                    self.save_status_lbl.setStyleSheet("color: #ff0000;")
                    QTimer.singleShot(3000, lambda: self.save_status_lbl.setText(""))
            except ValueError: pass

    def trigger_system_reset(self):
        self.btn_system_reset.setEnabled(False)
        self.btn_system_reset.setText("Führe System-Reset aus...")
        QApplication.processEvents() 
        if self.main_app.general_system_reset():
            self.btn_system_reset.setText("System zurückgesetzt!")
            self.btn_system_reset.setStyleSheet("background-color: #00ff00; color: #111111;")
        else:
            self.btn_system_reset.setText("Reset FEHLGESCHLAGEN!")
            self.btn_system_reset.setStyleSheet("background-color: #ff0000; color: #ffffff;")
        QTimer.singleShot(3000, self.trigger_system_reset_style_reset)

    def trigger_system_reset_style_reset(self):
        self.btn_system_reset.setEnabled(True)
        self.btn_system_reset.setText("Generellen System-Reset ausführen")
        self.btn_system_reset.setStyleSheet("background-color: #ffaa00; color: #111111; font-weight: bold; border-radius: 4px;")

    def open_ip_change_dialog(self):
        aktuelle_ip = self.settings.get("Modbus-IP", "192.168.8.203")
        dialog = NumpadDialog(self, title="Neue IP-Adresse eingeben", initial_value=aktuelle_ip, is_password=False)

        if dialog.exec_() == QDialog.Accepted:
            neue_ip = dialog.get_raw_text()
            if neue_ip.count('.') == 3 and len(neue_ip) >= 7:
                self.settings["Modbus-IP"] = neue_ip
                save_settings(self.settings)
                self.main_app.times["Modbus-IP"] = neue_ip
                self.save_status_lbl.setText("IP geändert! Reset nötig.")
                self.save_status_lbl.setStyleSheet("color: #00ff00;")
                QTimer.singleShot(4000, lambda: self.save_status_lbl.setText(""))
            else:
                self.save_status_lbl.setText("FEHLER: Ungültiges IP-Format!")
                self.save_status_lbl.setStyleSheet("color: #ff0000;")
                QTimer.singleShot(4000, lambda: self.save_status_lbl.setText(""))

    def closeEvent(self, event):
        self.io_timer.stop()
        event.accept()

>>>>>>> aea6e0f3cc44f05c8b75f9cd480e934127c702a5
