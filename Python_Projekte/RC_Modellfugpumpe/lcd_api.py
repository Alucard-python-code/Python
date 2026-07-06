import time

class Lcd:
    def __init__(self, i2c, i2c_addr):
        self.i2c = i2c
        self.i2c_addr = i2c_addr
        self.backlightval = 0x08
        self._write(0x33)
        time.sleep_ms(5)
        self._write(0x32)
        time.sleep_ms(5)
        self._write(0x28)
        self._write(0x0C)
        self._write(0x06)
        self.clear()

    def _write_four_bits(self, data):
        self.i2c.writeto(self.i2c_addr, bytes([data | self.backlightval]))
        self.i2c.writeto(self.i2c_addr, bytes([data | 0x04 | self.backlightval]))
        time.sleep_us(300)
        self.i2c.writeto(self.i2c_addr, bytes([data & ~0x04 | self.backlightval]))
        time.sleep_us(50)

    def _write(self, cmd, mode=0):
        self._write_four_bits(mode | (cmd & 0xF0))
        self._write_four_bits(mode | ((cmd << 4) & 0xF0))

    def clear(self):
        self._write(0x01)
        time.sleep_ms(2)

    def move_to(self, cursor_x, cursor_y):
        addr = cursor_x & 0x1F
        if cursor_y == 1: addr += 0x40
        elif cursor_y == 2: addr += 0x14
        elif cursor_y == 3: addr += 0x54
        self._write(0x80 | addr)

    def putstr(self, string):
        for char in string:
            self._write(ord(char), 1)
