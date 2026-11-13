# HART-Feldcommunicator & Kalibrier-Assistent (CM4)

Mobiler HART-Communicator mit 5-Punkt-Kalibrierung, True-mA-Messung, Auftragsverwaltung,
Prüfprotokoll-PDF, QR-Etikettendruck und Grafana-Telemetrie.
Läuft auf Raspberry Pi CM4 (Pi OS Bookworm 64-Bit, Wayland/labwc) und im Simulationsmodus
auf jedem Entwicklungs-PC.

## Schnellstart (Entwicklungs-PC, ohne Hardware)

```bash
pip install -r requirements.txt
python hart_modem.py                 # Simuliertes Rosemount 3051 identifizieren
python hart_modem.py fisher_dvc6200  # anderes Szenario
python battery_bms.py                # 8S-BMS-Simulation inkl. Fehlerfall
pytest -q                            # Tests der Kernmodule
```

## Architektur

```
┌──────────────────────── Chromium Kiosk (Wayland) ─────────────────────────┐
│  templates/ + static/  ·  responsives 4-Wege-Layout  ·  Statusleiste       │
└──────────────▲──────────────────────── Socket.IO (Live) / REST ───────────┘
               │
┌──────────────┴──────────────────── app.py (Flask + Flask-SocketIO) ───────┐
│  Workflow-Engine: Auftrag → Identifikation → Fall A/B/C → Kalibrierung    │
│  ServiceRegistry: startet alle Dienste, verteilt Events an die UI          │
└─┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────┘
  │          │          │          │          │          │          │
hart_modem  battery_  rtc_      feedback_  rotation_  input_    camera_qr
+device_    bms       manager   manager    daemon     monitor   label_printer
 catalog    (BQ76930) (DS3231)  (DRV2605L  (LIS3DH +  (evdev,   (picamera2,
(AD5700)    +Power-             +I2S)      wlr-randr) GPIO16)   bleak BLE)
  │          Latch                                                 │
  └── database.py (hart_kalibrierung.db) ── pdf_generator.py ──────┘
      telemetry_logger.py (telemetry_logs.db, WAL) ── dual_usb_export.py
                     │
            hw_compat.py  (GPIO/I2C-Abstraktion, Simulations-Fallback, I2C-Lock)
            config.py     (Pins, Adressen, Grenzwerte, Theme)
```

| Modul | Aufgabe | Status |
|---|---|---|
| `config.py` | zentrale Konfiguration, per ENV überschreibbar | ✅ |
| `hw_compat.py` | GPIO-/I2C-Fabriken mit Mock-Fallback, gemeinsamer I2C-Lock | ✅ |
| `hart_modem.py` | HART-Stack, AD5700-Transport, Safe-Mode, Sniffer, Simulator | ✅ |
| `device_catalog.py` | Klartext-Geräteerkennung, Feld-Lernfunktion | ✅ |
| `battery_bms.py` | BQ76930, SOC LiFePO4, Alarme, Soft-Power | ✅ |
| `current_meter.py` | INA226 True-mA, Übersteuerungserkennung, Prüfmittel-Kalibrierung, Stabilitätserkennung | ✅ |
| `loop_relays.py` | G6K-Relais: Passiv / Passiv+250 Ω / Aktiv 24 V mit Verriegelungen | ✅ |
| `rtc_manager.py` | DS3231 (Kernel- oder I2C-Backend), Zeitquellen-Nachweis NTP/RTC/UNGEPRÜFT | ✅ |
| `feedback_manager.py` | DRV2605L-Haptik + synthetisierte Signaltöne (MAX98357A), Ereignis-Prioritäten | ✅ |
| `rotation_daemon.py`, `input_monitor.py` | LIS3DH/wlr-randr, Maus/Tastatur/Touch-Lock | Schritt 3 |
| `camera_qr.py`, `label_printer.py` | Kamera + PWM-Licht, SUPVAN T50M Pro | Schritt 4 |
| `database.py`, `telemetry_logger.py` | Auftrags-DB, Grafana-DB | Schritt 5 |
| `pdf_generator.py`, `dual_usb_export.py` | Auftrags-PDF, USB-Stick/Gadget-Export | Schritt 6 |
| `app.py`, `templates/`, `static/` | Web-UI, Workflow, Statusleiste | Schritt 7 |

### Threading-Modell
* **HART**: ein `RLock` serialisiert alle Bustransaktionen (Kalibrierung, Live-Werte, Sniffer).
* **I2C1**: ein gemeinsamer `RLock` in `hw_compat.I2CBus` – BQ76930, INA226, LIS3DH, DS3231 und
  DRV2605L teilen sich den Bus aus verschiedenen Threads.
* **Dienste** (BMS, Rotation, Input, Telemetrie) laufen als Daemon-Threads und melden über
  `subscribe()`-Callbacks an `app.py`, das per Socket.IO an die UI weiterreicht.

### Sicherheitskonzept
* **24/7-Safe-Mode** ist beim Start immer aktiv. Whitelist-Prinzip: im Safe-Mode verlassen nur
  die Lesekommandos aus `READ_ONLY_COMMANDS` das Modem. Alle anderen Kommandos, auch unbekannte
  gerätespezifische, werden *vor* dem Senden blockiert und im Sniffer als `BLOCK` protokolliert.
* Der Communicator ist **Secondary Master** und wartet vor jedem Senden, bis der Bus frei ist
  (OCD), damit ein Leitsystem (Primary Master) bzw. Burst-Geräte nicht gestört werden.
* **Schleifenrelais** sind im Ruhezustand stromlos = passiv, keine 24-V-Ausgabe.
* Nach Command 40 (Festwert/Sollwert) räumt der Kalibrierassistent immer mit
  `exit_fixed_current()` auf, auch nach Abbruch oder Fehler (`try/finally`).

## GPIO-Belegung (BCM)

| GPIO | Funktion | Richtung |
|---|---|---|
| 2/3 | I2C1 SDA/SCL (INA226 0x40, BQ76930 0x08, LIS3DH 0x18, DRV2605L 0x5A, DS3231 0x68) | – |
| 14/15 | UART0 TX/RX → AD5700 (1200 Baud 8E1) | – |
| 17 | AD5700 RTS (LOW = Senden) | Out |
| 27 | AD5700 OCD (HIGH = Träger) | In |
| 16 | Touch-Lock-Schiebeschalter (LOW = gesperrt) | In |
| 13 | PWM1 LED-Ringlicht / Taschenlampe | PWM |
| 18/19/21 | I2S → MAX98357A | – |
| 23 | DOCK_DETECT (CH224K PG) | In |
| 24 | BQ76930 ALERT | In |
| 25 | Soft-Power-Selbsthaltung | Out (Overlay) |
| 26 | reserviert (optionaler HW-Safe-Mode, `PIN_SAFE_MODE_HW=26`) | In |
| 5 / 6 / 22 | **Vorschlag:** Relais 24 V aktiv / Source-Sink / 250 Ω | Out |

## `/boot/firmware/config.txt` (Auszug)

```ini
dtparam=i2c_arm=on
enable_uart=1
# PL011 (ttyAMA0) für das HART-Modem freigeben, Bluetooth läuft über den Mini-UART.
# Grund: der Mini-UART kann keine Parität, HART braucht 8E1.
dtoverlay=miniuart-bt
# Soft-Power: Kernel hält GPIO25 bis zum Ende des Shutdowns
dtoverlay=gpio-poweroff,gpiopin=25,active_low=1
dtoverlay=i2c-rtc,ds3231
dtoverlay=max98357a
dtoverlay=pwm,pin=13,func=4
# USB-OTG für g_mass_storage (CM4: USB2 ist sonst deaktiviert)
dtoverlay=dwc2,dr_mode=otg
```

> Mit `dtoverlay=i2c-rtc,ds3231` übernimmt der Kernel die RTC (`/dev/rtc0`, `hwclock`).
> `rtc_manager.py` nutzt dann `/dev/rtc0` und spricht 0x68 nur im Fallback direkt an.

## Wichtige Hardware-Hinweise

* **INA226-Shunt:** Der Messbereich am Shunt endet bei ±81,92 mV. Mit den spezifizierten **10 Ω ist
  nur bis 8,19 mA messbar**. Bitte **3,3 Ω / 0,1 % / ≤ 25 ppm/K** bestücken (24 mA → 79,2 mV,
  Auflösung 0,76 µA) und `INA226_SHUNT_OHM=3.3` setzen. Der Treiber meldet Übersteuerung
  (`OverrangeError`, Anzeige „ÜBERSTEUERT“), statt falsche Werte zu liefern.
* **Relaisspulen** (G6K-2F-Y 3 V ≈ 33 mA) über Transistor + Freilaufdiode treiben, nicht direkt am GPIO.
* **24-V-Schleifenspeisung** hardwareseitig auf ~25 mA strombegrenzen.
* **Stellungsregler** sind stromgeführt: Für den Werkbank-Betrieb ohne Leitsystem braucht es eine
  mA-Stromquelle (z.B. AD5420/AD5421). Diese ist bisher nicht in der Stückliste.
  `ACTIVE_24V` ist für Stellungsregler deshalb gesperrt.
* **sudo-Rechte** für Uhrzeit und Poweroff: `deploy/sudoers.d-hart-communicator`.

## Simulation
`HART_SIM=auto` (Standard) simuliert alles, sobald kein Raspberry Pi erkannt wird.
Pro Komponente lässt sich das übersteuern, z.B. `HART_SIM=0 HART_SIM_BMS=1` (echtes Modem, simulierter Akku).
Der HART-Simulator bietet die Szenarien aus `hart_modem.SIM_SCENARIOS`, darunter einen Gerätetausch
(gleicher TAG, neue Unique-ID) und einen Micro-Motion-Transmitter mit absichtlichem Analogfehler,
um die Digital/Analog-Warnung zu testen.
