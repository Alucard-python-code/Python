# hardware_simulator.py
import sys
import time
import types

print("[Simulator] Initialisiere Hardware-Simulation für Windows/PC...")

# Wir erstellen ein virtuelles 'machine'-Modul für den PC
machine = types.ModuleType('machine')

# Simulation der Hardware-Zustände
sim_poti_val = 30000  # Startwert in der Mitte (ca. 50%)
sim_motor_state = 0   # 0=Stop, 1=Open, 2=Close

class MockPin:
    OUT = 1
    IN = 2
    PULL_UP = 3
    def __init__(self, pin_num, mode=None, pull=None):
        self.pin_num = pin_num
    def value(self, val=None):
        global sim_poti_val
        # Endschalter ZU (Pin 7)
        if self.pin_num == 7:
            return 0 if sim_poti_val <= 10500 else 1
        # Endschalter AUF (Pin 8)
        if self.pin_num == 8:
            return 0 if sim_poti_val >= 49500 else 1
        return 1

class MockADC:
    def __init__(self, pin): pass
    def read_u16(self):
        global sim_poti_val, sim_motor_state
        # Wenn der Motor läuft, verändere den Poti-Wert virtuell
        if sim_motor_state == 1 and sim_poti_val < 50000:
            sim_poti_val += 800  # Simuliere Auffahren
        elif sim_motor_state == 2 and sim_poti_val > 10000:
            sim_poti_val -= 800  # Simuliere Zufahren
        return sim_poti_val

class MockPWM:
    def __init__(self, pin):
        self.pin = pin
    def freq(self, hz): pass
    def duty_u16(self, duty):
        global sim_motor_state
        if duty > 0:
            # Pin 2 ist Motor Open, Pin 3 ist Motor Close
            sim_motor_state = 1 if self.pin.pin_num == 2 else 2
        else:
            # Wenn die Bremse/Stopp aktiv ist
            if duty == 0 and sim_motor_state != 0:
                # Nur stoppen, wenn dieser spezifische Pin abgeschaltet wird
                if (self.pin.pin_num == 2 and sim_motor_state == 1) or (self.pin.pin_num == 3 and sim_motor_state == 2):
                    sim_motor_state = 0

class MockSPI:
    def __init__(self, id, **kwargs): pass
    def write(self, buf): pass
    def read(self, nbytes):
        # Gibt ein simuliertes Bytearray für ca. 22.5 °C an den PT1000 zurück
        return b'\x3e\x20'

# MicroPython Zeit-Funktionen anpassen
def ticks_ms(): return int(time.time() * 1000)
def ticks_diff(t1, t2): return t1 - t2
def sleep_us(us): time.sleep(us / 1000000.0)
def sleep_ms(ms): time.sleep(ms / 1000.0)

# Befülle das virtuelle machine-Modul
machine.Pin = MockPin
machine.ADC = MockADC
machine.PWM = MockPWM
machine.SPI = MockSPI
time.ticks_ms = ticks_ms
time.ticks_diff = ticks_diff
time.sleep_us = sleep_us
time.sleep_ms = sleep_ms
machine.reset = lambda: print("[Simulator] RESET TRIGGERED! Beende Simulation.") or sys.exit(0)

# Virtuelles 'network'-Modul für den PC
network = types.ModuleType('network')
class MockWIZNET5K:
    def __init__(self, spi, cs, rst): pass
    def active(self, state): pass
    def ifconfig(self, config=None):
        return ("127.0.0.1", "255.255.255.0", "127.0.0.1", "127.0.0.1")
    def isconnected(self): return True

network.WIZNET5K = MockWIZNET5K
network.LAN = MockWIZNET5K

# Module in den Python-Systempfad injizieren, bevor die echten Skripte laden!
sys.modules['machine'] = machine
sys.modules['network'] = network
sys.modules['time'] = time
