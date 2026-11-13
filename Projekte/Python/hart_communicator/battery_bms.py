"""
battery_bms.py – 8S-LiFePO4-Akkuüberwachung mit TI BQ76930 + Soft-Power (GPIO25).

Inhalt:
  * BQ76930            – Registertreiber (I2C1 @ 0x08, optional CRC-8), ADC-Gain/Offset
                         aus dem Werks-Trim, Schutzschwellen OV/UV/OCD/SCD, FET-Steuerung,
                         Coulomb-Counter, Thermistoren TS1/TS2, CELLBAL-Register
  * SimulatedBQ76930   – registergenaue Simulation (gleicher Treiber-Code wird getestet!)
  * SocEstimator       – Coulomb-Counting + OCV-Rekalibrierung an den steilen
                         Kennlinienenden (LiFePO4-Plateau ist für OCV ungeeignet)
  * BatteryMonitor     – Hintergrund-Thread, ALERT-Interrupt (GPIO24), Zelldrift,
                         Fehler, Grenzwert-Callbacks (geordneter Shutdown)
  * PowerLatch         – Soft-Power-Selbsthaltung an GPIO25

Balancing:
  Das AKTIVE Balancing übernehmen 7x ETA3000 autonom in Hardware (je ein Baustein
  zwischen zwei benachbarten Zellen). Die Software überwacht die Drift und kann
  optional zusätzlich passives Top-Balancing über die BQ-CELLBAL-Register nutzen.
"""
from __future__ import annotations

import json
import logging
import math
import os
import random
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

import config
from hw_compat import digital_input, digital_output, get_i2c_bus, simulation_requested

log = logging.getLogger(__name__)
BC = config.Battery

# =============================================================================
# BQ76930 Register
# =============================================================================
SYS_STAT, CELLBAL1, CELLBAL2 = 0x00, 0x01, 0x02
SYS_CTRL1, SYS_CTRL2 = 0x04, 0x05
PROTECT1, PROTECT2, PROTECT3 = 0x06, 0x07, 0x08
OV_TRIP, UV_TRIP, CC_CFG = 0x09, 0x0A, 0x0B
VC1_HI = 0x0C            # VC1..VC10: 0x0C..0x1F (je HI/LO)
BAT_HI = 0x2A
TS1_HI, TS2_HI = 0x2C, 0x2E
CC_HI = 0x32
ADCGAIN1, ADCOFFSET, ADCGAIN2 = 0x50, 0x51, 0x59

# SYS_STAT-Bits
ST_CC_READY, ST_XREADY, ST_OVRD_ALERT = 0x80, 0x20, 0x10
ST_UV, ST_OV, ST_SCD, ST_OCD = 0x08, 0x04, 0x02, 0x01
FAULT_TEXT = {
    ST_XREADY: "BQ76930 Interner Fehler (DEVICE_XREADY)",
    ST_OVRD_ALERT: "Externer ALERT-Override",
    ST_UV: "Zellen-Unterspannung (UV)",
    ST_OV: "Zellen-Überspannung (OV)",
    ST_SCD: "Kurzschluss beim Entladen (SCD)",
    ST_OCD: "Überstrom beim Entladen (OCD)",
}
FAULT_MASK = ST_XREADY | ST_OVRD_ALERT | ST_UV | ST_OV | ST_SCD | ST_OCD

# SYS_CTRL-Bits
CTRL1_ADC_EN, CTRL1_TEMP_SEL = 0x10, 0x08
CTRL2_CC_EN, CTRL2_DSG_ON, CTRL2_CHG_ON = 0x40, 0x02, 0x01

CC_LSB_UV = 8.44           # Coulomb-Counter: 8,44 µV/LSB
TS_LSB_UV = 382            # Thermistor-ADC: 382 µV/LSB

# Schutzschwellen bei RSNS=1 (Datenblatt Tabelle PROTECT1/2), in mV über dem Shunt
SCD_THRESH_MV = (44, 67, 89, 111, 133, 155, 178, 200)
OCD_THRESH_MV = (17, 22, 28, 33, 39, 44, 50, 56, 61, 67, 72, 78, 83, 89, 94, 100)
SCD_DELAY_US = (70, 100, 200, 400)
OCD_DELAY_MS = (8, 20, 40, 80, 160, 320, 640, 1280)
UV_DELAY_S = (1, 4, 8, 16)
OV_DELAY_S = (1, 2, 4, 8)


def crc8(data: bytes | list[int], crc: int = 0) -> int:
    """CRC-8, Polynom x^8+x^2+x+1 (0x07), Startwert 0 – wie im BQ769x0-Datenblatt."""
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def _nearest_index(table: tuple, value: float, below: bool = True) -> int:
    """Index der größten Schwelle <= value (konservativ) bzw. nächster Wert."""
    if below:
        idx = 0
        for i, t in enumerate(table):
            if t <= value:
                idx = i
        return idx
    return min(range(len(table)), key=lambda i: abs(table[i] - value))


# =============================================================================
# LiFePO4-Ruhespannungskennlinie (pro Zelle, 25 °C)
# =============================================================================
LFP_OCV = (
    (2.50, 0.0), (2.90, 2.0), (3.05, 5.0), (3.15, 9.0), (3.20, 14.0), (3.23, 20.0),
    (3.25, 30.0), (3.27, 40.0), (3.285, 50.0), (3.295, 60.0), (3.305, 70.0),
    (3.32, 80.0), (3.335, 90.0), (3.35, 95.0), (3.40, 98.0), (3.50, 99.5), (3.60, 100.0),
)


def ocv_to_soc(v: float) -> float:
    if v <= LFP_OCV[0][0]:
        return 0.0
    for (v0, s0), (v1, s1) in zip(LFP_OCV, LFP_OCV[1:]):
        if v <= v1:
            return s0 + (s1 - s0) * (v - v0) / (v1 - v0)
    return 100.0


def soc_to_ocv(soc: float) -> float:
    soc = max(0.0, min(100.0, soc))
    for (v0, s0), (v1, s1) in zip(LFP_OCV, LFP_OCV[1:]):
        if soc <= s1:
            return v0 + (v1 - v0) * (soc - s0) / ((s1 - s0) or 1)
    return LFP_OCV[-1][0]


def ocv_reliable(soc: float) -> bool:
    """OCV-Abgleich nur in den steilen Bereichen – im Plateau (20..90 %) zu ungenau."""
    return soc < 15.0 or soc > 95.0


# =============================================================================
# Registerzugriff: echte Hardware oder Simulation
# =============================================================================
class _RegisterIO:
    def read(self, reg: int, n: int = 1) -> list[int]:
        raise NotImplementedError

    def write(self, reg: int, value: int) -> None:
        raise NotImplementedError


class _I2CRegisterIO(_RegisterIO):
    def __init__(self, bus, addr: int, use_crc: bool):
        self.bus, self.addr, self.use_crc = bus, addr, use_crc
        self.crc_errors = 0

    def write(self, reg: int, value: int) -> None:
        if self.use_crc:
            c = crc8([self.addr << 1, reg, value & 0xFF])
            self.bus.write_block(self.addr, reg, [value & 0xFF, c])
        else:
            self.bus.write_byte_data(self.addr, reg, value)

    def read(self, reg: int, n: int = 1) -> list[int]:
        if not self.use_crc:
            return self.bus.read_block(self.addr, reg, n) if n > 1 else [self.bus.read_byte_data(self.addr, reg)]
        for attempt in range(3):
            raw = self.bus.write_then_read(self.addr, [reg], 2 * n)
            out, ok = [], True
            for i in range(n):
                d, c = raw[2 * i], raw[2 * i + 1]
                # erstes Byte: CRC über Leseadresse + Daten, Folgebytes nur über Daten
                exp = crc8([(self.addr << 1) | 1, d]) if i == 0 else crc8([d])
                if exp != c:
                    ok = False
                    break
                out.append(d)
            if ok:
                return out
            self.crc_errors += 1
        raise IOError(f"BQ76930 CRC-Fehler beim Lesen von Register 0x{reg:02X}")


class SimulatedBQ76930(_RegisterIO):
    """Registergenaue Simulation inkl. Zellphysik, ETA3000-Ausgleich und Coulomb-Counter.

    `current_provider()` liefert den Pack-Strom in A (positiv = Laden). Ohne Provider:
    Feldbetrieb mit ~0,35 A Entladestrom (CM4 + 7"-Display ≈ 9 W @ 25,6 V).
    """

    GAIN_UV = 380            # ergibt sich aus den Trim-Registern unten
    OFFSET_MV = 12

    def __init__(self, capacity_ah: float = BC.CAPACITY_AH, start_soc: float = 78.0,
                 current_provider: Optional[Callable[[], float]] = None):
        self.capacity_ah = capacity_ah
        rnd = random.Random(42)
        self.cell_soc = [start_soc + rnd.uniform(-2.5, 2.5) for _ in range(BC.CELLS)]
        self.cell_cap = [capacity_ah * rnd.uniform(0.97, 1.02) for _ in range(BC.CELLS)]
        self.cell_r = [0.012 + rnd.uniform(0, 0.004) for _ in range(BC.CELLS)]
        self.current_provider = current_provider
        self.regs = [0] * 0x60
        # Werks-Trim so wählen, dass GAIN = 380 µV und OFFSET = 12 mV
        g = self.GAIN_UV - 365           # 15 = 0b01111 -> GAIN<4:3>=01, GAIN<2:0>=111
        self.regs[ADCGAIN1] = ((g >> 3) & 0x03) << 2
        self.regs[ADCGAIN2] = (g & 0x07) << 5
        self.regs[ADCOFFSET] = self.OFFSET_MV & 0xFF
        self.regs[SYS_STAT] = ST_XREADY            # wie nach dem Booten
        self._last = time.monotonic()
        self._cc_acc = 0.0
        self._cc_n = 0
        self._last_cc = time.monotonic()
        self.temp_c = 24.0
        self.lock = threading.Lock()

    def current_a(self) -> float:
        if self.current_provider:
            return float(self.current_provider())
        return -0.35 + random.gauss(0, 0.03)

    def _step(self) -> None:
        now = time.monotonic()
        dt = now - self._last
        self._last = now
        ctrl2 = self.regs[SYS_CTRL2]
        i = self.current_a()
        if i > 0 and not ctrl2 & CTRL2_CHG_ON:
            i = 0.0
        if i < 0 and not ctrl2 & CTRL2_DSG_ON:
            i = 0.0
        if i > 0 and max(self.cell_soc) >= 100.0:  # Ladegerät regelt ab (CV-Phase)
            i = 0.02
        bal = self.regs[CELLBAL1] | (self.regs[CELLBAL2] << 5)
        for k in range(BC.CELLS):
            self.cell_soc[k] += i * dt / 3600.0 / self.cell_cap[k] * 100.0
            if bal >> BC.CELL_MAP[k] & 1:                    # passiver Bleeder ~50 mA
                self.cell_soc[k] -= 0.05 * dt / 3600.0 / self.cell_cap[k] * 100.0
        # ETA3000: Ladungsverschiebung zwischen Nachbarzellen (~0,3 A Ausgleichsstrom)
        for k in range(BC.CELLS - 1):
            diff = self.cell_soc[k] - self.cell_soc[k + 1]
            if abs(diff) > 0.3:
                shift = math.copysign(min(abs(diff) / 2, 0.3 * dt / 3600 / self.capacity_ah * 100), diff)
                self.cell_soc[k] -= shift
                self.cell_soc[k + 1] += shift
        self.cell_soc = [max(0.0, min(100.5, s)) for s in self.cell_soc]
        self._cc_acc += i * dt
        if now - self._last_cc >= 0.25:                      # CC-Wandlung alle 250 ms
            avg_i = self._cc_acc / (now - self._last_cc)
            raw = int(round(avg_i * BC.RSENSE_MOHM * 1000 / CC_LSB_UV))
            raw = max(-32768, min(32767, raw)) & 0xFFFF
            self.regs[CC_HI], self.regs[CC_HI + 1] = raw >> 8, raw & 0xFF
            if self.regs[SYS_CTRL2] & CTRL2_CC_EN:
                self.regs[SYS_STAT] |= ST_CC_READY
            self._cc_acc = 0.0
            self._last_cc = now
        self._i_now = i
        self._encode_voltages(i)

    def _adc_for_uv(self, uv: float) -> int:
        return max(0, min(0x3FFF, int(round((uv - self.OFFSET_MV * 1000) / self.GAIN_UV))))

    def _encode_voltages(self, i: float) -> None:
        cells_v = [soc_to_ocv(s) + i * r for s, r in zip(self.cell_soc, self.cell_r)]
        phys = [0.0] * 10
        for k, p in enumerate(BC.CELL_MAP):
            phys[p] = cells_v[k]
        for p in range(10):
            adc = self._adc_for_uv(phys[p] * 1e6) if phys[p] > 0 else 0
            self.regs[VC1_HI + 2 * p] = (adc >> 8) & 0x3F
            self.regs[VC1_HI + 2 * p + 1] = adc & 0xFF
        pack_uv = sum(cells_v) * 1e6
        adc = int(round((pack_uv - BC.CELLS * self.OFFSET_MV * 1000) / (4 * self.GAIN_UV)))
        self.regs[BAT_HI], self.regs[BAT_HI + 1] = (adc >> 8) & 0xFF, adc & 0xFF
        # NTC 10k/B3435 am internen 10k-Pullup (3,3 V)
        r = 10000 * math.exp(3435 * (1 / (self.temp_c + 273.15) - 1 / 298.15))
        v = 3.3 * r / (10000 + r)
        ts = int(v * 1e6 / TS_LSB_UV)
        for reg in (TS1_HI, TS2_HI):
            self.regs[reg], self.regs[reg + 1] = (ts >> 8) & 0x3F, ts & 0xFF
        # Hardware-Schutz nachbilden
        if max(cells_v) > BC.OV_CELL_V:
            self.regs[SYS_STAT] |= ST_OV
            self.regs[SYS_CTRL2] &= ~CTRL2_CHG_ON
        if min(cells_v) < BC.UV_CELL_V:
            self.regs[SYS_STAT] |= ST_UV
            self.regs[SYS_CTRL2] &= ~CTRL2_DSG_ON

    def read(self, reg: int, n: int = 1) -> list[int]:
        with self.lock:
            self._step()
            return self.regs[reg:reg + n]

    def write(self, reg: int, value: int) -> None:
        with self.lock:
            self._step()
            if reg == SYS_STAT:                       # Bits durch Schreiben einer 1 löschen
                self.regs[SYS_STAT] &= ~value & 0xFF
            else:
                self.regs[reg] = value & 0xFF

    def inject_fault(self, bits: int) -> None:
        """Für Tests/Demo: Fehlerbits setzen (z.B. ST_OCD) und FET abschalten."""
        with self.lock:
            self.regs[SYS_STAT] |= bits
            if bits & (ST_OCD | ST_SCD | ST_UV):
                self.regs[SYS_CTRL2] &= ~CTRL2_DSG_ON


# =============================================================================
# BQ76930-Treiber
# =============================================================================
class BQ76930:
    def __init__(self, io: _RegisterIO, rsense_mohm: float = BC.RSENSE_MOHM,
                 cell_map: tuple[int, ...] = BC.CELL_MAP):
        self.io = io
        self.rsense_mohm = rsense_mohm
        self.cell_map = cell_map
        self.gain_uv = 380
        self.offset_mv = 0
        self.simulated = isinstance(io, SimulatedBQ76930)

    # ---------- Initialisierung ----------
    def initialize(self) -> None:
        self.io.write(CC_CFG, 0x19)                   # laut Datenblatt Pflicht
        g1 = self.io.read(ADCGAIN1)[0]
        g2 = self.io.read(ADCGAIN2)[0]
        off = self.io.read(ADCOFFSET)[0]
        self.gain_uv = 365 + (((g1 & 0x0C) << 1) | ((g2 & 0xE0) >> 5))
        self.offset_mv = off - 256 if off & 0x80 else off
        self.io.write(SYS_CTRL1, CTRL1_ADC_EN | CTRL1_TEMP_SEL)   # ADC an, externe NTCs
        self.configure_protection()
        self.io.write(SYS_STAT, 0xFF)                 # alle Flags quittieren
        self.io.write(SYS_CTRL2, CTRL2_CC_EN)         # CC kontinuierlich (250 ms), FETs noch aus
        self.set_fets(chg=True, dsg=True)
        log.info("BQ76930 init: GAIN=%d µV/LSB, OFFSET=%d mV%s", self.gain_uv, self.offset_mv,
                 " (Simulation)" if self.simulated else "")

    def configure_protection(self, ov_v: float = BC.OV_CELL_V, uv_v: float = BC.UV_CELL_V,
                             ocd_a: float = BC.OCD_A, scd_a: float = BC.SCD_A) -> dict:
        r = self.rsense_mohm
        scd_i = _nearest_index(SCD_THRESH_MV, scd_a * r)
        ocd_i = _nearest_index(OCD_THRESH_MV, ocd_a * r)
        scd_delay, ocd_delay = 2, 4                   # 200 µs / 160 ms
        uv_delay, ov_delay = 1, 1                     # 4 s / 2 s
        self.io.write(PROTECT1, 0x80 | (scd_delay << 3) | scd_i)   # RSNS = 1
        self.io.write(PROTECT2, (ocd_delay << 4) | ocd_i)
        self.io.write(PROTECT3, (uv_delay << 6) | (ov_delay << 4))
        # OV_TRIP: ADC = 10-XXXX-XXXX-1000, UV_TRIP: ADC = 01-XXXX-XXXX-0000
        ov_adc = int((ov_v * 1e6 - self.offset_mv * 1000) / self.gain_uv)
        uv_adc = int(math.ceil((uv_v * 1e6 - self.offset_mv * 1000) / self.gain_uv))
        self.io.write(OV_TRIP, (ov_adc >> 4) & 0xFF)
        self.io.write(UV_TRIP, ((uv_adc + 15) >> 4) & 0xFF)
        cfg = {"scd_a": SCD_THRESH_MV[scd_i] / r, "ocd_a": OCD_THRESH_MV[ocd_i] / r,
               "scd_delay_us": SCD_DELAY_US[scd_delay], "ocd_delay_ms": OCD_DELAY_MS[ocd_delay],
               "ov_v": ov_v, "uv_v": uv_v}
        log.info("BQ76930 Schutz: %s", cfg)
        return cfg

    # ---------- Messwerte ----------
    def read_cells_v(self) -> list[float]:
        raw = self.io.read(VC1_HI, 20)
        phys = []
        for p in range(10):
            adc = ((raw[2 * p] & 0x3F) << 8) | raw[2 * p + 1]
            phys.append((adc * self.gain_uv + self.offset_mv * 1000) / 1e6)
        return [phys[p] for p in self.cell_map]

    def read_pack_v(self) -> float:
        hi, lo = self.io.read(BAT_HI, 2)
        adc = (hi << 8) | lo
        return (4 * self.gain_uv * adc + len(self.cell_map) * self.offset_mv * 1000) / 1e6

    def read_current_a(self) -> float:
        hi, lo = self.io.read(CC_HI, 2)
        raw = (hi << 8) | lo
        if raw & 0x8000:
            raw -= 0x10000
        return raw * CC_LSB_UV / (self.rsense_mohm * 1000.0)

    def read_temperatures_c(self) -> list[float]:
        temps = []
        for reg in (TS1_HI, TS2_HI):
            hi, lo = self.io.read(reg, 2)
            v = (((hi & 0x3F) << 8) | lo) * TS_LSB_UV / 1e6
            if not 0.05 < v < 3.25:
                temps.append(float("nan"))           # NTC offen / Kurzschluss
                continue
            r = 10000.0 * v / (3.3 - v)
            temps.append(1.0 / (1.0 / 298.15 + math.log(r / 10000.0) / 3435.0) - 273.15)
        return temps

    def read_status(self) -> int:
        return self.io.read(SYS_STAT)[0]

    def clear_status(self, bits: int) -> None:
        self.io.write(SYS_STAT, bits)

    def read_fets(self) -> tuple[bool, bool]:
        c = self.io.read(SYS_CTRL2)[0]
        return bool(c & CTRL2_CHG_ON), bool(c & CTRL2_DSG_ON)

    def set_fets(self, chg: bool, dsg: bool) -> None:
        c = self.io.read(SYS_CTRL2)[0] & ~(CTRL2_CHG_ON | CTRL2_DSG_ON)
        self.io.write(SYS_CTRL2, c | (CTRL2_CHG_ON if chg else 0) | (CTRL2_DSG_ON if dsg else 0))

    # ---------- passives Balancing ----------
    def set_balancing(self, cells: set[int]) -> set[int]:
        """Logische Zellindizes 0..7. Benachbarte Zellen innerhalb einer 5er-Gruppe werden
        laut Datenblatt NICHT gleichzeitig entladen – Konflikte werden verworfen."""
        mask, applied = 0, set()
        for k in sorted(cells):
            p = self.cell_map[k]
            left = p % 5 != 0 and mask >> (p - 1) & 1
            right = p % 5 != 4 and mask >> (p + 1) & 1
            if left or right:
                continue
            mask |= 1 << p
            applied.add(k)
        self.io.write(CELLBAL1, mask & 0x1F)
        self.io.write(CELLBAL2, (mask >> 5) & 0x1F)
        return applied


# =============================================================================
# SOC-Schätzer
# =============================================================================
class SocEstimator:
    REST_CURRENT_A = 0.05
    REST_TIME_S = 1800

    def __init__(self, capacity_ah: float, state_file: Optional[Path] = None):
        self.capacity_ah = capacity_ah
        self.state_file = state_file
        self.soc: Optional[float] = None
        self.discharged_ah_total = 0.0
        self.charged_ah_total = 0.0
        self._rest_since: Optional[float] = None
        self._last_save = 0.0
        self._load()

    def _load(self) -> None:
        if not self.state_file or not self.state_file.exists():
            return
        try:
            st = json.loads(self.state_file.read_text())
            self.discharged_ah_total = st.get("discharged_ah_total", 0.0)
            self.charged_ah_total = st.get("charged_ah_total", 0.0)
            # gespeicherter SOC nur übernehmen, wenn jünger als 7 Tage (Selbstentladung)
            if time.time() - st.get("saved_at", 0) < 7 * 86400:
                self.soc = float(st["soc"])
        except (OSError, ValueError, KeyError) as exc:
            log.warning("BMS-Zustand nicht lesbar: %s", exc)

    def save(self, force: bool = False) -> None:
        if not self.state_file or self.soc is None:
            return
        if not force and time.monotonic() - self._last_save < 60:
            return
        self._last_save = time.monotonic()
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps({"soc": round(self.soc, 3), "saved_at": time.time(),
                                       "discharged_ah_total": self.discharged_ah_total,
                                       "charged_ah_total": self.charged_ah_total}))
            tmp.replace(self.state_file)
        except OSError as exc:
            log.warning("BMS-Zustand nicht speicherbar: %s", exc)

    @property
    def cycles(self) -> float:
        return self.discharged_ah_total / self.capacity_ah

    def update(self, current_a: float, dt_s: float, cells_v: list[float]) -> float:
        if self.soc is None:   # Erststart: OCV-Schätzung über die Zellen (Mittelwert)
            self.soc = sum(ocv_to_soc(v) for v in cells_v) / len(cells_v)
        ah = current_a * dt_s / 3600.0
        if ah < 0:
            self.discharged_ah_total += -ah
        else:
            self.charged_ah_total += ah
        self.soc += ah / self.capacity_ah * 100.0

        vmax, vmin = max(cells_v), min(cells_v)
        if current_a >= 0 and vmax >= 3.55 and current_a < self.capacity_ah / 20:
            self.soc = 100.0                       # Ladeschluss erkannt
        if vmin <= 2.80:
            self.soc = min(self.soc, 2.0)          # untere Kante – schwächste Zelle zählt

        if abs(current_a) < self.REST_CURRENT_A:   # Ruhephase -> OCV-Abgleich
            now = time.monotonic()
            self._rest_since = self._rest_since or now
            if now - self._rest_since > self.REST_TIME_S:
                ocv_soc = ocv_to_soc(sum(cells_v) / len(cells_v))
                if ocv_reliable(ocv_soc):
                    self.soc += (ocv_soc - self.soc) * 0.05
        else:
            self._rest_since = None
        self.soc = max(0.0, min(100.0, self.soc))
        self.save()
        return self.soc


# =============================================================================
# Status-Objekt (UI + Telemetrie)
# =============================================================================
@dataclass
class PackStatus:
    timestamp: float
    cells_v: list[float]
    pack_voltage_v: float
    current_a: float
    soc_percent: float
    temperatures_c: list[float]
    cell_drift_mv: float
    min_cell: int
    max_cell: int
    charging: bool
    chg_fet: bool
    dsg_fet: bool
    faults: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    passive_balancing: list[int] = field(default_factory=list)
    active_balancing: str = "inaktiv"
    remaining_wh: float = 0.0
    minutes_remaining: Optional[float] = None
    cycles: float = 0.0
    simulated: bool = False

    @property
    def level(self) -> str:
        """Ampel für die Statusleiste: ok | warn | critical"""
        if self.faults or self.soc_percent <= BC.CRITICAL_SOC:
            return "critical"
        if self.warnings or self.soc_percent <= BC.WARN_SOC:
            return "warn"
        return "ok"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["level"] = self.level
        d["cells"] = [{"name": f"Z{i + 1}", "v": round(v, 4),
                       "delta_mv": round((v - self.cells_v[self.min_cell]) * 1000, 1),
                       "balancing": i in self.passive_balancing}
                      for i, v in enumerate(self.cells_v)]
        d["temperatures_c"] = [None if math.isnan(t) else round(t, 1) for t in self.temperatures_c]
        return d

    def to_telemetry(self) -> dict:
        """Spalten für telemetry_timeseries (Grafana)."""
        row = {"pack_voltage_v": round(self.pack_voltage_v, 3),
               "pack_current_a": round(self.current_a, 3),
               "soc_percent": round(self.soc_percent, 2),
               "cell_drift_mv": round(self.cell_drift_mv, 1)}
        for i in range(BC.CELLS):
            row[f"cell_{i + 1}_v"] = round(self.cells_v[i], 4) if i < len(self.cells_v) else None
        return row


# =============================================================================
# BatteryMonitor – Hintergrunddienst
# =============================================================================
class BatteryMonitor:
    def __init__(self, *, simulate: Optional[bool] = None, capacity_ah: float = BC.CAPACITY_AH,
                 poll_interval_s: float = 1.0, state_file: Optional[Path] = config.BMS_STATE_FILE,
                 sim_current_provider: Optional[Callable[[], float]] = None):
        self.poll_interval_s = poll_interval_s
        self.capacity_ah = capacity_ah
        if simulate is None:
            simulate = simulation_requested("bms")
        io: Optional[_RegisterIO] = None
        if not simulate:
            bus = get_i2c_bus(config.I2C_BUS, component="bms")
            if bus and bus.probe(config.I2CAddr.BQ76930):
                io = _I2CRegisterIO(bus, config.I2CAddr.BQ76930, BC.USE_CRC)
            else:
                log.error("BQ76930 an 0x%02X nicht erreichbar – Simulation aktiv", config.I2CAddr.BQ76930)
        if io is None:
            simulate = True
            io = SimulatedBQ76930(capacity_ah, current_provider=sim_current_provider)
        self.simulated = simulate
        self.bq = BQ76930(io)
        self.soc = SocEstimator(capacity_ah, state_file)
        self._alert_event = threading.Event()
        self.alert_pin = digital_input(config.Pins.BMS_ALERT, pull_up=False, component="bms")
        self.alert_pin.when_activated = self._alert_event.set
        self._latest: Optional[PackStatus] = None
        self._lock = threading.Lock()
        self._subs: list[Callable[[PackStatus], None]] = []
        self._critical_cbs: list[Callable[[str], None]] = []
        self._fault_cbs: list[Callable[[list[str]], None]] = []
        self._critical_fired = False
        self._critical_since: Optional[float] = None
        self._active_faults: set[int] = set()
        self._current_a = 0.0
        self._last_cc_t = time.monotonic()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.passive_balancing_enabled = BC.PASSIVE_BALANCING
        self._bal_cells: set[int] = set()

    # ---------- Lebenszyklus ----------
    def start(self) -> "BatteryMonitor":
        self.bq.initialize()
        self._thread = threading.Thread(target=self._run, name="bms", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._alert_event.set()
        if self._thread:
            self._thread.join(timeout=3)
        try:
            self.bq.set_balancing(set())
        except Exception:
            pass
        self.soc.save(force=True)

    # ---------- Abos ----------
    def subscribe(self, cb: Callable[[PackStatus], None]) -> None:
        self._subs.append(cb)

    def on_critical(self, cb: Callable[[str], None]) -> None:
        """cb(reason) – einmalig bei kritischem Ladezustand -> App fährt geordnet herunter."""
        self._critical_cbs.append(cb)

    def on_fault(self, cb: Callable[[list[str]], None]) -> None:
        self._fault_cbs.append(cb)

    def latest(self) -> Optional[PackStatus]:
        with self._lock:
            return self._latest

    # ---------- Aktionen ----------
    def clear_faults(self) -> bool:
        """Fehler quittieren und FETs wieder einschalten (nur wenn Ursache beseitigt)."""
        self.bq.clear_status(FAULT_MASK)
        st = self.bq.read_status()
        if st & FAULT_MASK:
            return False
        self.bq.set_fets(chg=True, dsg=True)
        self._active_faults.clear()
        return True

    # ---------- Thread ----------
    def _run(self) -> None:
        last_full = 0.0
        while not self._stop.is_set():
            self._alert_event.wait(timeout=0.3)   # ALERT kommt mit CC_READY alle 250 ms
            self._alert_event.clear()
            try:
                self._service_alert()
                now = time.monotonic()
                if now - last_full >= self.poll_interval_s:
                    last_full = now
                    self._publish(self._measure())
            except Exception:
                log.exception("BMS-Abfrage fehlgeschlagen")
                time.sleep(1.0)

    def _service_alert(self) -> None:
        st = self.bq.read_status()
        if st & ST_CC_READY:
            self._current_a = self.bq.read_current_a()
            self._last_cc_t = time.monotonic()
            self.bq.clear_status(ST_CC_READY)
        new = {b for b in FAULT_TEXT if st & b} - self._active_faults
        if new:
            self._active_faults |= new
            texts = [FAULT_TEXT[b] for b in sorted(new)]
            log.error("BMS-Fehler: %s", ", ".join(texts))
            for cb in list(self._fault_cbs):
                try:
                    cb(texts)
                except Exception:
                    log.exception("BMS-Fehler-Callback")

    def _measure(self) -> PackStatus:
        cells = self.bq.read_cells_v()
        pack = self.bq.read_pack_v()
        temps = self.bq.read_temperatures_c()
        chg, dsg = self.bq.read_fets()
        i = self._current_a
        dt = getattr(self, "_last_soc_t", None)
        now = time.monotonic()
        self._last_soc_t = now
        soc = self.soc.update(i, (now - dt) if dt else 0.0, cells)

        vmin, vmax = min(cells), max(cells)
        drift = (vmax - vmin) * 1000.0
        warnings = []
        if drift >= BC.DRIFT_ALARM_MV:
            warnings.append(f"Zelldrift {drift:.0f} mV – Akku prüfen")
        elif drift >= BC.DRIFT_WARN_MV:
            warnings.append(f"Zelldrift {drift:.0f} mV")
        valid_t = [t for t in temps if not math.isnan(t)]
        if valid_t and (max(valid_t) > 50 or (i > 0.05 and min(valid_t) < 0)):
            warnings.append("Akkutemperatur außerhalb des Ladebereichs (0..45 °C)")
        if soc <= BC.WARN_SOC:
            warnings.append(f"Akku niedrig ({soc:.0f} %)")

        self._update_passive_balancing(cells, i)
        energy_wh = soc / 100.0 * self.capacity_ah * BC.CELLS * BC.NOMINAL_CELL_V
        mins = None
        if i < -0.02:
            mins = soc / 100.0 * self.capacity_ah / -i * 60.0
        elif i > 0.02:
            mins = (100.0 - soc) / 100.0 * self.capacity_ah / i * 60.0

        st = PackStatus(
            timestamp=time.time(), cells_v=cells, pack_voltage_v=pack, current_a=i,
            soc_percent=soc, temperatures_c=temps, cell_drift_mv=drift,
            min_cell=cells.index(vmin), max_cell=cells.index(vmax), charging=i > 0.02,
            chg_fet=chg, dsg_fet=dsg, faults=[FAULT_TEXT[b] for b in sorted(self._active_faults)],
            warnings=warnings, passive_balancing=sorted(self._bal_cells),
            active_balancing=f"ETA3000 x{BC.ETA3000_COUNT} " + ("gleicht aus" if drift > 10 else "im Gleichgewicht"),
            remaining_wh=energy_wh, minutes_remaining=mins, cycles=self.soc.cycles,
            simulated=self.simulated)
        self._check_critical(st)
        return st

    def _update_passive_balancing(self, cells: list[float], current_a: float) -> None:
        want: set[int] = set()
        if self.passive_balancing_enabled and current_a > 0.02:
            vmin = min(cells)
            want = {k for k, v in enumerate(cells)
                    if v >= BC.PASSIVE_BAL_START_V and (v - vmin) * 1000 > BC.DRIFT_WARN_MV}
        if want != self._bal_cells:
            self._bal_cells = self.bq.set_balancing(want)

    def _check_critical(self, st: PackStatus) -> None:
        reason = None
        if st.soc_percent <= BC.CRITICAL_SOC and not st.charging:
            reason = f"Akku kritisch: {st.soc_percent:.1f} %"
        elif min(st.cells_v) <= BC.CRITICAL_CELL_V and not st.charging:
            reason = f"Zelle Z{st.min_cell + 1} kritisch: {min(st.cells_v):.3f} V"
        if reason is None:
            self._critical_since = None
            self._critical_fired = False
            return
        self._critical_since = self._critical_since or time.monotonic()
        # 10 s entprellen (Lastspitzen beim Kamerastart o.ä.)
        if not self._critical_fired and time.monotonic() - self._critical_since >= 10:
            self._critical_fired = True
            log.critical(reason)
            for cb in list(self._critical_cbs):
                try:
                    cb(reason)
                except Exception:
                    log.exception("Kritisch-Callback")

    def _publish(self, st: PackStatus) -> None:
        with self._lock:
            self._latest = st
        for cb in list(self._subs):
            try:
                cb(st)
            except Exception:
                log.exception("BMS-Subscriber")


# =============================================================================
# Soft-Power-Selbsthaltung (GPIO25)
# =============================================================================
class PowerLatch:
    """Selbsthaltung der Versorgung.

    Empfohlene Variante (POWER_LATCH_VIA_OVERLAY=True), config.txt:
        dtoverlay=gpio-poweroff,gpiopin=25,active_low=1
    Der Kernel hält GPIO25 dann ab Boot HIGH und zieht ihn erst ganz am Ende des
    Shutdowns (nach dem Unmount der eMMC) auf LOW. Python löst nur `poweroff` aus.

    Ohne Overlay hält Python den Pin. Achtung: Endet der Prozess, fällt die
    Selbsthaltung – daher wird dann VOR dem Abschalten explizit `sync` ausgeführt.
    """

    def __init__(self, via_overlay: bool = config.POWER_LATCH_VIA_OVERLAY,
                 simulate: Optional[bool] = None):
        self.via_overlay = via_overlay
        self.simulated = simulation_requested("power") if simulate is None else simulate
        self._pin = None
        if not via_overlay:
            self._pin = digital_output(config.Pins.POWER_LATCH, active_high=True,
                                       initial_value=True, component="power")
        self._shutdown_hooks: list[Callable[[str], None]] = []
        self._shutting_down = False

    def add_shutdown_hook(self, cb: Callable[[str], None]) -> None:
        """z.B. Telemetrie 'SHUTDOWN'-Event schreiben, offene DB-Transaktionen schließen."""
        self._shutdown_hooks.append(cb)

    def shutdown(self, reason: str = "Benutzer") -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        log.warning("Geordneter Shutdown: %s", reason)
        for cb in self._shutdown_hooks:
            try:
                cb(reason)
            except Exception:
                log.exception("Shutdown-Hook")
        if self.simulated:
            log.warning("[SIM] poweroff würde jetzt ausgeführt")
            return
        os.sync()
        if self.via_overlay:
            subprocess.Popen(["sudo", "-n", "systemctl", "poweroff"])
        else:  # pragma: no cover - nur Notfallvariante
            time.sleep(1.0)
            self._pin.off()


# =============================================================================
# Demo:  python battery_bms.py
# =============================================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    mon = BatteryMonitor(simulate=True, state_file=None, poll_interval_s=0.5)
    mon.on_fault(lambda f: print("!! FEHLER:", f))
    mon.start()
    time.sleep(1.6)
    s = mon.latest()
    print(f"Pack {s.pack_voltage_v:.2f} V  {s.current_a:+.3f} A  SOC {s.soc_percent:.1f} %  "
          f"Drift {s.cell_drift_mv:.1f} mV  T={s.temperatures_c[0]:.1f} °C  [{s.level}]")
    for c in s.to_dict()["cells"]:
        print(f"  {c['name']}: {c['v']:.4f} V  (+{c['delta_mv']:.1f} mV)")
    print("Telemetrie:", s.to_telemetry())
    mon.bq.io.inject_fault(ST_OCD)
    time.sleep(0.8)
    print("Faults:", mon.latest().faults, "DSG-FET:", mon.latest().dsg_fet)
    mon.bq.io.regs[SYS_STAT] &= ~ST_OCD
    print("Quittiert:", mon.clear_faults())
    mon.stop()
