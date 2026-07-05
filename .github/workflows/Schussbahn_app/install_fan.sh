#!/bin/bash

# installations Anweisungen:
# cd Desktop/bahn_3 ( oder 4 ) /schussbahn_modbus chmod +x install_fan.sh
# (gleicher Pfad)./install_fan.sh

# Verhalten: 
# Dieses Skript installiert automatisch die Steuerung für einen PWM-Gehäuselüfter
# Es richtet ein Python-Skript ein, das die CPU-Temperatur überwacht und den Lüfter entsprechend steuert.
# Außerdem wird ein Systemd-Dienst erstellt, der das Skript beim Booten automatisch startet.

# ==============================================================================

# INSTALLATIONSSKRIPT FÜR RASPBERRY PI 5 PWM-GEHÄUSELÜFTER
# Belegung: Pin 4 (+5V) | Pin 6 (GND) | Pin 12 (GPIO 18 / PWM)
# Regelung: 25% bis 100% basierend auf der CPU-Temperatur (40°C - 75°C)

# ==============================================================================

# 1. Automatische Prüfung und Anforderung von Root-Rechten (sudo)
if [ "$EUID" -ne 0 ]; then 
  echo "[INFO] Skript benötigt Root-Rechte. Starte automatisch mit sudo..."
  exec sudo bash "$0" "$@"
  exit 1
fi

echo "=========================================================="
echo " Starte automatische Gehäuselüfter-Installation..."
echo "=========================================================="

# 2. Systempakete aktualisieren und gpiozero installieren
echo "[1/4] Installiere benötigte Python3-Bibliotheken..."
apt-get update -y && apt-get install -y python3-gpiozero python3-rpi.gpio

# 3. Das eigentliche Python-Steuerungsskript im System erstellen
echo "[2/4] Erstelle Steuerungs-Skript unter /usr/local/bin/case_fan_control.py..."
cat << 'PYTHON_EOF' > /usr/local/bin/case_fan_control.py
#!/usr/bin/env python3
import time
from gpiozero import PWMOutputDevice, CPUTemperature

# Hardware-Konfiguration (Pin 12 entspricht GPIO 18)
PWM_PIN = 18          
# +5V liegt dauerhaft auf Pin 4, GND liegt auf Pin 6

# Lüfterkurven-Konfiguration
MIN_TEMP = 40.0       # Ab 40°C startet der Lüfter bei 25%
MAX_TEMP = 75.0       # Ab 75°C läuft er auf vollen 100%
MIN_PWM = 0.25        # 25% Mindestdrehzahl
MAX_PWM = 1.00        # 100% maximale Drehzahl
INTERVAL = 5          # Messung alle 5 Sekunden

def calculate_pwm(current_temp):
    if current_temp <= MIN_TEMP:
        return MIN_PWM
    if current_temp >= MAX_TEMP:
        return MAX_PWM
    
    # Lineare Skalierung zwischen 25% und 100%
    temp_range = MAX_TEMP - MIN_TEMP
    pwm_range = MAX_PWM - MIN_PWM
    scaled_pwm = MIN_PWM + ((current_temp - MIN_TEMP) / temp_range) * pwm_range
    return round(scaled_pwm, 2)

def main():
    # Initialisiere PWM auf GPIO 18 mit 100Hz (optimal für 5V-Lüfter)
    fan = PWMOutputDevice(PWM_PIN, frequency=100, initial_value=MIN_PWM)
    cpu = CPUTemperature()

    try:
        while True:
            temp = cpu.temperature
            target_pwm = calculate_pwm(temp)
            fan.value = target_pwm
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        fan.close()

if __name__ == '__main__':
    main()
PYTHON_EOF

# Dateirechte für das Python-Skript vollautomatisch setzen
chmod +x /usr/local/bin/case_fan_control.py

# 4. Systemd-Hintergrunddienst für den Autostart einrichten
echo "[3/4] Erstelle Systemd-Hintergrunddienst für automatischen Boot-Start..."
cat << 'SERVICE_EOF' > /etc/systemd/system/case_fan.service
[Unit]
Description=Sichere PWM Gehaeuseluefter-Steuerung (Pin 12)
After=multi-user.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/local/bin/case_fan_control.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE_EOF

# 5. Dienst aktivieren und sofort starten
echo "[4/4] Aktiviere und starte den Dienst im Hintergrund..."
systemctl daemon-reload
systemctl enable case_fan.service
systemctl start case_fan.service

echo "=========================================================="
echo " FERTIG! Der Lüfter ist sicher eingerichtet und aktiv."
echo " Überwachung via: sudo systemctl status case_fan.service"
echo "=========================================================="
