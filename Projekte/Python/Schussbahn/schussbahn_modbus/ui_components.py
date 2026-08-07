# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import QPushButton, QLabel, QProgressBar, QGridLayout, QHBoxLayout, QVBoxLayout, QSizePolicy
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt

def setup_app_ui(app):
    app.setStyleSheet("background-color: #2b2b2b; color: #ffffff;")
    app.setWindowFlags(Qt.FramelessWindowHint)

    main_layout = QVBoxLayout()
    main_layout.setContentsMargins(8, 8, 8, 8)
    main_layout.setSpacing(6)

    grid_layout = QGridLayout()
    grid_layout.setSpacing(8)

    app.btn_beschuss = QPushButton("Beschuss")
    app.btn_licht_an = QPushButton("Licht an")
    app.btn_einstellungen = QPushButton("Einstellungen")
    app.btn_wertung = QPushButton("Wertung")
    app.btn_licht_aus = QPushButton("Licht aus")
    app.btn_exit = QPushButton("Exit")

    buttons = [
        (app.btn_beschuss, 0, 0), (app.btn_licht_an, 0, 1), (app.btn_einstellungen, 0, 2),
        (app.btn_wertung, 1, 0), (app.btn_licht_aus, 1, 1), (app.btn_exit, 1, 2)
    ]

    button_font = QFont("Arial", 18, QFont.Bold)
    for btn, row, col in buttons:
        btn.setFont(button_font)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        if btn == app.btn_exit:
            btn.setStyleSheet("QPushButton { background-color: #552222; color: #ffaaaa; border: 1px solid #774444; border-radius: 4px; } QPushButton:pressed { background-color: #773333; }")
        else:
            btn.setStyleSheet("QPushButton { background-color: #444444; color: white; border: 1px solid #555555; border-radius: 4px; } QPushButton:pressed { background-color: #666666; }")

        grid_layout.addWidget(btn, row, col)

    main_layout.addLayout(grid_layout, stretch=60)

    position_container = QWidget_Helper(app)
    main_layout.addWidget(position_container, stretch=20)

    status_layout = QHBoxLayout()
    status_title = QLabel("Status: ")
    status_title.setFont(QFont("Arial", 16, QFont.Bold))
    status_title.setFixedWidth(120)
    status_title.setFixedHeight(50) 
    status_layout.addWidget(status_title)

    app.status_msg = QLabel("Initialisierung...")
    app.status_msg.setFont(QFont("Arial", 16, QFont.Bold))
    app.status_msg.setFixedHeight(50)
    app.status_msg.setStyleSheet("color: #00ff00; background-color: #111111; padding-left: 15px; border-radius: 6px;")
    status_layout.addWidget(app.status_msg)

    main_layout.addLayout(status_layout, stretch=20)
    app.setLayout(main_layout)

def QWidget_Helper(app):
    from PyQt5.QtWidgets import QWidget
    container = QWidget()
    container.setFixedHeight(75) 
    container.setStyleSheet("background-color: #1a1a1a; border-radius: 6px; border: 1px solid #444444;")

    layout = QHBoxLayout(container)
    layout.setContentsMargins(15, 0, 15, 0)
    layout.setSpacing(10)

    lbl_home = QLabel("Stand")
    lbl_home.setFont(QFont("Arial", 14, QFont.Bold)) 
    lbl_home.setStyleSheet("color: #00ffcc; border: none;")

    app.track_bar = QProgressBar()
    app.track_bar.setRange(0, 100)
    app.track_bar.setValue(0)
    app.track_bar.setTextVisible(False)
    app.track_bar.setFixedHeight(35) 
    app.track_bar.setStyleSheet("QProgressBar { background-color: #252525; border-radius: 4px; border: 1px solid #444444; } QProgressBar::chunk { background-color: #113322; border-radius: 3px; }")

    app.moving_target = QLabel(" ", app.track_bar)
    app.moving_target.setFont(QFont("Arial", 20)) 
    app.moving_target.setStyleSheet("border: none; background: transparent;")
    app.moving_target.move(0, -3) 

    lbl_end = QLabel("Kugelfang")
    lbl_end.setFont(QFont("Arial", 14, QFont.Bold))
    lbl_end.setStyleSheet("color: #ffaa00; border: none;")

    layout.addWidget(lbl_home)
    layout.addWidget(app.track_bar, stretch=1)
    layout.addWidget(lbl_end)
    return container
