import time
from config import sys_settings, ModelConfig
from hardware import sensors, pump

def display_clear():
    print("\n" * 2 + "="*40)

def check_pin_dialog():
    if sys_settings.system_locked:
        print("SYSTEM GESPERRT! PUK benötigt.")
        if input("Geben Sie den PUK ein: ") == sys_settings.puk:
            sys_settings.system_locked = False
            sys_settings.pin_attempts = 0
            sys_settings.pin = input("Neuen PIN festlegen: ")
            sys_settings.save_to_flash()
            return True
        return False

    while sys_settings.pin_attempts < 3:
        if not sys_settings.pin_lock_enabled:
            return True
        pin_in = input("PIN eingeben zum Entsperren: ")
        if pin_in == sys_settings.pin:
            sys_settings.pin_attempts = 0
            return True
        sys_settings.pin_attempts += 1
        print(f"Falscher PIN! Versuch {sys_settings.pin_attempts}/3")
        
    sys_settings.system_locked = True
    sys_settings.save_to_flash()
    print("System gesperrt.")
    return False

def menu_einstellungen():
    while True:
        display_clear()
        print("--- EINSTELLUNGEN ---")
        print("[1] Modell anlegen   [2] Modell löschen")
        print("[3] Durchfluss kalb. [4] Druck Nullabgleich")
        print("[5] Besitzer ändern  [6] PIN ändern")
        print("[7] PIN-Sperre umschalten [8] Zurück")
        
        choice = input("Auswahl: ")
        if choice == "8": break
        elif choice == "1": cal_create_model()
        elif choice == "2": cal_delete_model()
        elif choice == "3": cal_flow_sensor()
        elif choice == "4": cal_pressure_zero()
        elif choice == "5": change_owner_info()
        elif choice == "6": change_pin()
        elif choice == "7": toggle_pin_lock()

def cal_create_model():
    display_clear()
    idx = int(input("Speicherplatz (0-9): "))
    name = input("Modellname: ")
    size = float(input("Tankgröße in Litern: "))
    ttype = "Beutel" if input("Typ: [1] Beutel [2] Fest: ") == "1" else "Fest"
    
    def_press = 100 if ttype == "Beutel" else 150
    press = int(input(f"Max Druck in mbar (Standard {def_press}): ") or def_press)
    
    d_time = 140 if ttype == "Beutel" else 0
    if ttype == "Beutel":
        d_time = int(input("Enttankzeit in Sek (Standard 140): ") or 140)
        
    sys_settings.models[idx] = ModelConfig(name, size, ttype, press, d_time)
    sys_settings.save_to_flash()
    print("Modell erfolgreich gespeichert!")
    time.sleep(1.5)

def cal_delete_model():
    display_clear()
    idx = int(input("Lösche Speicherplatz (0-9): "))
    if input(f"Modell {sys_settings.models[idx].name} wirklich löschen? [j/n]: ").lower() == 'j':
        sys_settings.models[idx] = ModelConfig()
        sys_settings.save_to_flash()
        print("Gelöscht.")
    time.sleep(1)

def cal_pressure_zero():
    display_clear()
    print("DRUCKSENSOR NULLABGLEICH\nSensor muss frei sein.")
    if input("[1] Abgleich [2] Abbruch: ") == "1":
        raw_adc = sensors.adc.read_u16()
        voltage = (raw_adc / 65535.0) * 3.3
        sys_settings.pressure_offset = (voltage / 3.3) * 5.0 * 68.9476
        sys_settings.save_to_flash()
        print("Nullpunkt kalibriert.")
    time.sleep(1.5)

def cal_flow_sensor():
    display_clear()
    print("DURCHFLUSS KALIBRIEREN\nBitte exakt 1.000 ml umpumpen.")
    input("Starten mit Enter...")
    sensors.reset_volume()
    pump.set_speed(30, "tanken")
    input("Stoppen mit Enter bei Erreichen von 1L...")
    pump.stop_pump()
    
    pulses = sensors.pulse_count
    if pulses > 0:
        sys_settings.pulses_per_ml = pulses / 1000.0
        sys_settings.save_to_flash()
        print(f"Erfolg: {sys_settings.pulses_per_ml:.3f} Pulse/ml")
    else:
        print("Fehler: Keine Pulse!")
    time.sleep(2)

def change_owner_info():
    if not check_pin_dialog(): return
    display_clear()
    sys_settings.owner_name = input("Neuer Name: ") or sys_settings.owner_name
    sys_settings.owner_address = input("Neue Adresse: ") or sys_settings.owner_address
    sys_settings.save_to_flash()
    print("Besitzerdaten geändert.")
    time.sleep(1.5)

def change_pin():
    display_clear()
    old_pin = input("Alten PIN eingeben (oder PUK): ")
    if old_pin == sys_settings.pin or old_pin == sys_settings.puk:
        new_pin = input("Neuer PIN: ")
        if input("PIN bestätigen: ") == new_pin:
            sys_settings.pin = new_pin
            sys_settings.save_to_flash()
            print("PIN erfolgreich geändert.")
            return
    print("Fehler beim Ändern.")
    time.sleep(1.5)

def toggle_pin_lock():
    if not check_pin_dialog(): return
    sys_settings.pin_lock_enabled = not sys_settings.pin_lock_enabled
    sys_settings.save_to_flash()
    print(f"PIN-Abfrage beim Start ist jetzt: {'AKTIV' if sys_settings.pin_lock_enabled else 'INAKTIV'}")
    time.sleep(1.5)
