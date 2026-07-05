# motor.py - v1.2.2
import machine
import time
from config import PIN_MOTOR_OPEN, PIN_MOTOR_CLOSE, PIN_LED_GREEN, PIN_LED_YELLOW, PIN_LED_RED, PIN_LIMIT_CLOSE, PIN_LIMIT_OPEN, state, settings, save_calibration
from sensors import read_position_percent

m_open_pwm = machine.PWM(machine.Pin(PIN_MOTOR_OPEN))
m_open_pwm.freq(1000)
m_open_pwm.duty_u16(0)

m_close_pwm = machine.PWM(machine.Pin(PIN_MOTOR_CLOSE))
m_close_pwm.freq(1000)
m_close_pwm.duty_u16(0)

led_g = machine.Pin(PIN_LED_GREEN, machine.Pin.OUT)
led_y = machine.Pin(PIN_LED_YELLOW, machine.Pin.OUT)
led_r = machine.Pin(PIN_LED_RED, machine.Pin.OUT)

limit_close = machine.Pin(PIN_LIMIT_CLOSE, machine.Pin.IN, machine.Pin.PULL_UP)
limit_open = machine.Pin(PIN_LIMIT_OPEN, machine.Pin.IN, machine.Pin.PULL_UP)

# Globale Steuervariablen für nicht-blockierende LED-Muster
last_blink_time = time.ticks_ms()
blink_state = False
blink_counter = 0
in_pause = False

def stop_motor():
    m_open_pwm.duty_u16(0)
    m_close_pwm.duty_u16(0)

def drive_motor_soft(direction_pwm):
    """Sanfter Motorstart per PWM-Rampe."""
    for duty in range(0, 65536, 4096): 
        direction_pwm.duty_u16(duty)
        time.sleep_ms(10)

def handle_led_blinking_non_blocking():
    """Korrektur: Blinkt fehlerabhängig ohne die CPU zu blockieren."""
    global last_blink_time, blink_state, blink_counter, in_pause
    now = time.ticks_ms()
    
    if state["fehler_code"] == 0:
        led_r.value(0)
        blink_counter = 0
        in_pause = False
        if state["status_code"] != 0:
            led_g.value(0); led_y.value(1) # In Bewegung
        else:
            led_g.value(1); led_y.value(0) # Bereit
        return

    led_g.value(0); led_y.value(0)
    blinks_target = state["fehler_code"]
    
    if in_pause:
        if time.ticks_diff(now, last_blink_time) > 1000:
            in_pause = False
            blink_counter = 0
            last_blink_time = now
        return

    if blink_state:
        if time.ticks_diff(now, last_blink_time) > 200:
            led_r.value(0); blink_state = False; last_blink_time = now
            blink_counter += 1
            if blink_counter >= blinks_target: in_pause = True
    else:
        if time.ticks_diff(now, last_blink_time) > 200:
            led_r.value(1); blink_state = True; last_blink_time = now

def motor_control_loop():
    HYSTERESE = 2
    last_pos_change = time.ticks_ms()
    prev_ist = -1
    
    while True:
        handle_led_blinking_non_blocking()
        
        poti = read_position_percent()
        if poti != -1:
            state["ist_oeffnung"] = poti
            if state["fehler_code"] == 1: state["fehler_code"] = 0

        if state["ist_oeffnung"] != prev_ist:
            last_pos_change = time.ticks_ms()
            prev_ist = state["ist_oeffnung"]

        # Blockadeüberwachung (gilt jetzt auch bei Kalibrierung!)
        if state["status_code"] != 0 and time.ticks_diff(time.ticks_ms(), last_pos_change) > settings["motor_block_ms"]:
            state["fehler_code"] = 3 
            stop_motor()
            state["status_code"] = 0
            state["auto_calib_active"] = False
            continue

        if (state["watchdog_triggered"] or state["fehler_code"] != 0) and not state["auto_calib_active"]:
            stop_motor(); state["status_code"] = 0
            time.sleep_ms(10)
            continue

        # =========================================================================
        # KALIBRIERRUTINE (Homing per Endschalter)
        # =========================================================================
        if state["auto_calib_active"]:
            if state["auto_calib_step"] == 1:
                if limit_close.value() == 0: # Anschlag erreicht
                    stop_motor()
                    state["poti_min"] = state["poti_raw_live"]
                    state["auto_calib_step"] = 2
                    last_pos_change = time.ticks_ms()
                else:
                    if state["status_code"] != 2:
                        stop_motor(); state["status_code"] = 2
                        last_pos_change = time.ticks_ms()
                        drive_motor_soft(m_close_pwm)
            
            elif state["auto_calib_step"] == 2:
                if limit_open.value() == 0: # Anschlag erreicht
                    stop_motor()
                    state["poti_max"] = state["poti_raw_live"]
                    save_calibration()
                    state["auto_calib_active"] = False
                    state["auto_calib_step"] = 0
                    state["status_code"] = 0
                    state["soll_oeffnung"] = 100
                else:
                    if state["status_code"] != 1:
                        stop_motor(); state["status_code"] = 1
                        last_pos_change = time.ticks_ms()
                        drive_motor_soft(m_open_pwm)
            time.sleep_ms(10)
            continue

        # =========================================================================
        # NORMALE REGELUNG (Hardware-Schutz durch Endschalter)
        # =========================================================================
        if limit_close.value() == 0 and state["status_code"] == 2:
            stop_motor(); state["status_code"] = 0
        if limit_open.value() == 0 and state["status_code"] == 1:
            stop_motor(); state["status_code"] = 0

        abweichung = state["soll_oeffnung"] - state["ist_oeffnung"]
        
        if abs(abweichung) <= HYSTERESE:
            if state["status_code"] != 0:
                stop_motor(); state["status_code"] = 0
        elif abweichung > 0 and limit_open.value() == 1:
            if state["status_code"] != 1:
                stop_motor(); state["status_code"] = 1
                last_pos_change = time.ticks_ms()
                drive_motor_soft(m_open_pwm)
        elif abweichung < 0 and limit_close.value() == 1:
            if state["status_code"] != 2:
                stop_motor(); state["status_code"] = 2
                last_pos_change = time.ticks_ms()
                drive_motor_soft(m_close_pwm)
                
        time.sleep_ms(10)
