#!/bin/bash

# ====================================================================
# MASTER-INSTALLATIONSSKRIPT (GitHub & Minimal-Download)
# ====================================================================

# HIER DEINE GITHUB-DATEN EINTRAGEN
GITHUB_REPO_URL="https://github.com/Alucard-python-code/Python.git"
GITHUB_BRANCH="main" # oder "master"

# HIER DEINE GEWÜNSCHTE AUFLÖSUNG EINTRAGEN
HDMI_MODE=85 

# 1. Root-Check & Ermittlung des echten Benutzers
if [ "$EUID" -ne 0 ]; then
    echo "[INFO] Skript benötigt Root-Rechte. Starte neu mit sudo..."
    exec sudo bash "$0" "$@"
fi

if [ -n "$SUDO_USER" ]; then
    REAL_USER="$SUDO_USER"
else
    REAL_USER="pi"
fi

REAL_HOME="/home/$REAL_USER"

# 2. Auflösung konfigurieren
echo "[INFO] Konfiguriere System-Auflösung..."
sed -i '/hdmi_group/d' /boot/config.txt
sed -i '/hdmi_mode/d' /boot/config.txt
sed -i '/hdmi_force_hotplug/d' /boot/config.txt
echo "hdmi_force_hotplug=1" >> /boot/config.txt
echo "hdmi_group=2" >> /boot/config.txt
echo "hdmi_mode=$HDMI_MODE" >> /boot/config.txt

# 3. Internet-Check
if ! ping -c 1 8.8.8.8 &> /dev/null; then
    echo "[FEHLER] Keine Internetverbindung gefunden!"
    exit 1
fi

# 4. System Update & Basis-Pakete (inkl. Git)
echo "[INFO] Aktualisiere System und installiere Git..."
apt-get update -y && apt-get upgrade -y -q
apt-get install -y git
apt-get autoremove -y && apt-get autoclean -y

# 5. Auswahlmenü für die App-Variante
echo "=========================================================="
echo "         SCHUSSBAHN-INSTALLATION WENKHEIM                 "
echo "=========================================================="
echo "1) Schussbahn Modbus App starten"
echo "2) Schussbahn GPIO App starten"
read -p "Auswahl (1 oder 2): " variante

if [ "$variante" == "1" ]; then
    TARGET_SUBFOLDER="schussbahn_modbus"
    VARIANT_NAME="Modbus"
elif [ "$variante" == "2" ]; then
    TARGET_SUBFOLDER="schussbahn_gpio"
    VARIANT_NAME="GPIO"
else
    echo "[FEHLER] Ungültige Auswahl."
    exit 1
fi

APP_NAME="Schussbahn_app"
INSTALL_PATH="$REAL_HOME/Desktop/$APP_NAME"

# 6. Backup der alten Installation falls vorhanden
if [ -d "$INSTALL_PATH" ]; then
    BACKUP_NAME="${INSTALL_PATH}_backup_$(date +%Y%m%d_%H%M)"
    echo "[INFO] Erstelle Backup der alten App: $BACKUP_NAME"
    mv "$INSTALL_PATH" "$BACKUP_NAME"
fi

# 7. Minimaler GitHub-Download via Sparse-Checkout
echo "[INFO] Starte minimalen Download von GitHub..."
TEMP_CLONE_DIR="/tmp/schussbahn_git_clone"
rm -rf "$TEMP_CLONE_DIR"
mkdir -p "$TEMP_CLONE_DIR"
cd "$TEMP_CLONE_DIR"

# Git initialisieren und auf den Zielordner beschränken
git init -q
git remote add origin "$GITHUB_REPO_URL"
git config core.sparseCheckout true

# Nur den ausgewählten Unterordner für den Download definieren
echo "$TARGET_SUBFOLDER/" >> .git/info/sparse-checkout

# Nur diesen spezifischen Ordner vom Server abrufen
echo "[INFO] Downloade ausschließlich Ordner: $TARGET_SUBFOLDER..."
if ! git pull origin "$GITHUB_BRANCH" --depth=1; then
    echo "[FEHLER] Download von GitHub fehlgeschlagen! Überprüfe URL und Branch-Namen."
    exit 1
fi

# Dateien an den finalen Zielort verschieben und aufräumen
mkdir -p "$INSTALL_PATH"
if [ -d "$TARGET_SUBFOLDER" ]; then
    cp -r "$TARGET_SUBFOLDER/"* "$INSTALL_PATH/"
    echo "[INFO] App-Dateien erfolgreich extrahiert."
else
    echo "[FEHLER] Der erwartete Ordner $TARGET_SUBFOLDER existiert nicht im Repository!"
    exit 1
fi

# Temporären Download-Müll sofort restlos löschen
cd /
rm -rf "$TEMP_CLONE_DIR"

# Version schreiben und Rechte an den Pi-User übergeben
echo "Version: 1.0 (GitHub Stand: $(date))" > "$INSTALL_PATH/version.txt"
chown -R "$REAL_USER":"$REAL_USER" "$INSTALL_PATH"

# 8. Abhängigkeiten installieren (Immer aktiv)
echo "[INFO] Installiere APT-Abhängigkeiten (GPIO & GUI)..."
apt-get install -y python3-pip python3-pyqt5 fonts-noto-color-emoji python3-gpiozero python3-lgpio

echo "[INFO] Installiere Python-Modbus-Bibliothek..."
pip3 install pyModbusTCP --break-system-packages 2>/dev/null
sudo -u "$REAL_USER" pip3 install pyModbusTCP --break-system-packages 2>/dev/null

# 9. Lüftersteuerung einrichten (Immer aktiv)
echo "[INFO] Richte PWM-Lüftersteuerung ein..."
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

systemctl daemon-reload
systemctl enable case_fan.service && systemctl restart case_fan.service

# 10. Desktop-Verknüpfung & Autostart (mit korrekter User-Rechte-Zuweisung)
DESKTOP_FILE="$REAL_HOME/Desktop/Schussbahn.desktop"
cat <<EOF > "$DESKTOP_FILE"
[Desktop Entry]
Name=Schussbahn Steuerung ($VARIANT_NAME)
Exec=bash -c 'python3 $INSTALL_PATH/Schussbahn.py > $REAL_HOME/Desktop/schussbahn.log 2>&1'
Icon=target
Terminal=false
Type=Application
EOF

chmod +x "$DESKTOP_FILE"
chown "$REAL_USER":"$REAL_USER" "$DESKTOP_FILE"

# Desktop-Icon als vertrauenswürdig markieren (Behebt Blockierung auf dem Pi)
sudo -u "$REAL_USER" DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u $REAL_USER)/bus gio set "$DESKTOP_FILE" metadata::trusted true 2>/dev/null

# Autostart einrichten
mkdir -p "$REAL_HOME/.config/autostart"
AUTOSTART_FILE="$REAL_HOME/.config/autostart/schussbahn_autostart.desktop"
cat <<EOF > "$AUTOSTART_FILE"
[Desktop Entry]
Type=Application
Exec=bash -c 'python3 $INSTALL_PATH/Schussbahn.py > $REAL_HOME/Desktop/schussbahn.log 2>&1'
X-GNOME-Autostart-enabled=true
Name=Schussbahn Autostart
EOF

chown -R "$REAL_USER":"$REAL_USER" "$REAL_HOME/.config/autostart"

echo "[ERFOLG] Installation abgeschlossen!"
echo "[INFO] Übrig geblieben ist nur: $INSTALL_PATH"
echo "[INFO] Logs finden sich unter $REAL_HOME/Desktop/schussbahn.log"
echo "[INFO] Neustart in 5 Sekunden..."
sleep 5
reboot
