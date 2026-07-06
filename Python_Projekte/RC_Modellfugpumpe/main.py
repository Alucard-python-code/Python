import time
from config import sys_settings
import menus
import modes

def display_welcome():
    print("\n" * 5 + "="*40)
    print(f"   WILLKOMMEN AN DER TANKSTATION")
    print(f"   Besitzer: {sys_settings.owner_name}")
    print(f"   Adresse:  {sys_settings.owner_address}")
    print("="*40 + "\n")
    time.sleep(3) # Auf 3 Sekunden für schnelleren Testlauf im Terminal gekürzt

def main():
    # 1. Gespeicherte Einstellungen vom Flash-Speicher laden
    sys_settings.load_from_flash()
    
    # 2. Begrüßung anzeigen (Besitzer-Info)
    display_welcome()
    
    # 3. Sicherheits-PIN abfragen falls im Menü aktiviert
    if not menus.check_pin_dialog():
        print("Systemzugriff verweigert!")
        return

    # 4. Hauptmenü-Schleife
    options = ["Automatik", "Manuell", "Einstellungen"]
    idx = 0
    
    while True:
        modes.display_clear()
        print("--- HAUPTMENÜ ---")
        for i, opt in enumerate(options):
            prefix = "> " if i == idx else "  "
            print(f"{prefix}{opt}")
        print("="*40)
        
        cmd = input("Auswahl mit [w] (hoch), [s] (runter), [e] (Bestätigen): ").lower()
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
