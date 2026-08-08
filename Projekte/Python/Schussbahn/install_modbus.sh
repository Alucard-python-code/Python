#!/bin/bash

# Abbrechen bei Fehlern
set -e

echo "======================================================"
echo " Gesamt-Installation & Kiosk & Desktop-Icon & Lüfter"
echo "======================================================"
echo ""

# 1. Konfigurations-Abfragen
read -p "Bitte die IP-Adresse des Waveshare-Moduls eingeben: " IN_HOST
HOST=${IN_HOST:-192.168.8.250}

read -p "Bitte den Modbus-Port des Waveshare-Moduls eingeben: " IN_PORT
PORT=${IN_PORT:-502}

read -p "Bitte den IPC-Port für die GUI-Kommunikation eingeben: " IN_IPC_PORT
IPC_PORT=${IN_IPC_PORT:-65432}

USER_NAME=$(whoami)
TARGET_DIR="/home/$USER_NAME"

echo ""
echo "-> Wechsle in Zielverzeichnis: $TARGET_DIR"
cd "$TARGET_DIR"

# 2. System-Pakete installieren & automatische Updates sperren
echo "-> Installiere System-Abhängigkeiten (Python3 venv, Qt5, GPIO & Git)..."
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip python3-pyqt5 python3-gpiozero python3-lgpio git curl

echo "-> Deaktiviere automatische Hintergrund-Updates permanent..."
sudo apt-get remove -y unattended-upgrades || true
sudo systemctl stop apt-daily.timer apt-daily-upgrade.timer || true
sudo systemctl disable apt-daily.timer apt-daily-upgrade.timer || true

# 3. Projektdaten direkt aus dem Unterordner von GitHub herunterladen
echo "-> Lade Projektdaten von GitHub herunter..."
rm -rf /tmp/schussbahn_repo
git clone -b main "https://github.com/Alucard-python-code/Python.git" /tmp/schussbahn_repo

# Kopiert gezielt den Inhalt des Schussbahn-Ordners direkt ins User-Verzeichnis
if [ -d "/tmp/schussbahn_repo/Projekte/Python/Schussbahn" ]; then
    cp -r /tmp/schussbahn_repo/Projekte/Python/Schussbahn/* "$TARGET_DIR/"
else
    echo "[FEHLER] Der spezifische Projektordner wurde im Repository nicht gefunden!"
    exit 1
fi
rm -rf /tmp/schussbahn_repo

# 4. Virtuelle Umgebung für die App einrichten
echo "-> Erstelle virtuelle Python-Umgebung..."
python3 -m venv --system-site-packages venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install pymodbus

# 5. Modbus-Backend mit moderner PyModbus 3.14.0 Syntax generieren
echo "-> Konfiguriere Modbus RTU-over-TCP Backend (PyModbus v3.14.0)..."
cat << EOF > modbus_backend.py
import socket
import json
import threading
import time
import logging
from pymodbus.client import ModbusTcpClient

# Logging einrichten
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

HOST = "$HOST"
PORT = $PORT
SLAVE_ID = 1  # Entspricht der Geräte-ID (device_id) für das Waveshare Board
IPC_HOST = "127.0.0.1"
IPC_PORT = $IPC_PORT

data_lock = threading.Lock()
relay_write_list = [False, False, False, False]
results_list = [False] * 8

def modbus_worker():
    global relay_write_list, results_list
    
    while True:
        try:
            logging.info(f"Modbus: Verbinde per RTU-over-TCP auf {HOST}:{PORT}...")
            client = ModbusTcpClient(host=HOST, port=PORT, framer="rtu", timeout=2.0)
            
            if not client.connect():
                logging.warning("Verbindung zum Waveshare-Modul fehlgeschlagen. Reconnect in 5s...")
                time.sleep(5)
                continue
            
            logging.info("Erfolgreich mit Waveshare POE Modul (RTU-over-TCP) verbunden.")
            heartbeat_state = False
            last_heartbeat_time = 0
            
            while True:
                current_time = time.time()
                
                # Heartbeat-Taktung (Watchdog an Register/Coil 4)
                if current_time - last_heartbeat_time >= 0.5:
                    heartbeat_state = not heartbeat_state
                    client.write_coil(address=4, value=heartbeat_state, device_id=SLAVE_ID)
                    last_heartbeat_time = current_time
                
                # Relais-Schreibbefehle abarbeiten
                with data_lock:
                    current_relays = list(relay_write_list)
                
                client.write_coils(address=0, values=current_relays[:4], device_id=SLAVE_ID)
                
                # Digitale Eingänge einlesen
                rr = client.read_discrete_inputs(address=0, count=8, device_id=SLAVE_ID)
                
                if rr and not rr.isError():
                    with data_lock:
                        results_list = rr.bits[:8]
                else:
                    logging.warning(f"Modbus-Protokollfehler bei der Abfrage: {rr}")
                    raise Exception("Kommunikationsfehler zum Modul")
                
                time.sleep(0.1)
        except Exception as e:
            logging.error(f"Verbindungsfehler im Modbus-Worker: {e}")
            time.sleep(2)
        finally:
            try: client.close()
            except: pass

def handle_client(conn):
    global relay_write_list, results_list
    try:
        data = conn.recv(1024).decode('utf-8')
        if not data: return
        request = json.loads(data)
        with data_lock:
            if "set_relays" in request:
                relay_write_list = request["set_relays"][:4]
            response = {"inputs": results_list}
        conn.sendall(json.dumps(response).encode('utf-8'))
    except Exception as e:
        logging.error(f"Fehler bei IPC-Client-Verarbeitung: {e}")
    finally: conn.close()

def start_ipc_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((IPC_HOST, IPC_PORT))
    server.listen()
    logging.info(f"IPC-Server gestartet auf {IPC_HOST}:{IPC_PORT}")
    while True:
        conn, _ = server.accept()
        threading.Thread(target=handle_client, args=(conn,), daemon=True).start()

if __name__ == "__main__":
    logging.info("Starte Modbus Backend-Dienst...")
    threading.Thread(target=modbus_worker, daemon=True).start()
    start_ipc_server()
EOF

# 6. Systemd Linux-Dienst für das Modbus-Backend einrichten
echo "-> Erstelle systemd-Hintergrunddienst für Modbus..."
SERVICE_FILE="/etc/systemd/system/modbus_backend.service"

sudo bash -c "cat << EOF > $SERVICE_FILE
[Unit]
Description=Waveshare Modbus IPC Service
After=network.target

[Service]
ExecStart=$TARGET_DIR/venv/bin/python $TARGET_DIR/modbus_backend.py
WorkingDirectory=$TARGET_DIR
Restart=always
RestartSec=5
User=$USER_NAME

[Install]
WantedBy=multi-user.target
EOF"

echo "-> Starte Modbus-Hintergrunddienst..."
sudo systemctl daemon-reload
sudo systemctl enable modbus_backend.service
sudo systemctl restart modbus_backend.service

# 7. ZUVERLÄSSIGER XDG-AUTOSTARTORDNER (Für Wayland/Labwc auf dem Pi 5)
echo "-> Richte XDG-Desktop-Autostart ein..."
AUTOSTART_DIR="/home/$USER_NAME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"

# Alte unzuverlässige Labwc-Startdatei restlos bereinigen
LABWC_DIR="/home/$USER_NAME/.config/labwc"
if [ -f "$LABWC_DIR/autostart" ]; then
    sed -i '/Schussbahn.py/d' "$LABWC_DIR/autostart"
fi

# 8. ICON-PFAD PRÄZISE ERMITTELN
ICON_PATH=$(find "$TARGET_DIR" -maxdepth 3 -type f \( -name "*zielscheibe*" -o -name "*icon*" -o -name "*logo*" \) \( -name "*.png" -o -name "*.ico" -o -name "*.jpg" \) | head -n 1)

if [ -z "$ICON_PATH" ]; then
    ICON_PATH="mark-location"
fi

# Erstelle die XDG .desktop Datei für den Autostart
cat << EOF > "$AUTOSTART_DIR/Schussbahn.desktop"
[Desktop Entry]
Type=Application
Name=Schussbahn-App
Comment=Startet die Schussbahn Qt5 GUI
Exec=$TARGET_DIR/venv/bin/python $TARGET_DIR/Schussbahn.py
Icon=$ICON_PATH
Terminal=false
Categories=Utility;Development;
Path=$TARGET_DIR
X-GNOME-Autostart-enabled=true
EOF

chmod +x "$AUTOSTART_DIR/Schussbahn.desktop"

# Kopie direkt auf den Desktop legen
DESKTOP_DIR="/home/$USER_NAME/Desktop"
mkdir -p "$DESKTOP_DIR"
cp "$AUTOSTART_DIR/Schussbahn.desktop" "$DESKTOP_DIR/"
chmod +x "$DESKTOP_DIR/Schussbahn.desktop"

# 9. PWM-LÜFTERSTEUERUNG INTEGRIEREN
echo "[INFO] Richte PWM-Lüftersteuerung ein..."

sudo bash -c "cat << 'PYTHON_EOF' > /usr/local/bin/case_fan_control.py
import time
from gpiozero import PWMOutputDevice, CPUTemperature
from gpiozero.pins.lgpio import LGPIOFactory
fan = PWMOutputDevice(18, frequency=100, initial_value=0.25, pin_factory=LGPIOFactory())
cpu = CPUTemperature()
while True:
    fan.value = 0.45 if cpu.temperature < 40 else min(1.0, (cpu.temperature - 40) / 35)
    time.sleep(5)
PYTHON_EOF"

sudo chmod +x /usr/local/bin/case_fan_control.py

sudo bash -c "cat << 'SERVICE_EOF' > /etc/systemd/system/case_fan.service
[Unit]
Description=PWM Luefter
After=multi-user.target

[Service]
ExecStart=/usr/bin/python3 /usr/local/bin/case_fan_control.py
Restart=always

[Install]
WantedBy=multi-user.target
SERVICE_EOF"

echo "-> Aktiviere und starte den Lüfterdienst..."
sudo systemctl daemon-reload
sudo systemctl enable case_fan.service
sudo systemctl restart case_fan.service

echo ""
echo "======================================================"
echo " Installation erfolgreich abgeschlossen!"
echo "======================================================"
echo " 1. Modbus-IP wurde auf $HOST:$PORT gesetzt."
echo " 2. Der Modbus-Hintergrunddienst (RTU-over-TCP) läuft."
echo " 3. Der XDG-Desktop-Autostart (Wayland) wurde eingerichtet."
echo " 4. Desktop-Icon wurde mit Grafik '$ICON_PATH' erstellt."
echo " 5. PWM-Lüftersteuerung an GPIO 18 wurde eingerichtet."
echo " 6. Automatische OS-Updates wurden dauerhaft blockiert."
echo "======================================================"
echo ""

# 10. AUTO-REBOOT ABFRAGE
read -p "Soll der Raspberry Pi jetzt automatisch neu gestartet werden? [J/n]: " IN_REBOOT
REBOOT=${IN_REBOOT:-J}

if [[ "$REBOOT" =~ ^[JjYy] ]]; then
    echo "-> System wird in 3 Sekunden neu gestartet..."
    sleep 3
    sudo reboot
else
    echo "-> Installation beendet. Bitte starte den Pi später manuell neu (sudo reboot)."
fi
