"""
rtc_manager.py – Vertrauenswürdige Zeitstempel ohne Internet (DS3231 @ 0x68).

Backends (automatisch gewählt):
  kernel – Empfohlen. dtoverlay=i2c-rtc,ds3231 -> /dev/rtc0. Lesen über sysfs,
           Schreiben über `hwclock`. Temperatur über hwmon ("ds3231").
           (Der Kernel belegt dann 0x68 – direkter I2C-Zugriff ist NICHT möglich.)
  i2c    – Fallback ohne Overlay: direkter Registerzugriff (BCD), inkl. OSF-Flag.
  sim    – Entwicklungs-PC: Systemuhr + simulierte Drift.

Zeitquellen-Hierarchie für Prüfprotokolle:
  1. NTP synchronisiert (nur im Dock mit Netz)      -> "NTP"      (RTC wird nachgeführt)
  2. RTC gültig (Oszillator lief durch, OSF=0)       -> "RTC"
  3. sonst                                            -> "UNGEPRÜFT" (Warnung in UI + PDF)

Alle Zeitstempel werden in UTC gespeichert und lokal (config.TIMEZONE) angezeigt.

Für Systemzeit/RTC-Schreiben braucht der Dienstbenutzer sudo-Rechte ohne Passwort:
  deploy/sudoers.d/hart-communicator  ->  /usr/bin/date, /usr/sbin/hwclock
"""
from __future__ import annotations

import ctypes
import logging
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import config
from hw_compat import get_i2c_bus, simulation_requested

log = logging.getLogger(__name__)
LOCAL_TZ = ZoneInfo(config.TIMEZONE)

REG_SECONDS, REG_CONTROL, REG_STATUS, REG_TEMP_MSB = 0x00, 0x0E, 0x0F, 0x11
STATUS_OSF = 0x80


def _bcd2bin(v: int) -> int:
    return (v & 0x0F) + (v >> 4) * 10


def _bin2bcd(v: int) -> int:
    return ((v // 10) << 4) | (v % 10)


def encode_ds3231(dt: datetime) -> list[int]:
    """UTC-datetime -> Register 0x00..0x06 (24-h-Modus, Jahrhundertbit für 2100+)."""
    dt = dt.astimezone(timezone.utc)
    century = 0x80 if dt.year >= 2100 else 0
    return [_bin2bcd(dt.second), _bin2bcd(dt.minute), _bin2bcd(dt.hour),
            dt.isoweekday(), _bin2bcd(dt.day), _bin2bcd(dt.month) | century, _bin2bcd(dt.year % 100)]


def decode_ds3231(r: list[int]) -> datetime:
    hour_reg = r[2]
    if hour_reg & 0x40:                                   # 12-h-Modus
        hour = _bcd2bin(hour_reg & 0x1F) % 12 + (12 if hour_reg & 0x20 else 0)
    else:
        hour = _bcd2bin(hour_reg & 0x3F)
    year = 2000 + _bcd2bin(r[6]) + (100 if r[5] & 0x80 else 0)
    return datetime(year, _bcd2bin(r[5] & 0x1F), _bcd2bin(r[4] & 0x3F), hour,
                    _bcd2bin(r[1] & 0x7F), _bcd2bin(r[0] & 0x7F), tzinfo=timezone.utc)


def _run(cmd: list[str], timeout: float = 5.0) -> Optional[str]:
    if shutil.which(cmd[0]) is None and not Path(cmd[0]).exists():
        return None
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("%s fehlgeschlagen: %s", " ".join(cmd), exc)
        return None
    if res.returncode != 0:
        log.warning("%s: %s", " ".join(cmd), res.stderr.strip())
        return None
    return res.stdout.strip()


TIME_ERROR = 5          # adjtimex(): Uhr nicht synchronisiert (STA_UNSYNC)
_ntp_cache: tuple[float, bool] = (0.0, False)


def kernel_clock_synchronized() -> bool:
    """NTP-Status direkt vom Kernel (adjtimex) – identisch zu timedatectl, aber ohne
    systemd/DBus und in Mikrosekunden statt eines Prozessstarts. 30 s gecacht."""
    global _ntp_cache
    if time.monotonic() - _ntp_cache[0] < 30:
        return _ntp_cache[1]
    synced = False
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        buf = ctypes.create_string_buffer(512)   # struct timex, modes = 0 -> nur lesen
        state = libc.adjtimex(buf)
        synced = state >= 0 and state != TIME_ERROR
    except (OSError, AttributeError):
        synced = False
    _ntp_cache = (time.monotonic(), synced)
    return synced


class RtcManager:
    def __init__(self, *, simulate: Optional[bool] = None, rtc_device: str = config.RTC_DEVICE):
        self.rtc_name = Path(rtc_device).name
        self._lock = threading.Lock()
        self._bus = None
        self._sim_offset_s = 0.0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_sync: Optional[dict] = None

        if simulate is None:
            simulate = simulation_requested("rtc")
        if simulate:
            self.backend = "sim"
        elif Path(f"/sys/class/rtc/{self.rtc_name}/since_epoch").exists():
            self.backend = "kernel"
        else:
            self._bus = get_i2c_bus(config.I2C_BUS, component="rtc")
            if self._bus and self._bus.probe(config.I2CAddr.DS3231):
                self.backend = "i2c"
            else:
                log.error("DS3231 weder als /dev/rtc0 noch an I2C 0x68 gefunden – Simulation")
                self.backend = "sim"
        log.info("RTC-Backend: %s", self.backend)

    # ------------------------------------------------------------------ RTC lesen/schreiben
    def read_rtc(self) -> Optional[datetime]:
        with self._lock:
            if self.backend == "sim":
                return datetime.fromtimestamp(time.time() + self._sim_offset_s, timezone.utc).replace(microsecond=0)
            if self.backend == "kernel":
                try:
                    s = Path(f"/sys/class/rtc/{self.rtc_name}/since_epoch").read_text().strip()
                    return datetime.fromtimestamp(int(s), timezone.utc)
                except (OSError, ValueError) as exc:
                    log.error("RTC (sysfs) nicht lesbar: %s", exc)
                    return None
            try:
                return decode_ds3231(self._bus.read_block(config.I2CAddr.DS3231, REG_SECONDS, 7))
            except (OSError, ValueError) as exc:
                log.error("DS3231 nicht lesbar: %s", exc)
                return None

    def write_rtc(self, dt_utc: datetime) -> bool:
        with self._lock:
            if self.backend == "sim":
                self._sim_offset_s = dt_utc.timestamp() - time.time()
                return True
            if self.backend == "kernel":
                # hwclock schreibt die SYSTEMZEIT -> dt_utc muss vorher Systemzeit sein
                if abs(dt_utc.timestamp() - time.time()) > 2:
                    log.error("write_rtc(kernel): nur Systemzeit kann übernommen werden")
                    return False
                return _run(["sudo", "-n", "/usr/sbin/hwclock", "--systohc", "--utc"]) is not None
            try:
                self._bus.write_block(config.I2CAddr.DS3231, REG_SECONDS, encode_ds3231(dt_utc))
                st = self._bus.read_byte_data(config.I2CAddr.DS3231, REG_STATUS)
                self._bus.write_byte_data(config.I2CAddr.DS3231, REG_STATUS, st & ~STATUS_OSF)
                return True
            except OSError as exc:
                log.error("DS3231 nicht beschreibbar: %s", exc)
                return False

    def oscillator_stopped(self) -> Optional[bool]:
        """OSF=1: Oszillator stand (Knopfzelle leer) -> RTC-Zeit ungültig. Kernel: None."""
        if self.backend != "i2c":
            return False if self.backend == "sim" else None
        try:
            with self._lock:
                return bool(self._bus.read_byte_data(config.I2CAddr.DS3231, REG_STATUS) & STATUS_OSF)
        except OSError:
            return None

    def temperature_c(self) -> Optional[float]:
        """DS3231-Chiptemperatur (±3 °C) – nützlich als Gehäusetemperatur."""
        if self.backend == "sim":
            return 27.25
        if self.backend == "i2c":
            try:
                with self._lock:
                    msb, lsb = self._bus.read_block(config.I2CAddr.DS3231, REG_TEMP_MSB, 2)
                return (msb - 256 if msb & 0x80 else msb) + (lsb >> 6) * 0.25
            except OSError:
                return None
        for hw in Path("/sys/class/hwmon").glob("hwmon*"):
            try:
                if (hw / "name").read_text().strip() == "ds3231":
                    return int((hw / "temp1_input").read_text()) / 1000.0
            except (OSError, ValueError):
                continue
        return None

    # ------------------------------------------------------------------ Systemzeit
    @staticmethod
    def ntp_synchronized() -> bool:
        return kernel_clock_synchronized()

    @staticmethod
    def system_time_plausible() -> bool:
        return datetime.now(timezone.utc).year >= config.MIN_PLAUSIBLE_YEAR

    def rtc_valid(self) -> bool:
        rtc = self.read_rtc()
        return rtc is not None and rtc.year >= config.MIN_PLAUSIBLE_YEAR and not self.oscillator_stopped()

    def _set_system_time(self, dt_utc: datetime) -> bool:
        if self.backend == "sim":
            log.warning("[SIM] Systemzeit würde auf %s gesetzt", dt_utc.isoformat())
            return True
        return _run(["sudo", "-n", "/usr/bin/date", "-u", "-s", f"@{int(dt_utc.timestamp())}"]) is not None

    def boot_sync(self) -> dict:
        """Beim Start aufrufen. Ohne NTP wird die Systemzeit aus der RTC übernommen."""
        result = {"action": "none", "source": self.time_source()}
        if self.ntp_synchronized():
            if self.write_rtc(datetime.now(timezone.utc)):
                result["action"] = "rtc_from_ntp"
        elif self.rtc_valid():
            rtc = self.read_rtc()
            drift = rtc.timestamp() - time.time()
            if abs(drift) > 2 or not self.system_time_plausible():
                if self._set_system_time(rtc):
                    result.update(action="system_from_rtc", drift_s=round(drift, 1))
        else:
            result["action"] = "no_valid_time"
            log.error("Weder NTP noch gültige RTC – Zeitstempel UNGEPRÜFT. Uhrzeit manuell stellen!")
        result["source"] = self.time_source()
        self.last_sync = {**result, "at": datetime.now(timezone.utc).isoformat()}
        log.info("Zeit-Sync beim Start: %s", result)
        return result

    def set_time_manual(self, local_dt: datetime, technician: str = "") -> dict:
        """Manuelles Stellen über die UI (Uhrzeit des Technikers, lokale Zeitzone)."""
        if local_dt.tzinfo is None:
            local_dt = local_dt.replace(tzinfo=LOCAL_TZ)
        dt_utc = local_dt.astimezone(timezone.utc)
        old = datetime.now(timezone.utc)
        ok = self._set_system_time(dt_utc)
        if ok:
            ok = self.write_rtc(dt_utc if self.backend != "kernel" else datetime.now(timezone.utc))
        res = {"ok": ok, "old_utc": old.isoformat(), "new_utc": dt_utc.isoformat(),
               "technician": technician}
        log.warning("Uhrzeit manuell gestellt: %s", res)
        return res

    # ------------------------------------------------------------------ Zeitstempel
    def time_source(self) -> str:
        if self.ntp_synchronized():
            return "NTP"
        if self.rtc_valid() and self.system_time_plausible():
            return "RTC"
        return "UNGEPRÜFT"

    def now(self) -> datetime:
        return datetime.now(LOCAL_TZ)

    def timestamp(self) -> dict:
        """Zeitstempel für Datenbank / Prüfprotokoll inkl. Herkunftsnachweis."""
        utc = datetime.now(timezone.utc)
        src = self.time_source()
        return {"unix": utc.timestamp(), "utc": utc.isoformat(timespec="seconds"),
                "local": utc.astimezone(LOCAL_TZ).isoformat(timespec="seconds"),
                "source": src, "trusted": src in ("NTP", "RTC")}

    def status(self) -> dict:
        rtc = self.read_rtc()
        return {"backend": self.backend, "source": self.time_source(),
                "rtc_utc": rtc.isoformat() if rtc else None,
                "drift_s": round(rtc.timestamp() - time.time(), 1) if rtc else None,
                "oscillator_stopped": self.oscillator_stopped(),
                "temperature_c": self.temperature_c(), "last_sync": self.last_sync}

    # ------------------------------------------------------------------ Hintergrund
    def start(self, interval_s: float = 3600) -> "RtcManager":
        """Stündlich: Wenn NTP verfügbar (Dock + WLAN), RTC bei Drift > 1 s nachführen."""
        def loop():
            while not self._stop.wait(interval_s):
                try:
                    rtc = self.read_rtc()
                    if self.ntp_synchronized() and rtc and abs(rtc.timestamp() - time.time()) > 1:
                        if self.write_rtc(datetime.now(timezone.utc)):
                            log.info("RTC per NTP nachgeführt (Drift war %.1f s)", rtc.timestamp() - time.time())
                except Exception:
                    log.exception("RTC-Nachführung")
        self._thread = threading.Thread(target=loop, name="rtc", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    rtc = RtcManager()
    print(rtc.boot_sync())
    print(rtc.status())
    print(rtc.timestamp())
