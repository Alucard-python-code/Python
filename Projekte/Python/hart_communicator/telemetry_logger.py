"""
telemetry_logger.py – Betriebsstunden, Telemetrie-Zeitreihe und Audit-Log (telemetry_logs.db).

Optimiert für das Grafana-SQLite-Plugin (frser-sqlite-datasource):
  * WAL-Modus -> Grafana kann lesen, während das Gerät schreibt
  * Zeitspalte `timestamp_unix` (INTEGER, Sekunden) mit Index
  * flache, typisierte Spalten (keine JSON-Felder in der Zeitreihe)

Tabellen:
  telemetry_timeseries – alle 15 s: Laufzeiten, Modus, Akku/Zellen, CPU-Temperatur
  system_events        – Boot, Shutdown, Dock, Auftrag, Kalibrierung (Dauer/Ergebnis), Gerätetausch …
  runtime_counters     – eine Zeile mit den aufsummierten Zählern (überlebt Neustarts)

Beispielabfragen für Grafana: deploy/GRAFANA.md
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import config

log = logging.getLogger(__name__)

RETENTION_DAYS = 400        # gut ein Jahr Rohdaten (~2,3 Mio. Zeilen, ca. 250 MB)

SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry_timeseries (
    timestamp_unix     INTEGER NOT NULL,
    total_runtime_sec  INTEGER NOT NULL,
    field_runtime_sec  INTEGER NOT NULL,
    dock_runtime_sec   INTEGER NOT NULL,
    active_hart_sec    INTEGER NOT NULL,
    mode               TEXT NOT NULL,
    pack_voltage_v     REAL,
    pack_current_a     REAL,
    soc_percent        REAL,
    cell_drift_mv      REAL,
    cell_1_v REAL, cell_2_v REAL, cell_3_v REAL, cell_4_v REAL,
    cell_5_v REAL, cell_6_v REAL, cell_7_v REAL, cell_8_v REAL,
    cpu_temp_c         REAL
);
CREATE INDEX IF NOT EXISTS ix_ts_time ON telemetry_timeseries(timestamp_unix);

CREATE TABLE IF NOT EXISTS system_events (
    id              INTEGER PRIMARY KEY,
    timestamp_unix  INTEGER NOT NULL,
    event_type      TEXT NOT NULL,
    severity        TEXT NOT NULL DEFAULT 'INFO',
    message         TEXT NOT NULL,
    order_no        TEXT,
    device_tag      TEXT,
    duration_sec    REAL,
    result          TEXT,
    time_source     TEXT,
    details         TEXT
);
CREATE INDEX IF NOT EXISTS ix_ev_time ON system_events(timestamp_unix);
CREATE INDEX IF NOT EXISTS ix_ev_type ON system_events(event_type);

CREATE TABLE IF NOT EXISTS runtime_counters (
    id                 INTEGER PRIMARY KEY CHECK (id = 1),
    total_runtime_sec  REAL NOT NULL DEFAULT 0,
    field_runtime_sec  REAL NOT NULL DEFAULT 0,
    dock_runtime_sec   REAL NOT NULL DEFAULT 0,
    active_hart_sec    REAL NOT NULL DEFAULT 0,
    boot_count         INTEGER NOT NULL DEFAULT 0,
    updated_at         REAL
);
INSERT OR IGNORE INTO runtime_counters(id) VALUES (1);
"""

# Ereignistypen (für Grafana-Filter und PDF/Statistik einheitlich)
EV_BOOT, EV_SHUTDOWN = "BOOT", "SHUTDOWN"
EV_DOCK, EV_UNDOCK = "DOCK", "UNDOCK"
EV_ORDER_START, EV_ORDER_END = "ORDER_START", "ORDER_END"
EV_CALIBRATION, EV_DEVICE_SWAP, EV_NEW_DEVICE = "CALIBRATION", "DEVICE_SWAP", "NEW_DEVICE"
EV_SAFE_MODE, EV_LOOP_MODE, EV_BATTERY, EV_TIME_SET = "SAFE_MODE", "LOOP_MODE", "BATTERY", "TIME_SET"
EV_EXPORT, EV_ERROR = "EXPORT", "ERROR"


def read_cpu_temp() -> Optional[float]:
    try:
        return int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000.0
    except (OSError, ValueError):
        return None


class TelemetryLogger:
    def __init__(self, path: Path | str = config.TELEMETRY_DB_PATH, *,
                 interval_s: float = config.TELEMETRY_INTERVAL_S,
                 battery_provider: Optional[Callable[[], Optional[dict]]] = None,
                 docked_provider: Optional[Callable[[], bool]] = None,
                 hart_seconds_provider: Optional[Callable[[], float]] = None,
                 clock: Optional[Callable[[], dict]] = None):
        """battery_provider -> PackStatus.to_telemetry(); hart_seconds_provider -> HartModem.active_seconds"""
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.interval_s = interval_s
        self.battery_provider = battery_provider or (lambda: None)
        self.docked_provider = docked_provider or (lambda: False)
        self.hart_seconds_provider = hart_seconds_provider or (lambda: 0.0)
        self.clock = clock or (lambda: {"unix": time.time(), "source": "SYSTEM"})
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.executescript(SCHEMA)
        c = dict(self.conn.execute("SELECT * FROM runtime_counters WHERE id=1").fetchone())
        self.counters = {k: float(c[k]) for k in ("total_runtime_sec", "field_runtime_sec",
                                                   "dock_runtime_sec", "active_hart_sec")}
        self.boot_count = int(c["boot_count"])
        self._last_tick = time.monotonic()
        self._last_hart = self.hart_seconds_provider()
        self._session_start = time.monotonic()
        self._last_cleanup = 0.0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ Ereignisse
    def event(self, event_type: str, message: str, *, severity: str = "INFO", order_no: Optional[str] = None,
              device_tag: Optional[str] = None, duration_sec: Optional[float] = None,
              result: Optional[str] = None, **details) -> int:
        ts = self.clock()
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO system_events(timestamp_unix, event_type, severity, message, order_no, device_tag, "
                "duration_sec, result, time_source, details) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (int(ts["unix"]), event_type, severity, message, order_no, device_tag, duration_sec, result,
                 ts.get("source"), json.dumps(details, ensure_ascii=False, default=str) if details else None))
        log.log(logging.WARNING if severity in ("WARN", "ERROR") else logging.INFO, "[%s] %s", event_type, message)
        return cur.lastrowid

    def events(self, limit: int = 100, event_type: Optional[str] = None) -> list[dict]:
        sql, args = "SELECT * FROM system_events", ()
        if event_type:
            sql, args = sql + " WHERE event_type=?", (event_type,)
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, limit))]

    # ------------------------------------------------------------------ Zähler
    def _accumulate(self) -> None:
        now = time.monotonic()
        dt = max(0.0, now - self._last_tick)
        self._last_tick = now
        hart = self.hart_seconds_provider()
        dh = max(0.0, hart - self._last_hart)
        self._last_hart = hart
        self.counters["total_runtime_sec"] += dt
        self.counters["dock_runtime_sec" if self.docked_provider() else "field_runtime_sec"] += dt
        self.counters["active_hart_sec"] += dh

    def _save_counters(self) -> None:
        self.conn.execute("UPDATE runtime_counters SET total_runtime_sec=?, field_runtime_sec=?, dock_runtime_sec=?, "
                          "active_hart_sec=?, updated_at=? WHERE id=1",
                          (*self.counters.values(), time.time()))

    def tick(self) -> dict:
        """Ein Telemetriepunkt (wird alle 15 s vom Thread aufgerufen; auch direkt testbar)."""
        with self._lock:
            self._accumulate()
            bat = self.battery_provider() or {}
            row = {"timestamp_unix": int(self.clock()["unix"]),
                   **{k: int(v) for k, v in self.counters.items()},
                   "mode": "DOCK" if self.docked_provider() else "FIELD",
                   "pack_voltage_v": bat.get("pack_voltage_v"), "pack_current_a": bat.get("pack_current_a"),
                   "soc_percent": bat.get("soc_percent"), "cell_drift_mv": bat.get("cell_drift_mv"),
                   **{f"cell_{i}_v": bat.get(f"cell_{i}_v") for i in range(1, 9)},
                   "cpu_temp_c": read_cpu_temp()}
            cols = ",".join(row)
            self.conn.execute("BEGIN")
            self.conn.execute(f"INSERT INTO telemetry_timeseries({cols}) VALUES ({','.join('?' * len(row))})",
                              tuple(row.values()))
            self._save_counters()
            self.conn.execute("COMMIT")
            if time.monotonic() - self._last_cleanup > 86400:
                self._last_cleanup = time.monotonic()
                cutoff = int(time.time() - RETENTION_DAYS * 86400)
                self.conn.execute("DELETE FROM telemetry_timeseries WHERE timestamp_unix < ?", (cutoff,))
            return row

    # ------------------------------------------------------------------ Statistik-Overlay
    def stats(self) -> dict:
        with self._lock:
            self._accumulate()
            self._save_counters()
            day = int(time.time()) - 86400
            ev = lambda t, since=0: self.conn.execute(
                "SELECT COUNT(*) FROM system_events WHERE event_type=? AND timestamp_unix>=?", (t, since)).fetchone()[0]
            cal = self.conn.execute(
                "SELECT COUNT(*), SUM(result='BESTANDEN'), AVG(duration_sec) FROM system_events "
                "WHERE event_type=?", (EV_CALIBRATION,)).fetchone()
        h = lambda s: round(s / 3600.0, 2)
        return {
            "total_hours": h(self.counters["total_runtime_sec"]),
            "field_hours": h(self.counters["field_runtime_sec"]),
            "dock_hours": h(self.counters["dock_runtime_sec"]),
            "hart_hours": h(self.counters["active_hart_sec"]),
            "session_minutes": round((time.monotonic() - self._session_start) / 60.0, 1),
            "boot_count": self.boot_count,
            "calibrations_total": cal[0] or 0,
            "calibrations_passed": int(cal[1] or 0),
            "avg_calibration_min": round((cal[2] or 0) / 60.0, 1),
            "calibrations_24h": ev(EV_CALIBRATION, day),
            "device_swaps_total": ev(EV_DEVICE_SWAP),
            "new_devices_total": ev(EV_NEW_DEVICE),
        }

    # ------------------------------------------------------------------ Lebenszyklus
    def start(self) -> "TelemetryLogger":
        with self._lock:
            self.conn.execute("UPDATE runtime_counters SET boot_count = boot_count + 1 WHERE id=1")
            self.boot_count += 1
        self.event(EV_BOOT, f"Gerät gestartet (Start Nr. {self.boot_count})",
                   total_hours=round(self.counters["total_runtime_sec"] / 3600, 2))
        self._thread = threading.Thread(target=self._run, name="telemetry", daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self.tick()
            except Exception:
                log.exception("Telemetrie-Schreibfehler")

    def stop(self, reason: str = "Normal") -> None:
        """Beim Shutdown aufrufen (PowerLatch-Hook): letzter Datenpunkt + Ereignis."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        try:
            self.tick()
            self.event(EV_SHUTDOWN, f"Herunterfahren: {reason}",
                       session_minutes=round((time.monotonic() - self._session_start) / 60, 1))
            with self._lock:
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")   # alles in die Hauptdatei
        except sqlite3.Error:
            log.exception("Telemetrie beim Herunterfahren")
        finally:
            with self._lock:
                self.conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from battery_bms import BatteryMonitor
    bms = BatteryMonitor(simulate=True, state_file=None, poll_interval_s=0.2).start()
    time.sleep(0.5)
    tl = TelemetryLogger(":memory:", battery_provider=lambda: bms.latest().to_telemetry())
    tl.start()
    tl.event(EV_ORDER_START, "Auftrag A-2026-001 gestartet", order_no="A-2026-001")
    tl.event(EV_CALIBRATION, "PT-4711 kalibriert", order_no="A-2026-001", device_tag="PT-4711",
             duration_sec=412.0, result="BESTANDEN")
    row = tl.tick()
    print({k: row[k] for k in ("mode", "pack_voltage_v", "soc_percent", "cell_1_v", "cell_8_v")})
    print(tl.stats())
    bms.stop()
