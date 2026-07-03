import machine
import json

# =========================================================================
# 1. HARDWARE PIN-BELEGUNG
# =========================================================================
PIN_POTI = 26          
PIN_MOTOR_OPEN = 2     
PIN_MOTOR_CLOSE = 3    
PIN_LED_GREEN = 4      
PIN_LED_YELLOW = 5     
PIN_LED_RED = 6        

# NEU: Pins für die mechanischen Endschalter (NC gegen GND)
PIN_LIMIT_CLOSE = 7    # Endschalter ZU
PIN_LIMIT_OPEN = 8     # Endschalter AUF

PIN_MAX_CS = 10
PIN_MAX_SCK = 13
PIN_MAX_MOSI = 11
PIN_MAX_MISO = 12

# =========================================================================
# 2. SYSTEM-EINSTELLUNGEN
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
# 3. LIVE STATE
# =========================================================================
state = {
    "soll_oeffnung": 0,          
    "ist_oeffnung": 0,           
    "poti_raw_live": 0,          
    "poti_min": 10000,           
    "poti_max": 50000,           
    "temperatur": 0.0,           
    "status_code": 0,            # 0=Bereit, 1=Oeffnet, 2=Schliesst
    "fehler_code": 0,            # 0=Kein, 1=Poti, 2=Watchdog, 3=Blockiert
    "last_modbus_activity": 0,   
    "watchdog_triggered": False, 
    "logged_in_users": [],       
    
    # NEU: Zustände für die vollautomatische Kalibrierung
    "auto_calib_active": False,
    "auto_calib_step": 0        # 0=Inaktiv, 1=Fahre zu ZU, 2=Fahre zu AUF
}

# =========================================================================
# 4. PERMANENTE SPEICHER-FUNKTIONEN
# =========================================================================
def save_calibration():
    try:
        with open("calib.txt", "w") as f:
            json.dump({"min": state["poti_min"], "max": state["poti_max"]}, f)
        print("[Calib] Werte permanent gespeichert:", state["poti_min"], state["poti_max"])
    except Exception as e:
        print("[Calib] Fehler beim Speichern:", e)

def load_calibration():
    try:
        with open("calib.txt", "r") as f:
            data = json.load(f)
            state["poti_min"] = data["min"]
            state["poti_max"] = data["max"]
        print("[Calib] Werte erfolgreich geladen:", state["poti_min"], state["poti_max"])
    except:
        print("[Calib] Keine Kalibrierdatei gefunden. Nutze Defaults.")

def save_password(new_pwd):
    try:
        with open("pwd.txt", "w") as f:
            f.write(new_pwd)
        print("[Auth] Passwort erfolgreich geändert.")
    except Exception as e:
        print("[Auth] Fehler beim Speichern des Passworts:", e)

def load_password():
    try:
        with open("pwd.txt", "r") as f:
            pwd = f.read().strip()
            if len(pwd) >= 8:
                return pwd
    except:
        pass
    return "123456789"
