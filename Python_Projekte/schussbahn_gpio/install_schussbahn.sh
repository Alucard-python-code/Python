#!/bin/bash

# ====================================================================
# AUTOMATISCHES EINRICHTUNGS-SKRIPT MIT EMOJI-ERWEITERUNG (GPIO)
# ====================================================================

# 1. Aktuellen Ordner ermitteln
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
echo "[INFO] Projekt-Ordner erkannt: $SCRIPT_DIR"

# 2. System-Updates und Abhängigkeiten installieren
echo "[INFO] Aktualisiere System-Pakete..."
sudo apt-get update -y

echo "[INFO] Installiere PyQt5 und GPIO-Bibliotheken..."
sudo apt-get install -y python3-pip python3-pyqt5 python3-gpiozero

# Installiert die Google-Emoji-Schriftart, damit das 🎯-Symbol keine Rechtecke mehr anzeigt
echo "[INFO] Installiere Emoji-Fonts für die Zielscheibe (🎯)..."
sudo apt-get install -y fonts-noto-color-emoji

# 3. Ausführungsrechte für die Skripte vergeben (Hier bleibt es bei Schussbahn.py)
echo "[INFO] Vergebe Berechtigungen für Python- und Systemskripte..."
chmod +x "$SCRIPT_DIR/Schussbahn.py"
chmod +x "${BASH_SOURCE[0]}"

# 4. Desktop-Verknüpfung erstellen
echo "[INFO] Erstelle Verknüpfung auf dem Desktop..."
DESKTOP_FILE="/home/$USER/Desktop/Schussbahn.desktop"

cat <<EOF > "$DESKTOP_FILE"
[Desktop Entry]
Name=Schussbahn Steuerung (GPIO)
Comment=Direkte Pin-Steuerung für die Schussbahn Wenkheim
Exec=python3 $SCRIPT_DIR/Schussbahn.py
Icon=target
Terminal=false
Type=Application
Categories=Development;
EOF

# Rechte für die Desktop-Datei anpassen, damit Raspbian sie als vertrauenswürdig einstuft
chmod +x "$DESKTOP_FILE"
gio set "$DESKTOP_FILE" metadata::trusted true 2>/dev/null

# 5. Autostart einrichten
echo "[INFO] Richte automatischen Programmstart beim Desktop-Login ein..."
AUTOSTART_DIR="/home/$USER/.config/autostart"
mkdir -p "$AUTOSTART_DIR"

rm -f "$AUTOSTART_DIR/schussbahn_autostart.desktop"
rm -f "$AUTOSTART_DIR/schussbahn_gpio_autostart.desktop"

cat <<EOF > "$AUTOSTART_DIR/schussbahn_gpio_autostart.desktop"
[Desktop Entry]
Type=Application
Exec=python3 $SCRIPT_DIR/Schussbahn.py
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name=Schussbahn GPIO Autostart
EOF

echo "===================================================================="
echo "[ERFOLG] Die Schussbahn-GPIO-App wurde erfolgreich eingerichtet!"
echo "[WICHTIG] Bitte starte den Raspberry Pi jetzt einmal neu!"
echo "===================================================================="