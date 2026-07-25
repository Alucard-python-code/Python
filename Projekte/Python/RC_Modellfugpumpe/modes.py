import time
from config import sys_settings
from hardware import pump, sensors, lcd

def display_lines(l1="", l2="", l3="", l4=""):
    """Hilfsfunktion zur sauberen Formatierung auf exakt 20 Zeichen pro Zeile"""
    lcd.clear()
    lcd.move_to(0, 0); lcd.putstr(f"{l1:<20}"[:20])
    lcd.move_to(0, 1); lcd.putstr(f"{l2:<20}"[:20])
    lcd.move_to(0, 2); lcd.putstr(f"{l3:<20}"[:20])
    lcd.move_to(0, 3); lcd.putstr(f"{l4:<20}"[:20])

def show_live_data(model, speed, mode):
    p_ist = sensors.get_pressure_mbar()
    vol_ist = sensors.get_volume_ml()
    vol_str = f"{vol_ist/1000.0:.2f}L" if vol_ist >= 1000.0 else f"{int(vol_ist)}ml"
    
    display_lines(
        f"MODUS: {mode.upper()}",
        f"{model.name[:20]}",
        f"P:{int(model.max_press)}/{int(p_ist)}mbar",
        f"V:{vol_str} | Pmp:{speed}%"
    )

def run_manuell():
    speed = 0
    direction = "tanken"
    while True:
        display_lines(
            "--- MANUELL ---",
            f"Richtung: {direction.upper()}",
            f"Geschw. : {speed} %",
            "[w/s]+- [d]Dir [e]Ex"
        )
        
        cmd = input("Eingabe: ").lower()
        if cmd == 'e':
            pump.stop_pump()
            break
        elif cmd == 'w': speed = min(100, speed + 10)
        elif cmd == 's': speed = max(0, speed - 10)
        elif cmd == 'd': direction = "enttanken" if direction == "tanken" else "tanken"
        
        pump.set_speed(speed, direction)

def run_automatik():
    lcd.clear()
    lcd.move_to(0, 0); lcd.putstr("Modell waehlen:")
    valid_models = [m for m in sys_settings.models if m.name != "Leer"]
    
    if not valid_models:
        display_lines("Fehler:", "Keine Modelle", "angelegt!", "Weiter mit Enter")
        input()
        return
        
    for i, m in enumerate(valid_models[:3]): # Maximal 3 Modelle auf einmal anzeigen
        lcd.move_to(0, i+1)
        lcd.putstr(f"[{i}] {m.name[:16]}")
            
    try:
        idx = int(input("Modell-Nummer eingeben: "))
        model = valid_models[idx]
    except:
        return

    display_lines(model.name, "1: Tanken", "2: Enttanken", "Auswahl eingeben:")
    action = input()
    if action == "1":
        execute_auto_tank(model, "tanken")
    elif action == "2":
        execute_auto_tank(model, "enttanken")

def execute_auto_tank(model, mode):
    sensors.reset_volume()
    pump.set_speed(40, mode)
    
    if model.tank_type == "Beutel" and mode == "tanken":
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
            display_lines("INFO:", "Maximaler Druck", "erreicht!", "Enter...")
            break
            
        if model.tank_type == "Fest" and (current_press - last_pressure) > 15.0:
            display_lines("INFO:", "Druckanstieg!", "Tank voll.", "Enter...")
            break
            
        last_pressure = current_press
        time.sleep(0.2)
        
    pump.stop_pump()
    input()
