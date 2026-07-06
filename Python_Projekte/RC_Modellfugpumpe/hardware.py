import machine
from config import sys_settings, PSI_TO_MBAR

# Hardware PIN-Belegung
PIN_FLOW_SENS  = 5
PIN_PWM_PUMP   = 6
PIN_PRESSURE   = 26  # ADC0

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

# Instanzen für das System initialisieren
pump = PumpController(PIN_PWM_PUMP)
sensors = SensorReader(PIN_PRESSURE, PIN_FLOW_SENS)
