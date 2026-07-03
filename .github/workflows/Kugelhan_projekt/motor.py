import machine
import time
from config import PIN_MOTOR_OPEN, PIN_MOTOR_CLOSE, PIN_LED_GREEN, PIN_LED_YELLOW, PIN_LED_RED, state, settings
from sensors import read_position_percent

# Pins konfigurieren
m_open = machine.Pin(PIN_MOTOR_OPEN, machine.Pin.OUT)
m_close = machine.Pin(PIN_MOTOR_CLOSE, machine.Pin.OUT)
led_g = machine.Pin(PIN_LED_GREEN, machine.Pin.OUT)
led_y = machine.Pin(PIN_LED_YELLOW, machine.Pin.OUT)
led_r = machine.Pin(PIN_LED_RED, machine.Pin.OUT)

def stop_motor():
    m_open.value(0)
    m_close.value(0)
    time.sleep_ms(300) # Kurzschlussschutz-Pause

def update_leds():
    if state["fehler_code"] != 0:
        led_r.value(1); led_g.value(0); led_y.value(0)
    elif state["status_code"] != 0:
        led_r.value(0); led_g.value(0); led_y.value(1)
    else:
        led_r.value(0); led_g.value(1); led_y.value(0)

def motor_control_loop():
    HYSTERESE = 2
    last_pos_change = time.ticks_ms()
    prev_ist = -1
    
    while True:
        poti = read_position_percent()
        if poti != -1:
            state["ist_oeffnung"] = poti
            if state["fehler_code"] == 1: state["fehler_code"] = 0

        if state["watchdog_triggered"] or state["fehler_code"] != 0:
            stop_motor()
            state["status_code"] = 0
            update_leds()
            time.sleep_ms(100)
            continue
            
        if state["status_code"] != 0 and time.ticks_diff(time.ticks_ms(), last_pos_change) > settings["motor_block_ms"]:
            state["fehler_code"] = 3 # Blockiert
            stop_motor()
            state["status_code"] = 0
            continue
            
        if state["status_code"] != 0 and time.ticks_diff(time.ticks_ms(), last_pos_change) > 3000:
            state["fehler_code"] = 3 # Blockiert
            stop_motor()
            state["status_code"] = 0
            continue

        abweichung = state["soll_oeffnung"] - state["ist_oeffnung"]
        
        if abs(abweichung) <= HYSTERESE:
            if state["status_code"] != 0:
                stop_motor()
                state["status_code"] = 0
        elif abweichung > 0:
            if state["status_code"] != 1:
                stop_motor(); m_open.value(1); state["status_code"] = 1
                last_pos_change = time.ticks_ms()
        elif abweichung < 0:
            if state["status_code"] != 2:
                stop_motor(); m_close.value(1); state["status_code"] = 2
                last_pos_change = time.ticks_ms()
                
        update_leds()
        time.sleep_ms(50)
