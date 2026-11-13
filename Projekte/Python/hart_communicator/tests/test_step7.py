"""Tests Schritt 7: REST-API und Arbeitsablauf (Flask-Testclient, komplette Simulation)."""
import functools
import os
import sys
from pathlib import Path

os.environ["HART_SIM"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import app as appmod
from hart_modem import SIM_BUS, SIM_SCENARIOS


@pytest.fixture
def ctx(tmp_path):
    SIM_BUS.connect(SIM_SCENARIOS["rosemount_3051"]())
    s = appmod.build_services(simulate=True, data_dir=tmp_path)
    s.modem.transport.latency_s = 0
    s.meter.read_stable = functools.partial(s.meter.read_stable, window_s=0.2, timeout_s=5)
    s.meter.sample_interval_s = 0.02
    flask_app = appmod.create_app(s, start=False, background=False)
    c = flask_app.test_client()
    yield c, s, flask_app.config["workflow"], tmp_path
    s.feedback.close()


def post(c, url, data=None, status=200):
    r = c.post(url, json=data or {})
    assert r.status_code == status, (url, r.status_code, r.get_json())
    return r.get_json()


def open_order(c):
    cust = post(c, "/api/customers", {"name": "Chemiepark Nord GmbH", "customer_no": "K-1001"})
    return post(c, "/api/order", {"customer_id": cust["id"], "order_no": "A-1", "technician": "M. Muster"})


def calibrate(c, positioner=False):
    for pct in (0, 25, 50, 75, 100):
        if positioner:
            post(c, "/api/calibration/setpoint", {"pct": pct})
        else:
            post(c, "/api/sim/process", {"pct": pct})
        pt = post(c, "/api/calibration/measure", {"pct": pct})
        assert pt["point_pct"] == pct
    return post(c, "/api/calibration/finish")


def test_index_and_status(ctx):
    c, *_ = ctx
    assert b"HART-Communicator" in c.get("/").data
    st = c.get("/api/status").get_json()
    assert st["safe_mode"] is True and st["order"] is None and st["loop"]["mode"] == "PASSIVE"


def test_workflow_requires_open_order(ctx):
    c, *_ = ctx
    r = post(c, "/api/identify/hart", status=400)
    assert "Auftrag" in r["error"]


def test_full_flow_new_device_to_pdf(ctx):
    c, s, wf, tmp = ctx
    open_order(c)
    st = post(c, "/api/identify/hart")
    assert st["match"]["case"] == "NEUAUFNAHME" and st["info"]["tag"] == "PT-4711"
    # Safe-Mode: Schreiben ins Gerät blockiert, nur DB-Anlage möglich
    err = post(c, "/api/device/register", {"tag": "PT-4711", "write_to_device": True}, status=400)
    assert "Safe-Mode" in err["error"]
    st = post(c, "/api/device/register", {"tag": "PT-4711", "tolerance_pct": "0,25"})
    assert st["device"]["tolerance_pct"] == 0.25
    post(c, "/api/calibration/start")
    res = calibrate(c)
    assert res["stage"] == "done" and res["last_result"]["result"] == "BESTANDEN"
    assert c.get("/api/label/preview.png").data[:4] == b"\x89PNG"
    assert post(c, "/api/label/print")["ok"]
    out = post(c, "/api/order/close")
    assert out["pdf"]["pages"] == 3 and Path(out["pdf"]["path"]).exists()
    assert c.get(out["pdf"]["url"]).status_code == 200
    types = [e["event_type"] for e in s.telemetry.events(20)]
    assert {"ORDER_START", "NEW_DEVICE", "CALIBRATION", "ORDER_END"} <= set(types)


def test_finish_needs_all_points(ctx):
    c, *_ = ctx
    open_order(c)
    post(c, "/api/identify/hart")
    post(c, "/api/device/register", {"tag": "PT-4711"})
    post(c, "/api/calibration/start")
    post(c, "/api/calibration/measure", {"pct": 0})
    assert "Noch nicht gemessen" in post(c, "/api/calibration/finish", status=400)["error"]
    assert "Kalibrierung läuft" in post(c, "/api/order/close", status=400)["error"]


def test_device_swap_needs_two_confirmations(ctx):
    c, s, wf, _ = ctx
    open_order(c)
    post(c, "/api/identify/hart")
    post(c, "/api/device/register", {"tag": "PT-4711"})
    post(c, "/api/workflow/reset")
    SIM_BUS.connect(SIM_SCENARIOS["rosemount_3051_replaced"]())
    st = post(c, "/api/identify/hart")
    assert st["match"]["case"] == "GERAETETAUSCH" and st["device"] is None
    assert "Bestätigung" in post(c, "/api/swap/confirm", {"step": 2}, status=400)["error"]
    assert post(c, "/api/swap/confirm", {"step": 1})["swap_confirmations"] == 1
    st = post(c, "/api/swap/confirm", {"step": 2})
    assert st["device"]["hart_unique_id"] == "26060C0FFE" and st["device"]["tag"] == "PT-4711"


def test_positioner_cmd40_blocked_by_safe_mode_and_released(ctx):
    c, s, wf, _ = ctx
    dev = SIM_BUS.connect(SIM_SCENARIOS["fisher_dvc6200"]())
    open_order(c)
    st = post(c, "/api/identify/hart")
    assert st["is_positioner"]
    post(c, "/api/device/register", {"tag": "FV-3001"})
    post(c, "/api/calibration/start")
    assert "Safe-Mode" in post(c, "/api/calibration/setpoint", {"pct": 50}, status=400)["error"]
    assert "bestätigt" in post(c, "/api/safe_mode", {"enabled": False}, status=400)["error"]
    post(c, "/api/safe_mode", {"enabled": False, "confirmed": True})
    res = calibrate(c, positioner=True)
    assert res["last_result"]["result"] == "BESTANDEN"
    assert dev.fixed_current is None and not res["fixed_current_active"]      # Cmd 40 wieder verlassen


def test_abort_releases_fixed_current(ctx):
    c, s, wf, _ = ctx
    dev = SIM_BUS.connect(SIM_SCENARIOS["siemens_sipart_ps2"]())
    open_order(c)
    post(c, "/api/safe_mode", {"enabled": False, "confirmed": True})
    post(c, "/api/identify/hart")
    post(c, "/api/device/register", {"tag": "LV-1203"})
    post(c, "/api/calibration/start")
    post(c, "/api/calibration/setpoint", {"pct": 75})
    assert dev.fixed_current == pytest.approx(16.0)
    post(c, "/api/calibration/abort")
    assert dev.fixed_current is None


def test_positioner_blocks_24v_loop(ctx):
    c, *_ = ctx
    SIM_BUS.connect(SIM_SCENARIOS["fisher_dvc6200"]())
    open_order(c)
    post(c, "/api/identify/hart")
    err = post(c, "/api/loop_mode", {"mode": "ACTIVE_24V", "confirmed": True}, status=400)
    assert "Stellungsregler" in err["error"]


def test_qr_customer_separation(ctx):
    c, *_ = ctx
    open_order(c)
    err = post(c, "/api/identify/qr", {"text": "CUST:K-9999|TAG:PT-4711|UID:26060A1B2C"}, status=400)
    assert "strikt getrennt" in err["error"]
    st = post(c, "/api/identify/qr", {"text": "CUST:K-1001|TAG:PT-4711|UID:26060A1B2C"})
    assert st["qr"]["tag"] == "PT-4711" and st["qr"]["known_device"] is None


def test_qr_uid_mismatch_warning(ctx):
    c, *_ = ctx
    open_order(c)
    post(c, "/api/identify/qr", {"text": "CUST:K-1001|TAG:PT-4711|UID:26060FFFFF"})
    st = post(c, "/api/identify/hart")
    assert any("26060FFFFF" in m["text"] for m in st["messages"])


def test_event_stream_sends_initial_state(ctx):
    c, s, wf, _ = ctx
    hub = c.application.config["hub"]
    hub.publish("status", {"x": 1})
    gen = hub.stream()
    first = next(gen)
    assert first.startswith("event: status") and '"x": 1' in first
    gen.close()


def test_sim_endpoints_and_sniffer(ctx):
    c, *_ = ctx
    open_order(c)
    post(c, "/api/identify/hart")
    sn = c.get("/api/sniffer").get_json()
    assert any(e["dir"] == "TX" for e in sn["events"]) and "ocd" in sn
    post(c, "/api/sim/dock", {"docked": True})
    assert c.get("/api/status").get_json()["dock"] is True
