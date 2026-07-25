#!/bin/bash

# ====================================================================
# MASTER-INSTALLATIONSSKRIPT (Vollständig)
# ====================================================================

# HIER DEINE GEWÜNSCHTE AUFLÖSUNG EINTRAGEN (Beispiel: 85 für 1280x720)
HDMI_MODE=85 

# 1. Root-Check
if [ "$EUID" -ne 0 ]; then
    echo "[INFO] Skript benötigt Root-Rechte. Starte neu mit sudo..."
    exec sudo bash "$0" "$@"
fi

# 2. Auflösung konfigurieren
echo "[INFO] Konfiguriere System-Auflösung..."
sudo sed -i '/hdmi_group/d' /boot/config.txt
sudo sed -i '/hdmi_mode/d' /boot/config.txt
sudo sed -i '/hdmi_force_hotplug/d' /boot/config.txt
echo "hdmi_force_hotplug=1" | sudo tee -a /boot/config.txt
echo "hdmi_group=2" | sudo tee -a /boot/config.txt
echo "hdmi_mode=$HDMI_MODE" | sudo tee -a /boot/config.txt

# 3. Internet-Check
if ! ping -c 1 8.8.8.8 &> /dev/null; then
    echo "[FEHLER] Keine Internetverbindung gefunden!"
    exit 1
fi

# 4. System Update & Cleanup
echo "[INFO] Aktualisiere System..."
apt-get update -y && apt-get upgrade -y -q
apt-get autoremove -y && apt-get autoclean -y

# 5. Auswahlmenü
echo "=========================================================="
echo " SCHUSSBAHN-INSTALLATION WENKHEIM"
echo "=========================================================="
echo "1) Schussbahn Modbus (inkl. Lüfter & Netzwerk-Check)"
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

# 6. Backup der alten Installation
if [ -d "$INSTALL_PATH" ]; then
    BACKUP_NAME="${INSTALL_PATH}_backup_$(date +%Y%m%d_%H%M)"
    echo "[INFO] Erstelle Backup: $BACKUP_NAME"
    mv "$INSTALL_PATH" "$BACKUP_NAME"
fi

# 7. Installation der App
mkdir -p "$INSTALL_PATH"
cp -r "$SOURCE_DIR/"* "$INSTALL_PATH/"
echo "Version: 1.0 (Stand: $(date))" > "$INSTALL_PATH/version.txt"

# 8. Abhängigkeiten
apt-get install -y python3-pip python3-pyqt5 fonts-noto-color-emoji python3-gpiozero python3-lgpio

# 9. Modbus spezifisch: Lüfter-Steuerung
if [ "$variante" == "1" ]; then
    pip3 install pyModbusTCP --break-system-packages 2>/dev/null
    
    # Lüfter-Skript erstellen
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
    
    # Dienst erstellen
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

# 10. Desktop-Verknüpfung & Autostart (mit Logging)
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

mkdir -p "/home/$USER/.config/autostart"
cat <<EOF > "/home/$USER/.config/autostart/schussbahn_autostart.desktop"
[Desktop Entry]
Type=Application
Exec=bash -c 'python3 $INSTALL_PATH/Schussbahn.py > /home/$USER/Desktop/schussbahn.log 2>&1'
X-GNOME-Autostart-enabled=true
Name=Schussbahn Autostart
EOF

echo "[ERFOLG] Installation abgeschlossen!"
echo "[INFO] Logs finden sich unter ~/Desktop/schussbahn.log"
echo "[INFO] Neustart in 5 Sekunden..."
sleep 5
reboot