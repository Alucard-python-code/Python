class Pin:
    IN = 0
    PULL_UP = 0
    IRQ_RISING = 0

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def irq(self, *args, **kwargs):
        return None


class PWM:
    def __init__(self, *args, **kwargs):
        pass

    def freq(self, *args, **kwargs):
        pass

    def duty_ns(self, *args, **kwargs):
        pass


class ADC:
    def __init__(self, *args, **kwargs):
        pass

    def read_u16(self):
        return 0


class I2C:
    def __init__(self, *args, **kwargs):
        pass

    def writeto(self, *args, **kwargs):
        return None
