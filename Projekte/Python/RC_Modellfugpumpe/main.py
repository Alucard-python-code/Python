import time
from config import sys_settings
import hardware
import menus
import modes

def display_welcome():
    hardware.lcd.clear()
    hardware.lcd.move_to(0, 0); hardware.lcd.putstr("=== TANKSTATION ===")
    hardware.lcd.move_to(0, 1); hardware.lcd.putstr(f"Pilot: {sys_settings.owner_name[:13]}")
    hardware.lcd.move_to(0, 2); hardware.lcd.putstr(f"Adr: {sys_settings.owner_address[:15]}")
    hardware.lcd.move_to(0, 3); hardware.lcd.putstr("Bitte warten (10s)..")
    time.sleep(10)

def main():
    display_welcome()
    sys_settings.load_from_flash()
    
    if not menus.check_pin_dialog():
        hardware.lcd.clear()
        hardware.lcd.move_to(0, 1); hardware.lcd.putstr("ZUGRIFF VERWEIGERT!")
        return

    options = ["Automatik", "Manuell", "Einstellungen"]
    hardware.encoder.set(min_val=0, max_val=len(options)-1, value=0)
    
    last_idx = -1

    while True:
        idx = hardware.encoder.value()
        
        if idx != last_idx:
            hardware.lcd.clear()
            hardware.lcd.move_to(0, 0); hardware.lcd.putstr("--- HAUPTMENUE ---")
            for i, opt in enumerate(options):
                hardware.lcd.move_to(0, i+1)
                prefix = "> " if i == idx else "  "
                hardware.lcd.putstr(f"{prefix}{opt}")
            last_idx = idx

        if hardware.encoder.is_pressed():
            time.sleep(0.3)
            selected_option = options[idx]
            if selected_option == "Manuell":
                modes.run_manuell()
            elif selected_option == "Automatik":
                modes.run_automatik()
            elif selected_option == "Einstellungen":
                menus.menu_einstellungen()
            
            hardware.encoder.set(min_val=0, max_val=len(options)-1, value=idx)
            last_idx = -1

        time.sleep(0.05)

if __name__ == "__main__":
    main()