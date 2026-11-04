from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QPushButton, QHBoxLayout, QMessageBox
from PyQt6.QtGui import QColor
import os

class HistoryScreen(QWidget):
    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        layout = QVBoxLayout()

        layout.addWidget(QLabel("<h2>Historie & Dokumenten-Archiv</h2>"))
        layout.addWidget(QLabel("Hier sehen Sie alle abgeschlossenen UVV-Prüfungen und Fristen:"))

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Firma", "Prüfer/Kontakt", "Prüfdatum", "Nächste Prüfung 📅", "Archivpfad (ZIP)"])
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        btn_back = QPushButton("Zurück zum Hauptmenü")
        btn_back.clicked.connect(self.main_app.show_customer_screen)
        
        btn_open = QPushButton("Ausgewähltes ZIP lokalisieren")
        btn_open.clicked.connect(self.locate_zip)
        
        btn_layout.addWidget(btn_back)
        btn_layout.addWidget(btn_open)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def refresh_history(self):
        history_entries = self.main_app.db.get_history()
        self.table.setRowCount(len(history_entries))
        
        for row_idx, row_data in enumerate(history_entries):
            # row_data: (id, company, name, date_checked, next_due, zip_path)
            self.table.setItem(row_idx, 0, QTableWidgetItem(str(row_data)))
            self.table.setItem(row_idx, 1, QTableWidgetItem(str(row_data)))
            self.table.setItem(row_idx, 2, QTableWidgetItem(str(row_data)))
            
            # Fälligkeit visuell hervorheben
            due_item = QTableWidgetItem(str(row_data))
            due_item.setForeground(QColor("#D32F2F")) # Signalrot für Fristen
            self.table.setItem(row_idx, 3, due_item)
            
            path_item = QTableWidgetItem(str(row_data))
            self.table.setItem(row_idx, 4, path_item)

    def locate_zip(self):
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            zip_path = self.table.item(selected_row, 4).text()
            if os.path.exists(zip_path):
                QMessageBox.information(self, "Datei Gefunden", f"Die Archivdatei existiert im Verzeichnis:\n\n{os.path.abspath(zip_path)}")
            else:
                QMessageBox.warning(self, "Datei nicht auffindbar", "Das Archiv wurde verschoben oder gelöscht.")
        else:
            QMessageBox.warning(self, "Auswahl fehlt", "Bitte markieren Sie eine Zeile in der Tabelle.")
