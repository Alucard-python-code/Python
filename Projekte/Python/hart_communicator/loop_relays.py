"""
loop_relays.py – Schleifen-Betriebsarten über SMD-Signalrelais (Omron G6K-2F-Y).

Relais (alle monostabil, stromlos = sicherer Zustand):
  K1  RELAY_LOOP_POWER_24V  – 24-V-Schleifenspeisung (aus = keine Spannungsausgabe)
  K2  RELAY_SOURCE_SINK     – Topologie: aus = SINK (Fremdspeisung), ein = SOURCE (eigene 24 V)
  K3  RELAY_HART_RESISTOR   – 250-Ω-HART-Bürde zuschalten

Betriebsarten:
  PASSIVE       – Ruhezustand. Alle Relais aus. Messung/HART in fremdgespeister Schleife (DCS).
  PASSIVE_250R  – wie PASSIVE, zusätzlich 250 Ω (Werkbank mit Labornetzteil ohne Bürde).
  ACTIVE_24V    – Communicator speist einen 2-Leiter-TRANSMITTER mit 24 V über 250 Ω.

Verriegelungen:
  * ACTIVE_24V nur nach expliziter Bestätigung und nur, wenn KEINE Fremdspannung an den
    Klemmen anliegt (INA226-Busspannung) – sonst würden zwei Speisungen gegeneinander arbeiten.
  * ACTIVE_24V ist für STELLUNGSREGLER gesperrt: diese sind stromgeführt und brauchen eine
    Stromquelle, keine Spannungsquelle.
  * Schaltfolge "break-before-make": 24 V immer zuerst aus und zuletzt ein.
  * Automatischer Rückfall auf PASSIVE: bei Akku kritisch, Programmende und nach
    LOOP_AUTO_PASSIVE_MIN Minuten ohne Bedienung.

Hardware-Hinweise:
  * Die G6K-Spule (3 V: ~33 mA) NICHT direkt an den GPIO hängen: Transistor/MOSFET-Treiber
    + Freilaufdiode (oder ULN2003A-ähnlicher Treiber).
  * Die 24-V-Speisung muss hardwareseitig strombegrenzt sein (~25 mA), damit ein Kurzschluss
    der Feldleitung keinen Schaden anrichtet.
"""
from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Callable, Optional

import config
from hw_compat import digital_output

log = logging.getLogger(__name__)

RELAY_SETTLE_S = 0.010      # G6K: Ansprech-/Rückfallzeit ≤ 3 ms, Prellen ≤ 3 ms -> 10 ms Reserve


class LoopMode(str, Enum):
    PASSIVE = "PASSIVE"
    PASSIVE_250R = "PASSIVE_250R"
    ACTIVE_24V = "ACTIVE_24V"

    @property
    def label(self) -> str:
        return {
            "PASSIVE": "Passiv (Fremdspeisung, sicher)",
            "PASSIVE_250R": "Passiv + 250 Ω HART-Bürde",
            "ACTIVE_24V": "Aktiv 24 V (Transmitterspeisung)",
        }[self.value]

    @property
    def relays(self) -> tuple[bool, bool, bool]:
        """(K1 24 V, K2 Source, K3 250 Ω)"""
        return {
            "PASSIVE": (False, False, False),
            "PASSIVE_250R": (False, False, True),
            "ACTIVE_24V": (True, True, True),
        }[self.value]


class InterlockError(RuntimeError):
    """Umschaltung durch Sicherheitsverriegelung abgelehnt."""


class LoopController:
    def __init__(self, *, voltage_probe: Optional[Callable[[], float]] = None,
                 auto_passive_min: float = config.LOOP_AUTO_PASSIVE_MIN, sim_meter=None):
        """voltage_probe: liefert die Klemmenspannung in V (z.B. INA226-Busspannung).
        sim_meter: SimulatedINA226, damit die Simulation die 24 V "sieht"."""
        P = config.Pins
        self.k1_power = digital_output(P.RELAY_LOOP_POWER_24V, initial_value=False, component="relays")
        self.k2_source = digital_output(P.RELAY_SOURCE_SINK, initial_value=False, component="relays")
        self.k3_res = digital_output(P.RELAY_HART_RESISTOR, initial_value=False, component="relays")
        self.voltage_probe = voltage_probe
        self.auto_passive_s = auto_passive_min * 60 if auto_passive_min else 0
        self.sim_meter = sim_meter
        self._mode = LoopMode.PASSIVE
        self._lock = threading.RLock()
        self._last_activity = time.monotonic()
        self._listeners: list[Callable[[LoopMode, str], None]] = []
        self._stop = threading.Event()
        self._watchdog: Optional[threading.Thread] = None
        self._apply(LoopMode.PASSIVE)

    # ---------- Status ----------
    @property
    def mode(self) -> LoopMode:
        return self._mode

    def status(self) -> dict:
        k1, k2, k3 = self._mode.relays
        remaining = None
        if self._mode != LoopMode.PASSIVE and self.auto_passive_s:
            remaining = max(0, self.auto_passive_s - (time.monotonic() - self._last_activity))
        return {"mode": self._mode.value, "label": self._mode.label, "k1_24v": k1, "k2_source": k2,
                "k3_250r": k3, "auto_passive_in_s": remaining,
                "simulated": getattr(self.k1_power, "simulated", True)}

    def add_listener(self, cb: Callable[[LoopMode, str], None]) -> None:
        self._listeners.append(cb)

    def touch(self) -> None:
        """Bedienaktivität -> Auto-Passiv-Timer zurücksetzen."""
        self._last_activity = time.monotonic()

    # ---------- Umschalten ----------
    def set_mode(self, mode: LoopMode | str, *, confirmed: bool = False, is_positioner: bool = False,
                 reason: str = "ui") -> LoopMode:
        mode = LoopMode(mode)
        with self._lock:
            if mode == self._mode:
                self.touch()
                return mode
            if mode == LoopMode.ACTIVE_24V:
                if not confirmed:
                    raise InterlockError("24-V-Speisung erfordert eine ausdrückliche Bestätigung")
                if is_positioner:
                    raise InterlockError("24-V-Spannungsspeisung für Stellungsregler gesperrt "
                                         "(stromgeführtes Gerät – Stromquelle erforderlich)")
                v = self._terminal_voltage()
                if v is not None and v > config.CurrentMeter.FOREIGN_VOLTAGE_LIMIT_V:
                    raise InterlockError(f"Fremdspannung {v:.1f} V an den Klemmen – Schleife ist bereits "
                                         "gespeist. Passivmodus verwenden!")
            self._apply(mode)
            self.touch()
        log.warning("Schleifenmodus -> %s (%s)", mode.label, reason)
        for cb in list(self._listeners):
            try:
                cb(mode, reason)
            except Exception:
                log.exception("Loop-Listener")
        return mode

    def to_passive(self, reason: str = "sicherer Zustand") -> None:
        self.set_mode(LoopMode.PASSIVE, reason=reason)

    def _terminal_voltage(self) -> Optional[float]:
        if self.voltage_probe is None:
            return None
        try:
            return float(self.voltage_probe())
        except Exception:
            log.exception("Klemmenspannung nicht messbar")
            return None

    def _apply(self, mode: LoopMode) -> None:
        k1, k2, k3 = mode.relays
        # 1) 24 V immer zuerst trennen
        self.k1_power.off()
        if self.sim_meter is not None:
            self.sim_meter.supply_voltage_v = None
        time.sleep(RELAY_SETTLE_S)
        # 2) Topologie und Bürde
        self.k2_source.value = k2
        self.k3_res.value = k3
        time.sleep(RELAY_SETTLE_S)
        # 3) 24 V zuletzt zuschalten
        if k1:
            self.k1_power.on()
            if self.sim_meter is not None:
                self.sim_meter.supply_voltage_v = 23.8
            time.sleep(RELAY_SETTLE_S)
        self._mode = mode

    # ---------- Watchdog ----------
    def start(self) -> "LoopController":
        self._watchdog = threading.Thread(target=self._run, name="loop-watchdog", daemon=True)
        self._watchdog.start()
        return self

    def check_auto_passive(self) -> bool:
        """True, wenn wegen Inaktivität in den Passivmodus zurückgeschaltet wurde."""
        if self._mode != LoopMode.PASSIVE and self.auto_passive_s and \
                time.monotonic() - self._last_activity > self.auto_passive_s:
            self.to_passive(f"Auto-Passiv nach {self.auto_passive_s / 60:.0f} min ohne Bedienung")
            return True
        return False

    def _run(self) -> None:
        while not self._stop.wait(5.0):
            self.check_auto_passive()

    def close(self) -> None:
        self._stop.set()
        try:
            self.to_passive("Programmende")
        finally:
            for r in (self.k1_power, self.k2_source, self.k3_res):
                r.close()
