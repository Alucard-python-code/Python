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

USER_NAME=$(whoami)
TARGET_DIR="/home/$USER_NAME"
cd "$TARGET_DIR"

# 2. Abhängigkeiten installieren
echo "-> Installiere System-Abhängigkeiten (Python3 venv, Qt5, GPIO & Git)..."
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip python3-pyqt5 python3-gpiozero python3-lgpio git curl

echo "-> Deaktiviere automatische OS-Hintergrund-Updates permanent..."
sudo apt-get remove -y unattended-upgrades || true
sudo systemctl stop apt-daily.timer apt-daily-upgrade.timer || true
sudo systemctl disable apt-daily.timer apt-daily-upgrade.timer || true

# 3. Projektdaten aus dem aktuellen Unterordner von GitHub laden
echo "-> Lade Projektdaten von GitHub..."
rm -rf /tmp/schussbahn_repo
git clone -b main "https://github.com/Alucard-python-code/Python.git" /tmp/schussbahn_repo

# Kopiert die Daten aus dem neuen schussbahn_modbus_2 Ordner
if [ -d "/tmp/schussbahn_repo/Projekte/Python/Schussbahn/schussbahn_modbus_2" ]; then
    cp -r /tmp/schussbahn_repo/Projekte/Python/Schussbahn/schussbahn_modbus_2/* "$TARGET_DIR/"
else
    echo "[FEHLER] Ordner schussbahn_modbus_2 wurde im Repository nicht gefunden!"
    exit 1
fi
rm -rf /tmp/schussbahn_repo

# 4. Virtuelle Umgebung einrichten und Pymodbus installieren
echo "-> Erstelle virtuelle Python-Umgebung (venv)..."
python3 -m venv --system-site-packages venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install pymodbus

# Alte Rückstände des nicht mehr benötigten Modbus-Backend-Services entfernen
if systemctl is-enabled modbus_backend.service >/dev/null 2>&1; then
    sudo systemctl stop modbus_backend.service || true
    sudo systemctl disable modbus_backend.service || true
    sudo rm -f /etc/systemd/system/modbus_backend.service
    sudo systemctl daemon-reload
fi

# ======================================================
# TEIL 2: INITIALE HARDWARE-CONFIG & AUTOSTART
# ======================================================

# 5. Generiere die initiale config.json direkt mit den eingegebenen IP-Werten
echo "-> Erstelle initiale config.json..."
cat << EOF > config.json
{
    "ip": "$HOST",
    "port": $PORT,
    "pin": "1234",
    "b_schnell": 3.0,
    "b_langsam": 2.0,
    "a_schnell": 4.0,
    "wd_homing": 15.0,
    "wd_beschuss": 10.0,
    "wd_auswertung": 20.0
}
EOF

# 6. Desktop-Autostart einrichten
echo "-> Richte XDG-Desktop-Autostart für das Hauptprogramm ein..."
AUTOSTART_DIR="/home/$USER_NAME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"

LABWC_DIR="/home/$USER_NAME/.config/labwc"
if [ -f "$LABWC_DIR/autostart" ]; then sed -i '/main.py/d' "$LABWC_DIR/autostart"; fi

# Bildsuche für das Icon auf der Oberfläche
ICON_PATH=$(find "$TARGET_DIR" -maxdepth 2 -name "*zielscheibe*" -o -name "*icon*" | head -n 1)
if [ -z "$ICON_PATH" ]; then ICON_PATH="mark-location"; fi

# Startbefehl lädt das Hauptprogramm direkt über die Python-Venv
START_COMMAND="$TARGET_DIR/venv/bin/python $TARGET_DIR/main.py"

cat << EOF > "$AUTOSTART_DIR/Schussbahn.desktop"
[Desktop Entry]
Type=Application
Name=Schussbahn-App
Comment=Startet die Schussbahn GUI beim Booten
Exec=$START_COMMAND
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
Comment=Startet die Schussbahn GUI manuell
Exec=$START_COMMAND
Icon=$ICON_PATH
Terminal=false
Path=$TARGET_DIR
EOF
chmod +x "$DESKTOP_DIR/Schussbahn.desktop"

# 7. Lüftersteuerung integrieren
echo "-> Richte PWM-Lüftersteuerung ein..."
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
echo "====================================================="
echo " SETUP ERFOLGREICH ABGESCHLOSSEN!"
echo " Das Programm startet beim nächsten Reboot automatisch."
echo "====================================================="
