from PyQt5.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, 
                             QListWidget, QLabel, QPushButton, QTextEdit)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

class HARTGui(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('HART Advanced Auto-Detect Terminal')
        self.setFixedSize(1024, 600) # Optimiert für dein 1024x600 Display
        self.setStyleSheet("QMainWindow { background-color: #0d1117; }")
        self.initUI()
        
    def initUI(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # ---- SIDEBAR ----
        sidebar = QVBoxLayout()
        
        self.btn_scan = QPushButton("🔍 NEUEN SENSOR SCAN_DETEKT")
        self.btn_scan.setStyleSheet("QPushButton { background-color: #1f6feb; color: white; font-weight: bold; padding: 15px; border-radius: 6px; font-size: 12px; margin-bottom: 5px;}")
        sidebar.addWidget(self.btn_scan)

        side_title = QLabel("GESPEICHERTE MESSSTELLEN")
        side_title.setFont(QFont('Courier', 12, QFont.Bold))
        side_title.setStyleSheet("color: #8b949e; padding-top: 5px;")
        sidebar.addWidget(side_title)

        self.tag_list = QListWidget()
        self.tag_list.setStyleSheet("""
            QListWidget { background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; color: #c9d1d9; }
            QListWidget::item { padding: 15px; border-bottom: 1px solid #21262d; font-size: 13px; }
            QListWidget::item:selected { background-color: #1f6feb; color: white; font-weight: bold; }
        """)
        sidebar.addWidget(self.tag_list, stretch=1)
        
        self.battery_label = QLabel("🔋 BATT: 98% (LiFePO4 25.6V)")
        self.battery_label.setFont(QFont('Courier', 12, QFont.Bold))
        self.battery_label.setStyleSheet("color: #3fb950; padding-top: 5px;")
        sidebar.addWidget(self.battery_label)
        
        main_layout.addLayout(sidebar, stretch=1)

        # ---- CONTENT AREA ----
        content_layout = QVBoxLayout()
        
        self.live_display = QLabel("--- bar")
        self.live_display.setAlignment(Qt.AlignCenter)
        self.live_display.setFont(QFont('Courier', 48, QFont.Bold))
        self.live_display.setStyleSheet("background-color: #161b22; color: #3fb950; border: 2px solid #30363d; border-radius: 10px; padding: 20px;")
        content_layout.addWidget(self.live_display)

        self.meta_label = QLabel("Bitte Sensor scannen oder aus der Liste wählen.")
        self.meta_label.setFont(QFont('Arial', 13))
        self.meta_label.setStyleSheet("color: #8b949e; padding: 5px 0px;")
        content_layout.addWidget(self.meta_label)

        # Workflow Box
        self.step_box = QWidget()
        self.step_box.setStyleSheet("background-color: #161b22; border: 1px solid #30363d; border-radius: 8px;")
        step_layout = QVBoxLayout(self.step_box)
        
        self.step_title = QLabel("Schritt X")
        self.step_title.setFont(QFont('Arial', 12, QFont.Bold))
        self.step_title.setStyleSheet("color: #58a6ff; border: none;")
        step_layout.addWidget(self.step_title)
        
        self.step_text = QTextEdit()
        self.step_text.setReadOnly(True)
        self.step_text.setFont(QFont('Arial', 14))
        self.step_text.setStyleSheet("color: #c9d1d9; border: none; background: transparent;")
        step_layout.addWidget(self.step_text)
        
        btn_layout = QHBoxLayout()
        self.btn_action = QPushButton("Bereit...")
        self.btn_action.setStyleSheet("QPushButton { background-color: #238636; color: white; font-weight: bold; padding: 15px; border-radius: 6px; font-size: 14px; } QPushButton:disabled { background-color: #21262d; color: #8b949e; }")
        
        self.btn_next = QPushButton("Weiter ►")
        self.btn_next.setStyleSheet("QPushButton { background-color: #216feb; color: white; font-weight: bold; padding: 15px; border-radius: 6px; font-size: 14px; }")
        
        btn_layout.addWidget(self.btn_action, stretch=1)
        btn_layout.addWidget(self.btn_next, stretch=1)
        step_layout.addLayout(btn_layout)
        
        content_layout.addWidget(self.step_box, stretch=1)
        main_layout.addLayout(content_layout, stretch=2)
        
        self.step_box.setVisible(False)
