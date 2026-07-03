import machine
import time
from config import PIN_MOTOR_OPEN, PIN_MOTOR_CLOSE, PIN_LED_GREEN, PIN_LED_YELLOW, PIN_LED_RED, PIN_LIMIT_CLOSE, PIN_LIMIT_OPEN, state, settings, save_calibration
from sensors import read_position_percent

# PWM-Ausgänge für H-Brücke
m_open_pwm = machine.PWM(machine.Pin(PIN_MOTOR_OPEN))
m_open_pwm.freq(1000)
m_open_pwm.duty_u16(0)

m_close_pwm = machine.PWM(machine.Pin(PIN_MOTOR_CLOSE))
m_close_pwm.freq(1000)
m_close_pwm.duty_u16(0)

# LEDs
led_g = machine.Pin(PIN_LED_GREEN, machine.Pin.OUT)
led_y = machine.Pin(PIN_LED_YELLOW, machine.Pin.OUT)
led_r = machine.Pin(PIN_LED_RED, machine.Pin.OUT)

# NEU: Endschalter-Eingänge (NC gegen GND -> Pullup aktivieren)
# switch.value() == 0 bedeutet: Schalter gedrückt (Anschlag erreicht)
# switch.value() == 1 bedeutet: Schalter frei (Normalbetrieb)
limit_close = machine.Pin(PIN_LIMIT_CLOSE, machine.Pin.IN, machine.Pin.PULL_UP)
limit_open = machine.Pin(PIN_LIMIT_OPEN, machine.Pin.IN, machine.Pin.PULL_UP)

def stop_motor():
    m_open_pwm.duty_u16(0)
    m_close_pwm.duty_u16(0)
    time.sleep_ms(300) 

def drive_motor_soft(direction_pwm):
    """Sanfter Motorstart per PWM-Rampe."""
    for duty in range(0, 65536, 4096): 
        direction_pwm.duty_u16(duty)
        time.sleep_ms(20)

def handle_led_blinking():
    """Punkt 2: Rote LED blinkt entsprechend dem Fehlercode."""
    if state["fehler_code"] == 0:
        led_r.value(0)
        if state["status_code"] != 0:
            led_g.value(0); led_y.value(1) # In Bewegung
        else:
            led_g.value(1); led_y.value(0) # Bereit
        return

    # Wenn Fehler vorliegt, alles andere aus und rote LED blinken lassen
    led_g.value(0)
    led_y.value(0)
    
    blinks = state["fehler_code"] # 1=Poti, 2=Watchdog, 3=Blockiert
    for _ in range(blinks):
        led_r.value(1)
        time.sleep_ms(200)
        led_r.value(0)
        time.sleep_ms(200)
    time.sleep_ms(800) # Pause vor dem nächsten Blinkzyklus

def motor_control_loop():
    HYSTERESE = 2
    last_pos_change = time.ticks_ms()
    prev_ist = -1
    
    while True:
        # 1. LED-Blinken/Status parallel abarbeiten
        handle_led_blinking()
        
        # 2. Sensoren auslesen
        poti = read_position_percent()
        if poti != -1:
            state["ist_oeffnung"] = poti
            if state["fehler_code"] == 1: state["fehler_code"] = 0

        # 3. Sicherheitsstopp bei Fehlern (außer während der Auto-Kalibrierung)
        if (state["watchdog_triggered"] or state["fehler_code"] != 0) and not state["auto_calib_active"]:
            stop_motor()
            state["status_code"] = 0
            time.sleep_ms(50)
            continue

        # =========================================================================
        # NEU: VOLLAUTOMATISCHE KALIBRIERRUTINE (Homing per Endschalter)
        # =========================================================================
        if state["auto_calib_active"]:
            # --- SCHRITT 1: Fahre zu ZU-Anschlag ---
            if state["auto_calib_step"] == 1:
                if limit_close.value() == 0: # Endschalter ZU ausgelöst!
                    stop_motor()
                    state["poti_min"] = state["poti_raw_live"] # Grenzwert ZU sichern
                    state["auto_calib_step"] = 2 # Nächster Schritt
                else:
                    if state["status_code"] != 2:
                        stop_motor()
                        state["status_code"] = 2
                        drive_motor_soft(m_close_pwm)
            
            # --- SCHRITT 2: Fahre zu AUF-Anschlag ---
            elif state["auto_calib_step"] == 2:
                if limit_open.value() == 0: # Endschalter AUF ausgelöst!
                    stop_motor()
                    state["poti_max"] = state["poti_raw_live"] # Grenzwert AUF sichern
                    save_calibration() # Direkt permanent im Flash speichern
                    state["auto_calib_active"] = False
                    state["auto_calib_step"] = 0
                    state["status_code"] = 0
                    state["soll_oeffnung"] = 100 # Als Test auf Offen setzen
                else:
                    if state["status_code"] != 1:
                        stop_motor()
                        state["status_code"] = 1
                        drive_motor_soft(m_open_pwm)
            
            time.sleep_ms(50)
            continue # Überspringe normale Regelung während der Kalibrierung

        # =========================================================================
        # NORMALE REGELUNG (Inklusive Endschalter-Hardware-Schutz)
        # =========================================================================
        # Hardware-Schutz: Wenn Schalter gedrückt, darf Motor in diese Richtung nicht fahren!
        if limit_close.value() == 0 and state["status_code"] == 2:
            stop_motor()
            state["status_code"] = 0
        if limit_open.value() == 0 and state["status_code"] == 1:
            stop_motor()
            state["status_code"] = 0

        # Blockade-Überwachung
        if state["ist_oeffnung"] != prev_ist:
            last_pos_change = time.ticks_ms()
            prev_ist = state["ist_oeffnung"]
            
        if state["status_code"] != 0 and time.ticks_diff(time.ticks_ms(), last_pos_change) > settings["motor_block_ms"]:
            state["fehler_code"] = 3 
            stop_motor()
            state["status_code"] = 0
            continue

        abweichung = state["soll_oeffnung"] - state["ist_oeffnung"]
        
        if abs(abweichung) <= HYSTERESE:
            if state["status_code"] != 0:
                stop_motor()
                state["status_code"] = 0
        elif abweichung > 0 and limit_open.value() == 1: # Nur fahren wenn Schalter frei
            if state["status_code"] != 1:
                stop_motor(); state["status_code"] = 1
                last_pos_change = time.ticks_ms()
                drive_motor_soft(m_open_pwm)
        elif abweichung < 0 and limit_close.value() == 1: # Nur fahren wenn Schalter frei
            if state["status_code"] != 2:
                stop_motor(); state["status_code"] = 2
                last_pos_change = time.ticks_ms()
                drive_motor_soft(m_close_pwm)
                
        time.sleep_ms(50)
