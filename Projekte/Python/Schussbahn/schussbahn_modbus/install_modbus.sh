#!/bin/bash

# Abbrechen bei Fehlern
set -e

echo "======================================================"
echo "   Waveshare Modbus-Dienst Installation für Raspberry Pi"
echo "======================================================"
echo ""

# 1. Benutzerabfragen für die Konfiguration
read -p "Bitte die IP-Adresse des Waveshare-Moduls eingeben: " IN_HOST
HOST=${IN_HOST:-192.168.1.200}

read -p "Bitte den Modbus-Port des Waveshare-Moduls eingeben: " IN_PORT
PORT=${IN_PORT:-502}

read -p "Bitte den IPC-Port für deine anderen Programme eingeben: " IN_IPC_PORT
IPC_PORT=${IN_IPC_PORT:-65432}

# Aktuellen Benutzer und Home-Verzeichnis ermitteln
USER_NAME=$(whoami)
TARGET_DIR="/home/$USER_NAME/waveshare_modbus"

echo ""
echo "-> Erstelle Verzeichnis: $TARGET_DIR"
mkdir -p "$TARGET_DIR"
cd "$TARGET_DIR"

# 2. System-Pakete aktualisieren und venv installieren
echo "-> Installiere benötigte System-Pakete (python3-venv)..."
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip

# 3. Virtuelle Umgebung einrichten und pymodbus installieren
echo "-> Erstelle virtuelle Python-Umgebung..."
python3 -m venv venv
echo "-> Installiere pymodbus..."
./venv/bin/pip install --upgrade pip
./venv/bin/pip install pymodbus

# 4. Python-Skript generieren
echo "-> Generiere Python-Skript (modbus_backend.py)..."
cat << EOF > modbus_backend.py
import socket
import json
import threading
import time
from pymodbus.client import ModbusTcpClient
from pymodbus.transaction import ModbusRtuFramer

# --- Konfiguration Waveshare (Automatisch generiert) ---
HOST = "$HOST"
PORT = $PORT
SLAVE_ID = 1

# --- Konfiguration IPC-Server ---
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
                print(f"[Modbus] Verbindung zu {HOST} fehlgeschlagen. Erneuter Versuch in 5s...")
                time.sleep(5)
                continue

            print(f"[Modbus] Erfolgreich mit Waveshare ({HOST}:{PORT}) verbunden.")
            heartbeat_state = False
            last_heartbeat_time = 0

            while True:
                current_time = time.time()

                # 1. Heartbeat Relais 5 (0,5 Sek Intervall)
                if current_time - last_heartbeat_time >= 0.5:
                    heartbeat_state = not heartbeat_state
                    client.write_coil(address=4, value=heartbeat_state, slave=SLAVE_ID)
                    last_heartbeat_time = current_time

                # 2. Relais 1-4 schalten
                with data_lock:
                    current_relays = list(relay_write_list)

                for i in range(4):
                    client.write_coil(address=i, value=current_relays[i], slave=SLAVE_ID)

                # 3. Die 8 Eingänge lesen
                rr = client.read_discrete_inputs(address=0, count=8, slave=SLAVE_ID)
                if not rr.isError():
                    with data_lock:
                        results_list = rr.bits[:8]
                
                time.sleep(0.1)
        except Exception as e:
            print(f"[Modbus] Fehler im Loop: {e}. Reconnect in 2s...")
            time.sleep(2)
        finally:
            try:
                client.close()
            except:
                pass

def handle_client(conn):
    global relay_write_list, results_list
    try:
        data = conn.recv(1024).decode('utf-8')
        if not data:
            return
        
        request = json.loads(data)
        
        with data_lock:
            if "set_relays" in request:
                relay_write_list = request["set_relays"][:4]
            response = {"inputs": results_list}
            
        conn.sendall(json.dumps(response).encode('utf-8'))
    except Exception:
        pass
    finally:
        conn.close()

def start_ipc_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((IPC_HOST, IPC_PORT))
    server.listen()
    print(f"[IPC-Server] Aktiv auf Port {IPC_PORT} für andere Programme...")

    while True:
        conn, _ = server.accept()
        threading.Thread(target=handle_client, args=(conn,), daemon=True).start()

if __name__ == "__main__":
    threading.Thread(target=modbus_worker, daemon=True).start()
    start_ipc_server()
EOF

# 5. Systemd Service-Datei generieren und aktivieren
echo "-> Erstelle systemd Hintergrund-Dienst..."
SERVICE_FILE="/etc/systemd/system/modbus_backend.service"

sudo bash -c "cat << EOF > $SERVICE_FILE
[Unit]
Description=Waveshare Modbus TCP RTU Background Service
After=network.target

[Service]
ExecStart=$TARGET_DIR/venv/bin/python $TARGET_DIR/modbus_backend.py
WorkingDirectory=$TARGET_DIR
StandardOutput=inherit
StandardError=inherit
Restart=always
RestartSec=5
User=$USER_NAME

[Install]
WantedBy=multi-user.target
EOF"

echo "-> Aktiviere und starte den Dienst..."
sudo systemctl daemon-reload
sudo systemctl enable modbus_backend.service
sudo systemctl restart modbus_backend.service

echo ""
echo "======================================================"
echo " Fertig! Der Dienst läuft nun sauber im Hintergrund."
echo " Er startet bei jedem Boot-Vorgang automatisch."
echo " Modbus IP: $HOST:$PORT"
echo " IPC-Schnittstelle Port: $IPC_PORT"
echo "======================================================"
echo "Status abfragen mit: sudo systemctl status modbus_backend.service"
