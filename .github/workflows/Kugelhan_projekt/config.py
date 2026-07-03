import machine

# --- HARDWARE PIN-BELEGUNG ---
PIN_POTI = 26          # ADC0 für das 10k Ohm Positions-Poti
PIN_MOTOR_OPEN = 2     # H-Brücke: Richtung Öffnen
PIN_MOTOR_CLOSE = 3    # H-Brücke: Richtung Schließen
PIN_LED_GREEN = 4      # Status-LED: Alles i.O. / Bereit
PIN_LED_YELLOW = 5     # Status-LED: In Bewegung
PIN_LED_RED = 6        # Status-LED: Fehler / Watchdog

# SPI-Pins für den MAX31865 (PT1000 Wandler)
PIN_MAX_CS = 10
PIN_MAX_SCK = 13
PIN_MAX_MOSI = 11
PIN_MAX_MISO = 12

# --- SYSTEM-EINSTELLUNGEN ---
settings = {
    "ip": "192.168.1.150",
    "subnet": "255.255.255.0",
    "gateway": "192.168.1.1",
    "dns": "192.168.1.1",
    "modbus_port": 502,
    "web_port": 80,
    "watchdog_timeout_ms": 60000  # 60 Sekunden Standard
}

# --- LIVE STATE (Globale Laufzeitdaten) ---
state = {
    "soll_oeffnung": 0,
    "ist_oeffnung": 0,
    "temperatur": 0.0,
    "status_code": 0,  # 0=Bereit, 1=Öffnet, 2=Schließt
    "fehler_code": 0,  # 0=Kein, 1=Poti, 2=Watchdog, 3=Blockiert
    "last_modbus_activity": 0,
    "watchdog_triggered": False
}
