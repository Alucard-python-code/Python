#v1.2
import machine
import json

# =========================================================================
# 1. HARDWARE PIN-BELEGUNG
# =========================================================================
PIN_POTI = 26          # ADC0 für das 10k Ohm Positions-Poti
PIN_MOTOR_OPEN = 2     # H-Brücke / Motortreiber: Richtung Öffnen
PIN_MOTOR_CLOSE = 3    # H-Brücke / Motortreiber: Richtung Schließen
PIN_LED_GREEN = 4      # Status-LED: Alles i.O. / Bereit
PIN_LED_YELLOW = 5     # Status-LED: In Bewegung
PIN_LED_RED = 6        # Status-LED: Fehler / Watchdog

# SPI-Pins für den MAX31865 (PT1000 Wandler)
PIN_MAX_CS = 10
PIN_MAX_SCK = 13
PIN_MAX_MOSI = 11
PIN_MAX_MISO = 12

# =========================================================================
# 2. SYSTEM-EINSTELLUNGEN (Netzwerk- & Zeit-Standards)
# =========================================================================
settings = {
    "ip": "192.168.1.150",
    "subnet": "255.255.255.0",
    "gateway": "192.168.1.1",
    "dns": "192.168.1.1",
    "modbus_port": 502,
    "web_port": 80,
    "watchdog_timeout_ms": 60000,
    "motor_block_ms": 1500
}

# =========================================================================
# 3. LIVE STATE (Globale Laufzeitdaten)
# =========================================================================
state = {
    "soll_oeffnung": 0,          # Vorgabe über Modbus (0 bis 100 %)
    "ist_oeffnung": 0,           # Errechneter Ist-Wert (0 bis 100 %)
    "poti_raw_live": 0,          # Aktueller, gefilterter ADC-Rohwert des Potis
    "poti_min": 10000,           # Kalibrierwert für ZU (0%) – Fallback
    "poti_max": 50000,           # Kalibrierwert für AUF (100%) – Fallback
    "temperatur": 0.0,           # Aktuelle Temperatur vom PT1000 in °C
    "status_code": 0,            # 0=Bereit/Stillstand, 1=Öffnet, 2=Schließt
    "fehler_code": 0,            # 0=Kein Fehler, 1=Poti defekt, 2=Watchdog, 3=Blockiert
    "last_modbus_activity": 0,   # Zeitstempel der letzten Modbus-Anfrage
    "watchdog_triggered": False, # Status des Netzwerk-Watchdogs
    "logged_in_users": []        # Liste der IPs, die aktuell im Webinterface angemeldet sind
}

# =========================================================================
# 4. PERMANENTE SPEICHER-FUNKTIONEN (Flash-ROM)
# =========================================================================

def save_calibration():
    """Speichert die gelernten Poti-Grenzen permanent im Flash-Speicher als JSON."""
    try:
        with open("calib.txt", "w") as f:
            json.dump({"min": state["poti_min"], "max": state["poti_max"]}, f)
        print("[Calib] Werte erfolgreich gespeichert:", state["poti_min"], state["poti_max"])
    except Exception as e:
        print("[Calib] Fehler beim Speichern:", e)

def load_calibration():
    """Lädt die gelernten Poti-Grenzen beim Systemstart aus dem Flash-Speicher."""
    try:
        with open("calib.txt", "r") as f:
            data = json.load(f)
            state["poti_min"] = data["min"]
            state["poti_max"] = data["max"]
        print("[Calib] Werte erfolgreich geladen:", state["poti_min"], state["poti_max"])
    except:
        print("[Calib] Keine Kalibrierdatei gefunden. Nutze Defaults.")

def save_password(new_pwd):
    """Speichert das geänderte Webinterface-Passwort sicher im Flash-Speicher."""
    try:
        with open("pwd.txt", "w") as f:
            f.write(new_pwd)
        print("[Auth] Passwort erfolgreich geändert.")
    except Exception as e:
        print("[Auth] Fehler beim Speichern des Passworts:", e)

def load_password():
    """
    Lädt das Passwort beim Start. Falls keine Datei existiert, 
    gilt das vorgegebene Standard-Passwort.
    """
    try:
        with open("pwd.txt", "r") as f:
            pwd = f.read().strip()
            if len(pwd) >= 8: # Sicherheitsprüfung: Passwort muss mindestens 8 Zeichen haben
                return pwd
    except:
        pass
    return "123456789"  # Werks-Standardpasswort laut Vorgabe
