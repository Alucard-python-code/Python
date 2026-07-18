#!/bin/bash

# ====================================================================
# MASTER-INSTALLATIONSSKRIPT (Update, Upgrade & Clean)
# ====================================================================

# 1. Root-Check
if [ "$EUID" -ne 0 ]; then 
  echo "[INFO] Skript benötigt Root-Rechte..."
  exec sudo bash "$0" "$@"
fi

# 2. Internet-Check
if ! ping -c 1 8.8.8.8 &> /dev/null; then
    echo "[FEHLER] Keine Internetverbindung!"
    exit 1
fi

# 3. System auf den neuesten Stand bringen
echo "[INFO] Aktualisiere das System (Update & Upgrade)..."
apt-get update -y
apt-get upgrade -y
echo "[INFO] Entferne nicht mehr benötigte Pakete..."
apt-get autoremove -y
apt-get autoclean -y

# 4. Auswahlmenü
echo "=========================================================="
echo " SCHUSSBAHN-INSTALLATION WENKHEIM"
echo "=========================================================="
echo "1) Schussbahn Modbus (inkl. Lüfter)"
echo "2) Schussbahn GPIO (Direkt)"
read -p "Auswahl (1 oder 2): " variante

if [ "$variante" == "1" ]; then
    SOURCE_DIR="schussbahn_modbus"
    VARIANT_NAME="Modbus"
elif [ "$variante" == "2" ]; then
    SOURCE_DIR="schussbahn_gpio"
    VARIANT_NAME="GPIO"
else
    echo "[FEHLER] Ungültige Auswahl."
    exit 1
fi

APP_NAME="Schussbahn_app"
INSTALL_PATH="/home/$USER/Desktop/$APP_NAME"

# 5. Neuinstallations-Check
if [ -d "$INSTALL_PATH" ]; then
    read -p "[ACHTUNG] Installation existiert bereits. Überschreiben? (j/n): " confirm
    [[ $confirm == [jJ] ]] && rm -rf "$INSTALL_PATH" || exit 0
fi

# 6. Kopieren
mkdir -p "$INSTALL_PATH"
cp -r "$SOURCE_DIR/"* "$INSTALL_PATH/"

# 7. Abhängigkeiten
echo "[INFO] Installiere benötigte Bibliotheken..."
apt-get install -y python3-pip python3-pyqt5 fonts-noto-color-emoji python3-gpiozero python3-lgpio

# 8. Modbus-Logik & Lüfter (falls gewählt)
if [ "$variante" == "1" ]; then
    pip3 install pyModbusTCP --break-system-packages 2>/dev/null
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
    cat << 'SERVICE_EOF' > /etc/systemd/system/case_fan.service
[Unit]
Description=PWM Luefter
[Service]
ExecStart=/usr/bin/python3 /usr/local/bin/case_fan_control.py
Restart=always
[Install]
WantedBy=multi-user.target
SERVICE_EOF
    systemctl enable case_fan.service && systemctl restart case_fan.service
fi

# 9. Abschluss (Verknüpfungen)
chmod +x "$INSTALL_PATH/Schussbahn.py"
DESKTOP_FILE="/home/$USER/Desktop/Schussbahn.desktop"

cat <<EOF > "$DESKTOP_FILE"
[Desktop Entry]
Name=Schussbahn Steuerung ($VARIANT_NAME)
Exec=python3 $INSTALL_PATH/Schussbahn.py
Icon=target
Terminal=false
Type=Application
Categories=Development;
EOF

chmod +x "$DESKTOP_FILE"
gio set "$DESKTOP_FILE" metadata::trusted true 2>/dev/null

mkdir -p "/home/$USER/.config/autostart"
cat <<EOF > "/home/$USER/.config/autostart/schussbahn_autostart.desktop"
[Desktop Entry]
Type=Application
Exec=python3 $INSTALL_PATH/Schussbahn.py
X-GNOME-Autostart-enabled=true
Name=Schussbahn Autostart
EOF

echo "[ERFOLG] Alles fertig! Neustart in 5 Sekunden..."
sleep 5
reboot