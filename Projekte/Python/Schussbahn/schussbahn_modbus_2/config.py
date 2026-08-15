# config.py

import json
import os

# Speicherpfad für die dauerhafte Konfiguration
CONFIG_FILE = "config.json"

# Werkseinstellungen / Fallback-Werte
DEFAULT_CONFIG = {
    'ip': '192.168.8.250',
    'port': 502,
    'pin': '1234',
    'b_schnell': 3.0,
    'b_langsam': 2.0,
    'a_schnell': 4.0,
    'wd_homing': 15.0,      # NEU: Watchdog Homing (Sekunden)
    'wd_beschuss': 10.0,    # NEU: Watchdog Beschuss (Sekunden)
    'wd_auswertung': 20.0   # NEU: Watchdog Auswertung (Sekunden)
}

def load_stored_config():
    """Lädt die Konfiguration aus der JSON-Datei oder erstellt sie mit Standardwerten."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                stored = json.load(f)
                # Sicherheitsabgleich: Falls Schlüssel in der Datei fehlen, mit Default auffüllen
                for key, value in DEFAULT_CONFIG.items():
                    if key not in stored:
                        stored[key] = value
                return stored
        except Exception:
            return DEFAULT_CONFIG.copy()
    else:
        # Datei existiert nicht -> Erstellen mit Standardwerten
        save_stored_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

def save_stored_config(config_dict):
    """Schreibt die aktuellen Einstellungen dauerhaft in die JSON-Datei."""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_dict, f, indent=4, ensure_ascii=False)
    except Exception:
        pass

# Register-Mapping für die Modbus-Hardware
INPUT_MOTORSCHUTZ = 0   # IN1
INPUT_ENDSCHALTER = 1   # IN2
INPUT_RM_RECHTS   = 2   # IN3
INPUT_RM_LINKS    = 3   # IN4
INPUT_RM_LANGSAM  = 4   # IN5
INPUT_RM_SCHNELL  = 5   # IN6

OUTPUT_RECHTS     = 0   # CH1
OUTPUT_LINKS      = 1   # CH2
OUTPUT_LANGSAM    = 2   # CH3
OUTPUT_SCHNELL    = 3   # CH4
OUTPUT_LICHT      = 7   # CH8
