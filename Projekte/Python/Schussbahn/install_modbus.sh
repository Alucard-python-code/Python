#!/bin/bash
# ======================================================
# TEIL 1: SYSTEM-SETUP & GITHUB DOWNLOAD
# ======================================================
set -e

# 1. Konfigurations-Abfragen
read -p "Bitte die IP-Adresse des Waveshare-Moduls eingeben: " IN_HOST
HOST=${IN_HOST:-192.168.8.250}
read -p "Bitte den Modbus-Port des Waveshare-Moduls eingeben: " IN_PORT
PORT=${IN_PORT:-502}
read -p "Bitte den IPC-Port für die GUI-Kommunikation eingeben: " IN_IPC_PORT
IPC_PORT=${IN_IPC_PORT:-65432}

USER_NAME=$(whoami)
TARGET_DIR="/home/$USER_NAME"
cd "$TARGET_DIR"

# 2. Abhängigkeiten installieren
echo "-> Installiere System-Abhängigkeiten (Python3 venv, Qt5, GPIO & Git)..."
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip python3-pyqt5 python3-gpiozero python3-lgpio git curl netcat-openbsd

echo "-> Deaktiviere automatische OS-Hintergrund-Updates permanent..."
sudo apt-get remove -y unattended-upgrades || true
sudo systemctl stop apt-daily.timer apt-daily-upgrade.timer || true
sudo systemctl disable apt-daily.timer apt-daily-upgrade.timer || true

# 3. Projektdaten aus dem Unterordner von GitHub laden
echo "-> Lade Projektdaten von GitHub..."
rm -rf /tmp/schussbahn_repo
git clone -b main "https://github.com/Alucard-python-code/Python.git" /tmp/schussbahn_repo

if [ -d "/tmp/schussbahn_repo/Projekte/Python/Schussbahn/schussbahn_modbus" ]; then
    cp -r /tmp/schussbahn_repo/Projekte/Python/Schussbahn/schussbahn_modbus/* "$TARGET_DIR/"
else
    echo "[FEHLER] Ordner schussbahn_modbus wurde im Repository nicht gefunden!"
    exit 1
fi
rm -rf /tmp/schussbahn_repo

# 4. Virtuelle Umgebung einrichten
echo "-> Erstelle virtuelle Python-Umgebung (venv)..."
python3 -m venv --system-site-packages venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install pymodbus
# ======================================================
# TEIL 2: MODBUS BACKEND, SERVICES & AUTOSTART
# ======================================================

# 5. Modbus-Backend mit PyModbus 3.14.0 Syntax generieren
echo "-> Generiere modbus_backend.py..."
cat << EOF > modbus_backend.py
import socket
import json
import threading
import time
import logging
from pymodbus.client import ModbusTcpClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

HOST = "$HOST"
PORT = $PORT
SLAVE_ID = 1
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
                logging.warning("Verbindung fehlgeschlagen. Reconnect in 5s...")
                time.sleep(5)
                continue
            logging.info("Erfolgreich mit Waveshare POE Modul verbunden.")
            heartbeat_state = False
            last_heartbeat_time = 0
            while True:
                current_time = time.time()
                if current_time - last_heartbeat_time >= 0.5:
                    heartbeat_state = not heartbeat_state
                    client.write_coil(address=7, value=heartbeat_state, device_id=SLAVE_ID)
                    last_heartbeat_time = current_time
                with data_lock:
                    current_relays = list(relay_write_list)
                client.write_coils(address=0, values=current_relays[:4], device_id=SLAVE_ID)
                rr = client.read_discrete_inputs(address=0, count=8, device_id=SLAVE_ID)
                if rr and not rr.isError():
                    with data_lock:
                        results_list = rr.bits[:8]
                else:
                    raise Exception("Fehlerhafte Antwort vom Modul")
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
    except Exception: pass
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

# 6. Systemd-Dienst einrichten
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

sudo systemctl daemon-reload
sudo systemctl enable modbus_backend.service
sudo systemctl restart modbus_backend.service

# 7. XDG-Autostart mit Netcat-Warteschleife einrichten
echo "-> Richte verzögerten XDG-Desktop-Autostart ein..."
AUTOSTART_DIR="/home/$USER_NAME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"

LABWC_DIR="/home/$USER_NAME/.config/labwc"
if [ -f "$LABWC_DIR/autostart" ]; then sed -i '/Schussbahn.py/d' "$LABWC_DIR/autostart"; fi

# Vereinfachte Bildsuche ohne problematische Klammern-Syntax
ICON_PATH=$(find "$TARGET_DIR" -maxdepth 2 -name "*zielscheibe*" -o -name "*icon*" | head -n 1)
if [ -z "$ICON_PATH" ]; then ICON_PATH="mark-location"; fi

WAIT_AND_START="bash -c 'until nc -z 127.0.0.1 $IPC_PORT; do sleep 2; done; exec $TARGET_DIR/venv/bin/python $TARGET_DIR/Schussbahn.py'"

cat << EOF > "$AUTOSTART_DIR/Schussbahn.desktop"
[Desktop Entry]
Type=Application
Name=Schussbahn-App
Comment=Startet die Schussbahn GUI verzoegert
Exec=$WAIT_AND_START
Icon=$ICON_PATH
Terminal=false
Path=$TARGET_DIR
X-GNOME-Autostart-enabled=true
EOF
chmod +x "$AUTOSTART_DIR/Schussbahn.desktop"

# Desktop-Icon für manuelles Klicken generieren
DESKTOP_DIR="/home/$USER_NAME/Desktop"
mkdir -p "$DESKTOP_DIR"
cat << EOF > "$DESKTOP_DIR/Schussbahn.desktop"
[Desktop Entry]
Type=Application
Name=Schussbahn-App
Comment=Startet die Schussbahn GUI direkt
Exec=$TARGET_DIR/venv/bin/python $TARGET_DIR/Schussbahn.py
Icon=$ICON_PATH
Terminal=false
Path=$TARGET_DIR
EOF
chmod +x "$DESKTOP_DIR/Schussbahn.desktop"

# 8. Lüftersteuerung integrieren
echo "-> Richte Lüftersteuerung ein..."
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

sudo systemctl daemon-reload
sudo systemctl enable case_fan.service
sudo systemctl restart case_fan.service

echo ""
echo "======================================================"
echo " Installation erfolgreich beendet!"
echo "======================================================"
echo ""
read -p "Soll der Raspberry Pi jetzt automatisch neu gestartet werden? [J/n]: " IN_REBOOT
REBOOT=${IN_REBOOT:-J}
if [[ "$REBOOT" =~ ^[JjYy] ]]; then sudo reboot; fi
