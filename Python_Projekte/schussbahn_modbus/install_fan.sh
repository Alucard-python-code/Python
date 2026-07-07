#!/bin/bash

# Installations-Anweisungen:
# cd Desktop/bahn_3/schussbahn_modbus 
# chmod +x install_fan.sh
# ./install_fan.sh

# Verhalten: 
# Dieses Skript installiert die Steuerung für einen PWM-Gehäuselüfter auf dem Raspberry Pi 5.
# Es richtet ein Python-Skript ein, das die CPU-Temperatur überwacht und den Lüfter steuert.
# Es wird ein Systemd-Dienst erstellt, der das Skript beim Booten automatisch startet.

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
echo " Starte automatische Raspberry Pi 5 Lüfter-Installation..."
echo "=========================================================="

# 2. Inkompatible Pakete entfernen und Pi 5 Treiber installieren
echo "[1/5] Bereinige alte Treiber und installiere Raspberry Pi 5 Pakete..."
# RPi.GPIO verursacht Fehler auf dem Pi 5, daher entfernen wir es zur Sicherheit
apt-get remove -y python3-rpi.gpio
apt-get update -y
# python3-lgpio ist zwingend erforderlich für gpiozero auf dem Pi 5
apt-get install -y python3-gpiozero python3-lgpio

# 3. Das eigentliche Python-Steuerungsskript im System erstellen
echo "[2/5] Erstelle Steuerungs-Skript unter /usr/local/bin/case_fan_control.py..."
cat << 'PYTHON_EOF' > /usr/local/bin/case_fan_control.py
#!/usr/bin/env python3
import time
from gpiozero import PWMOutputDevice, CPUTemperature
from gpiozero.pins.lgpio import LGPIOFactory  # Pi 5 kompatibler Pin-Treiber

# Hardware-Konfiguration (Pin 12 entspricht GPIO 18)
PWM_PIN = 18          

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
    # Nutzen explizit die LGPIO-Factory für den Raspberry Pi 5
    factory = LGPIOFactory()
    fan = PWMOutputDevice(PWM_PIN, frequency=100, initial_value=MIN_PWM, pin_factory=factory)
    cpu = CPUTemperature()

    print("[START] Lueftersteuerung aktiv.", flush=True)

    try:
        while True:
            temp = cpu.temperature
            target_pwm = calculate_pwm(temp)
            fan.value = target_pwm
            
            # Wichtig für die Protokollierung im System-Log (journalctl)
            print(f"CPU-Temp: {temp:.1f}°C -> Luefter-PWM: {target_pwm * 100:.0f}%", flush=True)
            
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
echo "[3/5] Erstelle Systemd-Hintergrunddienst für automatischen Boot-Start..."
cat << 'SERVICE_EOF' > /etc/systemd/system/case_fan.service
[Unit]
Description=Sichere PWM Gehaeuseluefter-Steuerung fuer Raspberry Pi 5 (Pin 12)
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
echo "[4/5] Aktiviere und starte den Dienst im Hintergrund..."
systemctl daemon-reload
systemctl enable case_fan.service
systemctl restart case_fan.service

# 6. Funktionstest vorbereiten
echo "[5/5] Ueberpruefe GPIO 18 Pin-Status..."
sleep 2 # Kurze Pause, damit der Dienst anlaufen kann

echo "=========================================================="
echo " FERTIG! Der Luefter ist auf dem Pi 5 eingerichtet."
echo "=========================================================="
echo " -> Live-Werte des Skripts sehen:   sudo journalctl -u case_fan.service -f"
echo " -> Status des Dienstes abfragen:   sudo systemctl status case_fan.service"
echo " -> Pin-Signal live pruefen:        pinctrl get 18"
echo "=========================================================="
