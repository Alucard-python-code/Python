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
    time.sleep(10) # Exakt 10 Sekunden Anzeige laut Pflichtenheft

def main():
    sys_settings.load_from_flash()
    display_welcome()
    
    if not menus.check_pin_dialog():
        hardware.lcd.clear()
        hardware.lcd.move_to(0, 1); hardware.lcd.putstr("ZUGRIFF VERWEIGERT!")
        return

    options = ["Automatik", "Manuell", "Einstellungen"]
    idx = 0
    
    while True:
        hardware.lcd.clear()
        hardware.lcd.move_to(0, 0); hardware.lcd.putstr("--- HAUPTMENUE ---")
        for i, opt in enumerate(options):
            hardware.lcd.move_to(0, i+1)
            prefix = "> " if i == idx else "  "
            hardware.lcd.putstr(f"{prefix}{opt}")
        
        cmd = input("Navigation [w/s], Bestaetigen [e]: ").lower()
        if cmd == 'w': idx = (idx - 1) % len(options)
        elif cmd == 's': idx = (idx + 1) % len(options)
        elif cmd == 'e':
            if options[idx] == "Manuell": 
                modes.run_manuell()
            elif options[idx] == "Automatik": 
                modes.run_automatik()
            elif options[idx] == "Einstellungen": 
                menus.menu_einstellungen()

if __name__ == "__main__":
    main()
