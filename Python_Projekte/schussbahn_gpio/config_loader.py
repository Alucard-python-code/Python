<<<<<<< HEAD
# -*- coding: utf-8 -*-
import os
import json
import logging

# Zentraler Ordner-Pfad direkt zur Laufzeit berechnet
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

SETTINGS_FILE = os.path.join(SCRIPT_DIR, "Einstellungswerte.json")
HOURS_FILE = os.path.join(SCRIPT_DIR, "betriebsstunden.json")
LOG_JSON_FILE = os.path.join(SCRIPT_DIR, "fehler_historie.json")

# Standardwerte basierend auf deinen Original-Fahrzeiten (7s Schnell / 2.5s Langsam)
DEFAULT_SETTINGS = {
    "Beschuss Schnell" : 7.0,
    "Beschuss Langsam" : 2.5,
    "Wertung Schnell" : 6.5,
    "Sicherheits-Timeout": 15.0,
    "Home-Timeout": 25.0,
    "Anlauf-Überwachung": 2.0,
    "Wartungsintervall": 50.0,
    "Service-PIN": 1234,
    "Bremse": 0.2,
    "Anschlag": 0.4,
    "Umschaltpause": 0.05
}

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Fehler beim Laden der Einstellungen: {e}")
    return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Fehler beim Speichern der Einstellungen: {e}")
def load_operating_hours():
    if os.path.exists(HOURS_FILE):
        try:
            with open(HOURS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Fehler beim Laden der Betriebsstunden: {e}")
    return {"gesamt_sekunden": 0.0, "fahrzeit_sekunden": 0.0}

def save_operating_hours(hours):
    try:
        with open(HOURS_FILE, 'w', encoding='utf-8') as f:
            json.dump(hours, f, indent=4)
    except Exception as e:
        logging.error(f"Fehler beim Speichern der Betriebsstunden: {e}")

def load_error_log():
    if os.path.exists(LOG_JSON_FILE):
        try:
            with open(LOG_JSON_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Fehler beim Laden des Fehler-Logs: {e}")
    return []

def save_error_log(error_list):
    try:
        with open(LOG_JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(error_list, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Fehler beim Speichern des Fehler-Logs: {e}")
=======
# -*- coding: utf-8 -*-
import os
import json
import logging

# Zentraler Ordner-Pfad direkt zur Laufzeit berechnet
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

SETTINGS_FILE = os.path.join(SCRIPT_DIR, "Einstellungswerte.json")
HOURS_FILE = os.path.join(SCRIPT_DIR, "betriebsstunden.json")
LOG_JSON_FILE = os.path.join(SCRIPT_DIR, "fehler_historie.json")

# Standardwerte basierend auf deinen Original-Fahrzeiten (7s Schnell / 2.5s Langsam)
DEFAULT_SETTINGS = {
    "Beschuss Schnell" : 7.0,
    "Beschuss Langsam" : 2.5,
    "Wertung Schnell" : 6.5,
    "Sicherheits-Timeout": 15.0,
    "Home-Timeout": 25.0,
    "Anlauf-Überwachung": 2.0,
    "Wartungsintervall": 50.0,
    "Service-PIN": 1234,
    "Bremse": 0.2,
    "Anschlag": 0.4,
    "Umschaltpause": 0.05
}

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Fehler beim Laden der Einstellungen: {e}")
    return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Fehler beim Speichern der Einstellungen: {e}")
def load_operating_hours():
    if os.path.exists(HOURS_FILE):
        try:
            with open(HOURS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Fehler beim Laden der Betriebsstunden: {e}")
    return {"gesamt_sekunden": 0.0, "fahrzeit_sekunden": 0.0}

def save_operating_hours(hours):
    try:
        with open(HOURS_FILE, 'w', encoding='utf-8') as f:
            json.dump(hours, f, indent=4)
    except Exception as e:
        logging.error(f"Fehler beim Speichern der Betriebsstunden: {e}")

def load_error_log():
    if os.path.exists(LOG_JSON_FILE):
        try:
            with open(LOG_JSON_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Fehler beim Laden des Fehler-Logs: {e}")
    return []

def save_error_log(error_list):
    try:
        with open(LOG_JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(error_list, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Fehler beim Speichern des Fehler-Logs: {e}")
>>>>>>> aea6e0f3cc44f05c8b75f9cd480e934127c702a5
