"""
hw_compat.py – Hardware-Abstraktion mit automatischem Simulations-Fallback.

Stellt einheitliche Fabriken für GPIO-Ein-/Ausgänge und einen thread-sicheren
I2C-Bus bereit. Auf einem Entwicklungs-PC (oder bei HART_SIM=1) werden
Mock-Objekte mit identischer Schnittstelle zurückgegeben, sodass die gesamte
Anwendung ohne angeschlossene Hardware lauffähig und testbar bleibt.
"""
from __future__ import annotations

import logging
import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)

_TRUE = ("1", "true", "yes", "on", "ja")
_FALSE = ("0", "false", "no", "off", "nein")


@lru_cache(maxsize=1)
def is_raspberry_pi() -> bool:
    try:
        model = Path("/proc/device-tree/model").read_text(errors="ignore").lower()
        return "raspberry pi" in model
    except OSError:
        return False


def simulation_requested(component: str) -> bool:
    """Entscheidet pro Komponente, ob simuliert wird (siehe config.py)."""
    specific = os.environ.get(f"HART_SIM_{component.upper()}")
    val = (specific if specific is not None else os.environ.get("HART_SIM", "auto")).strip().lower()
    if val in _TRUE:
        return True
    if val in _FALSE:
        return False
    return not is_raspberry_pi()


class HardwareUnavailable(RuntimeError):
    """Hardware wird verlangt (HART_SIM=0), ist aber nicht erreichbar."""


# ---------------------------------------------------------------------------
# GPIO-Mocks (API-kompatibel zum benötigten Teil von gpiozero)
# ---------------------------------------------------------------------------
class MockDigitalOutput:
    simulated = True

    def __init__(self, pin: Optional[int], active_high: bool = True, initial_value: bool = False):
        self.pin = pin
        self.active_high = active_high
        self._value = bool(initial_value)

    @property
    def value(self) -> int:
        return int(self._value)

    @value.setter
    def value(self, v) -> None:
        self._value = bool(v)

    @property
    def is_active(self) -> bool:
        return self._value

    def on(self) -> None:
        self._value = True

    def off(self) -> None:
        self._value = False

    def toggle(self) -> None:
        self._value = not self._value

    def close(self) -> None:
        pass


class MockDigitalInput:
    """Simulierter Eingang. `simulate_level()` löst die Callbacks wie echte Flanken aus."""
    simulated = True

    def __init__(self, pin: Optional[int], initial_active: bool = False):
        self.pin = pin
        self._active = initial_active
        self.when_activated: Optional[Callable] = None
        self.when_deactivated: Optional[Callable] = None

    @property
    def value(self) -> int:
        return int(self._active)

    @property
    def is_active(self) -> bool:
        return self._active

    def simulate_level(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        cb = self.when_activated if active else self.when_deactivated
        if cb:
            try:
                cb()
            except TypeError:
                cb(self)

    def close(self) -> None:
        pass


def digital_output(pin: Optional[int], *, active_high: bool = True, initial_value: bool = False,
                   component: str = "gpio"):
    """Digitaler Ausgang. `initial_value` bezieht sich auf den LOGISCHEN Zustand."""
    if pin is not None and not simulation_requested(component):
        try:
            from gpiozero import DigitalOutputDevice
            dev = DigitalOutputDevice(pin, active_high=active_high, initial_value=initial_value)
            dev.simulated = False
            return dev
        except Exception as exc:  # pragma: no cover - nur auf Hardware
            if os.environ.get("HART_SIM", "auto").lower() in _FALSE:
                raise HardwareUnavailable(f"GPIO{pin}: {exc}") from exc
            log.warning("GPIO%s Ausgang nicht verfügbar (%s) – Simulation", pin, exc)
    return MockDigitalOutput(pin, active_high, initial_value)


def digital_input(pin: Optional[int], *, pull_up: Optional[bool] = None, active_state: Optional[bool] = None,
                  bounce_time: Optional[float] = None, component: str = "gpio",
                  sim_initial_active: bool = False):
    """Digitaler Eingang. Bei pull_up=None MUSS active_state angegeben werden (gpiozero-Regel)."""
    if pin is not None and not simulation_requested(component):
        try:
            from gpiozero import DigitalInputDevice
            dev = DigitalInputDevice(pin, pull_up=pull_up, active_state=active_state, bounce_time=bounce_time)
            dev.simulated = False
            return dev
        except Exception as exc:  # pragma: no cover
            if os.environ.get("HART_SIM", "auto").lower() in _FALSE:
                raise HardwareUnavailable(f"GPIO{pin}: {exc}") from exc
            log.warning("GPIO%s Eingang nicht verfügbar (%s) – Simulation", pin, exc)
    return MockDigitalInput(pin, sim_initial_active)


# ---------------------------------------------------------------------------
# Thread-sicherer I2C-Bus (alle Sensoren teilen sich I2C1!)
# ---------------------------------------------------------------------------
class I2CBus:
    def __init__(self, bus_no: int):
        from smbus2 import SMBus  # Import erst hier -> PC ohne smbus2 möglich
        self.bus_no = bus_no
        self._bus = SMBus(bus_no)
        self.lock = threading.RLock()

    def read_byte_data(self, addr: int, reg: int) -> int:
        with self.lock:
            return self._bus.read_byte_data(addr, reg)

    def write_byte_data(self, addr: int, reg: int, value: int) -> None:
        with self.lock:
            self._bus.write_byte_data(addr, reg, value & 0xFF)

    def read_block(self, addr: int, reg: int, length: int) -> list[int]:
        with self.lock:
            return self._bus.read_i2c_block_data(addr, reg, length)

    def write_block(self, addr: int, reg: int, data: list[int]) -> None:
        with self.lock:
            self._bus.write_i2c_block_data(addr, reg, [b & 0xFF for b in data])

    def write_then_read(self, addr: int, out: list[int], read_len: int) -> list[int]:
        """Kombinierte Transaktion mit Repeated Start (für CRC-Lesezugriffe)."""
        from smbus2 import i2c_msg
        with self.lock:
            w = i2c_msg.write(addr, out)
            r = i2c_msg.read(addr, read_len)
            self._bus.i2c_rdwr(w, r)
            return list(r)

    def probe(self, addr: int) -> bool:
        with self.lock:
            try:
                self._bus.read_byte(addr)
                return True
            except OSError:
                return False

    def close(self) -> None:
        with self.lock:
            self._bus.close()


_bus_cache: dict[int, I2CBus] = {}
_bus_cache_lock = threading.Lock()


def get_i2c_bus(bus_no: int = 1, component: str = "i2c") -> Optional[I2CBus]:
    """Liefert den gemeinsamen I2C-Bus oder None (-> Aufrufer simuliert)."""
    if simulation_requested(component):
        return None
    with _bus_cache_lock:
        if bus_no in _bus_cache:
            return _bus_cache[bus_no]
        try:
            bus = I2CBus(bus_no)
        except Exception as exc:  # pragma: no cover
            if os.environ.get("HART_SIM", "auto").lower() in _FALSE:
                raise HardwareUnavailable(f"/dev/i2c-{bus_no}: {exc}") from exc
            log.warning("I2C-Bus %s nicht verfügbar (%s) – Simulation", bus_no, exc)
            return None
        _bus_cache[bus_no] = bus
        return bus
