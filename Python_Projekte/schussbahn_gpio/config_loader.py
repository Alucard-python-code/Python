#!/usr/bin/python3
# -*- coding: utf-8 -*-
import json
import os
import sys

try:
    import __main__
    if hasattr(__main__, '__file__'):
        SCRIPT_DIR = os.path.dirname(os.path.abspath(__main__.__file__))
    else:
        SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except Exception:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

SETTINGS_FILE = os.path.join(SCRIPT_DIR, "settings.json")
HOURS_FILE = os.path.join(SCRIPT_DIR, "betriebsstunden.json")
ERROR_FILE = os.path.join(SCRIPT_DIR, "error_log.json")

DEFAULT_SETTINGS = {
    "Beschuss Schnell": 7.0,
    "Beschuss Langsam": 2.5,
    "Bremszeit Vorwaerts": 0.5,
    "Wartezeit Kugelfang": 3.0,
    "Wertung Schnell": 6.5,
    "Bremszeit Rueckwaerts": 0.5
}

DEFAULT_HOURS = {
    "gesamt_sekunden": 0.0,
    "fahrzeit_sekunden": 0.0
}

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_SETTINGS

def save_settings(data):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception:
        return False

def load_operating_hours():
    if not os.path.exists(HOURS_FILE):
        save_operating_hours(DEFAULT_HOURS)
        return DEFAULT_HOURS
    try:
        with open(HOURS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_HOURS

def save_operating_hours(data):
    try:
        with open(HOURS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception:
        return False

def load_error_log():
    if not os.path.exists(ERROR_FILE):
        return []
    try:
        with open(ERROR_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_error_log(error_list):
    try:
        with open(ERROR_FILE, "w", encoding="utf-8") as f:
            json.dump(error_list, f, indent=4, ensure_ascii=False)
        return True
    except Exception:
        return False