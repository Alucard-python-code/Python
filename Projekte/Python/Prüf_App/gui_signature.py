import os
from datetime import datetime, timedelta
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QMessageBox, QSpinBox
from PyQt6.QtGui import QPainter, QPen, QImage
from PyQt6.QtCore import Qt, QPoint
from pdf_generator import PDFGenerator
from archiving import ArchiveManager

class SignaturePad(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(400, 200)
        self.image = QImage(400, 200, QImage.Format.Format_RGB32)
        self.image.fill(Qt.GlobalColor.white)
        self.last_point = QPoint()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.last_point = event.position().toPoint()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            painter = QPainter(self.image)
            painter.setPen(QPen(Qt.GlobalColor.black, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(self.last_point, event.position().toPoint())
            self.last_point = event.position().toPoint()
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawImage(QPoint(0, 0), self.image)

    def clear(self):
        self.image.fill(Qt.GlobalColor.white)
        self.update()

class SignatureScreen(QWidget):
    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        layout = QVBoxLayout()

        layout.addWidget(QLabel("<h2>Rechtssichere Signatur & Intervalle</h2>"))
        
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("Nächste Prüfung fällig in (Monate):"))
        self.sb_months = QSpinBox()
        self.sb_months.setRange(1, 48)
        self.sb_months.setValue(12)
        self.sb_months.setFixedWidth(80)
        interval_layout.addWidget(self.sb_months)
        interval_layout.addStretch()
        layout.addLayout(interval_layout)

        layout.addWidget(QLabel("Der Kunde bestätigt mit seiner Unterschrift den Erhalt des Prüfergebnisses:"))

        self.pad = SignaturePad()
        layout.addWidget(self.pad)

        btn_layout = QHBoxLayout()
        btn_clear = QPushButton("Unterschrift zurücksetzen")
        btn_clear.clicked.connect(self.pad.clear)
        btn_save = QPushButton("💾 Protokoll finalisieren & archivieren")
        btn_save.clicked.connect(self.finalize_report)
        
        btn_layout.addWidget(btn_clear)
        btn_save.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def calculate_due_date(self, months):
        now = datetime.now()
        new_month = now.month - 1 + months
        new_year = now.year + (new_month // 12)
        new_month = (new_month % 12) + 1
        try:
            return datetime(new_year, new_month, now.day)
        except ValueError:
            if new_month == 12:
                next_mon = datetime(new_year + 1, 1, 1)
            else:
                next_mon = datetime(new_year, new_month + 1, 1)
            return next_mon - timedelta(days=1)

    def finalize_report(self):
        customer = self.main_app.db.get_customer(self.main_app.current_customer_id)
        cust_id, name, company, email = customer
        
        months_intervall = self.sb_months.value()
        due_date_obj = self.calculate_due_date(months_intervall)
        due_date_str = due_date_obj.strftime("%d.%m.%Y")
        
        sig_path = "temp_signature.png"
        self.pad.image.save(sig_path)

        # 1. PDF generieren mit berechnetem Datum
        pdf_path = f"Pruefbericht_{company.replace(' ', '_')}.pdf"
        PDFGenerator.create_pdf(pdf_path, customer, self.main_app.exam_results, sig_path, due_date_str, months_intervall)

        # 2. ZIP Archivieren & E-Mail versenden (reicht das Fälligkeitsdatum an den Mail-Inhalt weiter)
        mgr = ArchiveManager()
        zip_path, success_mail = mgr.generate_archive_and_email(customer, pdf_path, sig_path, due_date_str)
        
        # 3. In lokaler Datenbank protokollieren
        self.main_app.db.add_protocol(self.main_app.current_customer_id, zip_path, due_date_str)

        # Bereinigung temporärer Dateien
        if os.path.exists(sig_path): os.remove(sig_path)
        if os.path.exists(pdf_path): os.remove(pdf_path)

        msg = f"Prüfung erfolgreich archiviert unter:\n{zip_path}\n\n"
        msg += "E-Mail wurde versendet." if success_mail else "E-Mail-Versand übersprungen (SMTP-Daten prüfen)."
        QMessageBox.information(self, "Erfolg", msg)

        self.pad.clear()
        self.sb_months.setValue(12)
        self.main_app.show_customer_screen()
