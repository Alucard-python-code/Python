import machine
import time
from config import PIN_POTI, PIN_MAX_CS, PIN_MAX_SCK, PIN_MAX_MOSI, PIN_MAX_MISO, state

# Hardware initialisieren
poti_adc = machine.ADC(PIN_POTI)
cs = machine.Pin(PIN_MAX_CS, machine.Pin.OUT)
cs.value(1)
spi = machine.SPI(0, baudrate=1000000, polarity=1, phase=1, 
                  sck=machine.Pin(PIN_MAX_SCK), mosi=machine.Pin(PIN_MAX_MOSI), miso=machine.Pin(PIN_MAX_MISO))

def read_position_percent():
    """Liest das Poti aus und filtert das Rauschen."""
    total = 0
    for _ in range(10):
        total += poti_adc.read_u16()
        time.sleep_us(100)
    raw_val = total // 10
    
    # Fehlerprüfung (Kabelbruch / Kurzschluss)
    if raw_val < 500 or raw_val > 65000:
        state["fehler_code"] = 1
        return -1
    
    percent = int((raw_val / 65535) * 100)
    if percent < 0: percent = 0
    if percent > 100: percent = 100
    return percent

def read_pt1000_temperature():
    """Liest den MAX31865 via SPI aus."""
    RREF = 4300.0  
    cs.value(0)
    spi.write(b'\x01') 
    data = spi.read(2)
    cs.value(1)
    
    rtd_raw = ((data[0] << 8) | data[1]) >> 1
    if rtd_raw == 0:
        return -99.0
        
    r_rtd = (rtd_raw / 32768.0) * RREF
    temp = (r_rtd - 1000.0) / 3.9083
    return round(temp, 1)
