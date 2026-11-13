"""
database.py – Auftrags- und Kalibrierdatenbank (hart_kalibrierung.db, SQLite/WAL).

Datenmodell:
  customers ─┬─ orders (status OPEN/CLOSED, höchstens EIN offener Auftrag – per Index erzwungen)
             └─ devices (TAG eindeutig je Kunde unter den AKTIVEN Geräten; Tausch = neue Zeile,
                         alte Zeile bleibt als Historie mit replaced_by erhalten)
  calibrations (je Auftrag + Gerät) ─ calibration_points (5-Punkt-Messung) ─ photos
  device_history (Neuaufnahme, Tausch, Stammdatenänderung)

Identifikation beim Anschließen (immer NUR innerhalb des Kunden des offenen Auftrags):
  Fall A  UID bekannt                         -> NACHKALIBRIERUNG (Solldaten aus der DB)
  Fall B  UID neu, TAG beim Kunden vorhanden  -> GERAETETAUSCH (zweistufige Bestätigung)
  Fall C  UID neu, TAG neu                    -> NEUAUFNAHME
"""
from __future__ import annotations

import json
import logging
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import config

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_TOLERANCE_PCT = 0.25
SWAP_TOKEN_TTL_S = 180

CASE_RECAL, CASE_SWAP, CASE_NEW = "NACHKALIBRIERUNG", "GERAETETAUSCH", "NEUAUFNAHME"
RESULT_PASS, RESULT_FAIL, RESULT_ABORT = "BESTANDEN", "NICHT BESTANDEN", "ABGEBROCHEN"

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    customer_no   TEXT UNIQUE,
    address       TEXT DEFAULT '',
    contact       TEXT DEFAULT '',
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY,
    customer_id   INTEGER NOT NULL REFERENCES customers(id),
    order_no      TEXT NOT NULL UNIQUE,
    description   TEXT DEFAULT '',
    technician    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED')),
    opened_at     REAL NOT NULL,
    closed_at     REAL,
    pdf_path      TEXT,
    notes         TEXT DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_single_open ON orders(status) WHERE status = 'OPEN';

CREATE TABLE IF NOT EXISTS devices (
    id              INTEGER PRIMARY KEY,
    customer_id     INTEGER NOT NULL REFERENCES customers(id),
    tag             TEXT NOT NULL,
    hart_unique_id  TEXT NOT NULL,
    manufacturer_id INTEGER,
    device_type     INTEGER,
    display_name    TEXT DEFAULT '',
    device_class    TEXT DEFAULT '',
    is_positioner   INTEGER NOT NULL DEFAULT 0,
    descriptor      TEXT DEFAULT '',
    location        TEXT DEFAULT '',
    lrv             REAL,
    urv             REAL,
    unit_code       INTEGER,
    unit            TEXT DEFAULT '',
    tolerance_pct   REAL NOT NULL DEFAULT 0.25,
    universal_rev   INTEGER,
    software_rev    INTEGER,
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL,
    replaced_at     REAL,
    replaced_by     INTEGER REFERENCES devices(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_devices_active_tag ON devices(customer_id, tag) WHERE active = 1;
CREATE UNIQUE INDEX IF NOT EXISTS ux_devices_active_uid ON devices(customer_id, hart_unique_id) WHERE active = 1;
CREATE INDEX IF NOT EXISTS ix_devices_uid ON devices(hart_unique_id);

CREATE TABLE IF NOT EXISTS device_history (
    id          INTEGER PRIMARY KEY,
    device_id   INTEGER NOT NULL REFERENCES devices(id),
    order_id    INTEGER REFERENCES orders(id),
    event       TEXT NOT NULL,
    old_uid     TEXT,
    new_uid     TEXT,
    technician  TEXT,
    details     TEXT,
    ts          REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS calibrations (
    id            INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES orders(id),
    device_id     INTEGER NOT NULL REFERENCES devices(id),
    case_type     TEXT NOT NULL CHECK (case_type IN ('NACHKALIBRIERUNG','GERAETETAUSCH','NEUAUFNAHME')),
    technician    TEXT NOT NULL,
    started_at    REAL NOT NULL,
    finished_at   REAL,
    duration_s    REAL,
    result        TEXT CHECK (result IN ('BESTANDEN','NICHT BESTANDEN','ABGEBROCHEN')),
    max_error_pct REAL,
    tolerance_pct REAL NOT NULL,
    lrv           REAL,
    urv           REAL,
    unit          TEXT,
    time_source   TEXT DEFAULT 'SYSTEM',
    meter_info    TEXT,
    notes         TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_cal_order ON calibrations(order_id);

CREATE TABLE IF NOT EXISTS calibration_points (
    id              INTEGER PRIMARY KEY,
    calibration_id  INTEGER NOT NULL REFERENCES calibrations(id) ON DELETE CASCADE,
    point_pct       REAL NOT NULL,
    setpoint_value  REAL,
    setpoint_ma     REAL,
    hart_pv         REAL,
    hart_ma         REAL,
    true_ma         REAL,
    error_pv_pct    REAL,
    error_ma_pct    REAL,
    da_mismatch_pct REAL,
    passed          INTEGER NOT NULL,
    ts              REAL NOT NULL,
    UNIQUE (calibration_id, point_pct)
);

CREATE TABLE IF NOT EXISTS photos (
    id              INTEGER PRIMARY KEY,
    order_id        INTEGER REFERENCES orders(id),
    device_id       INTEGER REFERENCES devices(id),
    calibration_id  INTEGER REFERENCES calibrations(id),
    point_pct       REAL,
    path            TEXT NOT NULL,
    thumbnail       TEXT,
    sha256          TEXT NOT NULL,
    note            TEXT DEFAULT '',
    captured_at     REAL NOT NULL
);
"""


class DatabaseError(RuntimeError):
    """Fachlicher Fehler (wird der UI im Klartext angezeigt)."""


@dataclass
class DeviceMatch:
    case: str                          # NACHKALIBRIERUNG | GERAETETAUSCH | NEUAUFNAHME
    device: Optional[dict] = None      # bekanntes Gerät (Fall A) bzw. bisheriges Gerät (Fall B)
    hints: list[str] = field(default_factory=list)
    swap_token: Optional[str] = None   # Fall B: Bestätigung 1 -> Token für Bestätigung 2

    def to_dict(self) -> dict:
        return {"case": self.case, "device": self.device, "hints": self.hints,
                "swap_token": self.swap_token}


def _row(r: Optional[sqlite3.Row]) -> Optional[dict]:
    return dict(r) if r is not None else None


class Database:
    def __init__(self, path: Path | str = config.DB_PATH,
                 clock: Optional[Callable[[], dict]] = None):
        """clock(): liefert z.B. RtcManager.timestamp() -> {'unix':…, 'source':…}"""
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock or (lambda: {"unix": time.time(), "source": "SYSTEM"})
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")      # WAL: sicher bei Stromausfall
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self._swap_tokens: dict[str, tuple[float, int, str]] = {}
        self._migrate()

    # ------------------------------------------------------------------ Infrastruktur
    def _migrate(self) -> None:
        with self._lock:
            ver = self.conn.execute("PRAGMA user_version").fetchone()[0]
            if ver < 1:
                self.conn.executescript(SCHEMA)
                self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Transaktion: alles oder nichts (wichtig beim Gerätetausch)."""
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")

    def now(self) -> float:
        return float(self.clock()["unix"])

    def q(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def q1(self, sql: str, args: tuple = ()) -> Optional[dict]:
        with self._lock:
            return _row(self.conn.execute(sql, args).fetchone())

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # ------------------------------------------------------------------ Kunden
    def create_customer(self, name: str, customer_no: Optional[str] = None, address: str = "",
                        contact: str = "") -> int:
        if not name.strip():
            raise DatabaseError("Kundenname fehlt")
        try:
            with self.tx() as c:
                cur = c.execute("INSERT INTO customers(name, customer_no, address, contact, created_at) "
                                "VALUES (?,?,?,?,?)", (name.strip(), customer_no or None, address, contact, self.now()))
                return cur.lastrowid
        except sqlite3.IntegrityError as exc:
            raise DatabaseError(f"Kundennummer {customer_no} existiert bereits") from exc

    def customer(self, customer_id: int) -> Optional[dict]:
        return self.q1("SELECT * FROM customers WHERE id=?", (customer_id,))

    def customers(self, search: str = "") -> list[dict]:
        like = f"%{search.strip()}%"
        return self.q("SELECT c.*, (SELECT COUNT(*) FROM devices d WHERE d.customer_id=c.id AND d.active=1) "
                      "AS device_count FROM customers c WHERE c.name LIKE ? OR IFNULL(c.customer_no,'') LIKE ? "
                      "ORDER BY c.name", (like, like))

    # ------------------------------------------------------------------ Aufträge
    def open_order(self, customer_id: int, order_no: str, technician: str, description: str = "") -> int:
        if not self.customer(customer_id):
            raise DatabaseError("Kunde nicht gefunden")
        if not order_no.strip() or not technician.strip():
            raise DatabaseError("Auftragsnummer und Prüfer sind Pflichtfelder")
        existing = self.get_open_order()
        if existing:
            raise DatabaseError(f"Auftrag {existing['order_no']} ist noch offen – bitte zuerst abschließen")
        try:
            with self.tx() as c:
                return c.execute("INSERT INTO orders(customer_id, order_no, description, technician, status, opened_at) "
                                 "VALUES (?,?,?,?, 'OPEN', ?)",
                                 (customer_id, order_no.strip(), description, technician.strip(), self.now())).lastrowid
        except sqlite3.IntegrityError as exc:
            raise DatabaseError(f"Auftragsnummer {order_no} wurde bereits verwendet") from exc

    def get_open_order(self) -> Optional[dict]:
        """Der aktive Auftrag – bleibt über Neustarts erhalten (liegt in der DB)."""
        return self.q1("SELECT o.*, c.name AS customer_name, c.customer_no FROM orders o "
                       "JOIN customers c ON c.id=o.customer_id WHERE o.status='OPEN'")

    def order(self, order_id: int) -> Optional[dict]:
        return self.q1("SELECT o.*, c.name AS customer_name, c.customer_no FROM orders o "
                       "JOIN customers c ON c.id=o.customer_id WHERE o.id=?", (order_id,))

    def orders(self, limit: int = 50) -> list[dict]:
        return self.q("SELECT o.*, c.name AS customer_name FROM orders o JOIN customers c ON c.id=o.customer_id "
                      "ORDER BY o.opened_at DESC LIMIT ?", (limit,))

    def close_order(self, order_id: int, pdf_path: Optional[str] = None) -> dict:
        o = self.order(order_id)
        if not o or o["status"] != "OPEN":
            raise DatabaseError("Kein offener Auftrag mit dieser ID")
        running = self.q1("SELECT id FROM calibrations WHERE order_id=? AND finished_at IS NULL", (order_id,))
        if running:
            raise DatabaseError("Eine Kalibrierung läuft noch – bitte abschließen oder abbrechen")
        with self.tx() as c:
            c.execute("UPDATE orders SET status='CLOSED', closed_at=?, pdf_path=? WHERE id=?",
                      (self.now(), pdf_path, order_id))
        return self.order(order_id)

    def set_order_pdf(self, order_id: int, pdf_path: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE orders SET pdf_path=? WHERE id=?", (pdf_path, order_id))

    # ------------------------------------------------------------------ Geräte
    def device(self, device_id: int) -> Optional[dict]:
        return self.q1("SELECT * FROM devices WHERE id=?", (device_id,))

    def devices(self, customer_id: int, include_inactive: bool = False) -> list[dict]:
        sql = "SELECT * FROM devices WHERE customer_id=?" + ("" if include_inactive else " AND active=1")
        return self.q(sql + " ORDER BY tag, created_at", (customer_id,))

    def device_history(self, device_id: int) -> list[dict]:
        """Historie über alle Vorgänger (Tauschkette) hinweg."""
        ids, cur = [], device_id
        while cur:
            ids.append(cur)
            prev = self.q1("SELECT id FROM devices WHERE replaced_by=?", (cur,))
            cur = prev["id"] if prev else None
        marks = ",".join("?" * len(ids))
        return self.q(f"SELECT * FROM device_history WHERE device_id IN ({marks}) ORDER BY ts", tuple(ids))

    def match_device(self, customer_id: int, unique_id: str, tag: str) -> DeviceMatch:
        """Fallunterscheidung A/B/C – streng innerhalb des Kunden."""
        uid = unique_id.strip().upper()
        tag = tag.strip()
        hints = []
        known = self.q1("SELECT * FROM devices WHERE customer_id=? AND hart_unique_id=? AND active=1",
                        (customer_id, uid))
        if known:
            if tag and tag != known["tag"]:
                hints.append(f"Im Gerät ist TAG '{tag}' hinterlegt, in der Datenbank '{known['tag']}'")
            return DeviceMatch(CASE_RECAL, known, hints)
        same_tag = self.q1("SELECT * FROM devices WHERE customer_id=? AND tag=? AND active=1", (customer_id, tag)) \
            if tag else None
        elsewhere = self.q1("SELECT COUNT(*) AS n FROM devices WHERE hart_unique_id=? AND customer_id<>?",
                            (uid, customer_id))
        if elsewhere and elsewhere["n"]:
            hints.append("Diese Unique-ID ist bei einem ANDEREN Kunden registriert")
        retired = self.q1("SELECT tag FROM devices WHERE customer_id=? AND hart_unique_id=? AND active=0",
                          (customer_id, uid))
        if retired:
            hints.append(f"Gerät war früher als '{retired['tag']}' im Einsatz (ausgetauscht)")
        if same_tag:
            token = secrets.token_hex(8)
            self._swap_tokens[token] = (time.monotonic(), same_tag["id"], uid)
            hints.insert(0, f"TAG {tag}: alte Unique-ID {same_tag['hart_unique_id']} → neue {uid}")
            return DeviceMatch(CASE_SWAP, same_tag, hints, swap_token=token)
        return DeviceMatch(CASE_NEW, None, hints)

    def _device_values(self, info: dict) -> dict:
        allowed = ("manufacturer_id", "device_type", "display_name", "device_class", "is_positioner",
                   "descriptor", "location", "lrv", "urv", "unit_code", "unit", "tolerance_pct",
                   "universal_rev", "software_rev")
        out = {k: info[k] for k in allowed if k in info and info[k] is not None}
        if "is_positioner" in out:
            out["is_positioner"] = int(bool(out["is_positioner"]))
        return out

    def create_device(self, customer_id: int, tag: str, unique_id: str, info: dict,
                      order_id: Optional[int] = None, technician: str = "") -> int:
        """Fall C – Neuaufnahme."""
        if not tag.strip():
            raise DatabaseError("TAG fehlt")
        vals = self._device_values(info)
        vals.setdefault("tolerance_pct", DEFAULT_TOLERANCE_PCT)
        now = self.now()
        cols = ["customer_id", "tag", "hart_unique_id", "created_at", "updated_at", *vals]
        args = [customer_id, tag.strip(), unique_id.strip().upper(), now, now, *vals.values()]
        try:
            with self.tx() as c:
                dev_id = c.execute(f"INSERT INTO devices({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                                   args).lastrowid
                c.execute("INSERT INTO device_history(device_id, order_id, event, new_uid, technician, details, ts) "
                          "VALUES (?,?,?,?,?,?,?)", (dev_id, order_id, CASE_NEW, unique_id.upper(), technician,
                                                     json.dumps(vals, ensure_ascii=False), now))
                return dev_id
        except sqlite3.IntegrityError as exc:
            raise DatabaseError(f"TAG {tag} oder Unique-ID ist beim Kunden bereits aktiv vergeben") from exc

    def update_device(self, device_id: int, changes: dict, order_id: Optional[int] = None,
                      technician: str = "") -> dict:
        """Stammdatenänderung mit Historie (alte/neue Werte)."""
        old = self.device(device_id)
        if not old:
            raise DatabaseError("Gerät nicht gefunden")
        vals = self._device_values(changes)
        if "tag" in changes and changes["tag"].strip():
            vals["tag"] = changes["tag"].strip()
        diff = {k: {"alt": old.get(k), "neu": v} for k, v in vals.items() if old.get(k) != v}
        if not diff:
            return old
        sets = ", ".join(f"{k}=?" for k in vals)
        try:
            with self.tx() as c:
                c.execute(f"UPDATE devices SET {sets}, updated_at=? WHERE id=?", (*vals.values(), self.now(), device_id))
                c.execute("INSERT INTO device_history(device_id, order_id, event, technician, details, ts) "
                          "VALUES (?,?,?,?,?,?)", (device_id, order_id, "STAMMDATEN", technician,
                                                   json.dumps(diff, ensure_ascii=False), self.now()))
        except sqlite3.IntegrityError as exc:
            raise DatabaseError("Der neue TAG ist beim Kunden bereits vergeben") from exc
        return self.device(device_id)

    def confirm_device_swap(self, swap_token: str, final_confirmation: bool, new_info: dict,
                            order_id: Optional[int] = None, technician: str = "") -> int:
        """Fall B – zweite Bestätigung. Das alte Gerät wird inaktiv (Historie bleibt),
        das neue übernimmt TAG und Solldaten (Messbereich, Toleranz) des alten."""
        entry = self._swap_tokens.pop(swap_token, None)
        if entry is None:
            raise DatabaseError("Bestätigung ungültig oder bereits verwendet – Gerät bitte neu einlesen")
        t0, old_id, new_uid = entry
        if time.monotonic() - t0 > SWAP_TOKEN_TTL_S:
            raise DatabaseError("Bestätigung abgelaufen – Gerät bitte neu einlesen")
        if not final_confirmation:
            raise DatabaseError("Gerätetausch nicht bestätigt")
        old = self.device(old_id)
        if not old or not old["active"]:
            raise DatabaseError("Bisheriges Gerät ist nicht mehr aktiv")
        inherited = {k: old[k] for k in ("lrv", "urv", "unit_code", "unit", "tolerance_pct", "location",
                                         "descriptor")}
        vals = {**inherited, **self._device_values(new_info)}
        now = self.now()
        cols = ["customer_id", "tag", "hart_unique_id", "created_at", "updated_at", *vals]
        with self.tx() as c:
            c.execute("UPDATE devices SET active=0, replaced_at=?, updated_at=? WHERE id=?", (now, now, old_id))
            new_id = c.execute(f"INSERT INTO devices({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                               [old["customer_id"], old["tag"], new_uid, now, now, *vals.values()]).lastrowid
            c.execute("UPDATE devices SET replaced_by=? WHERE id=?", (new_id, old_id))
            for dev in (old_id, new_id):
                c.execute("INSERT INTO device_history(device_id, order_id, event, old_uid, new_uid, technician, ts) "
                          "VALUES (?,?,?,?,?,?,?)", (dev, order_id, CASE_SWAP, old["hart_unique_id"], new_uid,
                                                     technician, now))
        log.warning("Gerätetausch %s: %s -> %s", old["tag"], old["hart_unique_id"], new_uid)
        return new_id

    # ------------------------------------------------------------------ Kalibrierungen
    def start_calibration(self, order_id: int, device_id: int, case_type: str, technician: str,
                          meter_info: Optional[dict] = None) -> int:
        o = self.order(order_id)
        if not o or o["status"] != "OPEN":
            raise DatabaseError("Kalibrierung nur innerhalb eines offenen Auftrags möglich")
        d = self.device(device_id)
        if not d or d["customer_id"] != o["customer_id"]:
            raise DatabaseError("Gerät gehört nicht zum Kunden des Auftrags")
        if d["lrv"] is None or d["urv"] is None or d["lrv"] == d["urv"]:
            raise DatabaseError("Für das Gerät ist kein gültiger Messbereich hinterlegt")
        ts = self.clock()
        with self.tx() as c:
            c.execute("UPDATE calibrations SET finished_at=?, result=?, notes='Automatisch abgebrochen (neuer Start)' "
                      "WHERE device_id=? AND order_id=? AND finished_at IS NULL",
                      (ts["unix"], RESULT_ABORT, device_id, order_id))
            return c.execute(
                "INSERT INTO calibrations(order_id, device_id, case_type, technician, started_at, tolerance_pct, "
                "lrv, urv, unit, time_source, meter_info) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (order_id, device_id, case_type, technician, ts["unix"], d["tolerance_pct"], d["lrv"], d["urv"],
                 d["unit"], ts.get("source", "SYSTEM"), json.dumps(meter_info or {}, ensure_ascii=False))).lastrowid

    def add_point(self, calibration_id: int, point: dict) -> dict:
        """point: Ergebnis von calibration.evaluate_point() (Schritt 7). Wiederholung ersetzt den Punkt."""
        cal = self.calibration(calibration_id)
        if not cal or cal["finished_at"] is not None:
            raise DatabaseError("Kalibrierung ist nicht aktiv")
        cols = ("point_pct", "setpoint_value", "setpoint_ma", "hart_pv", "hart_ma", "true_ma",
                "error_pv_pct", "error_ma_pct", "da_mismatch_pct", "passed")
        with self.tx() as c:
            c.execute(f"INSERT OR REPLACE INTO calibration_points(calibration_id, {','.join(cols)}, ts) "
                      f"VALUES (?, {','.join('?' * len(cols))}, ?)",
                      (calibration_id, *[point.get(k) for k in cols[:-1]], int(bool(point["passed"])), self.now()))
        return point

    def finish_calibration(self, calibration_id: int, aborted: bool = False, notes: str = "") -> dict:
        cal = self.calibration(calibration_id)
        if not cal or cal["finished_at"] is not None:
            raise DatabaseError("Kalibrierung ist nicht aktiv")
        pts = self.points(calibration_id)
        if aborted:
            result, max_err = RESULT_ABORT, None
        else:
            if len(pts) < 5:
                raise DatabaseError(f"Erst {len(pts)} von 5 Messpunkten erfasst")
            errs = [abs(v) for p in pts for v in (p["error_pv_pct"], p["error_ma_pct"]) if v is not None]
            max_err = max(errs) if errs else None
            result = RESULT_PASS if all(p["passed"] for p in pts) else RESULT_FAIL
        now = self.now()
        with self.tx() as c:
            c.execute("UPDATE calibrations SET finished_at=?, duration_s=?, result=?, max_error_pct=?, notes=? "
                      "WHERE id=?", (now, now - cal["started_at"], result, max_err, notes, calibration_id))
        return self.calibration(calibration_id)

    def calibration(self, calibration_id: int) -> Optional[dict]:
        return self.q1("SELECT * FROM calibrations WHERE id=?", (calibration_id,))

    def points(self, calibration_id: int) -> list[dict]:
        return self.q("SELECT * FROM calibration_points WHERE calibration_id=? ORDER BY point_pct", (calibration_id,))

    def last_calibration(self, device_id: int) -> Optional[dict]:
        return self.q1("SELECT * FROM calibrations WHERE device_id=? AND result IN (?,?) "
                       "ORDER BY finished_at DESC LIMIT 1", (device_id, RESULT_PASS, RESULT_FAIL))

    # ------------------------------------------------------------------ Fotos
    def add_photo(self, photo: dict, order_id: Optional[int] = None, device_id: Optional[int] = None,
                  calibration_id: Optional[int] = None, point_pct: Optional[float] = None) -> int:
        with self.tx() as c:
            return c.execute("INSERT INTO photos(order_id, device_id, calibration_id, point_pct, path, thumbnail, "
                             "sha256, note, captured_at) VALUES (?,?,?,?,?,?,?,?,?)",
                             (order_id, device_id, calibration_id, point_pct, photo["path"], photo.get("thumbnail"),
                              photo["sha256"], photo.get("note", ""), photo.get("captured_at", self.now()))).lastrowid

    def photos(self, calibration_id: Optional[int] = None, device_id: Optional[int] = None) -> list[dict]:
        if calibration_id is not None:
            return self.q("SELECT * FROM photos WHERE calibration_id=? ORDER BY captured_at", (calibration_id,))
        return self.q("SELECT * FROM photos WHERE device_id=? ORDER BY captured_at", (device_id,))

    # ------------------------------------------------------------------ Bericht (PDF)
    def order_report(self, order_id: int) -> dict:
        """Alle Daten für pdf_generator: Auftrag, Kunde, je Gerät die LETZTE abgeschlossene Prüfung."""
        o = self.order(order_id)
        if not o:
            raise DatabaseError("Auftrag nicht gefunden")
        customer = self.customer(o["customer_id"])
        cals = self.q("SELECT * FROM calibrations WHERE order_id=? AND result IN (?,?) ORDER BY started_at",
                      (order_id, RESULT_PASS, RESULT_FAIL))
        latest: dict[int, dict] = {}
        for c in cals:                                   # Wiederholungsprüfung ersetzt frühere
            latest[c["device_id"]] = c
        entries = []
        for c in sorted(latest.values(), key=lambda c: self.device(c["device_id"])["tag"]):
            dev = self.device(c["device_id"])
            prev = self.q1("SELECT * FROM devices WHERE replaced_by=?", (dev["id"],))
            entries.append({"calibration": c, "device": dev, "points": self.points(c["id"]),
                            "photos": self.photos(calibration_id=c["id"]),
                            "replaced_device": prev, "attempts": sum(1 for x in cals if x["device_id"] == dev["id"])})
        summary = {
            "calibrations": len(entries),
            "passed": sum(1 for e in entries if e["calibration"]["result"] == RESULT_PASS),
            "failed": sum(1 for e in entries if e["calibration"]["result"] == RESULT_FAIL),
            "swaps": sum(1 for e in entries if e["calibration"]["case_type"] == CASE_SWAP),
            "new_devices": sum(1 for e in entries if e["calibration"]["case_type"] == CASE_NEW),
            "recalibrations": sum(1 for e in entries if e["calibration"]["case_type"] == CASE_RECAL),
        }
        return {"order": o, "customer": customer, "entries": entries, "summary": summary}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    db = Database(":memory:")
    cust = db.create_customer("Chemiepark Nord GmbH", "K-1001", "Werkstraße 1, 12345 Musterstadt")
    oid = db.open_order(cust, "A-2026-001", "M. Muster", "Jahresprüfung Kolonne K1")
    print("Offener Auftrag:", db.get_open_order()["order_no"])
    print("Fall:", db.match_device(cust, "26060A1B2C", "PT-4711").case)
    dev = db.create_device(cust, "PT-4711", "26060A1B2C", {"lrv": 0, "urv": 2500, "unit": "mbar", "unit_code": 8})
    print("Fall:", db.match_device(cust, "26060A1B2C", "PT-4711").case)
    m = db.match_device(cust, "26060C0FFE", "PT-4711")
    print("Fall:", m.case, m.hints)
    new = db.confirm_device_swap(m.swap_token, True, {"display_name": "Rosemount 3051"}, oid, "M. Muster")
    print("Neues Gerät erbt Messbereich:", db.device(new)["urv"], db.device(new)["unit"])
    print("Historie:", [h["event"] for h in db.device_history(new)])
