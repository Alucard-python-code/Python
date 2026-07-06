# RC-Modellflugzeug Tankstation (Raspberry Pi Pico)

Dieses Projekt implementiert eine intelligente, modulare Jet- und Modellbau-Tankstation auf Basis eines Raspberry Pi Pico. Die Software überwacht den Füllvorgang über Druck- und Durchflusssensoren, schützt Festtanks vor Überdruck und steuert Beuteltanks über automatisierte Entlüftungszyklen.

---

## 🛠️ Hardware-Komponenten

*   **Controller:** Raspberry Pi Pico (oder Pico W)
*   **Anzeige:** LCD-Display (über I2C / HD44780 oder kompatibel)
*   **Bedienelement:** Drehgeber (Rotary Encoder) mit integriertem Taster
*   **Sensorik:** 
    *   0-5 PSI Drucksensor (linearer Analogausgang an ADC0)
    *   Durchflusssensor (Impulsausgang mit Pull-Up)
*   **Aktuatorik:** PWM-Kreiselpumpe / Regler (ESC mit Standard-Servosignal)
*   **Zustandsanzeige:** Programmierbarer RGB-LED-Streifen (WS2812B / NeoPixel)

---

## 📂 Dateistruktur

Das Programm ist modular in fünf Funktionseinheiten unterteilt:

1.  `main.py` – Hauptprogramm, Startbildschirm und Hauptmenü-Schleife.
2.  `config.py` – Datenstrukturen für Modellspeicher und permanente JSON-Sicherung auf dem Flash-Speicher.
3.  `hardware.py` – Abstraktionsschicht und Pin-Konfiguration für Sensoren und Pumpensteuerung.
4.  `modes.py` – Ablaufsteuerungen für den manuellen und den automatischen Tankbetrieb.
5.  `menus.py` – Menüstrukturen für Einstellungen, PIN-Sicherheit und Kalibrierungs-Dialoge.

---

## 💻 Installations-Anleitung (Schritt für Schritt)

### 1. Vorbereitung auf dem PC
1. Stellen Sie sicher, dass **VS Code** auf Ihrem Computer installiert ist.
2. Installieren Sie die Erweiterung **MicroPico** (ehemals Pico-W-Go) oder **Thonny IDE** in VS Code,
   um mit dem Raspberry Pi Pico zu kommunizieren.
3. Laden Sie die aktuelle **MicroPython-Firmware**
   (.uf2-Datei) von [micropython.org](https://micropython.org) herunter.

### 2. Raspberry Pi Pico flashen
1. Halten Sie die **BOOTSEL-Taste** auf dem Pico gedrückt.
2. Verbinden Sie den Pico per USB-Kabel mit dem PC. Der Pico erscheint nun als Laufwerk namens `RPI-RP2`.
3. Ziehen Sie die heruntergeladene `.uf2`-Firmware-Datei per Drag-and-Drop auf das Laufwerk. Der Pico startet automatisch neu und ist nun bereit für MicroPython.

### 3. Projekt in VS Code einrichten
1. Erstellen Sie einen neuen, leeren Ordner auf Ihrem PC für das Projekt (z.B. `Jet-Tankstation`).
2. Erstellen Sie in diesem Ordner die fünf Programmdateien:
   *   `config.py`
   *   `hardware.py`
   *   `modes.py`
   *   `menus.py`
   *   `main.py`
3. Kopieren Sie den jeweiligen Quellcode in die entsprechenden Dateien.

### 4. Dateien auf den Pico hochladen
1. Öffnen Sie den Projektordner in VS Code.
2. Verbinden Sie den Pico mit dem USB-Kabel.
3. Nutzen Sie die VS Code MicroPico-Erweiterung (unten in der Statusleiste auf **Connect** klicken).
4. Wählen Sie per Rechtsklick auf den Projektordner oder über die Befehlspalette
    (`Strg+Umschalt+P` / `Cmd+Umschalt+P`) den Befehl: **MicroPico: Upload project to Pico**.
5. Nach erfolgreichem Upload startet das Programm automatisch. 
    Über das Terminal in VS Code können Sie die Ausgaben sehen und das System per Tastatur
    (`w`, `s`, `e`) testweise steuern.

---

## 📍 Pin-Belegung (Standardkonfiguration)

Die Pins können in der Datei `hardware.py` jederzeit angepasst werden:

| Komponente | Pico-Pin | Beschreibung |
| :--- | :--- | :--- |
| **Drehgeber CLK** | GP2 | Impuls-Eingang A |
| **Drehgeber DT** | GP3 | Impuls-Eingang B |
| **Drehgeber SW** | GP4 | Taster-Eingang (Klick) |
| **Durchflusssensor** | GP5 | Pulssignal (Eingang mit internem Pull-Up) |
| **Pumpen-Regler (ESC)**| GP6 | RC-PWM Ausgang (50 Hz, 1ms - 2ms Signal) |
| **Drucksensor** | GP26 | ADC0 Analogeingang (0V bis 3.3V für 0-5 PSI) |

---

## 🔐 Standard-Sicherheitsdaten

Sollte die PIN-Abfrage bei der Inbetriebnahme aktiv sein, gelten folgende Standardwerte:
*   **Standard-PIN:** `1234`
*   **Standard-PUK:** `87654321`

*Hinweis: Nach dreimaliger Falscheingabe der PIN sperrt sich das System temporär und
fordert zwingend die Eingabe des PUKs an.*
