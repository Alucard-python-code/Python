# gui_base.py

from PyQt5.QtWidgets import (QMainWindow, QWidget, QGridLayout, QHBoxLayout, 
                             QVBoxLayout, QPushButton, QLabel, QSizePolicy)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont


class ScalableButton(QPushButton):
    """Ein Button, der seine Schriftgröße dynamisch an seine Gesamtfläche anpasst."""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Berechne die Schriftgröße basierend auf der Diagonale/Fläche des Buttons
        # Dadurch skaliert die Schrift sowohl bei Höhen- als auch bei Breitenänderung ideal
        width = self.width()
        height = self.height()
        
        # Ein robuster Faktor, der im Vollbildmodus und im kleinen Fenster passt
        font_size = max(11, int((width + height) * 0.045))
        
        # Begrenzung nach oben, damit die Schrift bei riesigen 4K-Monitoren nicht zu extrem wird
        if font_size > 36:
            font_size = 36
            
        font = self.font()
        font.setPointSize(font_size)
        self.setFont(font)


class Ui_SchlittenSteuerung(QMainWindow):
    """Kapselt das gesamte Layout und Design der Anwendung."""
    def setup_ui(self):
        self.setWindowTitle("Maschinensteuerung Schlitten (PyQt5)")
        self.setMinimumSize(850, 450)
        self.resize(1024, 600)
        
        # Darkmode-Design
        self.setStyleSheet("""
            QMainWindow { background-color: #121212; }
            QLabel { color: #e0e0e0; font-family: Arial; }
            QPushButton { 
                background-color: #1f5eff; 
                color: white; 
                border-radius: 6px; 
                font-family: Arial;
                font-weight: bold;
                padding: 10px;
            }
            QPushButton:hover { background-color: #1a4ecc; }
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # ---- STEUERUNGSPANEL (LINKS) ----
        left_box = QWidget()
        grid = QGridLayout(left_box)
        grid.setSpacing(15)
        grid.setContentsMargins(0, 0, 0, 0)

        # Zeilen und Spalten im QGridLayout flexibel skalieren lassen
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        # Buttons erstellen
        self.btn_beschuss = ScalableButton("Beschuss")
        self.btn_auswertung = ScalableButton("Auswertung")

        self.btn_licht_an = ScalableButton("Licht AN")
        self.btn_licht_an.setStyleSheet("background-color: #2e7d32; color: white;")

        self.btn_licht_aus = ScalableButton("Licht AUS")
        self.btn_licht_aus.setStyleSheet("background-color: #c62828; color: white;")

        self.btn_settings = ScalableButton("Einstellungen")
        self.btn_settings.setStyleSheet("background-color: #37474f; color: white;")

        self.btn_exit = ScalableButton("EXIT")
        self.btn_exit.setStyleSheet("background-color: #d32f2f; color: white;")

        # Buttons ins Gitternetz einfügen
        grid.addWidget(self.btn_beschuss, 0, 0)
        grid.addWidget(self.btn_auswertung, 1, 0)
        grid.addWidget(self.btn_licht_an, 0, 1)
        grid.addWidget(self.btn_licht_aus, 1, 1)
        grid.addWidget(self.btn_settings, 0, 2)
        grid.addWidget(self.btn_exit, 1, 2)

        main_layout.addWidget(left_box, stretch=7)

        # ---- LED MATRIX (RECHTS) ----
        right_box = QWidget()
        right_box.setStyleSheet("background-color: #1e1e1e; border-radius: 8px;")
        right_box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        right_box.setMinimumWidth(280)
        right_box.setMaximumWidth(400)
        
        led_layout = QGridLayout(right_box)
        led_layout.setContentsMargins(12, 12, 12, 12)
        led_layout.setVerticalSpacing(6)
        
        led_layout.setColumnStretch(1, 1)
        led_layout.setColumnStretch(3, 1)

        # Header für die Tabellen-Anzeige
        lbl_in_hdr = QLabel("Eingänge (IN)")
        lbl_in_hdr.setFont(QFont("Arial", 11, QFont.Bold))
        lbl_out_hdr = QLabel("Ausgänge (CH)")
        lbl_out_hdr.setFont(QFont("Arial", 11, QFont.Bold))
        led_layout.addWidget(lbl_in_hdr, 0, 0, 1, 2, Qt.AlignCenter)
        led_layout.addWidget(lbl_out_hdr, 0, 2, 1, 2, Qt.AlignCenter)

        in_names = ["1: Motorschutz", "2: Endschalter", "3: RM Rechts", "4: RM Links", "5: RM Langsam", "6: RM Schnell", "7: Frei", "8: Frei"]
        out_names = ["1: Rechtslauf", "2: Linkslauf", "3: Langsam", "4: Schnell", "5: Frei", "6: Frei", "7: Frei", "8: Licht (CH8)", "9: Heartbeat (CH9)"]

        self.in_leds = []
        self.out_leds = []

        for i in range(8):
            led_layout.setRowStretch(i+1, 1)
            
            # Eingangs-LED & Name
            led_in = QLabel()
            led_in.setFixedSize(14, 14)
            led_layout.addWidget(led_in, i+1, 0)
            txt_in = QLabel(in_names[i])
            txt_in.setFont(QFont("Arial", 9))
            led_layout.addWidget(txt_in, i+1, 1)
            self.in_leds.append(led_in)

            # Ausgangs-LED & Name
            led_out = QLabel()
            led_out.setFixedSize(14, 14)
            led_layout.addWidget(led_out, i+1, 2)
            txt_out = QLabel(out_names[i])
            txt_out.setFont(QFont("Arial", 9))
            led_layout.addWidget(txt_out, i+1, 3)
            self.out_leds.append(led_out)

        main_layout.addWidget(right_box, stretch=3)
