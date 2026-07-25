import time
from config import sys_settings
from hardware import pump, sensors, lcd, encoder

def display_lines(l1="", l2="", l3="", l4=""):
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
        f"V:{vol_str} | Pmp: {speed}%"
    )

def run_manuell():
    speed = 0
    direction = "tanken"
    encoder.set(min_val=0, max_val=100, incr=10, value=speed)
    
    while True:
        speed = encoder.value()
        
        display_lines(
            "--- MANUELL ---",
            f"Richtung: {direction.upper()}",
            f"Geschw. {speed}%",
            "[Press] Exit/Dir"
        )
        
        pump.set_speed(speed, direction)
        
        if encoder.is_pressed():
            time.sleep(0.3)
            direction = "enttanken" if direction == "tanken" else "tanken"
            
        time.sleep(0.1)

def run_automatik():
    lcd.clear()
    lcd.move_to(0, 0); lcd.putstr("Modell waehlen:")
    valid_models = [m for m in sys_settings.models if m.name != "Leer"]
    
    if not valid_models:
        display_lines("Fehler:", "Keine Modelle", "angelegt!", "Weiter mit Klick")
        while not encoder.is_pressed():
            time.sleep(0.1)
        time.sleep(0.3)
        return

    encoder.set(min_val=0, max_val=len(valid_models)-1, incr=1, value=0)
    last_idx = -1

    while not encoder.is_pressed():
        idx = encoder.value()
        if idx != last_idx:
            lcd.clear()
            lcd.move_to(0, 0); lcd.putstr("Modell waehlen:")
            for i, m in enumerate(valid_models[:3]):
                lcd.move_to(0, i+1)
                prefix = "> " if i == idx else "  "
                lcd.putstr(f"{prefix}[{i}] {m.name[:14]}")
            last_idx = idx
        time.sleep(0.05)

    time.sleep(0.3)
    model = valid_models[encoder.value()]

    display_lines(model.name, "1: Tanken", "2: Enttanken", "Klick = Tanken")
    execute_auto_tank(model, "tanken")

def execute_auto_tank(model, mode):
    sensors.reset_volume()
    pump.set_speed(40, mode)
    
    if model.tank_type == "Beutel" and mode == "tanken":
        pump.set_speed(50, "enttanken")
        t_end = time.time() + model.defuel_time
        while time.time() < t_end:
            show_live_data(model, 50, "enttanken")
            if encoder.is_pressed():
                break
            time.sleep(0.5)
        pump.set_speed(40, "tanken")

    last_pressure = sensors.get_pressure_mbar()

    while True:
        current_press = sensors.get_pressure_mbar()
        show_live_data(model, 40, mode)
        
        if encoder.is_pressed():
            break
            
        if current_press >= model.max_press:
            display_lines("INFO:", "Maximaler Druck", "erreicht!", "Klick zum Beenden")
            break

        if model.tank_type == "Fest" and (current_press - last_pressure) > 15.0:
            display_lines("INFO:", "Druckanstieg!", "Tank voll.", "Klick zum Beenden")
            break

        last_pressure = current_press
        time.sleep(0.2)

    pump.stop_pump()
    while not encoder.is_pressed():
        time.sleep(0.1)
    time.sleep(0.3)