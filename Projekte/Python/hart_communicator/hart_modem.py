"""
hart_modem.py – HART-Protokollstack + AD5700-Treiber + Bus-Sniffer + Simulation.

Schichten:
  1. Codec        – Packed-ASCII, IEEE-754, Einheiten, Rahmenaufbau/-parser
  2. Transport    – SerialTransport (AD5700: UART 1200 8E1, RTS GPIO17 active-low,
                    OCD GPIO27) oder SimulatedTransport (virtuelle Feldgeräte)
  3. HartModem    – Kommandos 0/1/2/3/12/13/15/48 (lesen) sowie 6/18/35/38/40/44
                    (schreiben), Wiederholungen, Busarbitrierung, 24/7-Safe-Mode

24/7-Safe-Mode (Nur-Lesen):
  Whitelist-Prinzip – im Safe-Mode werden AUSSCHLIESSLICH Kommandos aus
  READ_ONLY_COMMANDS gesendet. Alles andere (auch unbekannte, gerätespezifische
  Kommandos) wird VOR dem Senden mit SafeModeError abgelehnt. Fail-safe.

Der Communicator arbeitet als Secondary Master (Handheld), d.h. das Master-Bit
im Adressbyte ist 0 – so stört er ein Leitsystem (Primary Master) nicht.
"""
from __future__ import annotations

import logging
import math
import random
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Iterable, Optional

import config
from hw_compat import digital_input, digital_output, simulation_requested

log = logging.getLogger(__name__)

# =============================================================================
# 1. Protokollkonstanten
# =============================================================================
CHAR_TIME_S = 11.0 / config.HART_BAUDRATE   # 1 Start + 8 Daten + Parität + 1 Stopp

FRAME_BACK, FRAME_STX, FRAME_ACK = 0x01, 0x02, 0x06   # Bits 0..2 des Delimiters
DELIM_LONG_ADDR = 0x80
ADDR_MASTER_PRIMARY = 0x80
ADDR_BURST = 0x40

READ_ONLY_COMMANDS: frozenset[int] = frozenset({
    0,   # Read Unique Identifier
    1,   # Read Primary Variable
    2,   # Read Loop Current and Percent of Range
    3,   # Read Dynamic Variables and Loop Current
    7,   # Read Loop Configuration
    8,   # Read Dynamic Variable Classifications
    9,   # Read Device Variables with Status
    11,  # Read Unique Identifier Associated with Tag
    12,  # Read Message
    13,  # Read Tag, Descriptor, Date
    14,  # Read Primary Variable Transducer Information
    15,  # Read Device Information (Range)
    16,  # Read Final Assembly Number
    20,  # Read Long Tag
    21,  # Read Unique Identifier Associated with Long Tag
    48,  # Read Additional Device Status
})

WRITE_COMMANDS_INFO = {
    6: "Write Polling Address", 18: "Write Tag, Descriptor, Date", 35: "Write Range Values",
    38: "Reset Configuration Changed Flag", 40: "Enter/Exit Fixed Current Mode",
    44: "Write PV Units",
}

# Response Codes (allgemeine Bedeutung; kommandospezifische Abweichungen möglich)
RESPONSE_CODES = {
    0: "Erfolgreich",
    2: "Ungültige Auswahl",
    3: "Parameter zu groß",
    4: "Parameter zu klein",
    5: "Zu wenige Datenbytes",
    6: "Gerätespezifischer Kommandofehler",
    7: "Gerät im Schreibschutz",
    8: "Warnung: Wert angepasst / Update-Fehler",
    9: "Unterer Messbereichswert zu hoch / Wert unzulässig",
    10: "Unterer Messbereichswert zu niedrig",
    11: "Oberer Messbereichswert zu hoch / Schleifenstrom-Modus falsch",
    12: "Oberer Messbereichswert zu niedrig",
    13: "Beide Messbereichswerte außerhalb der Grenzen",
    14: "Warnung: Messspanne zu klein",
    16: "Zugriff eingeschränkt",
    32: "Gerät beschäftigt",
    33: "Verzögerte Antwort eingeleitet",
    34: "Verzögerte Antwort läuft",
    35: "Verzögerte Antwort abgeschlossen",
    64: "Kommando nicht implementiert",
}
WARNING_CODES = frozenset({8, 14})
BUSY_CODES = frozenset({32, 33, 34})

FIELD_DEVICE_STATUS_BITS = {
    0x80: "Gerätestörung (Device Malfunction)",
    0x40: "Konfiguration geändert",
    0x20: "Kaltstart",
    0x10: "Weitere Statusinformationen verfügbar (Cmd 48)",
    0x08: "Schleifenstrom fixiert",
    0x04: "Schleifenstrom gesättigt",
    0x02: "Nicht-Primärvariable außerhalb der Grenzen",
    0x01: "Primärvariable außerhalb der Grenzen",
}
COMM_ERROR_BITS = {
    0x40: "Paritätsfehler (vertikal)", 0x20: "Überlauf", 0x10: "Rahmenfehler (Framing)",
    0x08: "Prüfsummenfehler (longitudinal)", 0x02: "Puffer-Überlauf",
}

# Einheitencodes (HART Common Table 2, Auszug)
UNIT_CODES: dict[int, str] = {
    1: "inH2O", 2: "inHg", 3: "ftH2O", 4: "mmH2O", 5: "mmHg", 6: "psi", 7: "bar",
    8: "mbar", 9: "g/cm²", 10: "kg/cm²", 11: "Pa", 12: "kPa", 13: "Torr", 14: "atm",
    15: "ft³/min", 16: "gal/min", 17: "l/min", 19: "m³/h", 22: "gal/s", 24: "l/s",
    32: "°C", 33: "°F", 34: "°R", 35: "K", 36: "mV", 37: "Ω", 38: "Hz", 39: "mA",
    40: "gal", 41: "l", 43: "m³", 44: "ft", 45: "m", 47: "in", 48: "cm", 49: "mm",
    57: "%", 58: "V", 70: "g/s", 72: "g/h", 73: "kg/s", 74: "kg/min",
    75: "kg/h", 237: "MPa", 250: "nicht verwendet", 251: "keine", 252: "unbekannt",
    253: "spezial",
}
UNIT_BY_NAME = {v.lower(): k for k, v in UNIT_CODES.items()}


def unit_name(code: Optional[int]) -> str:
    if code is None:
        return ""
    return UNIT_CODES.get(code, f"Einheit {code}")


# =============================================================================
# 2. Exceptions
# =============================================================================
class HartError(Exception):
    """Basisklasse aller HART-Fehler."""


class HartTimeoutError(HartError):
    """Keine (vollständige) Antwort innerhalb der Zeit."""


class HartFrameError(HartError):
    """Prüfsumme, Adresse oder Kommando der Antwort passen nicht."""


class HartCommunicationError(HartError):
    """Das Feldgerät meldet einen Übertragungsfehler (Status-Byte 0, Bit 7)."""

    def __init__(self, flags: int):
        self.flags = flags
        txt = ", ".join(t for b, t in COMM_ERROR_BITS.items() if flags & b) or f"0x{flags:02X}"
        super().__init__(f"Kommunikationsfehler im Feldgerät: {txt}")


class HartCommandError(HartError):
    def __init__(self, command: int, response_code: int):
        self.command, self.response_code = command, response_code
        super().__init__(f"Cmd {command}: Response Code {response_code} – "
                         f"{RESPONSE_CODES.get(response_code, 'unbekannt')}")


class SafeModeError(HartError):
    """Schreibkommando im 24/7-Safe-Mode blockiert."""

    def __init__(self, command: int):
        self.command = command
        name = WRITE_COMMANDS_INFO.get(command, "Schreib-/gerätespezifisches Kommando")
        super().__init__(f"24/7-Safe-Mode aktiv: Command {command} ({name}) blockiert")


# =============================================================================
# 3. Codec-Hilfsfunktionen
# =============================================================================
_PACKED_ALLOWED = set("@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_ !\"#$%&'()*+,-./0123456789:;<=>?")


def sanitize_packed(text: str, length: int) -> str:
    """Großschreibung, ungültige Zeichen -> '?', auf Länge mit Leerzeichen."""
    t = "".join(c if c in _PACKED_ALLOWED else "?" for c in text.upper().replace("Ä", "AE")
                .replace("Ö", "OE").replace("Ü", "UE").replace("ß", "SS"))
    return t[:length].ljust(length)


def pack_ascii(text: str, n_chars: int) -> bytes:
    """Packed ASCII (6 Bit/Zeichen, 4 Zeichen -> 3 Bytes). n_chars muss Vielfaches von 4 sein."""
    if n_chars % 4:
        raise ValueError("n_chars muss ein Vielfaches von 4 sein")
    t = sanitize_packed(text, n_chars)
    out = bytearray()
    for i in range(0, n_chars, 4):
        v = 0
        for ch in t[i:i + 4]:
            v = (v << 6) | (ord(ch) & 0x3F)
        out += v.to_bytes(3, "big")
    return bytes(out)


def unpack_ascii(data: bytes) -> str:
    chars = []
    for i in range(0, len(data) - len(data) % 3, 3):
        v = int.from_bytes(data[i:i + 3], "big")
        for shift in (18, 12, 6, 0):
            c = (v >> shift) & 0x3F
            chars.append(chr(c | 0x40 if c < 0x20 else c))
    return "".join(chars)


def f32(data: bytes, offset: int = 0) -> float:
    return struct.unpack_from(">f", data, offset)[0]


def to_f32(value: float) -> bytes:
    return struct.pack(">f", value)


def encode_date(d: Optional[date]) -> bytes:
    d = d or date.today()
    return bytes([d.day, d.month, (d.year - 1900) & 0xFF])


def decode_date(b: bytes) -> Optional[date]:
    try:
        return date(1900 + b[2], b[1], b[0])
    except (ValueError, IndexError):
        return None


def checksum(data: bytes) -> int:
    c = 0
    for b in data:
        c ^= b
    return c


def hexdump(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def decode_device_status(status: int) -> list[str]:
    return [t for b, t in FIELD_DEVICE_STATUS_BITS.items() if status & b]


# =============================================================================
# 4. Rahmen
# =============================================================================
@dataclass
class HartFrame:
    delimiter: int
    address: bytes
    command: int
    payload: bytes = b""          # bei Antworten inkl. 2 Statusbytes
    expansion: bytes = b""
    preamble_len: int = 5

    @property
    def frame_type(self) -> int:
        return self.delimiter & 0x07

    @property
    def is_long(self) -> bool:
        return bool(self.delimiter & DELIM_LONG_ADDR)

    @property
    def is_request(self) -> bool:
        return self.frame_type == FRAME_STX

    @property
    def is_burst(self) -> bool:
        return self.frame_type == FRAME_BACK

    @property
    def status(self) -> tuple[int, int]:
        if self.is_request or len(self.payload) < 2:
            return (0, 0)
        return self.payload[0], self.payload[1]

    @property
    def data(self) -> bytes:
        return self.payload if self.is_request else self.payload[2:]

    def encode(self) -> bytes:
        body = bytes([self.delimiter]) + self.address + self.expansion + \
            bytes([self.command, len(self.payload)]) + self.payload
        return b"\xFF" * self.preamble_len + body + bytes([checksum(body)])

    def summary(self) -> str:
        kind = {FRAME_STX: "STX", FRAME_ACK: "ACK", FRAME_BACK: "BURST"}.get(self.frame_type, "?")
        if self.is_long:
            a = self.address
            addr = f"{a[0] & 0x3F:02X}{a[1]:02X}:{a[2]:02X}{a[3]:02X}{a[4]:02X}"
            master = "P" if a[0] & ADDR_MASTER_PRIMARY else "S"
        else:
            addr = f"Poll {self.address[0] & 0x3F}"
            master = "P" if self.address[0] & ADDR_MASTER_PRIMARY else "S"
        s = f"{kind} [{master}] {addr} CMD {self.command} BC {len(self.payload)}"
        if not self.is_request:
            rc, ds = self.status
            if rc & 0x80:
                s += f" COMM-ERR 0x{rc:02X}"
            else:
                s += f" RC {rc} DS 0x{ds:02X}"
        return s


def build_request(address: bytes, command: int, data: bytes = b"", preambles: int = 5) -> HartFrame:
    delim = FRAME_STX | (DELIM_LONG_ADDR if len(address) == 5 else 0)
    return HartFrame(delim, address, command, data, preamble_len=max(5, min(20, preambles)))


class FrameParser:
    """Inkrementeller Parser für den empfangenen Bytestrom (min. 2 Präambeln)."""

    MAX_BUFFER = 600

    def __init__(self):
        self.buf = bytearray()
        self.errors: list[str] = []

    def feed(self, data: bytes) -> list[HartFrame]:
        self.buf += data
        frames: list[HartFrame] = []
        while True:
            fr = self._try_parse()
            if fr is None:
                break
            frames.append(fr)
        if len(self.buf) > self.MAX_BUFFER:
            del self.buf[:-self.MAX_BUFFER]
        return frames

    def _try_parse(self) -> Optional[HartFrame]:
        b = self.buf
        i, n = 0, len(b)
        while i < n:
            # Präambel suchen: >= 2x 0xFF, gefolgt vom Delimiter
            if b[i] != 0xFF:
                i += 1
                continue
            j = i
            while j < n and b[j] == 0xFF:
                j += 1
            if j >= n:
                del b[:i]
                return None
            pre = j - i
            if pre < 2:
                i = j
                continue
            delim = b[j]
            if delim & 0x07 not in (FRAME_BACK, FRAME_STX, FRAME_ACK):
                i = j + 1
                continue
            alen = 5 if delim & DELIM_LONG_ADDR else 1
            exp = (delim >> 5) & 0x03
            hdr = 1 + alen + exp + 2
            if j + hdr > n:
                del b[:i]
                return None
            bc = b[j + hdr - 1]
            total = hdr + bc + 1
            if j + total > n:
                del b[:i]
                return None
            body = bytes(b[j:j + total - 1])
            chk = b[j + total - 1]
            if checksum(body) != chk:
                self.errors.append(f"Prüfsummenfehler ({hexdump(body[:8])}…)")
                i = j + 1
                continue
            fr = HartFrame(delimiter=delim, address=body[1:1 + alen],
                           expansion=body[1 + alen:1 + alen + exp],
                           command=body[1 + alen + exp], payload=body[hdr:], preamble_len=pre)
            del b[:j + total]
            return fr
        del b[:n]
        return None


# =============================================================================
# 5. Identität & Antworten
# =============================================================================
@dataclass
class DeviceIdentity:
    manufacturer_id: int
    device_type: int            # erweiterter 16-Bit-Gerätetyp
    device_id: int              # 24 Bit
    poll_address: int = 0
    preambles: int = 5
    universal_rev: int = 0
    device_rev: int = 0
    software_rev: int = 0
    hardware_rev: int = 0
    flags: int = 0
    config_change_counter: Optional[int] = None
    private_label_id: Optional[int] = None

    @property
    def unique_id(self) -> str:
        """Eindeutige Geräte-ID (5 Bytes Langadresse) als Hex-String – DB-Schlüssel."""
        return f"{self.device_type & 0x3FFF:04X}{self.device_id:06X}"

    def long_address(self, primary_master: bool = False) -> bytes:
        b0 = ((self.device_type >> 8) & 0x3F) | (ADDR_MASTER_PRIMARY if primary_master else 0)
        return bytes([b0, self.device_type & 0xFF]) + self.device_id.to_bytes(3, "big")

    @classmethod
    def from_cmd0(cls, data: bytes, poll_address: int = 0) -> "DeviceIdentity":
        if len(data) < 12 or data[0] != 254:
            raise HartFrameError(f"Ungültige Cmd-0-Antwort: {hexdump(data)}")
        urev = data[4]
        dtype = (data[1] << 8) | data[2]
        mfr = data[1]
        ccc = pl = None
        if urev >= 7 and len(data) >= 22:
            ccc = (data[14] << 8) | data[15]
            mfr = (data[17] << 8) | data[18]
            pl = (data[19] << 8) | data[20]
        return cls(manufacturer_id=mfr, device_type=dtype,
                   device_id=int.from_bytes(data[9:12], "big"), poll_address=poll_address,
                   preambles=data[3], universal_rev=urev, device_rev=data[5],
                   software_rev=data[6], hardware_rev=data[7] >> 3, flags=data[8],
                   config_change_counter=ccc, private_label_id=pl)

    def to_dict(self) -> dict:
        return {
            "unique_id": self.unique_id, "manufacturer_id": f"0x{self.manufacturer_id:04X}",
            "device_type": f"0x{self.device_type:04X}", "device_id": f"0x{self.device_id:06X}",
            "poll_address": self.poll_address, "universal_rev": self.universal_rev,
            "device_rev": self.device_rev, "software_rev": self.software_rev,
            "hardware_rev": self.hardware_rev, "preambles": self.preambles,
            "config_change_counter": self.config_change_counter,
        }


@dataclass
class HartResponse:
    command: int
    response_code: int
    device_status: int
    data: bytes
    raw_tx: bytes
    raw_rx: bytes

    @property
    def is_warning(self) -> bool:
        return self.response_code in WARNING_CODES

    @property
    def status_texts(self) -> list[str]:
        return decode_device_status(self.device_status)


# =============================================================================
# 6. Bus-Sniffer / Experten-Monitor
# =============================================================================
@dataclass
class SnifferEvent:
    timestamp: float
    direction: str          # "TX" | "RX" | "OCD" | "INFO" | "ERR" | "BLOCK"
    raw: bytes = b""
    ocd: bool = False
    summary: str = ""

    def to_dict(self) -> dict:
        return {"t": self.timestamp, "dir": self.direction, "hex": hexdump(self.raw),
                "ocd": self.ocd, "summary": self.summary}


class BusSniffer:
    def __init__(self, maxlen: int = 1000):
        self._events: deque[SnifferEvent] = deque(maxlen=maxlen)
        self._subs: list[Callable[[SnifferEvent], None]] = []
        self._lock = threading.Lock()
        self.enabled = True

    def record(self, direction: str, raw: bytes = b"", ocd: bool = False, summary: str = "") -> None:
        if not self.enabled:
            return
        ev = SnifferEvent(time.time(), direction, bytes(raw), ocd, summary)
        with self._lock:
            self._events.append(ev)
            subs = list(self._subs)
        for cb in subs:
            try:
                cb(ev)
            except Exception:  # Sniffer darf den Bus nie blockieren
                log.exception("Sniffer-Callback fehlgeschlagen")

    def subscribe(self, cb: Callable[[SnifferEvent], None]) -> None:
        with self._lock:
            self._subs.append(cb)

    def unsubscribe(self, cb: Callable[[SnifferEvent], None]) -> None:
        with self._lock:
            if cb in self._subs:
                self._subs.remove(cb)

    def snapshot(self, last: int = 200) -> list[dict]:
        with self._lock:
            return [e.to_dict() for e in list(self._events)[-last:]]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


# =============================================================================
# 7. Transporte
# =============================================================================
class Transport:
    simulated = False

    def transact(self, tx: bytes, timeout: float) -> list[HartFrame]:
        raise NotImplementedError

    def ocd_level(self) -> bool:
        return False

    def close(self) -> None:
        pass


class SerialTransport(Transport):
    """AD5700 an PL011-UART. RTS (GPIO17) LOW = Senden, OCD (GPIO27) HIGH = Träger."""

    def __init__(self, port: str, sniffer: BusSniffer):
        import serial  # pyserial
        self.sniffer = sniffer
        self.ser = serial.Serial(port, config.HART_BAUDRATE, bytesize=serial.EIGHTBITS,
                                 parity=serial.PARITY_EVEN, stopbits=serial.STOPBITS_ONE,
                                 timeout=CHAR_TIME_S * 2, write_timeout=5)
        # active_high=False -> on() zieht GPIO17 auf LOW (Senden), off() = HIGH (Empfang)
        self.rts = digital_output(config.Pins.HART_RTS, active_high=False, initial_value=False,
                                  component="hart")
        # AD5700 OCD ist ein Push-Pull-Ausgang -> kein Pull-Widerstand, HIGH = Träger erkannt
        self.ocd = digital_input(config.Pins.HART_OCD, pull_up=None, active_state=True, component="hart")
        self.ocd.when_activated = lambda *_: sniffer.record("OCD", ocd=True, summary="Träger EIN")
        self.ocd.when_deactivated = lambda *_: sniffer.record("OCD", ocd=False, summary="Träger AUS")

    def ocd_level(self) -> bool:
        return bool(self.ocd.is_active)

    def wait_bus_idle(self) -> bool:
        """Wartet, bis seit HART_BUS_IDLE_S kein Träger mehr anliegt (Primary Master / Burst)."""
        deadline = time.monotonic() + config.HART_BUS_IDLE_MAX_WAIT_S
        quiet_since = time.monotonic()
        while time.monotonic() < deadline:
            if self.ocd.is_active:
                quiet_since = time.monotonic()
            elif time.monotonic() - quiet_since >= config.HART_BUS_IDLE_S:
                return True
            time.sleep(0.005)
        return False

    def transact(self, tx: bytes, timeout: float) -> list[HartFrame]:
        if not self.wait_bus_idle():
            self.sniffer.record("INFO", summary="Bus dauerhaft belegt – sende trotzdem")
        self.ser.reset_input_buffer()
        self.rts.on()                              # Modulator ein (RTS LOW)
        time.sleep(CHAR_TIME_S)                    # Trägeraufbau ~1 Zeichenzeit
        try:
            self.ser.write(tx)
            self.ser.flush()                       # tcdrain()
            time.sleep(CHAR_TIME_S * 1.2)          # letztes Zeichen aus dem Schieberegister
        finally:
            self.rts.off()                         # zurück auf Empfang
        self.ser.reset_input_buffer()              # evtl. Echo verwerfen

        parser = FrameParser()
        rx = bytearray()
        t_end_first = time.monotonic() + timeout
        last_rx = None
        while True:
            chunk = self.ser.read(max(1, self.ser.in_waiting))
            now = time.monotonic()
            if chunk:
                rx += chunk
                last_rx = now
                frames = [f for f in parser.feed(chunk)]
                acks = [f for f in frames if not f.is_request]
                if acks:
                    for f in acks:
                        self.sniffer.record("RX", f.encode(), self.ocd_level(), f.summary())
                    return acks
            elif last_rx is None and now > t_end_first:
                break
            elif last_rx is not None and now - last_rx > 6 * CHAR_TIME_S:
                break                               # Lücke im Telegramm -> abbrechen
        for e in parser.errors:
            self.sniffer.record("ERR", bytes(rx), self.ocd_level(), e)
        if rx:
            self.sniffer.record("ERR", bytes(rx), self.ocd_level(), "Unvollständiges Telegramm")
        return []

    def close(self) -> None:
        try:
            self.rts.off()
            self.ser.close()
        finally:
            self.rts.close()
            self.ocd.close()


# ----------------------------------------------------------------------------
# Simulation: virtuelle Feldgeräte an einem virtuellen Bus
# ----------------------------------------------------------------------------
class SimulatedFieldDevice:
    """Verhaltensmodell eines HART-Feldgeräts (Transmitter oder Stellungsregler)."""

    def __init__(self, profile_key: str, *, poll_address: int = 0, device_id: Optional[int] = None,
                 tag: str = "PT-1001", descriptor: str = "SIMULATION", unit: Optional[int] = None,
                 lrv: float = 0.0, urv: float = 100.0, universal_rev: int = 7,
                 analog_error_ma: float = 0.0, noise: float = 0.0005):
        from device_catalog import get_catalog
        prof = get_catalog().profile(profile_key)
        self.profile = prof
        self.manufacturer_id = prof.manufacturer_id
        self.device_type = prof.device_types[0] if prof.device_types else (prof.manufacturer_id << 8)
        self.device_id = device_id if device_id is not None else random.randint(0x100000, 0xFFFFFF)
        self.poll_address = poll_address
        self.universal_rev = universal_rev
        self.tag, self.descriptor, self.date = tag, descriptor, date(2024, 3, 1)
        self.message = "HART SIMULATOR"
        self.unit = unit if unit is not None else prof.default_unit
        self.lrv, self.urv = lrv, urv
        self.damping = 0.5
        self.is_positioner = prof.is_positioner
        self.analog_error_ma = analog_error_ma   # Fehler DA-Wandler -> True-mA-Warnung testbar
        self.noise = noise
        self.process_percent = 0.0               # Prozess (Transmitter) / Stellung (Regler)
        self.fixed_current: Optional[float] = None
        self.cold_start = True
        self.config_changed = False
        self.ccc = 1
        self.write_protected = False
        self._lock = threading.Lock()

    # --- Physik -------------------------------------------------------------
    def set_process_percent(self, pct: float) -> None:
        self.process_percent = pct

    def pv(self) -> float:
        pct = self.process_percent * (1 + random.uniform(-self.noise, self.noise))
        return self.lrv + (self.urv - self.lrv) * pct / 100.0

    def percent_of_range(self) -> float:
        span = (self.urv - self.lrv) or 1.0
        return (self.pv() - self.lrv) / span * 100.0

    def digital_current(self) -> float:
        """Der Strom, den das Gerät DIGITAL meldet (Cmd 2/3)."""
        if self.fixed_current is not None:
            return self.fixed_current
        return max(3.8, min(20.5, 4.0 + 16.0 * self.percent_of_range() / 100.0))

    def loop_current_ma(self) -> float:
        """Der Strom, der ANALOG tatsächlich fließt (liest der INA226-Simulator)."""
        return self.digital_current() + self.analog_error_ma + random.gauss(0, 0.0015)

    # --- Kommandos ------------------------------------------------------------
    def status_byte(self) -> int:
        s = 0
        if self.cold_start:
            s |= 0x20
        if self.config_changed:
            s |= 0x40
        if self.fixed_current is not None:
            s |= 0x08
        pct = self.percent_of_range()
        if pct < -0.5 or pct > 100.5:
            s |= 0x01
        return s

    def handle(self, cmd: int, data: bytes) -> tuple[int, bytes]:
        with self._lock:
            rc, payload = self._handle(cmd, data)
            return rc, payload

    def _changed(self) -> None:
        self.config_changed = True
        self.ccc = (self.ccc + 1) & 0xFFFF

    def _handle(self, cmd: int, d: bytes) -> tuple[int, bytes]:
        if cmd == 0:
            mfr_hi = (self.manufacturer_id >> 8) & 0xFF
            base = bytes([254, (self.device_type >> 8) & 0xFF, self.device_type & 0xFF, 5,
                          self.universal_rev, 3, 12, (2 << 3) | 0, 0]) + \
                self.device_id.to_bytes(3, "big")
            if self.universal_rev >= 7:
                base += bytes([5, 4]) + self.ccc.to_bytes(2, "big") + bytes([0, mfr_hi,
                              self.manufacturer_id & 0xFF, mfr_hi, self.manufacturer_id & 0xFF, 1])
            return 0, base
        if cmd == 1:
            return 0, bytes([self.unit]) + to_f32(self.pv())
        if cmd == 2:
            return 0, to_f32(self.digital_current()) + to_f32(self.percent_of_range())
        if cmd == 3:
            return 0, (to_f32(self.digital_current()) + bytes([self.unit]) + to_f32(self.pv()) +
                       bytes([32]) + to_f32(23.4 + random.uniform(-0.1, 0.1)) +
                       bytes([39]) + to_f32(self.digital_current()) +
                       bytes([57]) + to_f32(self.percent_of_range()))
        if cmd == 12:
            return 0, pack_ascii(self.message, 32)
        if cmd == 13:
            return 0, pack_ascii(self.tag, 8) + pack_ascii(self.descriptor, 16) + encode_date(self.date)
        if cmd == 15:
            return 0, (bytes([0, 0, self.unit]) + to_f32(self.urv) + to_f32(self.lrv) +
                       to_f32(self.damping) + bytes([1 if self.write_protected else 0, 250, 0]))
        if cmd == 48:
            return 0, bytes(9)
        # ---------------- Schreibkommandos ----------------
        if self.write_protected and cmd in (6, 18, 35, 44):
            return 7, b""
        if cmd == 6:
            if len(d) < 1:
                return 5, b""
            self.poll_address = d[0] & 0x3F
            self._changed()
            return 0, bytes([self.poll_address, 1])
        if cmd == 18:
            if len(d) < 21:
                return 5, b""
            self.tag = unpack_ascii(d[0:6]).rstrip()
            self.descriptor = unpack_ascii(d[6:18]).rstrip()
            self.date = decode_date(d[18:21]) or self.date
            self._changed()
            return 0, d[:21]
        if cmd == 35:
            if len(d) < 9:
                return 5, b""
            unit, urv, lrv = d[0], f32(d, 1), f32(d, 5)
            if urv == lrv:
                return 14, b""
            self.unit, self.urv, self.lrv = unit, urv, lrv
            self._changed()
            return 0, d[:9]
        if cmd == 38:
            self.config_changed = False
            return 0, b""
        if cmd == 40:
            if len(d) < 4:
                return 5, b""
            ma = f32(d)
            if ma == 0.0:
                self.fixed_current = None
            else:
                if not 3.5 <= ma <= 24.0:
                    return 3 if ma > 24 else 4, b""
                self.fixed_current = ma
                if self.is_positioner:          # Regler fährt auf Sollwert
                    self.process_percent = (ma - 4.0) / 16.0 * 100.0
            return 0, to_f32(ma)
        if cmd == 44:
            if len(d) < 1:
                return 5, b""
            self.unit = d[0]
            self._changed()
            return 0, d[:1]
        return 64, b""


class SimulatedHartBus:
    """Virtueller Multidrop-Bus. `connect()` simuliert das Anklemmen eines Geräts."""

    def __init__(self):
        self.devices: list[SimulatedFieldDevice] = []
        self.lock = threading.Lock()
        self.carrier = False

    def connect(self, device: SimulatedFieldDevice, exclusive: bool = True) -> SimulatedFieldDevice:
        with self.lock:
            if exclusive:
                self.devices.clear()
            self.devices.append(device)
        return device

    def disconnect_all(self) -> None:
        with self.lock:
            self.devices.clear()

    def active_device(self) -> Optional[SimulatedFieldDevice]:
        with self.lock:
            return self.devices[0] if self.devices else None

    def loop_current_ma(self) -> float:
        """Für den INA226-Simulator: Summe der Schleifenströme (Multidrop: je 4 mA)."""
        dev = self.active_device()
        return dev.loop_current_ma() if dev else 0.0

    def find(self, frame: HartFrame) -> Optional[SimulatedFieldDevice]:
        with self.lock:
            for d in self.devices:
                if frame.is_long:
                    a = frame.address
                    if (a[0] & 0x3F) == ((d.device_type >> 8) & 0x3F) and a[1] == (d.device_type & 0xFF) \
                            and int.from_bytes(a[2:5], "big") == d.device_id:
                        return d
                    if a[0] & 0x3F == 0 and a[1:] == b"\x00\x00\x00\x00":  # Broadcast
                        return d
                elif (frame.address[0] & 0x3F) == d.poll_address:
                    return d
        return None


def _default_sim_bus() -> SimulatedHartBus:
    bus = SimulatedHartBus()
    bus.connect(SimulatedFieldDevice("rosemount_3051", tag="PT-4711", descriptor="DRUCK KOLONNE K1",
                                     unit=8, lrv=0.0, urv=2500.0, device_id=0x0A1B2C,
                                     analog_error_ma=0.004))
    return bus


SIM_BUS = _default_sim_bus()

# Vordefinierte Szenarien für Entwicklung & Demo (UI: "Simulator"-Menü)
SIM_SCENARIOS: dict[str, Callable[[], SimulatedFieldDevice]] = {
    "rosemount_3051": lambda: SimulatedFieldDevice(
        "rosemount_3051", tag="PT-4711", descriptor="DRUCK KOLONNE K1", unit=8,
        lrv=0, urv=2500, device_id=0x0A1B2C, analog_error_ma=0.004),
    "rosemount_3051_replaced": lambda: SimulatedFieldDevice(
        "rosemount_3051", tag="PT-4711", descriptor="DRUCK KOLONNE K1", unit=8,
        lrv=0, urv=2500, device_id=0x0C0FFE),
    "micromotion_5700": lambda: SimulatedFieldDevice(
        "micromotion_5700", tag="FT-2001", descriptor="MASSESTROM ZULAUF", unit=75,
        lrv=0, urv=12000, analog_error_ma=0.09),   # absichtlich Analogfehler > Toleranz
    "fisher_dvc6200": lambda: SimulatedFieldDevice(
        "fisher_dvc6200", tag="FV-3001", descriptor="REGELVENTIL DAMPF", unit=57, lrv=0, urv=100),
    "siemens_sipart_ps2": lambda: SimulatedFieldDevice(
        "siemens_sipart_ps2", tag="LV-1203", descriptor="STANDREGELUNG T3", unit=57,
        lrv=0, urv=100, universal_rev=5),
    "siemens_sipart_ps100": lambda: SimulatedFieldDevice(
        "siemens_sipart_ps100", tag="TV-0815", descriptor="KUEHLWASSER", unit=57, lrv=0, urv=100),
    "rosemount_644": lambda: SimulatedFieldDevice(
        "rosemount_644", tag="TT-0042", descriptor="TEMP. REAKTOR R2", unit=32, lrv=-50, urv=250),
}


class SimulatedTransport(Transport):
    simulated = True

    def __init__(self, bus: SimulatedHartBus, sniffer: BusSniffer, latency_s: float = 0.03):
        self.bus, self.sniffer, self.latency_s = bus, sniffer, latency_s

    def ocd_level(self) -> bool:
        return self.bus.carrier

    def transact(self, tx: bytes, timeout: float) -> list[HartFrame]:
        req = FrameParser().feed(tx)
        if not req:
            return []
        frame = req[0]
        dev = self.bus.find(frame)
        if self.latency_s:
            time.sleep(self.latency_s)
        if dev is None:
            return []
        rc, payload = dev.handle(frame.command, frame.payload)
        status = dev.status_byte()
        if frame.command != 0:
            dev.cold_start = False
        address = bytes([frame.address[0] & 0xBF]) + frame.address[1:]
        resp = HartFrame(FRAME_ACK | (frame.delimiter & DELIM_LONG_ADDR), address, frame.command,
                         bytes([rc, status]) + (payload if rc in (0, *WARNING_CODES) else b""))
        self.bus.carrier = True
        self.sniffer.record("OCD", ocd=True, summary="Träger EIN")
        raw = resp.encode()
        self.sniffer.record("RX", raw, True, resp.summary())
        self.bus.carrier = False
        self.sniffer.record("OCD", ocd=False, summary="Träger AUS")
        return [resp]


# =============================================================================
# 8. HartModem – öffentliche API
# =============================================================================
class HartModem:
    def __init__(self, port: Optional[str] = None, *, simulate: Optional[bool] = None,
                 sniffer: Optional[BusSniffer] = None, safe_mode: bool = config.SAFE_MODE_DEFAULT,
                 primary_master: bool = config.HART_PRIMARY_MASTER,
                 sim_bus: Optional[SimulatedHartBus] = None):
        self.sniffer = sniffer or BusSniffer()
        self.primary_master = primary_master
        self._lock = threading.RLock()
        self._safe_mode = bool(safe_mode)
        self._safe_listeners: list[Callable[[bool, str], None]] = []
        self._hw_safe = digital_input(config.Pins.SAFE_MODE_HW, pull_up=True, component="hart") \
            if config.Pins.SAFE_MODE_HW is not None else None
        self.active_seconds = 0.0     # Summe Buszeit -> Telemetrie "active_hart_sec"

        if simulate is None:
            simulate = simulation_requested("hart")
        self.transport: Transport
        if not simulate:
            try:
                self.transport = SerialTransport(port or config.HART_SERIAL_PORT, self.sniffer)
            except Exception as exc:
                log.error("HART-Modem nicht verfügbar (%s) – Simulation aktiv", exc)
                simulate = True
        if simulate:
            self.sim_bus = sim_bus or SIM_BUS
            self.transport = SimulatedTransport(self.sim_bus, self.sniffer)
        else:
            self.sim_bus = None
        self.simulated = simulate
        self.sniffer.record("INFO", summary=f"HART-Modem gestartet ({'SIMULATION' if simulate else 'AD5700'}), "
                                            f"Safe-Mode {'EIN' if self._safe_mode else 'AUS'}")

    # ---------------- Safe-Mode ----------------
    @property
    def safe_mode(self) -> bool:
        hw = bool(self._hw_safe and self._hw_safe.is_active)
        return self._safe_mode or hw

    def set_safe_mode(self, enabled: bool, source: str = "ui") -> None:
        with self._lock:
            changed = enabled != self._safe_mode
            self._safe_mode = bool(enabled)
        if changed:
            self.sniffer.record("INFO", summary=f"24/7-Safe-Mode {'AKTIVIERT' if enabled else 'DEAKTIVIERT'} ({source})")
            for cb in list(self._safe_listeners):
                try:
                    cb(enabled, source)
                except Exception:
                    log.exception("Safe-Mode-Listener")

    def add_safe_mode_listener(self, cb: Callable[[bool, str], None]) -> None:
        self._safe_listeners.append(cb)

    def ocd_level(self) -> bool:
        return self.transport.ocd_level()

    # ---------------- Kern ----------------
    def _address_for(self, identity: Optional[DeviceIdentity], poll_address: Optional[int]) -> bytes:
        if identity is not None:
            return identity.long_address(self.primary_master)
        pa = (poll_address or 0) & 0x3F
        return bytes([pa | (ADDR_MASTER_PRIMARY if self.primary_master else 0)])

    def send(self, command: int, data: bytes = b"", *, identity: Optional[DeviceIdentity] = None,
             poll_address: Optional[int] = None, retries: Optional[int] = None,
             timeout: Optional[float] = None, allow_error: bool = False) -> HartResponse:
        if self.safe_mode and command not in READ_ONLY_COMMANDS:
            self.sniffer.record("BLOCK", summary=str(SafeModeError(command)))
            raise SafeModeError(command)

        address = self._address_for(identity, poll_address)
        frame = build_request(address, command, data, identity.preambles if identity else 5)
        tx = frame.encode()
        retries = config.HART_RETRIES if retries is None else retries
        timeout = timeout or config.HART_RESPONSE_TIMEOUT_S
        last_err: Exception = HartTimeoutError(f"Cmd {command}: keine Antwort")

        with self._lock:
            for attempt in range(retries + 1):
                t0 = time.monotonic()
                self.sniffer.record("TX", tx, self.ocd_level(),
                                    frame.summary() + (f" (Wdh. {attempt})" if attempt else ""))
                frames = self.transport.transact(tx, timeout)
                self.active_seconds += time.monotonic() - t0
                resp = next((f for f in frames if f.frame_type == FRAME_ACK), None)
                if resp is None:
                    last_err = HartTimeoutError(f"Cmd {command}: keine Antwort "
                                                f"({'Poll ' + str(poll_address) if identity is None else identity.unique_id})")
                    continue
                if resp.command != command or (resp.address[0] & 0x3F) != (address[0] & 0x3F) \
                        or resp.address[1:] != address[1:]:
                    last_err = HartFrameError(f"Antwort passt nicht zur Anfrage: {resp.summary()}")
                    continue
                if len(resp.payload) < 2:
                    last_err = HartFrameError("Antwort ohne Statusbytes")
                    continue
                rc, ds = resp.status
                if rc & 0x80:
                    last_err = HartCommunicationError(rc & 0x7F)
                    continue
                if rc in BUSY_CODES:
                    last_err = HartCommandError(command, rc)
                    time.sleep(0.25 * (attempt + 1))
                    continue
                result = HartResponse(command, rc, ds, resp.data, tx, resp.encode())
                if rc and rc not in WARNING_CODES and not allow_error:
                    raise HartCommandError(command, rc)
                return result
        raise last_err

    # ---------------- Identifikation ----------------
    def poll(self, poll_address: int = 0, retries: int = 1) -> Optional[DeviceIdentity]:
        try:
            r = self.send(0, poll_address=poll_address, retries=retries)
        except (HartTimeoutError, HartFrameError):
            return None
        return DeviceIdentity.from_cmd0(r.data, poll_address)

    def scan(self, addresses: Iterable[int] = range(16), stop_on_first: bool = False,
             progress: Optional[Callable[[int], None]] = None) -> list[DeviceIdentity]:
        found = []
        for pa in addresses:
            if progress:
                progress(pa)
            ident = self.poll(pa)
            if ident:
                found.append(ident)
                if stop_on_first:
                    break
        return found

    # ---------------- Lesekommandos ----------------
    def read_pv(self, ident: DeviceIdentity) -> tuple[float, int]:
        d = self.send(1, identity=ident).data
        return f32(d, 1), d[0]

    def read_current_and_percent(self, ident: DeviceIdentity) -> tuple[float, float]:
        d = self.send(2, identity=ident).data
        return f32(d, 0), f32(d, 4)

    def read_dynamic_variables(self, ident: DeviceIdentity) -> dict:
        r = self.send(3, identity=ident)
        d = r.data
        out = {"loop_current_ma": f32(d, 0), "device_status": r.device_status,
               "status_texts": r.status_texts}
        for i, name in enumerate(("pv", "sv", "tv", "qv")):
            off = 4 + i * 5
            if len(d) >= off + 5:
                val = f32(d, off + 1)
                out[name] = {"value": None if math.isnan(val) else val, "unit_code": d[off],
                             "unit": unit_name(d[off])}
        return out

    def read_message(self, ident: DeviceIdentity) -> str:
        return unpack_ascii(self.send(12, identity=ident).data[:24]).rstrip()

    def read_tag_info(self, ident: DeviceIdentity) -> dict:
        d = self.send(13, identity=ident).data
        dt = decode_date(d[18:21])
        return {"tag": unpack_ascii(d[0:6]).rstrip(), "descriptor": unpack_ascii(d[6:18]).rstrip(),
                "date": dt.isoformat() if dt else None}

    def read_range_info(self, ident: DeviceIdentity) -> dict:
        d = self.send(15, identity=ident).data
        return {"alarm_select": d[0], "transfer_function": d[1], "unit_code": d[2],
                "unit": unit_name(d[2]), "upper_range": f32(d, 3), "lower_range": f32(d, 7),
                "damping_s": f32(d, 11), "write_protect": d[15] == 1 if len(d) > 15 else False}

    def read_additional_status(self, ident: DeviceIdentity) -> bytes:
        return self.send(48, identity=ident, allow_error=True).data

    # ---------------- Schreibkommandos (Safe-Mode-geschützt) ----------------
    def write_tag_info(self, ident: DeviceIdentity, tag: str, descriptor: str,
                       on_date: Optional[date] = None) -> dict:
        data = pack_ascii(tag, 8) + pack_ascii(descriptor, 16) + encode_date(on_date)
        self.send(18, data, identity=ident)
        return self.read_tag_info(ident)

    def write_range(self, ident: DeviceIdentity, unit_code: int, lower: float, upper: float) -> dict:
        """Command 35 – Reihenfolge im Telegramm: Einheit, OBERER, UNTERER Wert."""
        self.send(35, bytes([unit_code]) + to_f32(upper) + to_f32(lower), identity=ident)
        return self.read_range_info(ident)

    def write_pv_unit(self, ident: DeviceIdentity, unit_code: int) -> None:
        self.send(44, bytes([unit_code]), identity=ident)

    def set_fixed_current(self, ident: DeviceIdentity, milliamps: float) -> float:
        """Command 40 – fester Schleifenstrom / Sollwertvorgabe Stellungsregler."""
        if not 3.5 <= milliamps <= 24.0:
            raise ValueError("Sollstrom muss zwischen 3,5 und 24 mA liegen")
        return f32(self.send(40, to_f32(milliamps), identity=ident).data)

    def exit_fixed_current(self, ident: DeviceIdentity) -> None:
        """Command 40 mit 0 mA beendet den Festwertmodus. Auch nach Abbrüchen aufrufen!"""
        self.send(40, to_f32(0.0), identity=ident)

    def reset_config_changed(self, ident: DeviceIdentity) -> None:
        self.send(38, identity=ident)

    # ---------------- Komplett-Identifikation ----------------
    def identify(self, poll_address: int = 0) -> Optional[dict]:
        """Cmd 0 + 13 + 15 + 3 -> vollständiger Gerätesteckbrief inkl. Klartext-Katalog."""
        from device_catalog import describe
        ident = self.poll(poll_address)
        if ident is None:
            return None
        info: dict = {"identity": ident, **ident.to_dict()}
        info.update(self.read_tag_info(ident))
        try:
            info["range"] = self.read_range_info(ident)
        except HartCommandError as exc:
            info["range"] = None
            info["range_error"] = str(exc)
        dyn = self.read_dynamic_variables(ident)
        info["dynamic"] = dyn
        pv_unit = dyn.get("pv", {}).get("unit_code")
        match = describe(ident.manufacturer_id, ident.device_type, pv_unit)
        info["catalog"] = match.to_dict()
        info["display_name"] = match.display_name
        info["is_positioner"] = match.profile.is_positioner
        return info

    def close(self) -> None:
        self.transport.close()


# =============================================================================
# Demo / Selbsttest:  python hart_modem.py [szenario]
# =============================================================================
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    modem = HartModem(simulate=True)
    if len(sys.argv) > 1:
        SIM_BUS.connect(SIM_SCENARIOS[sys.argv[1]]())
    info = modem.identify(0)
    if not info:
        print("Kein Gerät gefunden")
        sys.exit(1)
    print(f"Gerät:  {info['display_name']}  ({info['catalog']['profile']['device_class']})")
    print(f"TAG:    {info['tag']}   Beschreibung: {info['descriptor']}")
    print(f"UID:    {info['unique_id']}   HART-Rev {info['universal_rev']}")
    r = info["range"]
    print(f"Bereich: {r['lower_range']:g} .. {r['upper_range']:g} {r['unit']}")
    pv = info["dynamic"]["pv"]
    print(f"PV:     {pv['value']:.3f} {pv['unit']}   I = {info['dynamic']['loop_current_ma']:.3f} mA")
    try:
        modem.write_pv_unit(info["identity"], 7)
    except SafeModeError as e:
        print("OK, blockiert:", e)
    print("\nSniffer:")
    for ev in modem.sniffer.snapshot(12):
        print(f"  {ev['dir']:5s} {ev['summary']:55s} {ev['hex'][:60]}")
