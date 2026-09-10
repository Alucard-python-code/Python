import sys
from PyQt5.QtWidgets import QApplication, QMessageBox, QInputDialog
from PyQt5.QtCore import Qt, QTimer

import database as db
from hart_modem import HARTModem
from gui import HARTGui

class AppController(HARTGui):
    def __init__(self):
        super().__init__()
        self.modem = HARTModem()
        self.current_sensor = None
        self.current_step_idx = 0
        self.live_pressure_value = 0.0

        # Signale und Slots verbinden (Buttons verknüpfen)
        self.btn_scan.clicked.connect(self.handle_scan)
        self.tag_list.itemClicked.connect(self.handle_sensor_selected)
        self.btn_action.clicked.connect(self.handle_action_triggered)
        self.btn_next.clicked.connect(self.handle_next_step)

        # UI Liste aktualisieren
        self.refresh_ui_list()

        # Timer für Live-Werte
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_live_display)
        self.timer.start(1000)

    def refresh_ui_list(self):
        self.tag_list.clear()
        self.tag_list.addItems(db.get_all_tags())

    def handle_sensor_selected(self, item):
        self.current_sensor = db.get_sensor_by_tag(item.text())
        if self.current_sensor:
            self.current_step_idx = 0
            meta_text = f"⚙️ <b>TAG:</b> {self.current_sensor['tag']} | <b>S/N:</b> {self.current_sensor['serial_number']} | <b>Bereich:</b> {self.current_sensor['min']} - {self.current_sensor['max']} {self.current_sensor['unit']}"
            self.meta_label.setText(meta_text)
            self.step_box.setVisible(True)
            self.update_step_ui()

    def update_live_display(self):
        if self.current_sensor:
            self.live_pressure_value = self.modem.read_live_pressure(
                self.current_sensor['hart_address'], self.current_sensor['min'], self.current_sensor['max']
            )
            self.live_display.setText(f"{self.live_pressure_value} {self.current_sensor['unit']}")

    def handle_scan(self):
        self.meta_label.setText("⏳ Frage Sensor-Hardware ab...")
        QApplication.processEvents()

        specs = self.modem.scan_sensor_hardware()
        if not specs:
            QMessageBox.critical(self, "Fehler", "Kein Sensor am HART-Bus gefunden!")
            return

        user_tag, ok = QInputDialog.getText(self, 'Sensor-Zuweisung', f"Sensor erkannt!\nModell: {specs['model']}\nS/N: {specs['serial']}\n\nBitte TAG-Namen eingeben:")
        if ok and user_tag:
            user_tag = user_tag.strip().upper()
            existing_serial = db.check_tag_existence(user_tag)
            
            should_save = True
            info_msg = f"✅ TAG '{user_tag}' erfolgreich neu angelegt!"

            if existing_serial:
                if existing_serial != specs['serial']:
                    info_msg = f"⚠️ <b>Gerätetausch erkannt!</b><br>TAG '{user_tag}' wurde mit neuer S/N {specs['serial']} überschrieben."
                else:
                    reply = QMessageBox.question(self, 'Existiert bereits', "Eintrag mit dieser S/N überschreiben?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                    if reply == QMessageBox.No: should_save = False
                    else: info_msg = f"🔄 Specs für TAG '{user_tag}' aktualisiert."

            if should_save:
                default_steps = [
                    "Anlage absperren und komplett drucklos machen.",
                    f"0.0 {specs['unit']} stabilisieren lassen. Dann 'Nullpunkt Trimm' drücken.",
                    f"Prüfdruck auf exakt {specs['max']} {specs['unit']} aufprägen. Dann 'Endwert Trimm' drücken.",
                    "Druck ablassen und Kalibrierung im SQL-Logarchiv sichern."
                ]
                db.save_or_replace_sensor(user_tag, specs['serial'], specs['model'], 0, specs['min'], specs['max'], specs['unit'], 0.05, default_steps)
                self.refresh_ui_list()
                self.meta_label.setText(info_msg)
                
                items = self.tag_list.findItems(user_tag, Qt.MatchExactly)
                if items: self.tag_list.setCurrentItem(items[0]); self.handle_sensor_selected(items[0])

    def update_step_ui(self):
        steps = self.current_sensor['steps']
        total_steps = len(steps)
        self.step_title.setText(f"SCHRITT {self.current_step_idx + 1} VON {total_steps}")
        self.step_text.setText(steps[self.current_step_idx])
        
        if self.current_step_idx == 1:
            self.btn_action.setText("Universal-Zero Trim"); self.btn_action.setEnabled(True)
        elif self.current_step_idx == 2:
            self.btn_action.setText("Universal-Span Trim"); self.btn_action.setEnabled(True)
        elif self.current_step_idx == total_steps - 1:
            self.btn_action.setText("💾 In SQL protokollieren"); self.btn_action.setEnabled(True)
        else:
            self.btn_action.setText("Bitte Anweisung befolgen..."); self.btn_action.setEnabled(False)
        self.btn_next.setText("Abschließen" if self.current_step_idx == total_steps - 1 else "Weiter ►")

    def handle_next_step(self):
        if self.current_sensor:
            if self.current_step_idx < len(self.current_sensor['steps']) - 1:
                self.current_step_idx += 1
                self.update_step_ui()
            else:
                self.step_box.setVisible(False)
                self.meta_label.setText("Kalibrierung erfolgreich beendet.")
                self.live_display.setText("--- bar")

    def handle_action_triggered(self):
        total_steps = len(self.current_sensor['steps'])
        if self.current_step_idx == total_steps - 1:
            ts = db.log_calibration(self.current_sensor['tag'], self.current_sensor['serial_number'], "ERFOLGREICH", self.live_pressure_value, self.current_sensor['unit'])
            self.step_text.setText(f"✅ <b>Erfolgreich im SQL-Verlauf protokolliert!</b>\n\nZeit: {ts}\nTAG: {self.current_sensor['tag']}")
            self.btn_action.setEnabled(False)
            return

        action_type = "zero" if self.current_step_idx == 1 else "span"
        if self.modem.send_trim_command(self.current_sensor['hart_address'], action_type):
            self.step_text.append(f"\n\n<i>[HART] Sende Trim-Befehl ({action_type})... OK</i>")

if __name__ == '__main__':
    db.init_database()
    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_SynthesizeMouseForUnhandledTouchEvents, True)
    ex = AppController()
    ex.show()
    sys.exit(app.exec_())
