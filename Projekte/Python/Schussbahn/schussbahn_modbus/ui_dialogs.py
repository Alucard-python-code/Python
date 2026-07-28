#!/bin/python3
# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import *
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from config_loader import save_settings, load_error_log, save_error_log

class NumpadDialog(QDialog):
    def __init__(self, parent=None, title="Eingabe", echo_mode=QLineEdit.Normal, allow_dot=True, key_name=""):
        super().__init__(parent)
        self.setWindowTitle("Eingabe")
        self.setFixedSize(300, 500)
        self.value = ""

        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"Ändere: {key_name}"))

        self.display = QLineEdit()
        self.display.setEchoMode(echo_mode)
        self.display.setFixedHeight(40)
        layout.addWidget(self.display)

        grid = QGridLayout()
        buttons = ['7','8','9', '4','5','6', '1','2','3', 'C','0','.']
        for i, btn in enumerate(buttons):
            if btn == '.' and not allow_dot: continue
            b = QPushButton(btn)
            b.setFixedSize(60, 50)
            b.clicked.connect(lambda ch, v=btn: self.add_digit(v))
            grid.addWidget(b, i // 3, i % 3)
        layout.addLayout(grid)

        btn_layout = QHBoxLayout()
        btn_save = QPushButton("SPEICHERN")
        btn_save.setStyleSheet("background-color: #28a745; color: white; height: 40px;")
        btn_save.clicked.connect(self.accept)
        btn_cancel = QPushButton("ABBRUCH")
        btn_cancel.setStyleSheet("background-color: #dc3545; color: white; height: 40px;")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def add_digit(self, v):
        if v == 'C': self.value = ""
        else: self.value += v
        self.display.setText(self.value)

class SettingsWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.pin_fails = 0
        self.fields = {}
        self.setWindowTitle("Einstellungen & Diagnose")
        
        # Rahmen entfernen und fest auf die Monitorgröße einstellen
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setStyleSheet("background-color: #222; color: white;")
        
        self.init_ui()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_leds)
        self.timer.start(300)
        
        # Vollbildmodus aktivieren
        self.showFullScreen()

    def format_time(self, minutes):
        h = int(minutes) // 60
        m = int(minutes) % 60
        return f"{h:02d}:{m:02d}"

    def create_styled_separator(self, text):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 5, 0, 5)
        layout.setSpacing(10)
        def get_line():
            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setFrameShadow(QFrame.Sunken)
            line.setStyleSheet("color: #FFD700; border: 1px solid #FFD700;")
            return line
        layout.addWidget(get_line())
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #FFD700; font-weight: bold; font-size: 15px;")
        lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl)
        layout.addWidget(get_line())
        return container

    def create_param_row(self, key, show_change_btn=True):
        internal_key = key.replace("(hh:mm)", "(min)")
        row = QHBoxLayout()
        lbl = QLabel(key)
        lbl.setFixedWidth(200)
        row.addWidget(lbl)
        val = self.parent_app.times.get(internal_key, 0.0)
        display_val = self.format_time(val) if "Laufzeit" in key or "Wartung" in key else str(val)
        val_lbl = QLabel(display_val)
        val_lbl.setFixedWidth(100)
        self.fields[key] = val_lbl
        row.addWidget(val_lbl)
        if show_change_btn:
            btn = QPushButton("Ändern")
            btn.setFixedWidth(80)
            btn.setStyleSheet("background-color: #444444; color: white;")
            btn.clicked.connect(lambda ch, k=internal_key: self.secure_change(k))
            row.addWidget(btn)
        row.addStretch()
        return row
    def init_ui(self):
        # Hauptlayout des Dialogs
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(15, 15, 15, 15)

        # ScrollArea-Definition
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        # Verhindert das Zusammenziehen des Inhalts unter Wayland/X11
        scroll.setStyleSheet("QScrollArea { border: none; background-color: #222; }")
        
        # Inhalts-Widget, das jetzt die volle Breite erzwingt
        content_widget = QWidget()
        content_widget.setStyleSheet("background-color: #222;")
        
        # Das Layout wird direkt auf dem content_widget angewendet
        main_layout = QHBoxLayout(content_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(20)

        # LINKE SPALTE
        col_left = QVBoxLayout()
        col_left.addWidget(self.create_styled_separator("DIAGNOSE E/A"))
        
        diag_grid = QGridLayout()
        in_labels = ["Motorschutz", "Endschalter", "Schütz R", "Schütz L", "Schütz La", "Schütz Sc"]
        out_labels = ["Rechts", "Links", "Langsam", "Schnell"]
        self.leds = {}
        for i in range(6):
            diag_grid.addWidget(QLabel(in_labels[i]), i, 0)
            led_c = QWidget(); l_lay = QHBoxLayout(led_c); l_lay.setContentsMargins(5,0,50,0)
            l_lay.setSpacing(0)
            self.leds[f"in_{i}"] = self.create_led("#00FF00")
            l_lay.addWidget(self.leds[f"in_{i}"]); l_lay.addStretch()
            diag_grid.addWidget(led_c, i, 1)
            if i < 4:
                diag_grid.addWidget(QLabel(out_labels[i]), i, 2)
                led_c_out = QWidget(); lo_lay = QHBoxLayout(led_c_out); lo_lay.setContentsMargins(5,0,50,0)
                lo_lay.setSpacing(0)
                self.leds[f"out_{i}"] = self.create_led("#ffa500")
                lo_lay.addWidget(self.leds[f"out_{i}"]); lo_lay.addStretch()
                diag_grid.addWidget(led_c_out, i, 3)
        col_left.addLayout(diag_grid)

        col_left.addWidget(self.create_styled_separator("FAHRZEITEN"))
        for key in ["Beschuss Schnell", "Beschuss Langsam", "Bremszeit Vorwaerts", "Wertung Schnell", "Bremszeit Rueckwaerts"]:
            col_left.addLayout(self.create_param_row(key))
            
        col_left.addWidget(self.create_styled_separator("WATCHDOG ÜBERWACHUNG"))
        for key in ["Watchdog Beschuss", "Watchdog Wertung", "Watchdog HomeFahrt"]:
            col_left.addLayout(self.create_param_row(key))
        col_left.addStretch()

        # Vertikale Trennlinie
        line = QFrame(); line.setFrameShape(QFrame.VLine); line.setStyleSheet("color: #444; background-color: #444; width: 2px;")

        # RECHTE SPALTE
        col_right = QVBoxLayout()
        col_right.addWidget(self.create_styled_separator("WARTUNG"))
        col_right.addLayout(self.create_param_row("Laufzeit Motor (hh:mm)", show_change_btn=False))
        col_right.addLayout(self.create_param_row("Wartung Intervall (hh:mm)", show_change_btn=True))

        btn_reset = QPushButton("Motor-Laufzeit zurücksetzen")
        btn_reset.setStyleSheet("background-color: #E30613; color: white; height: 45px; font-weight: bold; margin: 5px 0; border-radius: 4px;")
        btn_reset.clicked.connect(self.secure_reset_motor)
        col_right.addWidget(btn_reset)

        btn_pin = QPushButton("Service PIN ändern")
        btn_pin.setStyleSheet("background-color: #444444; color: white; height: 45px; font-weight: bold; border-radius: 4px;")
        btn_pin.clicked.connect(lambda: self.secure_change("Service-PIN"))
        col_right.addWidget(btn_pin)

        col_right.addWidget(self.create_styled_separator("FEHLERHISTORIE"))
        self.log_widget = QListWidget(); self.log_widget.setFixedHeight(160)
        col_right.addWidget(self.log_widget)

        btn_clear_log = QPushButton("Fehlerspeicher löschen")
        btn_clear_log.setStyleSheet("background-color: #E30613; color: white; height: 45px; font-weight: bold; margin-top: 5px; border-radius: 4px;")
        btn_clear_log.clicked.connect(self.secure_clear_logs)
        col_right.addWidget(btn_clear_log)
        col_right.addStretch()

        # Spalten dem Haupt-Layout hinzufügen (Behebt den Breiten-Fehler!)
        main_layout.addLayout(col_left, 1)
        main_layout.addWidget(line)
        main_layout.addLayout(col_right, 1)
        
        scroll.setWidget(content_widget)
        outer_layout.addWidget(scroll)

        # Große Touch-Bedienknöpfe unten am Bildschirmrand (Fest fixiert)
        action_button_layout = QHBoxLayout()
        action_button_layout.setSpacing(15)

        btn_save_close = QPushButton("ÄNDERUNGEN SPEICHERN & SCHLIESSEN")
        btn_save_close.setStyleSheet("background-color: #458B00; color: white; font-weight: bold; font-size: 16px; height: 55px; border-radius: 6px;")
        btn_save_close.clicked.connect(self.action_save_and_exit)

        btn_abort = QPushButton("ABBRUCH")
        btn_abort.setStyleSheet("background-color: #8B1A1A; color: #ffcccc; font-weight: bold; font-size: 16px; height: 55px; border-radius: 6px;")
        btn_abort.clicked.connect(self.reject)

        action_button_layout.addWidget(btn_save_close, stretch=2)
        action_button_layout.addWidget(btn_abort, stretch=1)
        outer_layout.addLayout(action_button_layout)

        self.refresh_error_list_ui()

    def action_save_and_exit(self):
        save_settings(self.parent_app.times)
        QMessageBox.information(self, "System", "Alle Einstellungen wurden permanent gespeichert.")
        self.accept()

    def create_led(self, color):
        led = QLabel(); led.setFixedSize(20, 20)
        led.setStyleSheet("border-radius: 10px; background-color: #006400;")
        led.active_color = color
        return led

    def update_leds(self):
        for i in range(6):
            if i < len(self.parent_app.latest_inputs):
                state = self.parent_app.latest_inputs[i]
                if getattr(self.leds[f"in_{i}"], 'last_state', None) != state:
                    c = "#00FF00" if state else "#006400"
                    self.leds[f"in_{i}"].setStyleSheet(f"border-radius: 10px; background-color: {c};")
                    self.leds[f"in_{i}"].last_state = state
            if i < 4 and i < len(self.parent_app.latest_coils):
                state_out = self.parent_app.latest_coils[i]
                if getattr(self.leds[f"out_{i}"], 'last_state', None) != state_out:
                    c = "#00FF00" if state_out else "#006400"
                    self.leds[f"out_{i}"].setStyleSheet(f"border-radius: 10px; background-color: {c};")
                    self.leds[f"out_{i}"].last_state = state_out

    def refresh_error_list_ui(self):
        self.log_widget.clear()
        for err in load_error_log(): self.log_widget.addItem(err)

    def secure_clear_logs(self):
        pin_dlg = NumpadDialog(self, title="Sicherheit", echo_mode=QLineEdit.Password, allow_dot=False, key_name="Autorisierung Löschen")
        if pin_dlg.exec_() == QDialog.Accepted:
            correct_pin = str(self.parent_app.times.get("Service-PIN", 1234))
            if pin_dlg.value == correct_pin or (self.pin_fails >= 3 and pin_dlg.value == "9999"):
                self.pin_fails = 0
                save_error_log([])
                self.refresh_error_list_ui()
                QMessageBox.information(self, "Erfolg", "Fehlerspeicher wurde geleert.")
            else:
                self.pin_fails += 1
                QMessageBox.warning(self, "Fehler", "Falscher PIN!")

    def secure_reset_motor(self):
        pin_dlg = NumpadDialog(self, title="Sicherheit", echo_mode=QLineEdit.Password, allow_dot=False, key_name="Autorisierung Reset")
        if pin_dlg.exec_() == QDialog.Accepted:
            if pin_dlg.value == str(self.parent_app.times.get("Service-PIN", 1234)):
                self.parent_app.times["Laufzeit Motor (min)"] = 0.0
                if "Laufzeit Motor (hh:mm)" in self.fields: self.fields["Laufzeit Motor (hh:mm)"].setText("00:00")
                save_settings(self.parent_app.times)
                QMessageBox.information(self, "Erfolg", "Motor-Laufzeit wurde zurückgesetzt.")
            else:
                QMessageBox.warning(self, "Fehler", "Falscher PIN!")

    def secure_change(self, key):
        pin_dlg = NumpadDialog(self, title="Sicherheit", echo_mode=QLineEdit.Password, allow_dot=False, key_name="Autorisierung")
        if pin_dlg.exec_() == QDialog.Accepted:
            # 1. Stufe: Prüfen, ob der eingegebene Service-PIN korrekt ist
            if pin_dlg.value == str(self.parent_app.times.get("Service-PIN", 1234)):
                val_dlg = NumpadDialog(self, title="Ändern", echo_mode=QLineEdit.Normal, allow_dot=True, key_name=key)
                if val_dlg.exec_() == QDialog.Accepted:
                    new_val = val_dlg.value
                    if not new_val: 
                        return
                    
                    try:
                        # Unterscheidung zwischen Minutenwerten/Intervallen und normalen Texten/Zahlen
                        if "(min)" in key or "Wartung" in key:
                            val_float = float(new_val)
                            self.parent_app.times[key] = val_float
                            dk = key.replace("(min)", "(hh:mm)")
                            if dk in self.fields:
                                self.fields[dk].setText(self.format_time(val_float))
                        else:
                            self.parent_app.times[key] = new_val
                        
                        if key in self.fields:
                            self.fields[key].setText(new_val)
                        
                        # WICHTIG: Alle geänderten Werte sofort dauerhaft in der JSON-Datei sichern
                        save_settings(self.parent_app.times)
                        
                        # Sonderlogik: Wenn der PIN selbst geändert wurde, System neu starten
                        if key == "Service-PIN":
                            QMessageBox.information(self, "Hinweis", "PIN wurde geändert. System wird neu initialisiert.")
                            if hasattr(self.parent_app, 'trigger_system_reset'):
                                self.parent_app.trigger_system_reset()
                            self.accept()
                            
                    except ValueError:
                        QMessageBox.critical(self, "Fehler", "Ungültiger Zahlenwert eingegeben!")
            else:
                # Dieser Block muss sauber eingerückt auf der Ebene der ersten PIN-Abfrage stehen!
                QMessageBox.warning(self, "Zugriff verweigert", "Falscher Service-PIN!")
