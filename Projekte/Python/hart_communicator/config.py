"""
config.py – Zentrale Konfiguration des HART-Feldcommunicators.

Alle Pinbelegungen, I2C-Adressen, Grenzwerte und Pfade an EINER Stelle.
Jeder Wert kann per Umgebungsvariable überschrieben werden (praktisch für
systemd-Units und für Tests auf dem Entwicklungs-PC).

Simulation:
    HART_SIM=auto   (Standard) -> Simulation, wenn kein Raspberry Pi erkannt wird
    HART_SIM=1                 -> alles simulieren
    HART_SIM=0                 -> niemals simulieren (Fehler, wenn Hardware fehlt)
    HART_SIM_<KOMPONENTE>=1/0  -> Einzel-Override, z.B. HART_SIM_HART=1, HART_SIM_BMS=0
"""
from __future__ import annotations

import os
from pathlib import Path


def _env_int(name: str, default: int | None) -> int | None:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    if val.lower() in ("none", "off", "-"):
        return None
    return int(val, 0)


def _env_float(name: str, default: float) -> float:
    val = os.environ.get(name)
    return float(val) if val else default


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on", "ja")


# ---------------------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("HART_DATA_DIR", BASE_DIR / "data"))
PHOTO_DIR = DATA_DIR / "photos"
REPORT_DIR = DATA_DIR / "reports"
DB_PATH = DATA_DIR / "hart_kalibrierung.db"
TELEMETRY_DB_PATH = DATA_DIR / "telemetry_logs.db"
BMS_STATE_FILE = DATA_DIR / "bms_state.json"
USER_DEVICE_CATALOG = DATA_DIR / "device_catalog_user.json"


# ---------------------------------------------------------------------------
# GPIO-Belegung (BCM-Nummerierung)
# ---------------------------------------------------------------------------
class Pins:
    # HART-Modem AD5700
    HART_RTS = _env_int("PIN_HART_RTS", 17)            # Ausgang, Active LOW = Senden
    HART_OCD = _env_int("PIN_HART_OCD", 27)            # Eingang, HIGH = Carrier erkannt

    # 24/7-Safe-Mode ist laut finalem Gehäusekonzept REIN SOFTWARE.
    # GPIO26 bleibt reserviert; wird hier ein Pin gesetzt, wirkt ein
    # Hardwareschalter ZUSÄTZLICH als "erzwinge Nur-Lesen" (ODER-Verknüpfung).
    SAFE_MODE_HW = _env_int("PIN_SAFE_MODE_HW", None)  # optional: 26

    # Bedienelemente am Gehäuse
    POWER_LATCH = _env_int("PIN_POWER_LATCH", 25)      # Soft-Power-Selbsthaltung (EN)
    POWER_BUTTON_SENSE = _env_int("PIN_POWER_BUTTON", None)  # optional, falls Taster mitgelesen wird
    TOUCH_LOCK = _env_int("PIN_TOUCH_LOCK", 16)        # Schiebeschalter, LOW = gesperrt

    # Peripherie
    BMS_ALERT = _env_int("PIN_BMS_ALERT", 24)          # BQ76930 ALERT (active high)
    DOCK_DETECT = _env_int("PIN_DOCK_DETECT", 23)      # CH224K PG (active low: Power Good)
    CAMERA_LIGHT_PWM = _env_int("PIN_CAM_LIGHT", 13)   # PWM1 (Hardware-PWM)

    # Schleifen-Relais Omron G6K-2F-Y (VORSCHLAG – im Schaltplan nicht festgelegt)
    RELAY_LOOP_POWER_24V = _env_int("PIN_RELAY_LOOP_PWR", 5)   # aus = Passiv (sicher)
    RELAY_SOURCE_SINK = _env_int("PIN_RELAY_SRC_SINK", 6)      # aus = Sink
    RELAY_HART_RESISTOR = _env_int("PIN_RELAY_250R", 22)       # 250-Ohm-Bürde zuschalten


# ---------------------------------------------------------------------------
# I2C1 (/dev/i2c-1)
# ---------------------------------------------------------------------------
I2C_BUS = _env_int("I2C_BUS", 1)


class I2CAddr:
    INA226 = 0x40
    BQ76930 = 0x08
    DS3231 = 0x68
    DRV2605L = 0x5A
    LIS3DH = 0x18


# ---------------------------------------------------------------------------
# HART-Modem
# ---------------------------------------------------------------------------
# ACHTUNG CM4: /dev/ttyAMA0 (PL011) ist standardmäßig an Bluetooth gebunden.
# Da 8E1 (Parität!) benötigt wird, ist der Mini-UART (ttyS0) NICHT geeignet.
# Lösung: dtoverlay=miniuart-bt in config.txt -> PL011 wird für GPIO14/15 frei,
# Bluetooth (BLE-Drucker) läuft über den Mini-UART weiter.
HART_SERIAL_PORT = os.environ.get("HART_SERIAL_PORT", "/dev/ttyAMA0")
HART_BAUDRATE = 1200
HART_PRIMARY_MASTER = _env_bool("HART_PRIMARY_MASTER", False)  # Handheld = Secondary Master
HART_RETRIES = _env_int("HART_RETRIES", 3)
HART_RESPONSE_TIMEOUT_S = _env_float("HART_RESPONSE_TIMEOUT", 0.40)
HART_BUS_IDLE_S = _env_float("HART_BUS_IDLE", 0.080)            # ~RT2 (8 Zeichenzeiten)
HART_BUS_IDLE_MAX_WAIT_S = _env_float("HART_BUS_IDLE_MAX_WAIT", 2.5)
SAFE_MODE_DEFAULT = True  # Beim Start IMMER Nur-Lesen (24/7-Anlagen)


# ---------------------------------------------------------------------------
# Batterie / BMS (8S LiFePO4, BQ76930)
# ---------------------------------------------------------------------------
class Battery:
    CELLS = 8
    # BQ76930 hat 10 Zelleingänge. Bei 8 Zellen werden laut Datenblatt VC4 und
    # VC9 gebrückt -> genutzte physische Positionen (0-basiert):
    CELL_MAP = (0, 1, 2, 4, 5, 6, 7, 9)
    CAPACITY_AH = _env_float("BAT_CAPACITY_AH", 6.0)
    NOMINAL_CELL_V = 3.2
    RSENSE_MOHM = _env_float("BAT_RSENSE_MOHM", 5.0)
    USE_CRC = _env_bool("BMS_USE_CRC", True)    # BQ7693000x-Varianten mit CRC

    OV_CELL_V = 3.65          # Hardware-Überspannungsschutz
    UV_CELL_V = 2.50          # Hardware-Unterspannungsschutz
    OCD_A = 8.0               # Überstrom Entladen
    SCD_A = 20.0              # Kurzschluss

    CRITICAL_SOC = 5.0        # -> geordneter Shutdown
    WARN_SOC = 15.0
    CRITICAL_CELL_V = 2.90
    DRIFT_WARN_MV = 30.0
    DRIFT_ALARM_MV = 80.0

    # Optionales passives Top-Balancing über BQ CELLBAL (zusätzlich zu ETA3000)
    PASSIVE_BALANCING = _env_bool("BAT_PASSIVE_BAL", False)
    PASSIVE_BAL_START_V = 3.45
    ETA3000_COUNT = 7


# ---------------------------------------------------------------------------
# True-mA-Messung (INA226)
# ---------------------------------------------------------------------------
class CurrentMeter:
    # ACHTUNG: Der INA226 misst am Shunt max. ±81,92 mV. Mit 10 Ω (Spezifikation)
    # endet der Messbereich bei 8,19 mA! Empfehlung: 3,3 Ω 0,1 % (24 mA -> 79,2 mV).
    SHUNT_OHM = _env_float("INA226_SHUNT_OHM", 10.0)
    MAX_EXPECTED_MA = 24.0
    STABLE_WINDOW_S = 2.0          # Stabilitätsfenster für Kalibrierpunkte
    STABLE_TOLERANCE_MA = 0.010    # max. Spannweite im Fenster (10 µA = 0,06 % Spanne)
    CAL_FILE = DATA_DIR / "ina226_calibration.json"
    CAL_INTERVAL_DAYS = 365        # Prüfmittel-Rekalibrierung
    FOREIGN_VOLTAGE_LIMIT_V = 3.0  # Fremdspannung -> 24-V-Speisung verboten


# ---------------------------------------------------------------------------
# Uhrzeit / Audio / Haptik
# ---------------------------------------------------------------------------
TIMEZONE = os.environ.get("HART_TZ", "Europe/Berlin")
RTC_DEVICE = os.environ.get("RTC_DEVICE", "/dev/rtc0")
MIN_PLAUSIBLE_YEAR = 2025          # Systemzeit davor gilt als "nicht gestellt"

AUDIO_DEVICE = os.environ.get("AUDIO_DEVICE", "default")   # z.B. "plughw:CARD=MAX98357A"
SOUND_DIR = DATA_DIR / "sounds"
FEEDBACK_SETTINGS_FILE = DATA_DIR / "feedback_settings.json"
HAPTIC_ACTUATOR = os.environ.get("HAPTIC_ACTUATOR", "ERM")  # "ERM" oder "LRA"

# Automatisches Zurückschalten der Schleife in den sicheren Passivmodus
LOOP_AUTO_PASSIVE_MIN = _env_float("LOOP_AUTO_PASSIVE_MIN", 30.0)


# Soft-Power: Empfohlen ist dtoverlay=gpio-poweroff,gpiopin=25,active_low=1
# -> der Kernel hält GPIO25 bis zum letzten Moment des Shutdowns HIGH.
POWER_LATCH_VIA_OVERLAY = _env_bool("POWER_LATCH_VIA_OVERLAY", True)


# ---------------------------------------------------------------------------
# UI / Theme (Modern Industrial Dark Mode)
# ---------------------------------------------------------------------------
class Theme:
    BG = "#0D1117"
    CARD = "#161B22"
    BORDER = "#30363D"
    CYAN = "#00E5FF"
    GREEN = "#00E676"
    AMBER = "#FFAB00"
    RED = "#FF1744"
    TEXT = "#E6EDF3"
    TEXT_MUTED = "#8B949E"


WEB_HOST = os.environ.get("WEB_HOST", "127.0.0.1")
WEB_PORT = _env_int("WEB_PORT", 8080)

TELEMETRY_INTERVAL_S = 15
