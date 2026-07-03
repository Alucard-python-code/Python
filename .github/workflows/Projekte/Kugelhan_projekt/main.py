#v1.2
import network
import time
import _thread
from config import settings, state, load_calibration # load_calibration hinzugefügt
import motor
import network_services
import sensors

def init_ethernet():
    nic = network.LAN()
    nic.active(True)
    nic.ifconfig((settings["ip"], settings["subnet"], settings["gateway"], settings["dns"]))
    print("Ethernet bereit. IP:", nic.ifconfig())

print("[System] Starte modulare Ventilsteuerung...")

# Zuerst permanent gespeicherte Kalibrierwerte aus dem Flash laden!
load_calibration()

init_ethernet()
state["last_modbus_activity"] = time.ticks_ms()

_thread.start_new_thread(motor.motor_control_loop, ())
_thread.start_new_thread(network_services.modbus_server_loop, ())
_thread.start_new_thread(network_services.watchdog_check_loop, ())
_thread.start_new_thread(network_services.web_server_loop, ())

while True:
    try:
        state["temperatur"] = sensors.read_pt1000_temperature()
    except Exception as e:
        print("Fehler PT1000:", e)
    time.sleep(1)
