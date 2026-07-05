from rotary_irq_rp2 import RotaryIRQ
import time
from machine import Pin

max_val_1 = 3

r = RotaryIRQ(pin_num_clk=18,
              pin_num_dt=19,
              min_val=1,
              max_val=max_val_1,
              reverse=False,
              range_mode=RotaryIRQ.RANGE_WRAP)

def menue():
    if val_new == 1:
        name = str(Besitzer)
        return name
            if button == 1:
                
    elif val_new == 2:
        name = "Modell"
        return name
    elif val_new == 3:
        name = "Einstellungen"
        return name

val_old = r.value()
while True:
    val_new = r.value()
    
    val_new_off_1 = val_new - 1
    
    if val_new_off_1 <= 0:
        val_new_off_1 = max_val_1
        val_new = 1

    if val_new == max_val_1:
        val_new_off_2 = val_new - (max_val_1 - 1)
    else:
        val_new_off_2 = val_new + 1
    

    led_off_1 = Pin(val_new_off_1, Pin.OUT)
    led_off_2 = Pin(val_new_off_2, Pin.OUT)
    led_on = Pin(val_new, Pin.OUT)
    
    led_off_1.value(0)
    led_off_2.value(0)
    led_on.value(1)

    menue()

    

    if val_old != val_new:
        val_old = val_new
        print('result =', val_new, menue())

    time.sleep_ms(50)
