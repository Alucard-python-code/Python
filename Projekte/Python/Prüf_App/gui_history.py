import os
import subprocess
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QPushButton, QHBoxLayout, QMessageBox, QLineEdit
from PyQt6.QtGui import QColor

class HistoryScreen(QWidget):
    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        layout = QVBoxLayout()

        layout.addWidget(QLabel("<h2>Historie & Dokumenten-Archiv</h2>"))
        
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("🔍 Archiv durchsuchen:"))
        self.txt_search = QLineEdit(placeholderText="Nach Firma, Datum, Frist oder Pfad filtern...")
        self.txt_search.textChanged.connect(self.filter_history)
        search_layout.addWidget(self.txt_search)
        layout.addLayout(search_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Firma", "Prüfer/Kontakt", "Prüfdatum", "Nächste Prüfung 📅", "Archivpfad (ZIP)"])
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        btn_back = QPushButton("Zurück zum Hauptmenü")
        btn_back.clicked.connect(self.main_app.show_customer_screen)
        
        # Button-Text angepasst auf die neue Explorer-Funktion
        btn_open = QPushButton("📂 ZIP im Windows-Explorer öffnen & anzeigen")
        btn_open.clicked.connect(self.locate_zip)
        btn_open.setStyleSheet("font-weight: bold; background-color: #0078D7; color: white;")
        
        btn_layout.addWidget(btn_back)
        btn_layout.addWidget(btn_open)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def refresh_history(self):
        history_entries = self.main_app.db.get_history()
        self.table.setRowCount(len(history_entries))
        
        for row_idx, row_data in enumerate(history_entries):
            self.table.setItem(row_idx, 0, QTableWidgetItem(str(row_data[1])))
            self.table.setItem(row_idx, 1, QTableWidgetItem(str(row_data[2])))
            self.table.setItem(row_idx, 2, QTableWidgetItem(str(row_data[3])))
            
            due_item = QTableWidgetItem(str(row_data[4]))
            due_item.setForeground(QColor("#D32F2F"))
            self.table.setItem(row_idx, 3, due_item)
            
            path_item = QTableWidgetItem(str(row_data[5]))
            self.table.setItem(row_idx, 4, path_item)
            
        self.filter_history()

    def filter_history(self):
        search_text = self.txt_search.text().lower()
        for row_idx in range(self.table.rowCount()):
            row_match = False
            for col_idx in range(self.table.columnCount()):
                item = self.table.item(row_idx, col_idx)
                if item and search_text in item.text().lower():
                    row_match = True
                    break
            self.table.setRowHidden(row_idx, not row_match)

    def locate_zip(self):
        selected_row = self.table.currentRow()
        if selected_row >= 0 and not self.table.isRowHidden(selected_row):
            zip_path = self.table.item(selected_row, 4).text()
            absolute_path = os.path.abspath(zip_path)
            
            if os.path.exists(absolute_path):
                try:
                    # Öffnet den Windows-Explorer, steuert den Ordner an und markiert das ZIP [1]
                    subprocess.run(['explorer', '/select,', absolute_path])
                except Exception as e:
                    QMessageBox.warning(self, "Fehler", f"Explorer konnte nicht geöffnet werden: {str(e)}")
            else:
                QMessageBox.warning(self, "Datei nicht auffindbar", f"Das Archiv existiert nicht (mehr) unter:\n{absolute_path}")
        else:
            QMessageBox.warning(self, "Auswahl fehlt", "Bitte markieren Sie eine sichtbare Zeile in der Tabelle.")
