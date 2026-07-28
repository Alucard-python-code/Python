#!/bin/bash

# ====================================================================
# MASTER-INSTALLATIONSSKRIPT (Shortcut: Schussbahn | Icon: zielscheibe.png)
# bitte immer nach der installation folgenden befhl ausführen : pip3 install pyModbusTCP --break-system-packages
# ====================================================================

# DEINE GEPRÜFTE GITHUB-URL
GITHUB_REPO_URL="https://github.com/Alucard-python-code/Python.git"
GITHUB_BRANCH="main"

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

# 2. Monitor-Konfiguration (Automatisch über das System)
echo "[INFO] Nutze die automatische Standard-Auflösung des Bildschirms..."

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

# 5. Auswahlmenü mit deinen genauen GitHub-Pfaden
echo "=========================================================="
echo "         SCHUSSBAHN-INSTALLATION WENKHEIM                 "
echo "=========================================================="
echo "1) Schussbahn Modbus App starten"
echo "2) Schussbahn GPIO App starten"
read -p "Auswahl (1 oder 2): " variante

if [ "$variante" == "1" ]; then
    TARGET_SUBFOLDER="Projekte/Python/Schussbahn/schussbahn_modbus"
    VARIANT_NAME="Modbus"
elif [ "$variante" == "2" ]; then
    TARGET_SUBFOLDER="Projekte/Python/Schussbahn/schussbahn_gpio"
    VARIANT_NAME="GPIO"
else
    echo "[FEHLER] Ungültige Auswahl."
    exit 1
fi

APP_NAME="Schussbahn_app"
INSTALL_PATH="$REAL_HOME/Desktop/$APP_NAME"

# 6. ABSOLUTE REINIGUNG: Löscht die App UND alle alten Ordner/Backups restlos vom Desktop
echo "[INFO] Bereinige Desktop vollständig von alten Installationen..."
rm -rf "$REAL_HOME/Desktop/${APP_NAME}"*
rm -rf "$REAL_HOME/Desktop/Schussbahn.desktop"

# 7. Minimaler GitHub-Download aus der Unterstruktur (Sparse-Checkout)
echo "[INFO] Starte minimalen Download von GitHub..."
TEMP_CLONE_DIR="/tmp/schussbahn_git_clone"
rm -rf "$TEMP_CLONE_DIR"
mkdir -p "$TEMP_CLONE_DIR"
cd "$TEMP_CLONE_DIR"

git init -q
git remote add origin "$GITHUB_REPO_URL"
git config core.sparseCheckout true

# Git anweisen, nur deinen tiefen Pfad zu laden
echo "$TARGET_SUBFOLDER/" >> .git/info/sparse-checkout

if ! git pull origin "$GITHUB_BRANCH" --depth=1; then
    echo "[FEHLER] Download von GitHub fehlgeschlagen! Bitte Verbindung und URL prüfen."
    exit 1
fi

mkdir -p "$INSTALL_PATH"
# Direkt in den heruntergeladenen Unterordner greifen
if [ -d "$TARGET_SUBFOLDER" ]; then
    cp -r "$TARGET_SUBFOLDER/"* "$INSTALL_PATH/"
    echo "[INFO] App-Dateien erfolgreich extrahiert."
else
    echo "[FEHLER] Pfad nicht gefunden: $TARGET_SUBFOLDER"
    exit 1
fi

# Temporären Git-Strukturmüll restlos löschen (Keine Reste im System)
cd /
rm -rf "$TEMP_CLONE_DIR"

# Pfad zur mitgelieferten Icon-Datei festlegen
ICON_PATH="$INSTALL_PATH/zielscheibe.png"

echo "Version: 1.0 (GitHub Stand: $(date))" > "$INSTALL_PATH/version.txt"
chown -R "$REAL_USER":"$REAL_USER" "$INSTALL_PATH"

# 8. Abhängigkeiten installieren (GPIO & Modbus immer aktiv)
echo "[INFO] Installiere APT-Abhängigkeiten (GPIO & GUI)..."
apt-get install -y python3-pip python3-pyqt5 fonts-noto-color-emoji python3-gpiozero python3-lgpio

echo "[INFO] Installiere Python-Modbus-Bibliothek..."
# Ausführung deines exakten Pip-Befehls
pip3 install pyModbusTCP --break-system-packages
sudo -u "$REAL_USER" pip3 install pyModbusTCP --break-system-packages

# 9. Lüftersteuerung einrichten (Immer aktiv)
echo "[INFO] Richte PWM-Lüftersteuerung ein..."
cat << 'PYTHON_EOF' > /usr/local/bin/case_fan_control.py
import time
from gpiozero import PWMOutputDevice, CPUTemperature
from gpiozero.pins.lgpio import LGPIOFactory
fan = PWMOutputDevice(18, frequency=100, initial_value=0.25, pin_factory=LGPIOFactory())
cpu = CPUTemperature()
while True:
    fan.value = 0.45 if cpu.temperature < 40 else min(1.0, (cpu.temperature - 40) / 35)
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

systemctl daemon-reload
systemctl enable case_fan.service && systemctl restart case_fan.service

# 10. Desktop-Verknüpfung & Autostart (Name: Schussbahn | Icon: deine zielscheibe.png)
DESKTOP_FILE="$REAL_HOME/Desktop/Schussbahn.desktop"
cat <<EOF > "$DESKTOP_FILE"
[Desktop Entry]
Name=Schussbahn
Exec=env QT_QPA_PLATFORM=xcb python3 $INSTALL_PATH/Schussbahn.py
Path=$INSTALL_PATH
Icon=$ICON_PATH
Terminal=false
Type=Application
EOF

chmod +x "$DESKTOP_FILE"
chown "$REAL_USER":"$REAL_USER" "$DESKTOP_FILE"

# Desktop-Icon für Benutzeroberfläche freischalten
sudo -u "$REAL_USER" GIO_USE_VFS=local gio set "$DESKTOP_FILE" metadata::trusted true 2>/dev/null

# Autostart einrichten
mkdir -p "$REAL_HOME/.config/autostart"
AUTOSTART_FILE="$REAL_HOME/.config/autostart/schussbahn_autostart.desktop"
cat <<EOF > "$AUTOSTART_FILE"
[Desktop Entry]
Type=Application
Exec=env QT_QPA_PLATFORM=xcb python3 $INSTALL_PATH/Schussbahn.py
Path=$INSTALL_PATH
X-GNOME-Autostart-enabled=true
Name=Schussbahn Autostart
Icon=$ICON_PATH
EOF

chown -R "$REAL_USER":"$REAL_USER" "$REAL_HOME/.config/autostart"

echo "[ERFOLG] Installation abgeschlossen!"
echo "[INFO] Shortcut 'Schussbahn' wurde mit deinem Bildsymbol erstellt."
echo "[INFO] Neustart in 5 Sekunden..."
sleep 5
reboot
