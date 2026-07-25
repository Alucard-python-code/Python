# RC Jet-Tankstation

Software für eine Kerosin-Tankstation mit einem Raspberry Pi Pico.

---

## 📂 Dateistruktur

Das Programm ist modular in sechs Dateien aufgeteilt:

1. `main.py` – Hauptprogramm und Menüschleife.
2. `config.py` – Datenspeicher und JSON-Sicherung.
3. `hardware.py` – Pin-Zuweisung und I2C-LCD.
4. `modes.py` – Manueller und automatischer Betrieb.
5. `menus.py` – Einstellungen und PIN-Logik.
6. `lcd_api.py` – Treiber für Freenove LCD.

---

## 💻 Installation (Schritt für Schritt)

### Schritt 1: VS Code vorbereiten
1. Starten Sie VS Code auf Ihrem Computer.
2. Installieren Sie die Erweiterung **MicroPico**.

### Schritt 2: Pico flashen
1. Halten Sie die BOOTSEL-Taste auf dem Pico gedrückt.
2. Verbinden Sie den Pico per USB mit dem PC.
3. Laden Sie die MicroPython-Firmware (.uf2) von micropython.org herunter.
4. Ziehen Sie die Datei auf das Pico-Laufwerk.

### Schritt 3: Dateien übertragen
1. Erstellen Sie einen Projektordner in VS Code.
2. Legen Sie alle sechs Programmdateien dort an.
3. Kopieren Sie den Quellcode in die Dateien.
4. Klicken Sie in der Statusleiste auf **Connect**.
5. Wählen Sie den Befehl: **MicroPico: Upload project to Pico**.

---

## 📍 Verkabelung am Pico

| Gerät | Pin | GPIO | Funktion |
| :--- | :--- | :--- | :--- |
| **LCD** | VCC | VBUS | 5V Stromversorgung |
| **LCD** | GND | GND | Masse |
| **LCD** | SDA | GP0 | I2C Datenleitung |
| **LCD** | SCL | GP1 | I2C Taktleitung |
| **Encoder** | CLK | GP2 | Phase A |
| **Encoder** | DT | GP3 | Phase B |
| **Encoder** | SW | GP4 | Taster |
| **Sensor** | OUT | GP5 | Durchfluss Puls |
| **Regler** | PWM | GP6 | Pumpen-Signal (RC) |
| **Druck** | OUT | GP26 | Analog-Eingang (ADC0) |

*Hinweis: LCD-VCC muss an 5V VBUS für vollen Kontrast.*

---

## 🛠️ Inbetriebnahme & Kalibrierung

Justieren Sie bei Bedarf das Poti auf der LCD-Rückseite.

### 1. Druck Nullabgleich
* Wählen Sie `Einstellungen` -> `Druck Nullabgleich`.
* Der Sensor muss komplett frei von Schläuchen sein.
* Starten Sie den Abgleich für den Umgebungsdruck.

### 2. Durchfluss kalibrieren
* Wählen Sie `Einstellungen` -> `Durchfluss kalb.`.
* Messen Sie exakt 1.000 ml Flüssigkeit ab.
* Starten Sie die Pumpe per Knopfdruck.
* Stoppen Sie exakt bei 1.000 ml Menge.
* Die Pulse werden automatisch berechnet und gesichert.

---

## 🔐 Sicherheit & PIN

* Standard-PIN ist **1234**.
* Standard-PUK ist **87654321**.
* Nach drei Falscheingaben sperrt sich das System.
* Die Entsperrung erfordert zwingend den Master-PUK.
