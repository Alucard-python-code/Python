from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QCheckBox, QPushButton, QHBoxLayout
from checklist_data import CHECKLISTS

class ExamSelectScreen(QWidget):
    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.checkboxes = {}
        
        layout = QVBoxLayout()
        layout.addWidget(QLabel("<h2>Prüfobjekt-Auswahl</h2>"))
        layout.addWidget(QLabel("Wählen Sie alle zu prüfenden Bauteile/Objekte des Kunden aus:"))

        for key, data in CHECKLISTS.items():
            cb = QCheckBox(data["title"])
            layout.addWidget(cb)
            self.checkboxes[key] = cb

        btn_layout = QHBoxLayout()
        btn_back = QPushButton("Zurück zur Kundenverwaltung")
        btn_back.clicked.connect(lambda: self.main_app.show_customer_screen())
        btn_next = QPushButton("Prüfprotokolle laden")
        btn_next.clicked.connect(self.start_checking)
        
        btn_layout.addWidget(btn_back)
        btn_layout.addWidget(btn_next)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def start_checking(self):
        selected = [key for key, cb in self.checkboxes.items() if cb.isChecked()]
        self.main_app.start_exams(selected)
