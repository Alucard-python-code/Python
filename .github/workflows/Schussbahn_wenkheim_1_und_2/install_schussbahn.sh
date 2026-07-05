#!/bin/bash

# Command to assign installation permissions : chmod +x install_schussbahn.sh
# Install command : ./install_schussbahn.sh

# ====================================================================
# AUTOMATISCHES EINRICHTUNGS-SKRIPT FÜR DIE GPIO-SCHUSSBAHN-APP
# ====================================================================

# 1. Aktuellen Ordner ermitteln
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
echo "[INFO] Projekt-Ordner erkannt: $SCRIPT_DIR"

# 2. System-Updates und GPIO/PyQt5 Abhängigkeiten installieren
echo "[INFO] Installiere notwendige System-Pakete (PyQt5 & GPIO)..."
sudo apt-get update -y
sudo apt-get install -y python3-pip python3-pyqt5

# Installiert den GPIO-Treiber (Kompatibel mit alten und neuen Pi-OS Versionen)
sudo apt-get install -y python3-rpi.gpio || sudo apt-get install -y python3-rpi-lgpio

# 3. Benutzer-Rechte für GPIO-Zugriff ohne 'sudo' einrichten
echo "[INFO] Füge Benutzer zur GPIO-Gruppe hinzu..."
sudo usermod -a -G gpio $USER

# 4. Ausführungsrechte für die Skripte vergeben
echo "[INFO] Vergebe Berechtigungen für Python- und Systemskripte..."
chmod +x "$SCRIPT_DIR/Schussbahn.py"
chmod +x "${BASH_SOURCE[0]}"

# 5. Desktop-Verknüpfung erstellen
echo "[INFO] Erstelle Verknüpfung auf dem Desktop..."
DESKTOP_FILE="/home/$USER/Desktop/Schussbahn.desktop"

cat <<EOF > "$DESKTOP_FILE"
[Desktop Entry]
Name=Schussbahn Steuerung (GPIO)
Comment=Direktverdrahtete Steuerung für die Schussbahn Wenkheim
Exec=python3 $SCRIPT_DIR/Schussbahn.py
Icon=target
Terminal=false
Type=Application
Categories=Development;
EOF

# Rechte für die Desktop-Datei anpassen
chmod +x "$DESKTOP_FILE"
gio set "$DESKTOP_FILE" metadata::trusted true 2>/dev/null

# 6. Autostart einrichten (sobald der LXDE-Desktop geladen ist)
echo "[INFO] Richte automatischen Programmstart beim Desktop-Login ein..."
AUTOSTART_DIR="/home/$USER/.config/autostart"
mkdir -p "$AUTOSTART_DIR"

cat <<EOF > "$AUTOSTART_DIR/schussbahn_autostart.desktop"
[Desktop Entry]
Type=Application
Exec=python3 $SCRIPT_DIR/Schussbahn.py
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name=Schussbahn Autostart
EOF

echo "===================================================================="
echo "[ERFOLG] Die GPIO-Schussbahn-App wurde erfolgreich eingerichtet!"
echo "[INFO] - Desktop-Verknüpfung wurde erstellt."
echo "[INFO] - Autostart nach dem Laden des Desktops ist aktiv."
echo "[WICHTIG] Bitte starte den Raspberry Pi JETZT einmal neu,"
echo "[WICHTIG] damit die GPIO-Rechte wirksam werden!"
echo "===================================================================="
