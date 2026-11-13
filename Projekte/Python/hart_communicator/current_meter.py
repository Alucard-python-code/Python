"""
current_meter.py – True-mA-Messung des analogen 4–20-mA-Schleifenstroms (TI INA226).

* Registertreiber INA226 (I2C1 @ 0x40), Identitätsprüfung (MFR 0x5449 / DIE 0x2260)
* Hardware-Mittelung 64 x 1,1 ms -> die überlagerte HART-FSK (±0,5 mA, 1200/2200 Hz)
  wird zuverlässig herausgemittelt
* Strom direkt aus der Shuntspannung (2,5 µV/LSB) – genauer als das CURRENT-Register
* Übersteuerungserkennung (Shunt-Vollausschlag ±81,92 mV) statt stiller Falschwerte
* Prüfmittel-Kalibrierung (Offset + Gain, 2-Punkt gegen Referenz) mit Fälligkeitsdatum
* Stabilitätserkennung für Kalibrierpunkte (`read_stable`)
* Hintergrund-Sampler mit Abos für die Live-Anzeige
* Simulation: liest den Schleifenstrom des simulierten HART-Geräts (hart_modem.SIM_BUS)
"""
from __future__ import annotations

import json
import logging
import statistics
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import config
from hw_compat import get_i2c_bus, simulation_requested

log = logging.getLogger(__name__)
CC = config.CurrentMeter

# Register
REG_CONFIG, REG_SHUNT, REG_BUS, REG_POWER, REG_CURRENT, REG_CAL = 0x00, 0x01, 0x02, 0x03, 0x04, 0x05
REG_MASK, REG_ALERT, REG_MFR_ID, REG_DIE_ID = 0x06, 0x07, 0xFE, 0xFF
MFR_ID_TI, DIE_ID_INA226 = 0x5449, 0x2260

SHUNT_LSB_V = 2.5e-6
BUS_LSB_V = 1.25e-3
SHUNT_FULLSCALE_V = 32767 * SHUNT_LSB_V   # 81,9175 mV

AVG = {1: 0, 4: 1, 16: 2, 64: 3, 128: 4, 256: 5, 512: 6, 1024: 7}
CT_US = {140: 0, 204: 1, 332: 2, 588: 3, 1100: 4, 2116: 5, 4156: 6, 8244: 7}


def make_config(avg: int = 64, vbus_ct_us: int = 1100, vsh_ct_us: int = 1100, mode: int = 7) -> int:
    """Mode 7 = Shunt + Bus kontinuierlich. Bit 14 ist laut Datenblatt fest 1."""
    return 0x4000 | AVG[avg] << 9 | CT_US[vbus_ct_us] << 6 | CT_US[vsh_ct_us] << 3 | mode


DEFAULT_CONFIG = make_config(64, 1100, 1100)   # Wandlungszeit ≈ 64 × 2,2 ms ≈ 141 ms


class OverrangeError(RuntimeError):
    """Shuntspannung am Vollausschlag – Strom nicht messbar."""


# =============================================================================
# Register-I/O
# =============================================================================
class _INA226IO:
    def __init__(self, bus, addr: int):
        self.bus, self.addr = bus, addr

    def read_u16(self, reg: int) -> int:
        hi, lo = self.bus.read_block(self.addr, reg, 2)   # INA226: MSB zuerst
        return (hi << 8) | lo

    def write_u16(self, reg: int, value: int) -> None:
        self.bus.write_block(self.addr, reg, [(value >> 8) & 0xFF, value & 0xFF])


class SimulatedINA226(_INA226IO):
    """Registergenaue Simulation inkl. Shunt-Begrenzung, Rauschen und HART-FSK-Rest."""

    def __init__(self, shunt_ohm: float, current_source: Optional[Callable[[], float]] = None):
        self.shunt_ohm = shunt_ohm
        self.current_source = current_source
        self.terminal_voltage_v = 0.0     # Fremdspannung an den Klemmen (Test/Interlock)
        self.supply_voltage_v: Optional[float] = None   # gesetzt von loop_relays (24 V aktiv)
        self.regs = {REG_CONFIG: 0x4127, REG_CAL: 0, REG_MFR_ID: MFR_ID_TI, REG_DIE_ID: DIE_ID_INA226}

    def _current_ma(self) -> float:
        if self.current_source is not None:
            return self.current_source()
        try:
            from hart_modem import SIM_BUS
            return SIM_BUS.loop_current_ma()
        except Exception:
            return 0.0

    def read_u16(self, reg: int) -> int:
        if reg == REG_SHUNT:
            raw = round(self._current_ma() / 1000 * self.shunt_ohm / SHUNT_LSB_V)
            return max(-32768, min(32767, raw)) & 0xFFFF
        if reg == REG_BUS:
            v = self.supply_voltage_v if self.supply_voltage_v is not None else self.terminal_voltage_v
            return max(0, min(0x7FFF, round(v / BUS_LSB_V)))
        return self.regs.get(reg, 0)

    def write_u16(self, reg: int, value: int) -> None:
        if reg == REG_CONFIG and value & 0x8000:     # Reset
            self.regs[REG_CONFIG] = 0x4127
            return
        self.regs[reg] = value & 0xFFFF


# =============================================================================
# Kalibrierdaten des Prüfmittels
# =============================================================================
@dataclass
class MeterCalibration:
    offset_ma: float = 0.0
    gain: float = 1.0
    calibrated_at: Optional[str] = None     # ISO-Datum
    reference: str = ""                      # z.B. "Fluke 726, SN 1234567"
    certificate: str = ""                    # Kalibrierschein-Nr.
    technician: str = ""

    def apply(self, raw_ma: float) -> float:
        return (raw_ma - self.offset_ma) * self.gain

    @property
    def due_date(self) -> Optional[datetime]:
        if not self.calibrated_at:
            return None
        return datetime.fromisoformat(self.calibrated_at) + timedelta(days=CC.CAL_INTERVAL_DAYS)

    @property
    def is_due(self) -> bool:
        due = self.due_date
        return due is None or datetime.now(due.tzinfo) > due

    def to_dict(self) -> dict:
        d = asdict(self)
        d["due_date"] = self.due_date.date().isoformat() if self.due_date else None
        d["is_due"] = self.is_due
        return d


@dataclass
class CurrentReading:
    timestamp: float
    current_ma: Optional[float]        # kalibrierter Wert, None bei Übersteuerung
    raw_ma: Optional[float]
    terminal_voltage_v: float
    overrange: bool = False
    simulated: bool = False

    @property
    def percent(self) -> Optional[float]:
        return None if self.current_ma is None else (self.current_ma - 4.0) / 16.0 * 100.0

    @property
    def namur_state(self) -> str:
        """NAMUR NE 43: <3,6 mA bzw. >21 mA = Ausfall, 3,8..20,5 mA = Messbereich."""
        i = self.current_ma
        if i is None:
            return "ÜBERSTEUERT"
        if i < 0.5:
            return "KEIN STROM"
        if i < 3.6:
            return "AUSFALL (< 3,6 mA)"
        if i < 3.8:
            return "UNTERSTEUERT"
        if i <= 20.5:
            return "OK"
        if i <= 21.0:
            return "ÜBERSTEUERT"
        return "AUSFALL (> 21 mA)"

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(percent=self.percent, namur_state=self.namur_state)
        return d


# =============================================================================
# CurrentMeter
# =============================================================================
class CurrentMeter:
    def __init__(self, *, simulate: Optional[bool] = None, shunt_ohm: float = CC.SHUNT_OHM,
                 cal_file: Optional[Path] = CC.CAL_FILE, sample_interval_s: float = 0.15,
                 sim_current_source: Optional[Callable[[], float]] = None):
        self.shunt_ohm = shunt_ohm
        self.cal_file = cal_file
        self.sample_interval_s = sample_interval_s
        self.max_measurable_ma = SHUNT_FULLSCALE_V / shunt_ohm * 1000
        if self.max_measurable_ma < CC.MAX_EXPECTED_MA:
            log.critical("INA226: Shunt %.2f Ω -> Messbereich nur bis %.2f mA (benötigt %.0f mA)! "
                         "Shunt auf ≤ %.2f Ω ändern (Empfehlung 3,3 Ω).", shunt_ohm,
                         self.max_measurable_ma, CC.MAX_EXPECTED_MA,
                         SHUNT_FULLSCALE_V / (CC.MAX_EXPECTED_MA / 1000))

        if simulate is None:
            simulate = simulation_requested("ina226")
        io: Optional[_INA226IO] = None
        if not simulate:
            bus = get_i2c_bus(config.I2C_BUS, component="ina226")
            if bus and bus.probe(config.I2CAddr.INA226):
                io = _INA226IO(bus, config.I2CAddr.INA226)
            else:
                log.error("INA226 an 0x%02X nicht erreichbar – Simulation aktiv", config.I2CAddr.INA226)
        if io is None:
            simulate = True
            io = SimulatedINA226(shunt_ohm, sim_current_source)
        self.io = io
        self.simulated = simulate
        self.calibration = self._load_calibration()
        self._samples: deque[CurrentReading] = deque(maxlen=200)
        self._lock = threading.Lock()
        self._subs: list[Callable[[CurrentReading], None]] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._init_chip()

    # ---------- Initialisierung ----------
    def _init_chip(self) -> None:
        mfr, die = self.io.read_u16(REG_MFR_ID), self.io.read_u16(REG_DIE_ID)
        if mfr != MFR_ID_TI or (die & 0xFFF0) != DIE_ID_INA226:
            raise RuntimeError(f"INA226 nicht erkannt (MFR 0x{mfr:04X}, DIE 0x{die:04X})")
        self.io.write_u16(REG_CONFIG, 0x8000)          # Reset
        time.sleep(0.002)
        self.io.write_u16(REG_CONFIG, DEFAULT_CONFIG)
        # CAL-Register nur für das (ungenutzte) CURRENT-Register: Current_LSB = 1 µA
        current_lsb = 1e-6
        self.io.write_u16(REG_CAL, min(0xFFFF, int(0.00512 / (current_lsb * self.shunt_ohm))))

    # ---------- Kalibrierung ----------
    def _load_calibration(self) -> MeterCalibration:
        if self.cal_file and Path(self.cal_file).exists():
            try:
                return MeterCalibration(**json.loads(Path(self.cal_file).read_text()))
            except (OSError, ValueError, TypeError) as exc:
                log.error("INA226-Kalibrierdatei ungültig: %s", exc)
        return MeterCalibration()

    def _save_calibration(self) -> None:
        if not self.cal_file:
            return
        p = Path(self.cal_file)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self.calibration), indent=2, ensure_ascii=False))
        tmp.replace(p)

    def calibrate_two_point(self, ref_low_ma: float, raw_low_ma: float, ref_high_ma: float,
                            raw_high_ma: float, *, reference: str = "", certificate: str = "",
                            technician: str = "") -> MeterCalibration:
        """2-Punkt-Abgleich gegen ein Referenz-Kalibriergerät (z.B. 4 mA und 20 mA).
        raw_* sind ROHWERTE (CurrentReading.raw_ma) bei der jeweiligen Referenz."""
        if abs(raw_high_ma - raw_low_ma) < 1.0:
            raise ValueError("Messpunkte zu dicht beieinander")
        gain = (ref_high_ma - ref_low_ma) / (raw_high_ma - raw_low_ma)
        offset = raw_low_ma - ref_low_ma / gain
        if not 0.98 < gain < 1.02 or abs(offset) > 0.2:
            raise ValueError(f"Kalibrierergebnis unplausibel (Gain {gain:.5f}, Offset {offset:.4f} mA)")
        self.calibration = MeterCalibration(offset, gain, datetime.now(timezone.utc).isoformat(),
                                            reference, certificate, technician)
        self._save_calibration()
        log.info("INA226 kalibriert: Gain %.6f, Offset %.4f mA", gain, offset)
        return self.calibration

    # ---------- Messen ----------
    def read(self) -> CurrentReading:
        raw_sh = self.io.read_u16(REG_SHUNT)
        if raw_sh & 0x8000:
            raw_sh -= 0x10000
        raw_bus = self.io.read_u16(REG_BUS)
        overrange = abs(raw_sh) >= 32760
        raw_ma = raw_sh * SHUNT_LSB_V / self.shunt_ohm * 1000.0
        cal_ma = None if overrange else self.calibration.apply(raw_ma)
        r = CurrentReading(time.time(), cal_ma, None if overrange else raw_ma,
                           raw_bus * BUS_LSB_V, overrange, self.simulated)
        with self._lock:
            self._samples.append(r)
        return r

    def read_stable(self, window_s: float = CC.STABLE_WINDOW_S, tolerance_ma: float = CC.STABLE_TOLERANCE_MA,
                    timeout_s: float = 20.0, progress: Optional[Callable[[float, float], None]] = None
                    ) -> tuple[float, float]:
        """Wartet auf einen eingeschwungenen Wert. Rückgabe (Median mA, Spannweite mA).
        Wirft TimeoutError, wenn der Wert nicht stabil wird, OverrangeError bei Übersteuerung."""
        t0 = time.monotonic()
        window: deque[tuple[float, float]] = deque()
        while time.monotonic() - t0 < timeout_s:
            r = self.read()
            if r.overrange:
                raise OverrangeError(f"Strom > {self.max_measurable_ma:.2f} mA (Shunt {self.shunt_ohm} Ω)")
            now = time.monotonic()
            window.append((now, r.current_ma))
            while window and now - window[0][0] > window_s:
                window.popleft()
            vals = [v for _, v in window]
            span = max(vals) - min(vals)
            if progress:
                progress(r.current_ma, span)
            if now - t0 >= window_s and len(vals) >= 5 and span <= tolerance_ma:
                return statistics.median(vals), span
            time.sleep(self.sample_interval_s)
        raise TimeoutError(f"Schleifenstrom nicht stabil (Spannweite > {tolerance_ma * 1000:.0f} µA)")

    def latest(self) -> Optional[CurrentReading]:
        with self._lock:
            return self._samples[-1] if self._samples else None

    # ---------- Live-Sampler ----------
    def subscribe(self, cb: Callable[[CurrentReading], None]) -> None:
        self._subs.append(cb)

    def start(self) -> "CurrentMeter":
        self._thread = threading.Thread(target=self._run, name="ina226", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.wait(self.sample_interval_s):
            try:
                r = self.read()
            except Exception:
                log.exception("INA226-Lesefehler")
                time.sleep(1)
                continue
            for cb in list(self._subs):
                try:
                    cb(r)
                except Exception:
                    log.exception("INA226-Subscriber")

    def status(self) -> dict:
        return {"shunt_ohm": self.shunt_ohm, "max_measurable_ma": round(self.max_measurable_ma, 2),
                "range_ok": self.max_measurable_ma >= CC.MAX_EXPECTED_MA,
                "simulated": self.simulated, "calibration": self.calibration.to_dict()}


def compare_digital_analog(hart_ma: float, true_ma: float, span_tolerance_pct: float = 0.25) -> dict:
    """Vergleicht den digital gemeldeten Strom (HART Cmd 2/3) mit dem gemessenen.
    Toleranz in % der 16-mA-Spanne (0,25 % = 40 µA)."""
    dev_ma = true_ma - hart_ma
    dev_pct = dev_ma / 16.0 * 100.0
    return {"hart_ma": hart_ma, "true_ma": true_ma, "deviation_ma": dev_ma,
            "deviation_pct_span": dev_pct, "ok": abs(dev_pct) <= span_tolerance_pct,
            "message": None if abs(dev_pct) <= span_tolerance_pct else
            f"Digital/Analog-Abweichung {dev_ma * 1000:+.0f} µA ({dev_pct:+.2f} % der Spanne) – "
            "D/A-Wandler bzw. Schleifenabgleich prüfen (Cmd 45/46)"}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from hart_modem import SIM_BUS
    dev = SIM_BUS.active_device()
    for shunt in (10.0, 3.3):
        print(f"\n--- Shunt {shunt} Ω ---")
        m = CurrentMeter(simulate=True, shunt_ohm=shunt, cal_file=None, sample_interval_s=0.05)
        for pct in (0, 50, 100):
            dev.set_process_percent(pct)
            r = m.read()
            txt = f"{r.current_ma:7.4f} mA" if r.current_ma is not None else "   ---    "
            print(f"Prozess {pct:3d} %: {txt}  [{r.namur_state}]  digital {dev.digital_current():.4f} mA")
    dev.set_process_percent(50)
    val, span = m.read_stable(window_s=0.5, timeout_s=5)
    print(f"Stabil: {val:.4f} mA (Spannweite {span * 1000:.1f} µA)")
    print(compare_digital_analog(dev.digital_current(), val))
