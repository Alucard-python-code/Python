# config_loader.py - v2.0 (GPIO-Direktverdrahtung)
import os
import json
import logging

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(SCRIPT_DIR, "Einstellungswerte.json")
HOURS_FILE_NAME = "betriebsstunden.json"
LOG_JSON_FILE_NAME = "fehler_historie.json"

# Hardware PIN-Festlegung (BCM-Nummerierung aus der alten Variante)
PINS_OUT = {
    "Schnell": 6,
    "Langsam": 13,
    "Linkslauf": 19,
    "Rechtslauf": 26,
    "Licht": 23
}

PINS_IN = {
    "Motorschutz": 18,
    "Endschalter": 10,
    "Feedback_Schnell": 12,
    "Feedback_Langsam": 16,
    "Feedback_Links": 20,
    "Feedback_Rechts": 21
}

DEFAULT_SETTINGS = {
    "Beschuss Schnell" : 3.0,
    "Beschuss Langsam" : 2.0,
    "Wertung Schnell" : 2.5,
    "Sicherheits-Timeout": 15.0,
    "Home-Timeout": 25.0,
    "Anlauf-Überwachung": 2.0,
    "Wartungsintervall": 50.0,
    "Service-PIN": 1234
}

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f: return json.load(f)
        except Exception as e:
            logging.error(f"Fehler Einstellungen: {e}")
    return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w") as f: json.dump(settings, f, indent=4)
    except Exception as e: logging.error(f"Fehler Speichern: {e}")

def load_operating_hours():
    absolute_hours_path = os.path.join(SCRIPT_DIR, HOURS_FILE_NAME)
    if os.path.exists(absolute_hours_path):
        try:
            with open(absolute_hours_path, 'r', encoding='utf-8') as f: return json.load(f)
        except Exception as e: logging.error(f"Fehler Betriebsstunden: {e}")
    return {"gesamt_sekunden": 0.0, "fahrzeit_sekunden": 0.0}

def save_operating_hours(hours):
    absolute_hours_path = os.path.join(SCRIPT_DIR, HOURS_FILE_NAME)
    try:
        with open(absolute_hours_path, 'w', encoding='utf-8') as f: json.dump(hours, f, indent=4)
    except Exception as e: logging.error(f"Fehler Speichern Stunden: {e}")

def load_error_log():
    absolute_log_json_path = os.path.join(SCRIPT_DIR, LOG_JSON_FILE_NAME)
    if os.path.exists(absolute_log_json_path):
        try:
            with open(absolute_log_json_path, 'r', encoding='utf-8') as f: return json.load(f)
        except Exception as e: logging.error(f"Fehler Log: {e}")
    return []

def save_error_log(error_list):
    absolute_log_json_path = os.path.join(SCRIPT_DIR, LOG_JSON_FILE_NAME)
    try:
        with open(absolute_log_json_path, 'w', encoding='utf-8') as f:
            json.dump(error_list, f, indent=4, ensure_ascii=False)
    except Exception as e: logging.error(f"Fehler Speichern Log: {e}")
