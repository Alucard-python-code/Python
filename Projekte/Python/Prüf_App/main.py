import sys
import os
import zipfile

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QLabel, QLineEdit, QCheckBox, QPushButton, 
                             QFileDialog, QScrollArea, QFormLayout, QComboBox)

# Importe der Module aus den anderen beiden Abschnitten
from signature import SignaturePad
from pdf_generator import generate_anlage_pdf

class PruefApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Profi-Prüfprotokoll (Mehrfach-Anlagen)")
        self.resize(550, 800)
        
        self.gepruefte_anlagen = []
        self.aktuelle_fotos = []

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.setCentralWidget(scroll)

        main_widget = QWidget()
        scroll.setWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        # 1. KUNDEN-STAMMDATEN
        layout.addWidget(QLabel("<h2>1. Kunden-Stammdaten</h2>"))
        form_layout = QFormLayout()
        self.txt_betreiber = QLineEdit()
        self.txt_standort = QLineEdit()
        form_layout.addRow("Kunde / Betreiber:", self.txt_betreiber)
        form_layout.addRow("Standort / Werk:", self.txt_standort)
        layout.addLayout(form_layout)
        
        layout.addWidget(QLabel("<hr>"))

        # 2. ANLAGE PRÜFEN
        layout.addWidget(QLabel("<h2>2. Anlage prüfen</h2>"))
        form_anlage = QFormLayout()
        self.cb_typ = QComboBox()
        self.cb_typ.addItems(["Schrankenanlage", "Sektionaltor", "Rolltor", "Schiebetor", "Hubtor"])
        self.txt_bezeichnung = QLineEdit()
        self.txt_bezeichnung.setPlaceholderText("z.B. Haupteinfahrt, Halle 3 links")
        self.txt_hersteller = QLineEdit()
        
        form_anlage.addRow("Anlagentyp:", self.cb_typ)
        form_anlage.addRow("Eigene Bezeichnung / ID:", self.txt_bezeichnung)
        form_anlage.addRow("Hersteller / Modell:", self.txt_hersteller)
        layout.addLayout(form_anlage)

        self.chk_antrieb = QCheckBox("Antrieb & Mechanik fehlerfrei (i.O.)")
        self.chk_notaus = QCheckBox("Notentriegelung & Sicherheitssysteme (i.O.)")
        self.chk_allgemein = QCheckBox("Gehäuse, Bauteile & Beschilderung (i.O.)")
        layout.addWidget(self.chk_antrieb)
        layout.addWidget(self.chk_notaus)
        layout.addWidget(self.chk_allgemein)

        btn_photo = QPushButton("Fotos für DIESE Anlage hinzufügen")
        btn_photo.clicked.connect(self.add_photo)
        self.lbl_photo_count = QLabel("Keine Fotos für diese Anlage")
        layout.addWidget(btn_photo)
        layout.addWidget(self.lbl_photo_count)

        layout.addSpacing(10)
        btn_save_anlage = QPushButton("Anlage zum Kundenprotokoll hinzufügen")
        btn_save_anlage.setStyleSheet("background-color: #3498db; color: white; font-weight: bold; padding: 6px;")
        btn_save_anlage.clicked.connect(self.save_current_anlage)
        layout.addWidget(btn_save_anlage)
        
        self.lbl_gesamtzahl = QLabel("<b>Bereits erfasst: 0 Anlagen für diesen Kunden</b>")
        self.lbl_gesamtzahl.setStyleSheet("color: #2980b9;")
        layout.addWidget(self.lbl_gesamtzahl)

        layout.addWidget(QLabel("<hr>"))

        # 3. ABSCHLUSS
        layout.addWidget(QLabel("<h2>3. Einsatz abschließen (Gesamtkunde)</h2>"))
        self.sig_pad = SignaturePad()
        layout.addWidget(self.sig_pad)
        
        btn_clear_sig = QPushButton("Unterschrift lolschen")
        btn_clear_sig.clicked.connect(self.sig_pad.clear_canvas)
        layout.addWidget(btn_clear_sig)

        layout.addSpacing(15)
        btn_submit = QPushButton("GESAMTEN EINSATZ ABSCHLIESSEN & ZIP GENERIEREN")
        btn_submit.setStyleSheet("background-color: #2ecc71; font-weight: bold; color: white; padding: 12px; font-size: 14px;")
        btn_submit.clicked.connect(self.final_process)
        layout.addWidget(btn_submit)

    def add_photo(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Fotos für aktuelle Anlage wählen", "", "Bilder (*.png *.jpg *.jpeg)")
        if files:
            self.aktuelle_fotos.extend(files)
            self.lbl_photo_count.setText(f"{len(self.aktuelle_fotos)} Foto(s) bereit")

    def save_current_anlage(self):
        if not self.txt_bezeichnung.text().strip():
            self.txt_bezeichnung.setText(f"Anlage {len(self.gepruefte_anlagen) + 1}")
            
        anlagen_daten = {
            "typ": self.cb_typ.currentText(),
            "bezeichnung": self.txt_bezeichnung.text(),
            "hersteller": self.txt_hersteller.text(),
            "antrieb_io": self.chk_antrieb.isChecked(),
            "notaus_io": self.chk_notaus.isChecked(),
            "allgemein_io": self.chk_allgemein.isChecked(),
            "fotos": list(self.aktuelle_fotos)
        }
        
        self.gepruefte_anlagen.append(anlagen_daten)
        
        self.txt_bezeichnung.clear()
        self.txt_hersteller.clear()
        self.chk_antrieb.setChecked(False)
        self.chk_notaus.setChecked(False)
        self.chk_allgemein.setChecked(False)
        self.aktuelle_fotos.clear()
        self.lbl_photo_count.setText("Keine Fotos für diese Anlage")
        self.lbl_gesamtzahl.setText(f"<b>Bereits erfasst: {len(self.gepruefte_anlagen)} Anlage(n)</b>")

    def final_process(self):
        if self.txt_bezeichnung.text().strip() or self.chk_antrieb.isChecked():
            self.save_current_anlage()
            
        if not self.gepruefte_anlagen:
            return

        sig_path = "temp_signature.png"
        self.sig_pad.save_signature(sig_path)
        
        kunde_clean = self.txt_betreiber.text().replace(' ', '_') if self.txt_betreiber.text() else "Unbekannter_Kunde"
        zip_path = f"Pruefarchiv_{kunde_clean}.zip"
        erzeugte_pdfs = []
        
        for idx, anlage in enumerate(self.gepruefte_anlagen):
            pdf_name = f"Pruefbericht_{idx+1}_{anlage['bezeichnung'].replace(' ', '_')}.pdf"
            erzeugte_pdfs.append(pdf_name)
            generate_anlage_pdf(pdf_name, self.txt_betreiber.text(), self.txt_standort.text(), anlage, sig_path)
        
        with zipfile.ZipFile(zip_path, 'w') as archive:
            for pdf in erzeugte_pdfs:
                archive.write(pdf)
                os.remove(pdf)
                
            for a_idx, anlage in enumerate(self.gepruefte_anlagen):
                for f_idx, img_path in enumerate(anlage['fotos']):
                    archive.write(img_path, f"Anlage_{a_idx+1}_Foto_{f_idx+1}.jpg")
                    
        if os.path.exists(sig_path):
            os.remove(sig_path)
                    
        print(f"\n--- Archiv gespeichert: {zip_path} ---\n")
        
        self.gepruefte_anlagen.clear()
        self.txt_betreiber.clear()
        self.txt_standort.clear()
        self.sig_pad.clear_canvas()
        self.lbl_gesamtzahl.setText("<b>Bereits erfasst: 0 Anlagen</b>")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PruefApp()
    window.show()
    sys.exit(app.exec())
