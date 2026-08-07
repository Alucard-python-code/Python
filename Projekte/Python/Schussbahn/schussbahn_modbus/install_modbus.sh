#!/bin/bash

# Abbrechen bei Fehlern
set -e

echo "======================================================"
echo "   Gesamt-Installation & Kiosk & Desktop-Icon & Lüfter"
echo "======================================================"
echo ""

# 1. Konfigurations-Abfragen
read -p "Bitte die IP-Adresse des Waveshare-Moduls eingeben: " IN_HOST
HOST=${IN_HOST:-192.168.8.203}

read -p "Bitte den Modbus-Port des Waveshare-Moduls eingeben: " IN_PORT
PORT=${IN_PORT:-502}

read -p "Bitte den IPC-Port für die GUI-Kommunikation eingeben: " IN_IPC_PORT
IPC_PORT=${IN_IPC_PORT:-65432}

USER_NAME=$(whoami)
TARGET_DIR="/home/$USER_NAME/Alucard_Python/Projekte/Python/Schussbahn/schussbahn_modbus"

echo ""
echo "-> Wechsle in Zielverzeichnis: $TARGET_DIR"
cd "$TARGET_DIR"

# 2. System-Pakete installieren
echo "-> Installiere System-Abhängigkeiten (Python3 venv, Qt5 & GPIO)..."
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip python3-pyqt5 python3-gpiozero python3-lgpio

# 3. Virtuelle Umgebung für die App einrichten
echo "-> Erstelle virtuelle Python-Umgebung..."
python3 -m venv --system-site-packages venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install pymodbus

# 4. Modbus-Backend mit den abgefragten Werten generieren
echo "-> Konfiguriere Modbus-Backend..."
cat << EOF > modbus_backend.py
import socket
import json
import threading
import time
from pymodbus.client import ModbusTcpClient
from pymodbus.transaction import ModbusRtuFramer

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
            client = ModbusTcpClient(HOST, port=PORT, framer=ModbusRtuFramer)
            if not client.connect():
                time.sleep(5)
                continue

            heartbeat_state = False
            last_heartbeat_time = 0

            while True:
                current_time = time.time()
                if current_time - last_heartbeat_time >= 0.5:
                    heartbeat_state = not heartbeat_state
                    client.write_coil(address=4, value=heartbeat_state, slave=SLAVE_ID)
                    last_heartbeat_time = current_time

                with data_lock:
                    current_relays = list(relay_write_list)

                for i in range(4):
                    client.write_coil(address=i, value=current_relays[i], slave=SLAVE_ID)

                rr = client.read_discrete_inputs(address=0, count=8, slave=SLAVE_ID)
                if not rr.isError():
                    with data_lock:
                        results_list = rr.bits[:8]
                
                time.sleep(0.1)
        except Exception:
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
    while True:
        conn, _ = server.accept()
        threading.Thread(target=handle_client, args=(conn,), daemon=True).start()

if __name__ == "__main__":
    threading.Thread(target=modbus_worker, daemon=True).start()
    start_ipc_server()
EOF

# 5. Systemd Linux-Dienst für das Modbus-Backend einrichten
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


# 6. KIOSK-AUTOSTART FÜR DEN PI 5 (labwc compositor / Wayland)
echo "-> Konfiguriere Labwc-Kiosk-Modus für den Desktop-Autostart..."
LABWC_DIR="/home/$USER_NAME/.config/labwc"
mkdir -p "$LABWC_DIR"

if [ -f "$LABWC_DIR/autostart" ]; then
    sed -i '/Schussbahn.py/d' "$LABWC_DIR/autostart"
fi

cat << EOF >> "$LABWC_DIR/autostart"
# Automatisch generierter Kiosk-Start für Schussbahn GUI
$TARGET_DIR/venv/bin/python $TARGET_DIR/Schussbahn.py
EOF


# 7. DESKTOP ICON (VERKNÜPFUNG) ERSTELLEN
echo "-> Erstelle Desktop-Verknüpfung..."
DESKTOP_DIR="/home/$USER_NAME/Desktop"
mkdir -p "$DESKTOP_DIR"

ICON_PATH=$(find "$TARGET_DIR" -type f \( -name "*zielscheibe*" -o -name "*icon*" \) \( -name "*.png" -o -name "*.ico" -o -name "*.jpg" \) | head -n 1)

if [ -z "$ICON_PATH" ]; then
    ICON_PATH="mark-location"
fi

cat << EOF > "$DESKTOP_DIR/Schussbahn.desktop"
[Desktop Entry]
Type=Application
Name=Schussbahn-App
Comment=Startet die Schussbahn Qt5 GUI
Exec=$TARGET_DIR/venv/bin/python $TARGET_DIR/Schussbahn.py
Icon=$ICON_PATH
Terminal=false
Categories=Utility;Development;
Path=$TARGET_DIR
EOF

chmod +x "$DESKTOP_DIR/Schussbahn.desktop"


# 8. PWM-LÜFTERSTEUERUNG INTEGRIEREN
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
echo " 1. Modbus-IP wurde auf $HOST:$IN_PORT gesetzt."
echo " 2. Der Modbus-Hintergrunddienst läuft stabil."
echo " 3. Der Kiosk-Autostart für labwc (Wayland) ist aktiv."
echo " 4. Desktop-Icon wurde mit Grafik '$ICON_PATH' erstellt."
echo " 5. PWM-Lüftersteuerung an GPIO 18 wurde eingerichtet."
echo "======================================================"
echo ""

# 9. AUTO-REBOOT ABFRAGE
read -p "Soll der Raspberry Pi jetzt automatisch neu gestartet werden? [J/n]: " IN_REBOOT
REBOOT=${IN_REBOOT:-J}

if [[ "$REBOOT" =~ ^[JjYy] ]]; then
    echo "-> System wird in 3 Sekunden neu gestartet..."
    sleep 3
    sudo reboot
else
    echo "-> Installation beendet. Bitte starte den Pi später manuell neu (sudo reboot)."
fi
