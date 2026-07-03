import machine
import time
from config import PIN_MOTOR_OPEN, PIN_MOTOR_CLOSE, PIN_LED_GREEN, PIN_LED_YELLOW, PIN_LED_RED, state, settings
from sensors import read_position_percent

# Die Motorpins werden als PWM mit 1000 Hz initialisiert (Frequenz fuer H-Bruecken optimal)
m_open_pwm = machine.PWM(machine.Pin(PIN_MOTOR_OPEN))
m_open_pwm.freq(1000)
m_open_pwm.duty_u16(0) # 0% Start-Leistung

m_close_pwm = machine.PWM(machine.Pin(PIN_MOTOR_CLOSE))
m_close_pwm.freq(1000)
m_close_pwm.duty_u16(0) # 0% Start-Leistung

led_g = machine.Pin(PIN_LED_GREEN, machine.Pin.OUT)
led_y = machine.Pin(PIN_LED_YELLOW, machine.Pin.OUT)
led_r = machine.Pin(PIN_LED_RED, machine.Pin.OUT)

def stop_motor():
    """Bremst den Motor sanft aus und schaltet ihn stromlos."""
    m_open_pwm.duty_u16(0)
    m_close_pwm.duty_u16(0)
    time.sleep_ms(300) # Kurzschlussschutz-Pause fuer die H-Bruecke

def drive_motor_soft(direction_pwm):
    """
    Punkt 3: Sanfter Motorstart per PWM-Rampe.
    Erhoeht die Kraft innerhalb von 300ms stufenweise von 0 auf 100%.
    """
    # 0 bis 65535 entspricht 0% bis 100% Duty Cycle am RP2040
    for duty in range(0, 65536, 4096): 
        direction_pwm.duty_u16(duty)
        time.sleep_ms(20)

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

        # Sicherheitsstopp bei Fehlern oder Watchdog
        if state["watchdog_triggered"] or state["fehler_code"] != 0:
            stop_motor()
            state["status_code"] = 0
            update_leds()
            time.sleep_ms(100)
            continue
            
        # Blockade-Ueberwachung (Punkt 2: Zeit ueber settings["motor_block_ms"] regelbar)
        if state["ist_oeffnung"] != prev_ist:
            last_pos_change = time.ticks_ms()
            prev_ist = state["ist_oeffnung"]
            
        if state["status_code"] != 0 and time.ticks_diff(time.ticks_ms(), last_pos_change) > settings["motor_block_ms"]:
            state["fehler_code"] = 3 # Blockiert
            stop_motor()
            state["status_code"] = 0
            continue

        abweichung = state["soll_oeffnung"] - state["ist_oeffnung"]
        
        if abs(abweichung) <= HYSTERESE:
            if status := state["status_code"] != 0:
                stop_motor()
                state["status_code"] = 0
        elif abweichung > 0:
            if state["status_code"] != 1:
                stop_motor()
                state["status_code"] = 1
                last_pos_change = time.ticks_ms()
                drive_motor_soft(m_open_pwm) # Sanfter Anlauf in Richtung Oeffnen
        elif abweichung < 0:
            if state["status_code"] != 2:
                stop_motor()
                state["status_code"] = 2
                last_pos_change = time.ticks_ms()
                drive_motor_soft(m_close_pwm) # Sanfter Anlauf in Richtung Schliessen
                
        update_leds()
        time.sleep_ms(50)
