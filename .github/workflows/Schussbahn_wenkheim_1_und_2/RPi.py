# RPi.py (Simuliert das Raspberry Pi GPIO-Modul auf dem Windows-PC)
import types
import sys
import time

# Wir erstellen ein virtuelles GPIO-Modul
GPIO = types.ModuleType('GPIO')

# Konstanten für die App bereitstellen
GPIO.BCM = 11
GPIO.OUT = 1
GPIO.IN = 2
GPIO.PUD_UP = 3

# Virtueller Zustand der Hardware auf dem PC
# 0 = Stand, 100 = Kugelfang
_wagen_position = 0.0  
_pin_states = {}       # Speichert, welches Relais gerade an/aus ist

def setmode(mode):
    pass

def setwarnings(state):
    pass

def setup(pin, mode, pull_up_down=None):
    if mode == GPIO.OUT:
        _pin_states[pin] = True # HIGH = AUS im Startzustand

def output(pin, state):
    _pin_states[pin] = state

def input(pin):
    global _wagen_position
    
    # 1. AUSGÄNGE AUSWERTEN & BEWEGUNG SIMULIEREN
    # Pins: 26=Rechts, 19=Links, 13=Langsam, 6=Schnell
    # Relais schalten bei False (LOW) ein!
    rechts = not _pin_states.get(26, True)
    links = not _pin_states.get(19, True)
    langsam = not _pin_states.get(13, True)
    schnell = not _pin_states.get(6, True)
    
    speed = 0.0
    if schnell:
        speed = 2.0  # Schnelle Bewegung
    elif langsam:
        speed = 0.5  # Langsame Bewegung
        
    if rechts and not links:
        _wagen_position = min(_wagen_position + speed, 100.0)
    elif links and not rechts:
        _wagen_position = max(_wagen_position - speed, 0.0)

    # 2. EINGÄNGE AN DIE APP ZURÜCKGEBEN
    # Pin 18: Motorschutz (1 = Alles okay)
    if pin == 18:
        return 1
        
    # Pin 10: Endschalter Startposition
    # Er ist gedrückt (1), wenn der Wagen am Stand (Position <= 0) angekommen ist
    if pin == 10:
        return 1 if _wagen_position <= 0.0 else 0
        
    # Feedback-Pins für die Schütze (Spiegeln einfach den Zustand)
    if pin == 12: return 1 if schnell else 0
    if pin == 16: return 1 if langsam else 0
    if pin == 20: return 1 if links else 0
    if pin == 21: return 1 if rechts else 0
    
    return 0

def cleanup():
    pass

# Methoden an das virtuelle Modul binden
GPIO.setmode = setmode
GPIO.setwarnings = setwarnings
GPIO.setup = setup
GPIO.output = output
GPIO.input = input
GPIO.cleanup = cleanup

# Das Modul in das System injizieren
sys.modules['RPi'] = types.ModuleType('RPi')
sys.modules['RPi.GPIO'] = GPIO
