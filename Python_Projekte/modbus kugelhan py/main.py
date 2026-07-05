# main.py - v1.2.2
import machine
import network
import time
import _thread
from config import settings, state, load_calibration, PIN_W5500_CS, PIN_W5500_RST
import motor
import network_services
import sensors

def init_ethernet():
    """Initialisiert den W5500-Ethernet-Controller des Pico-PoE Boards über SPI."""
    try:
        # Der W5500 liegt hardwareseitig fest auf SPI0
        spi_eth = machine.SPI(0, baudrate=20000000, polarity=0, phase=0)
        cs_eth = machine.Pin(PIN_W5500_CS, machine.Pin.OUT)
        rst_eth = machine.Pin(PIN_W5500_RST, machine.Pin.OUT)
        
        # WIZNET5K Treiber initialisieren
        nic = network.WIZNET5K(spi_eth, cs_eth, rst_eth)
        nic.active(True)
        
        # Statische IP-Konfiguration zuweisen
        nic.ifconfig((settings["ip"], settings["subnet"], settings["gateway"], settings["dns"]))
        
        # Auf Netzwerkverbindung warten
        while not nic.isconnected():
            time.sleep_ms(100)
            
        print(f"[Ethernet] Erfolgreich initialisiert. IP: {nic.ifconfig()[0]}")
        return nic
    except Exception as e:
        print(f"[Ethernet] Kritischer Init-Fehler: {e}")
        return None

# =========================================================================
# SYSTEMSTART & THREAD-STEUERUNG
# =========================================================================
print("[System] Starte modulare Ventilsteuerung...")

# 1. Gespeicherte Kalibrierwerte aus dem Flash laden
load_calibration()

# 2. Netzwerk-Interface hochfahren
nic = init_ethernet()
state["last_modbus_activity"] = time.ticks_ms()

# 3. Hintergrund-Threads starten (Netzwerk- und Schutzfunktionen)
print("[System] Starte Hintergrund-Threads...")
_thread.start_new_thread(network_services.watchdog_check_loop, ())
_thread.start_new_thread(network_services.modbus_server_loop, ())
_thread.start_new_thread(network_services.web_server_loop, ())

# 4. Der Haupt-Thread (Core 0) übernimmt die zeitkritische Motor-Regelschleife
# Dies verhindert Ressourcen-Konflikte und sorgt für präzises Anhalten am Endschalter.
print("[System] Starte Motor-Regelschleife...")
motor.motor_control_loop()
