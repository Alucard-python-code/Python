try:
    import machine
except ImportError:
    class _DummyPin:
        IN = 0
        PULL_UP = 0
        IRQ_RISING = 0

        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def irq(self, *args, **kwargs):
            return None

    class _DummyPWM:
        def __init__(self, *args, **kwargs):
            pass

        def freq(self, *args, **kwargs):
            pass

        def duty_ns(self, *args, **kwargs):
            pass

    class _DummyADC:
        def __init__(self, *args, **kwargs):
            pass

        def read_u16(self):
            return 0

    class _DummyI2C:
        def __init__(self, *args, **kwargs):
            pass

        def writeto(self, *args, **kwargs):
            return None

    class machine:
        Pin = _DummyPin
        PWM = _DummyPWM
        ADC = _DummyADC
        I2C = _DummyI2C

from config import sys_settings, PSI_TO_MBAR
from lcd_api import Lcd

# Hardware PIN-Belegung
PIN_FLOW_SENS  = 5
PIN_PWM_PUMP   = 6
PIN_PRESSURE   = 26  # ADC0
PIN_I2C_SDA    = 0   # Pico Pin 1
PIN_I2C_SCL    = 1   # Pico Pin 2

class PumpController:
    def __init__(self, pin_num):
        self.pwm = machine.PWM(machine.Pin(pin_num))
        self.pwm.freq(50)
        self.stop_pump()
        
    def set_speed(self, speed_percent, direction="tanken"):
        if speed_percent == 0:
            self.stop_pump()
            return
            
        if direction == "tanken":
            duty = 1500000 + int(speed_percent * 5000)
        else:
            duty = 1500000 - int(speed_percent * 5000)
            
        self.pwm.duty_ns(duty)

    def stop_pump(self):
        self.pwm.duty_ns(1500000)

class SensorReader:
    def __init__(self, adc_pin, flow_pin):
        self.adc = machine.ADC(machine.Pin(adc_pin))
        self.flow_pin = machine.Pin(flow_pin, machine.Pin.IN, machine.Pin.PULL_UP)
        self.flow_pin.irq(trigger=machine.Pin.IRQ_RISING, handler=self._flow_isr)
        self.pulse_count = 0
        
    def _flow_isr(self, pin):
        self.pulse_count += 1
        
    def get_pressure_mbar(self):
        raw = self.adc.read_u16()
        voltage = (raw / 65535.0) * 3.3
        psi = (voltage / 3.3) * 5.0
        mbar = psi * PSI_TO_MBAR
        return max(0.0, mbar - sys_settings.pressure_offset)
        
    def get_volume_ml(self):
        return self.pulse_count / sys_settings.pulses_per_ml
        
    def reset_volume(self):
        self.pulse_count = 0

# I2C & LCD Hardware initialisieren
i2c = machine.I2C(0, sda=machine.Pin(PIN_I2C_SDA), scl=machine.Pin(PIN_I2C_SCL), freq=400000)
lcd = Lcd(i2c, 0x27) # 0x27 ist der Standard für das Freenove 2004 LCD

# Instanzen für das System
pump = PumpController(PIN_PWM_PUMP)
sensors = SensorReader(PIN_PRESSURE, PIN_FLOW_SENS)
