"""Tests Schritt 5: Auftrags-DB (Fälle A/B/C, Tausch, Kalibrierung) und Telemetrie."""
import os
import sqlite3
import sys
import time
from pathlib import Path

os.environ["HART_SIM"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import database as dbm
import telemetry_logger as tlm


@pytest.fixture
def db(tmp_path):
    d = dbm.Database(tmp_path / "t.db")
    yield d
    d.close()


@pytest.fixture
def setup(db):
    a = db.create_customer("Kunde A", "K-1")
    b = db.create_customer("Kunde B", "K-2")
    oid = db.open_order(a, "A-001", "M. Muster")
    dev = db.create_device(a, "PT-4711", "26060a1b2c", {"lrv": 0, "urv": 2500, "unit": "mbar",
                                                         "tolerance_pct": 0.25, "is_positioner": False}, oid)
    return db, a, b, oid, dev


def pt(pct, passed=True, err=0.05):
    return {"point_pct": pct, "setpoint_value": pct * 25, "setpoint_ma": 4 + 0.16 * pct, "hart_pv": pct * 25,
            "hart_ma": 4 + 0.16 * pct, "true_ma": 4 + 0.16 * pct, "error_pv_pct": err, "error_ma_pct": -err,
            "da_mismatch_pct": 0.01, "passed": passed}


# ------------------------------------------------------------------ Aufträge
def test_only_one_open_order_survives_restart(tmp_path):
    p = tmp_path / "x.db"
    d = dbm.Database(p)
    c = d.create_customer("X")
    d.open_order(c, "A-1", "Tech")
    with pytest.raises(dbm.DatabaseError, match="noch offen"):
        d.open_order(c, "A-2", "Tech")
    d.close()
    d2 = dbm.Database(p)                                   # "Neustart"
    assert d2.get_open_order()["order_no"] == "A-1"
    with pytest.raises(sqlite3.IntegrityError):            # auch per DB-Index erzwungen
        d2.conn.execute("INSERT INTO orders(customer_id, order_no, technician, status, opened_at) "
                        "VALUES (?,?,?, 'OPEN', 0)", (c, "A-3", "T"))


def test_order_numbers_unique_and_required_fields(setup):
    db, a, b, oid, _ = setup
    db.close_order(oid)
    with pytest.raises(dbm.DatabaseError, match="bereits verwendet"):
        db.open_order(a, "A-001", "X")
    with pytest.raises(dbm.DatabaseError, match="Pflichtfelder"):
        db.open_order(a, "A-002", " ")


# ------------------------------------------------------------------ Fälle A/B/C
def test_case_a_recalibration(setup):
    db, a, *_ = setup
    m = db.match_device(a, "26060A1B2C", "PT-4711")
    assert m.case == dbm.CASE_RECAL and m.device["urv"] == 2500 and not m.hints


def test_case_a_with_tag_mismatch_hint(setup):
    db, a, *_ = setup
    m = db.match_device(a, "26060A1B2C", "PT-9999")
    assert m.case == dbm.CASE_RECAL and "PT-9999" in m.hints[0]


def test_case_c_new_and_customer_separation(setup):
    db, a, b, *_ = setup
    m = db.match_device(b, "26060A1B2C", "PT-4711")          # gleicher TAG + UID, anderer Kunde
    assert m.case == dbm.CASE_NEW and m.device is None
    assert any("ANDEREN Kunden" in h for h in m.hints)
    db.create_device(b, "PT-4711", "26060FFFFF", {"lrv": 0, "urv": 10})   # gleicher TAG bei Kunde B erlaubt


def test_duplicate_tag_rejected(setup):
    db, a, *_ = setup
    with pytest.raises(dbm.DatabaseError):
        db.create_device(a, "PT-4711", "26060BBBBB", {})


def test_case_b_swap_needs_token_and_final_confirmation(setup):
    db, a, b, oid, old = setup
    m = db.match_device(a, "26060C0FFE", "PT-4711")
    assert m.case == dbm.CASE_SWAP and "26060A1B2C" in m.hints[0] and m.swap_token
    with pytest.raises(dbm.DatabaseError, match="nicht bestätigt"):
        db.confirm_device_swap(m.swap_token, False, {})
    with pytest.raises(dbm.DatabaseError, match="ungültig"):     # Token ist verbraucht
        db.confirm_device_swap(m.swap_token, True, {})
    m = db.match_device(a, "26060C0FFE", "PT-4711")
    new = db.confirm_device_swap(m.swap_token, True, {"display_name": "Rosemount 3051"}, oid, "M. Muster")
    old_row, new_row = db.device(old), db.device(new)
    assert old_row["active"] == 0 and old_row["replaced_by"] == new
    assert new_row["tag"] == "PT-4711" and new_row["urv"] == 2500 and new_row["hart_unique_id"] == "26060C0FFE"
    assert [h["event"] for h in db.device_history(new)] == ["NEUAUFNAHME", "GERAETETAUSCH", "GERAETETAUSCH"]
    assert db.match_device(a, "26060C0FFE", "PT-4711").case == dbm.CASE_RECAL
    hint = db.match_device(a, "26060A1B2C", "PT-4711").hints     # altes Gerät wieder angeklemmt
    assert any("früher" in h for h in hint)


def test_swap_token_expires(setup, monkeypatch):
    db, a, *_ = setup
    m = db.match_device(a, "26060C0FFE", "PT-4711")
    t0, old_id, uid = db._swap_tokens[m.swap_token]
    db._swap_tokens[m.swap_token] = (t0 - dbm.SWAP_TOKEN_TTL_S - 1, old_id, uid)
    with pytest.raises(dbm.DatabaseError, match="abgelaufen"):
        db.confirm_device_swap(m.swap_token, True, {})


def test_update_device_records_diff(setup):
    db, a, b, oid, dev = setup
    db.update_device(dev, {"urv": 4000, "unit": "mbar"}, oid, "M. Muster")
    h = db.device_history(dev)[-1]
    assert h["event"] == "STAMMDATEN" and '"urv"' in h["details"] and '"unit"' not in h["details"]


# ------------------------------------------------------------------ Kalibrierung
def test_calibration_flow_and_result(setup):
    db, a, b, oid, dev = setup
    cid = db.start_calibration(oid, dev, dbm.CASE_RECAL, "M. Muster")
    for p in (0, 25, 50, 75):
        db.add_point(cid, pt(p))
    with pytest.raises(dbm.DatabaseError, match="4 von 5"):
        db.finish_calibration(cid)
    db.add_point(cid, pt(100, passed=False, err=0.4))
    db.add_point(cid, pt(100, passed=True, err=0.1))       # Wiederholung ersetzt den Punkt
    res = db.finish_calibration(cid)
    assert res["result"] == dbm.RESULT_PASS and res["max_error_pct"] == pytest.approx(0.1)
    assert len(db.points(cid)) == 5


def test_failed_point_fails_calibration(setup):
    db, a, b, oid, dev = setup
    cid = db.start_calibration(oid, dev, dbm.CASE_RECAL, "T")
    for p in (0, 25, 50, 75, 100):
        db.add_point(cid, pt(p, passed=(p != 75), err=0.6 if p == 75 else 0.05))
    assert db.finish_calibration(cid)["result"] == dbm.RESULT_FAIL


def test_calibration_requires_open_order_and_own_customer(setup):
    db, a, b, oid, dev = setup
    foreign = db.create_device(b, "FT-1", "1F57000001", {"lrv": 0, "urv": 1})
    with pytest.raises(dbm.DatabaseError, match="Kunden"):
        db.start_calibration(oid, foreign, dbm.CASE_NEW, "T")
    cid = db.start_calibration(oid, dev, dbm.CASE_RECAL, "T")
    with pytest.raises(dbm.DatabaseError, match="läuft noch"):
        db.close_order(oid)
    db.finish_calibration(cid, aborted=True)
    db.close_order(oid)
    with pytest.raises(dbm.DatabaseError, match="offenen Auftrags"):
        db.start_calibration(oid, dev, dbm.CASE_RECAL, "T")


def test_order_report_uses_latest_attempt(setup):
    db, a, b, oid, dev = setup
    for passed in (False, True):
        cid = db.start_calibration(oid, dev, dbm.CASE_RECAL, "T")
        for p in (0, 25, 50, 75, 100):
            db.add_point(cid, pt(p, passed=passed))
        db.finish_calibration(cid)
    db.add_photo({"path": "/x.jpg", "sha256": "ab"}, oid, dev, cid, 50)
    rep = db.order_report(oid)
    assert rep["summary"]["calibrations"] == 1 and rep["summary"]["passed"] == 1
    e = rep["entries"][0]
    assert e["attempts"] == 2 and len(e["points"]) == 5 and e["photos"][0]["point_pct"] == 50


# ------------------------------------------------------------------ Telemetrie
def test_telemetry_counters_persist_and_modes(tmp_path):
    p = tmp_path / "tel.db"
    docked = {"v": False}
    hart = {"s": 0.0}
    t = tlm.TelemetryLogger(p, docked_provider=lambda: docked["v"], hart_seconds_provider=lambda: hart["s"],
                            battery_provider=lambda: {"pack_voltage_v": 26.4, "cell_3_v": 3.3})
    t.start()
    t._last_tick -= 100                    # 100 s im Feld
    hart["s"] = 30
    row = t.tick()
    assert row["mode"] == "FIELD" and row["field_runtime_sec"] >= 100 and row["active_hart_sec"] == 30
    assert row["cell_3_v"] == 3.3 and row["cell_4_v"] is None
    docked["v"] = True
    t._last_tick -= 50
    row = t.tick()
    assert row["mode"] == "DOCK" and row["dock_runtime_sec"] >= 50
    t.stop("Test")
    t2 = tlm.TelemetryLogger(p)
    assert t2.counters["total_runtime_sec"] >= 150 and t2.boot_count == 1
    types = [e["event_type"] for e in t2.events()]
    assert types == ["SHUTDOWN", "BOOT"]


def test_telemetry_schema_matches_spec(tmp_path):
    t = tlm.TelemetryLogger(tmp_path / "t.db")
    cols = [r[1] for r in t.conn.execute("PRAGMA table_info(telemetry_timeseries)")]
    expected = ["timestamp_unix", "total_runtime_sec", "field_runtime_sec", "dock_runtime_sec", "active_hart_sec",
                "mode", "pack_voltage_v", "pack_current_a", "soc_percent", "cell_drift_mv",
                *[f"cell_{i}_v" for i in range(1, 9)], "cpu_temp_c"]
    assert cols == expected
    assert t.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_stats(tmp_path):
    t = tlm.TelemetryLogger(tmp_path / "t.db")
    t.event(tlm.EV_CALIBRATION, "x", duration_sec=600, result="BESTANDEN")
    t.event(tlm.EV_CALIBRATION, "y", duration_sec=300, result="NICHT BESTANDEN")
    t.event(tlm.EV_DEVICE_SWAP, "z")
    s = t.stats()
    assert s["calibrations_total"] == 2 and s["calibrations_passed"] == 1
    assert s["avg_calibration_min"] == 7.5 and s["device_swaps_total"] == 1
