# settings_dialog.py

from PyQt5.QtWidgets import QDialog, QFormLayout, QLineEdit, QPushButton
from config import save_stored_config

class SettingsDialog(QDialog):
    """Einstellungsfenster für IP, Port, Fahrtzeiten und Watchdogs."""
    def __init__(self, parent, config):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Einstellungen")
        self.setFixedSize(380, 380)  # Höhe leicht erhöht für die neuen Felder
        self.setStyleSheet("background-color: #1e1e1e; color: #ffffff;")
        
        layout = QFormLayout(self)

        self.bahn_titel_edit = QLineEdit(self.config.get('bahn_titel', 'Bahn 1'))
        self.ip_edit = QLineEdit(self.config['ip'])
        self.port_edit = QLineEdit(str(self.config['port']))
        self.b_schnell_edit = QLineEdit(str(self.config['b_schnell']))
        self.b_langsam_edit = QLineEdit(str(self.config['b_langsam']))
        self.a_schnell_edit = QLineEdit(str(self.config['a_schnell']))
        self.wd_homing_edit = QLineEdit(str(self.config['wd_homing']))
        self.wd_beschuss_edit = QLineEdit(str(self.config['wd_beschuss']))
        self.wd_auswertung_edit = QLineEdit(str(self.config['wd_auswertung']))

        # Einheitliches Styling für Eingabefelder
        input_style = "background-color: #2d2d2d; border: 1px solid #555; padding: 4px; color: white;"
        for edit in [self.bahn_titel_edit, self.ip_edit, self.port_edit, self.b_schnell_edit, self.b_langsam_edit, 
                     self.a_schnell_edit, self.wd_homing_edit, self.wd_beschuss_edit, self.wd_auswertung_edit]:
            edit.setStyleSheet(input_style)

        layout.addRow("Bahn-Titel:", self.bahn_titel_edit)
        layout.addRow("Modbus IP:", self.ip_edit)
        layout.addRow("Modbus Port:", self.port_edit)
        layout.addRow("Beschuss Schnell (s):", self.b_schnell_edit)
        layout.addRow("Beschuss Langsam (s):", self.b_langsam_edit)
        layout.addRow("Auswertung Schnell (s):", self.a_schnell_edit)
        layout.addRow("Watchdog Homing (s):", self.wd_homing_edit)
        layout.addRow("Watchdog Beschuss (s):", self.wd_beschuss_edit)
        layout.addRow("Watchdog Auswertung (s):", self.wd_auswertung_edit)

        self.save_btn = QPushButton("Speichern")
        self.save_btn.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; padding: 8px;")
        self.save_btn.clicked.connect(self.save)
        layout.addRow(self.save_btn)

    def save(self):
        try:
            self.config['bahn_titel'] = self.bahn_titel_edit.text()
            self.config['ip'] = self.ip_edit.text()
            self.config['port'] = int(self.port_edit.text())
            self.config['b_schnell'] = float(self.b_schnell_edit.text())
            self.config['b_langsam'] = float(self.b_langsam_edit.text())
            self.config['a_schnell'] = float(self.a_schnell_edit.text())
            self.config['wd_homing'] = float(self.wd_homing_edit.text())
            self.config['wd_beschuss'] = float(self.wd_beschuss_edit.text())
            self.config['wd_auswertung'] = float(self.wd_auswertung_edit.text())
            
            save_stored_config(self.config)
            self.accept()
        except ValueError:
            pass  # Fehlerhafte Eingaben werden ignoriert
