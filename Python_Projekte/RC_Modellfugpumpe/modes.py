import time
from config import sys_settings
from hardware import pump, sensors

def display_clear():
    print("\n" * 2 + "="*40)

def show_live_data(model, speed, mode):
    p_ist = sensors.get_pressure_mbar()
    vol_ist = sensors.get_volume_ml()
    vol_str = f"{vol_ist/1000.0:.2f}L" if vol_ist >= 1000.0 else f"{int(vol_ist)}ml"
        
    display_clear()
    print(f"MODUS: {mode.upper()} | {model.name}")
    print(f"Druck Soll/Ist: {model.max_press} / {p_ist:.1f} mbar")
    print(f"Menge geflossen: {vol_str}")
    print(f"Pumpe Geschw.:   {speed} %")

def run_manuell():
    speed = 0
    direction = "tanken"
    while True:
        display_clear()
        print("--- MANUELLER MODUS ---")
        print(f"Richtung: {direction.upper()}")
        print(f"Geschw.:  {speed} %")
        print("[e] Zurück | [w/s] Ändern | [d] Richtung")
        
        cmd = input("Eingabe: ").lower()
        if cmd == 'e':
            pump.stop_pump()
            break
        elif cmd == 'w': speed = min(100, speed + 10)
        elif cmd == 's': speed = max(0, speed - 10)
        elif cmd == 'd': direction = "enttanken" if direction == "tanken" else "tanken"
        
        pump.set_speed(speed, direction)

def run_automatik():
    display_clear()
    print("Modell wählen:")
    valid_models = []
    for i, m in enumerate(sys_settings.models):
        if m.name != "Leer":
            print(f"[{len(valid_models)}] {m.name} ({m.tank_type})")
            valid_models.append(m)
            
    if not valid_models:
        input("Keine Modelle angelegt! Enter...")
        return
            
    try:
        idx = int(input("Modell-Nummer eingeben: "))
        model = valid_models[idx]
    except:
        return

    action = input("Aktion: [1] Tanken [2] Enttanken [3] Abbrechen: ")
    if action == "1":
        execute_auto_tank(model, "tanken")
    elif action == "2":
        execute_auto_tank(model, "enttanken")

def execute_auto_tank(model, mode):
    sensors.reset_volume()
    pump.set_speed(40, mode)
    
    # Beutel-Logik: Erst zeitbasiert enttanken
    if model.tank_type == "Beutel" and mode == "tanken":
        print(f"Beutel-Modus: Enttanke zuerst für {model.defuel_time} Sek...")
        pump.set_speed(50, "enttanken")
        t_end = time.time() + model.defuel_time
        while time.time() < t_end:
            show_live_data(model, 50, "enttanken")
            time.sleep(0.5)
        pump.set_speed(40, "tanken")

    last_pressure = sensors.get_pressure_mbar()
    
    while True:
        current_press = sensors.get_pressure_mbar()
        show_live_data(model, 40, mode)
        
        if current_press >= model.max_press:
            print("\n[INFO] Maximaler Tankdruck erreicht!")
            break
            
        if model.tank_type == "Fest" and (current_press - last_pressure) > 15.0:
            print("\n[INFO] Rascher Druckanstieg erkannt! Tank ist voll.")
            break
            
        last_pressure = current_press
        time.sleep(0.2)
        
    pump.stop_pump()
    input("\nAktion beendet. Drücke Enter für Hauptmenü.")
