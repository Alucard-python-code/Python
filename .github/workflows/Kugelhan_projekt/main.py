import network
import time
import _thread
from config import settings, state
import motor
import network_services
import sensors

def init_ethernet():
    nic = network.LAN()
    nic.active(True)
    nic.ifconfig((settings["ip"], settings["subnet"], settings["gateway"], settings["dns"]))
    print("Ethernet bereit. IP:", nic.ifconfig()[0])

print("[System] Starte modulare Ventilsteuerung...")
init_ethernet()

# Zeitstempel für Watchdog direkt beim Start initialisieren
state["last_modbus_activity"] = time.ticks_ms()

# Threads für parallele Aufgaben starten
_thread.start_new_thread(motor.motor_control_loop, ())
_thread.start_new_thread(network_services.modbus_server_loop, ())
_thread.start_new_thread(network_services.watchdog_check_loop, ())
_thread.start_new_thread(network_services.web_server_loop, ())

# Der Hauptthread liest im Sekundentakt die Temperatur
while True:
    try:
        state["temperatur"] = sensors.read_pt1000_temperature()
    except Exception as e:
        print("Fehler PT1000:", e)
    time.sleep(1)
