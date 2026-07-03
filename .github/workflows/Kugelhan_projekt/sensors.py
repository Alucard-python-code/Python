#v1.2
import machine
import time
from config import PIN_POTI, PIN_MAX_CS, PIN_MAX_SCK, PIN_MAX_MOSI, PIN_MAX_MISO, state

poti_adc = machine.ADC(PIN_POTI)
cs = machine.Pin(PIN_MAX_CS, machine.Pin.OUT)
cs.value(1)
spi = machine.SPI(0, baudrate=1000000, polarity=1, phase=1, 
                  sck=machine.Pin(PIN_MAX_SCK), mosi=machine.Pin(PIN_MAX_MOSI), miso=machine.Pin(PIN_MAX_MISO))

def read_position_percent():
    """Liest das Poti aus und filtert EMV-Spitzen per Median-Filter (Punkt 3)."""
    global state
    
    # 5 aufeinanderfolgende Messungen durchführen
    raw_values = []
    for _ in range(5):
        raw_values.append(poti_adc.read_u16())
        time.sleep_us(200)
    
    # Werte der Größe nach sortieren
    raw_values.sort()
    
    # Den mathematischen Mittelwert (Index 2 von 0,1,2,3,4) als stabilsten Wert nehmen
    raw_val = raw_values[2]
    
    # Live-Rohwert für das Webinterface bereitstellen
    state["poti_raw_live"] = raw_val
    
    # Fehlerprüfung (Kabelbruch / Kurzschluss)
    if raw_val < 500 or raw_val > 65000:
        state["fehler_code"] = 1
        return -1
    
    poti_spanne = state["poti_max"] - state["poti_min"]
    if poti_spanne == 0:
        return 0
        
    percent = int(((raw_val - state["poti_min"]) / poti_spanne) * 100)
    
    if percent < 0: percent = 0
    if percent > 100: percent = 100
    return percent


def read_pt1000_temperature():
    RREF = 4300.0  
    cs.value(0)
    spi.write(b'\x01') 
    data = spi.read(2)
    cs.value(1)
    
    rtd_raw = ((data << 8) | data) >> 1
    if rtd_raw == 0: return -99.0
        
    r_rtd = (rtd_raw / 32768.0) * RREF
    temp = (r_rtd - 1000.0) / 3.9083
    return round(temp, 1)
