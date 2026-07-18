#!/usr/bin/python3
# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import (QDialog, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, 
                             QGridLayout, QTableWidget, QTableWidgetItem, QHeaderView, QListWidget)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, QTimer
from config_loader import save_settings, load_operating_hours, load_error_log

class SettingsWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Einstellungen & Diagnose")
        self.setFixedSize(900, 520)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setStyleSheet("background-color: #333333; color: white; border: 1px solid #555555;")
        self.init_ui()

        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self.update_diagnostics)
        self.ui_timer.start(200)

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Titelzeile mit Global Reset Button
        top_bar = QHBoxLayout()
        lbl_title = QLabel("Systemeinstellungen & Diagnose")
        lbl_title.setFont(QFont("Arial", 16, QFont.Bold))
        top_bar.addWidget(lbl_title)
        
        btn_reset = QPushButton("GLOBAL SYSTEM RESET")
        btn_reset.setFont(QFont("Arial", 11, QFont.Bold))
        btn_reset.setStyleSheet("background-color: #772222; color: #ffcccc; padding: 6px; border-radius: 4px;")
        btn_reset.clicked.connect(self.trigger_global_reset)
        top_bar.addWidget(btn_reset)
        layout.addLayout(top_bar)

        grid = QGridLayout()
        grid.setSpacing(6)

        # Spalte 1: Zeiten-Parameter
        vbox_left = QVBoxLayout()
        lbl_sect1 = QLabel("Fahrzeiten konfigurieren (Sek.)")
        lbl_sect1.setFont(QFont("Arial", 12, QFont.Bold))
        vbox_left.addWidget(lbl_sect1)

        self.param_keys = [
            "Beschuss Schnell", "Beschuss Langsam", "Bremszeit Vorwaerts",
            "Wartezeit Kugelfang", "Wertung Schnell", "Bremszeit Rueckwaerts"
        ]
        self.fields = {}

        for key in self.param_keys:
            row_hb = QHBoxLayout()
            lbl = QLabel(key + ":")
            lbl.setFont(QFont("Arial", 10))
            lbl.setFixedWidth(160)
            
            val_lbl = QLabel(f"{self.parent_app.times.get(key, 0.0):.2f}")
            val_lbl.setFont(QFont("Arial", 12, QFont.Bold))
            val_lbl.setStyleSheet("background-color: #222222; padding: 4px; border-radius: 3px;")
            val_lbl.setAlignment(Qt.AlignCenter)
            val_lbl.setFixedWidth(60)
            self.fields[key] = val_lbl

            btn_minus = QPushButton("-")
            btn_minus.setFixedSize(36, 32)
            btn_minus.clicked.connect(lambda checked, k=key: self.modify_value(k, -0.1))
            
            btn_plus = QPushButton("+")
            btn_plus.setFixedSize(36, 32)
            btn_plus.clicked.connect(lambda checked, k=key: self.modify_value(k, 0.1))

            for b in [btn_minus, btn_plus]:
                b.setStyleSheet("background-color: #444444; font-size: 16px; font-weight: bold;")

            row_hb.addWidget(lbl)
            row_hb.addWidget(btn_minus)
            row_hb.addWidget(val_lbl)
            row_hb.addWidget(btn_plus)
            vbox_left.addLayout(row_hb)

        # Tippbetrieb
        lbl_tipp = QLabel("Manueller Tippbetrieb (Langsamlauf)")
        lbl_tipp.setFont(QFont("Arial", 11, QFont.Bold))
        lbl_tipp.setStyleSheet("margin-top: 6px; color: #ffaa00;")
        vbox_left.addWidget(lbl_tipp)

        tipp_hb = QHBoxLayout()
        self.btn_tipp_vor = QPushButton("Tipp VOR")
        self.btn_tipp_zurueck = QPushButton("Tipp ZURÜCK")
        for b in [self.btn_tipp_vor, self.btn_tipp_zurueck]:
            b.setFont(QFont("Arial", 11, QFont.Bold))
            b.setStyleSheet("background-color: #3e4d3e; color: white; height: 35px; border-radius: 4px;")
        
        self.btn_tipp_vor.pressed.connect(lambda: self.parent_app.start_tipp_mode("TippVor"))
        self.btn_tipp_vor.released.connect(self.parent_app.stop_tipp_mode)
        self.btn_tipp_zurueck.pressed.connect(lambda: self.parent_app.start_tipp_mode("TippRueck"))
        self.btn_tipp_zurueck.released.connect(self.parent_app.stop_tipp_mode)

        tipp_hb.addWidget(self.btn_tipp_zurueck)
        tipp_hb.addWidget(self.btn_tipp_vor)
        vbox_left.addLayout(tipp_hb)
        grid.addLayout(vbox_left, 0, 0)

        # Spalte 2: E/A Diagnose-Tabelle
        vbox_right = QVBoxLayout()
        lbl_sect2 = QLabel("Hardware E/A Live-Zustand")
        lbl_sect2.setFont(QFont("Arial", 12, QFont.Bold))
        vbox_right.addWidget(lbl_sect2)

        self.table = QTableWidget(7, 4)
        self.table.setHorizontalHeaderLabels(["Eingang", "Status", "Ausgang", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setStyleSheet("background-color: #252525; gridline-color: #444444; font-size: 11px;")
        
        inputs_desc = ["In1: Motorschutz", "In2: Endschalter", "In3: Schütz Rechts", "In4: Schütz Links", "In5: Schütz Langsam", "In6: Schütz Schnell", "-"]
        coils_desc = ["Out1: Rechts", "Out2: Links", "Out3: Langsam", "Out4: Schnell", "-", "-", "-", "Out8: Licht"]

        for i in range(7):
            self.table.setItem(i, 0, QTableWidgetItem(inputs_desc[i]))
            self.table.setItem(i, 1, QTableWidgetItem("0"))
            self.table.setItem(i, 2, QTableWidgetItem(coils_desc[i]))
            self.table.setItem(i, 3, QTableWidgetItem("OFF"))
            for col in range(4):
                item = self.table.item(i, col)
                if item: 
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                    item.setTextAlignment(Qt.AlignCenter)

        vbox_right.addWidget(self.table)

        # Betriebsstunden & Referenzstatus
        self.lbl_hours = QLabel("Betriebsstunden: Ges: 0.0h | Fahrt: 0.0h")
        self.lbl_hours.setFont(QFont("Arial", 10, QFont.Bold))
        self.lbl_hours.setStyleSheet("color: #00ffcc;")
        vbox_right.addWidget(self.lbl_hours)

        self.lbl_ref_state = QLabel("Kalibrierung: Unbekannt")
        self.lbl_ref_state.setFont(QFont("Arial", 10, QFont.Bold))
        vbox_right.addWidget(self.lbl_ref_state)

        grid.addLayout(vbox_right, 0, 1)
        layout.addLayout(grid)

        # Bereich Unten: Fehler-Logbox
        lbl_err_title = QLabel("Letzte Systemmeldungen / Fehlerhistorie:")
        lbl_err_title.setFont(QFont("Arial", 11, QFont.Bold))
        layout.addWidget(lbl_err_title)

        self.log_widget = QListWidget()
        self.log_widget.setFixedHeight(80)
        self.log_widget.setStyleSheet("background-color: #1a1a1a; color: #ff6666; font-family: monospace; font-size: 11px; border-radius: 4px;")
        layout.addWidget(self.log_widget)

        # Schließen
        btn_close = QPushButton("Schließen & Speichern")
        btn_close.setFont(QFont("Arial", 13, QFont.Bold))
        btn_close.setStyleSheet("background-color: #444444; height: 40px; border-radius: 4px;")
        btn_close.clicked.connect(self.close_window)
        layout.addWidget(btn_close)

        self.setLayout(layout)
        self.refresh_error_list_ui()

    def refresh_error_list_ui(self):
        self.log_widget.clear()
        errors = load_error_log()
        if not errors:
            self.log_widget.addItem("Keine Fehler protokolliert. System läuft fehlerfrei.")
            self.log_widget.item(0).setForeground(Qt.green)
        else:
            for err in errors:
                self.log_widget.addItem(err)

    def trigger_global_reset(self):
        self.ui_timer.stop()
        self.close()
        self.parent_app.general_system_reset()

    def modify_value(self, key, delta):
        cur = self.parent_app.times.get(key, 0.0)
        new_val = round(max(0.0, min(30.0, cur + delta)), 2)
        self.parent_app.times[key] = new_val
        self.fields[key].setText(f"{new_val:.2f}")

    def update_diagnostics(self):
        # inputs: [ms, es, schütz_r, schütz_l, schütz_la, schütz_sc]
        # coils:  [r, l, la, sc, 0, 0, 0, licht]
        inputs = self.parent_app.latest_inputs
        coils = self.parent_app.latest_coils

        # Zuweisungen Tabelle Eingänge
        for i in range(6):
            val_str = "1 (Signal)" if inputs[i] == 1 else "0 (Offen)"
            self.table.item(i, 1).setText(val_str)
            if i == 0:  # Motorschutz ist Active-High OK
                self.table.item(i, 1).setStyleSheet("color: #00ff00;" if inputs[i] == 1 else "color: #ff0000; font-weight: bold;")
            elif i == 1:  # Endschalter
                self.table.item(i, 1).setStyleSheet("color: #ffff00; font-weight: bold;" if inputs[i] == 1 else "color: white;")
            else:  # Schütze Feedback
                self.table.item(i, 1).setStyleSheet("color: #00ffcc;" if inputs[i] == 1 else "color: white;")

        # Zuweisungen Tabelle Ausgänge
        for i in range(4):
            self.table.item(i, 3).setText("ON" if coils[i] else "OFF")
            self.table.item(i, 3).setStyleSheet("color: #00ff00; font-weight: bold;" if coils[i] else "color: #888888;")

        # Sonderzeile Ausgang 8 (Licht) in Zeile index 6 mappen
        self.table.item(6, 3).setText("ON" if coils[7] else "OFF")
        self.table.item(6, 3).setStyleSheet("color: #ffff00; font-weight: bold;" if coils[7] else "color: #888888;")

        # Betriebsstunden
        hd = load_operating_hours()
        g_hours = hd.get("gesamt_sekunden", 0.0) / 3600.0
        f_hours = hd.get("fahrzeit_sekunden", 0.0) / 3600.0
        self.lbl_hours.setText(f"Betriebsstunden: Gesamt: {g_hours:.4f}h | Reine Fahrt: {f_hours:.4f}h")

        # Referenzierungsstatus visualisieren
        if self.parent_app.ist_referenziert:
            self.lbl_ref_state.setText("Kalibrierung: Schlitten referenziert (Bereit)")
            self.lbl_ref_state.setStyleSheet("color: #00ff00; font-weight: bold;")
        else:
            self.lbl_ref_state.setText("Kalibrierung: UNREFERENZIERT (Nächste Fahrt erfordert Home-Fahrt)")
            self.lbl_ref_state.setStyleSheet("color: #ff3333; font-weight: bold;")

        # Tipptasten sperren falls Automatik aktiv ist
        state = not self.parent_app.is_driving and not self.parent_app.system_fault
        self.btn_tipp_vor.setEnabled(state)
        self.btn_tipp_zurueck.setEnabled(state)

    def close_window(self):
        self.ui_timer.stop()
        save_settings(self.parent_app.times)
        self.close()