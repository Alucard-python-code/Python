# Einrichtung: Etikettendrucker SUPVAN T50M Pro

Der T50M Pro spricht **Bluetooth Classic (SPP/RFCOMM)**, nicht Bluetooth LE.
Gedruckt wird über CUPS mit dem Open-Source-Treiber **supvan-cups**:
https://github.com/heeen/supvan-cups (MIT-Lizenz). Der Autor gibt an, den T50M Pro
per Bluetooth damit getestet zu haben.

## 1. Drucker koppeln (einmalig)

```bash
bluetoothctl
```
In der bluetoothctl-Konsole (Drucker einschalten):
```
scan on
pair <MAC-ADRESSE>
trust <MAC-ADRESSE>
scan off
quit
```
Die MAC-Adresse erscheint beim Scannen. Der Name enthält meist "T50" oder "SUPVAN".

## 2. Treiber installieren

Bauen und installieren nach der Anleitung im README von supvan-cups (Rust-Projekt).
Danach eine Druckerwarteschlange mit dem Namen **SUPVAN_T50M** anlegen, oder einen anderen
Namen in `PRINTER_CUPS_QUEUE` eintragen.

Testdruck mit einem von der App erzeugten Etikett (liegt in `data/labels/`):
```bash
lp -d SUPVAN_T50M -o media=Custom.40x30mm -o print-scaling=none data/labels/<datei>.png
```

## 3. App konfigurieren (z.B. in der systemd-Unit)

```
PRINTER_BACKEND=cups
PRINTER_CUPS_QUEUE=SUPVAN_T50M
PRINTER_BT_ADDRESS=<MAC-ADRESSE>     # für die Statusanzeige (Etiketten leer, Deckel offen)
PRINTER_RFCOMM_CHANNEL=1
```

## Am echten Gerät zu prüfen

* **Statusanzeige:** Das Byte-Layout stammt aus `docs/PROTOCOL.md` von supvan-cups und ist
  laut Quelle selbst nicht vollständig verifiziert (Prüfsummenbereich, RFCOMM-Kanal).
  Zeigt die Statusleiste dauerhaft "Antwort unverständlich" oder "Nicht erreichbar",
  obwohl der Druck über CUPS funktioniert, bitte melden. Der Druck ist davon unabhängig.
* **Medienname:** Falls CUPS `media=Custom.40x30mm` ablehnt, mit
  `lpoptions -p SUPVAN_T50M -l` die unterstützten Größen anzeigen lassen.
* **Python mit Bluetooth-Sockets:** Das Python von Raspberry Pi OS unterstützt
  `socket.AF_BLUETOOTH`. Prüfen mit
  `python3 -c "import socket; print(socket.AF_BLUETOOTH)"`.
