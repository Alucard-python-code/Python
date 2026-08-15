#!/usr/bin/python3
# -*- coding: utf-8 -*-
import os
import json
import logging

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(SCRIPT_DIR, "Einstellungswerte.json")
HOURS_FILE = os.path.join(SCRIPT_DIR, "betriebsstunden.json")
LOG_JSON_FILE = os.path.join(SCRIPT_DIR, "fehler_historie.json")

DEFAULT_SETTINGS = {
    "Beschuss Schnell" : 3.0,
    "Beschuss Langsam" : 2.0,
    "Bremszeit Vorwaerts" : 0.5,
    "Wartezeit Kugelfang" : 0.5,
    "Wertung Schnell" : 0.5,
    "Bremszeit Rueckwaerts" : 0.5,
    "Watchdog Beschuss": 10.0,
    "Watchdog Wertung": 10.0,
    "Laufzeit Motor (min)": 0.0,
    "Wartung Intervall (min)": 500.0,
    "Service-PIN": 1234,
    "Modbus-IP": "192.168.8.203"
}

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                settings = json.load(f)
                # Merge mit Defaults, falls Schlüssel fehlen
                full_settings = DEFAULT_SETTINGS.copy()
                full_settings.update(settings)
                return full_settings
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
        except Exception:
            pass
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
        except Exception:
            pass
    return []

def save_error_log(error_list):
    try:
        with open(LOG_JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(error_list, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Fehler beim Speichern des Fehler-Logs: {e}")