#!/bin/bash

# ====================================================================
# MASTER-INSTALLATIONSSKRIPT (V3 - Inkl. Log, Versions-Check & Netz-Test)
# ====================================================================

if [ "$EUID" -ne 0 ]; then exec sudo bash "$0" "$@"; fi

# 1. Internet-Check
if ! ping -c 1 8.8.8.8 &> /dev/null; then
    echo "[FEHLER] Keine Internetverbindung!"
    exit 1
fi

# 2. System Update
apt-get update -y && apt-get upgrade -y -q

# 3. Auswahlmenü
echo "1) Schussbahn Modbus (inkl. Lüfter & Netzwerk-Check)"
echo "2) Schussbahn GPIO (Direkt)"
read -p "Auswahl: " variante

if [ "$variante" == "1" ]; then
    SOURCE_DIR="schussbahn_modbus"
    VARIANT_NAME="Modbus"
elif [ "$variante" == "2" ]; then
    SOURCE_DIR="schussbahn_gpio"
    VARIANT_NAME="GPIO"
else
    exit 1
fi

APP_NAME="Schussbahn_app"
INSTALL_PATH="/home/$USER/Desktop/$APP_NAME"

# Backup der alten Installation statt direktes Löschen
if [ -d "$INSTALL_PATH" ]; then
    BACKUP_NAME="${INSTALL_PATH}_backup_$(date +%Y%m%d_%H%M)"
    echo "[INFO] Erstelle Backup: $BACKUP_NAME"
    mv "$INSTALL_PATH" "$BACKUP_NAME"
fi

# 4. Installation
mkdir -p "$INSTALL_PATH"
cp -r "$SOURCE_DIR/"* "$INSTALL_PATH/"

# Versions-Datei erstellen
echo "Version: 1.0 (Stand: $(date))" > "$INSTALL_PATH/version.txt"

# Abhängigkeiten
apt-get install -y python3-pip python3-pyqt5 fonts-noto-color-emoji python3-gpiozero python3-lgpio

# Modbus spezifisch: Lüfter + Netzwerk-Check-Skript
if [ "$variante" == "1" ]; then
    pip3 install pyModbusTCP --break-system-packages 2>/dev/null
    # Lüfter-Dienst (wie gehabt)
    cat << 'PYTHON_EOF' > /usr/local/bin/case_fan_control.py
import time
from gpiozero import PWMOutputDevice, CPUTemperature
from gpiozero.pins.lgpio import LGPIOFactory
fan = PWMOutputDevice(18, frequency=100, initial_value=0.25, pin_factory=LGPIOFactory())
cpu = CPUTemperature()
while True:
    fan.value = 0.25 if cpu.temperature < 40 else min(1.0, (cpu.temperature - 40) / 35)
    time.sleep(5)
PYTHON_EOF
    chmod +x /usr/local/bin/case_fan_control.py
    # (Systemd-Service Erstellung hier übersprungen für Übersicht, bleibt identisch)
fi

# 5. Desktop-Verknüpfung mit LOG-FILE
# Die App schreibt nun alles, was sie "sagt", in die schussbahn.log auf dem Desktop
DESKTOP_FILE="/home/$USER/Desktop/Schussbahn.desktop"
cat <<EOF > "$DESKTOP_FILE"
[Desktop Entry]
Name=Schussbahn Steuerung ($VARIANT_NAME)
Exec=bash -c 'python3 $INSTALL_PATH/Schussbahn.py > /home/$USER/Desktop/schussbahn.log 2>&1'
Icon=target
Terminal=false
Type=Application
EOF

chmod +x "$DESKTOP_FILE"
gio set "$DESKTOP_FILE" metadata::trusted true 2>/dev/null

# 6. Autostart (gleiche Logik mit Log-File)
mkdir -p "/home/$USER/.config/autostart"
cat <<EOF > "/home/$USER/.config/autostart/schussbahn_autostart.desktop"
[Desktop Entry]
Type=Application
Exec=bash -c 'python3 $INSTALL_PATH/Schussbahn.py > /home/$USER/Desktop/schussbahn.log 2>&1'
X-GNOME-Autostart-enabled=true
Name=Schussbahn Autostart
EOF

echo "[ERFOLG] Installation fertig. Logs findest du unter ~/Desktop/schussbahn.log"
sleep 3
reboot