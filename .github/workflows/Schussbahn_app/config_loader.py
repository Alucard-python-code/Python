# -*- coding: utf-8 -*-
import os
import json
import logging

# DIESER BEFEHL IST ABSOLUT UNFEHLBAR: Er nimmt den Ordner, in dem DIESE config_loader.py liegt!
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Alle Dateien werden hiermit bombenfest und absolut an diesen Ordner gebunden:
SETTINGS_FILE = os.path.join(SCRIPT_DIR, "Einstellungswerte.json")
HOURS_FILE = os.path.join(SCRIPT_DIR, "betriebsstunden.json")
LOG_JSON_FILE = os.path.join(SCRIPT_DIR, "fehler_historie.json")

DEFAULT_SETTINGS = {
    "Beschuss Schnell" : 3.0,
    "Beschuss Langsam" : 2.0,
    "Wertung Schnell" : 2.5,
    "Sicherheits-Timeout": 15.0,
    "Home-Timeout": 25.0,
    "Anlauf-Überwachung": 2.0,
    "Wartungsintervall": 50.0,
    "Service-PIN": 1234,
    "Modbus-IP": "192.168.8.203"
}

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Fehler beim Laden der Einstellungen: {e}")
    return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        logging.error(f"Fehler beim Speichern der Einstellungen: {e}")
# Am Ende von Teil 1 hinzufügen:

HOURS_FILE_NAME = "betriebsstunden.json"

def load_operating_hours():
    # ZWANG: Absoluten Pfad direkt hier im Moment des Aufrufs neu berechnen
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    absolute_hours_path = os.path.join(current_script_dir, HOURS_FILE_NAME)
    
    if os.path.exists(absolute_hours_path):
        try:
            with open(absolute_hours_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Fehler beim Laden der Betriebsstunden: {e}")
    
    # Rückfallebene, falls Datei nicht existiert
    return {"gesamt_sekunden": 0.0, "fahrzeit_sekunden": 0.0}

def save_operating_hours(hours):
    # ZWANG: Absoluten Pfad direkt hier im Moment des Aufrufs neu berechnen
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    absolute_hours_path = os.path.join(current_script_dir, HOURS_FILE_NAME)
    
    try:
        with open(absolute_hours_path, 'w', encoding='utf-8') as f:
            json.dump(hours, f, indent=4)
    except Exception as e:
        logging.error(f"Fehler beim Speichern der Betriebsstunden: {e}")


LOG_JSON_FILE_NAME = "fehler_historie.json"

def load_error_log():
    # ZWANG: Absoluten Pfad direkt hier im Moment des Aufrufs neu berechnen
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    absolute_log_json_path = os.path.join(current_script_dir, LOG_JSON_FILE_NAME)
    
    if os.path.exists(absolute_log_json_path):
        try:
            with open(absolute_log_json_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Fehler beim Laden des Fehler-Logs: {e}")
    return []  # Gibt eine leere Liste zurück, falls die Datei noch nicht existiert

def save_error_log(error_list):
    # ZWANG: Absoluten Pfad direkt hier im Moment des Aufrufs neu berechnen
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    absolute_log_json_path = os.path.join(current_script_dir, LOG_JSON_FILE_NAME)
    
    try:
        with open(absolute_log_json_path, 'w', encoding='utf-8') as f:
            json.dump(error_list, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Fehler beim Speichern des Fehler-Logs: {e}")

