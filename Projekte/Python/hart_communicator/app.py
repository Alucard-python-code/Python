"""
app.py – Einstiegspunkt: startet alle Dienste und die Web-Oberfläche (Kiosk-Browser).

  python app.py              -> http://127.0.0.1:8080  (Hardware, sonst automatisch Simulation)
  HART_SIM=1 python app.py   -> komplette Simulation am Entwicklungs-PC

Architektur:
  Services     – alle Hardware-/Datendienste (ein Objekt, beim Start einmal aufgebaut)
  Workflow     – Arbeitsablauf an der Messstelle (workflow.py)
  REST /api/*  – Aktionen der Oberfläche (JSON)
  SSE /api/events – Live-Ereignisse an die Oberfläche (Statusleiste, Messwerte, Sniffer …).
                 Server-Sent Events statt WebSocket: im Browser eingebaut, keine
                 Client-Bibliothek nötig – wichtig für den Betrieb ohne Internet.

Der Server lauscht nur auf 127.0.0.1 (lokaler Kiosk). Für Fernzugriff im Dock bewusst
WEB_HOST setzen – es gibt keine Benutzeranmeldung.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from flask import Flask, Response, jsonify, render_template, request, send_from_directory

import config
from hw_compat import simulation_requested

log = logging.getLogger("app")
APP_VERSION = "1.0"


# =============================================================================
# Dienste
# =============================================================================
@dataclass
class Services:
    config: Any
    rtc: Any
    db: Any
    telemetry: Any
    bms: Any
    power: Any
    meter: Any
    loop: Any
    modem: Any
    feedback: Any
    rotation: Any
    inputs: Any
    camera: Any
    printer: Any
    export: Any
    simulated: bool = False
    stop_hooks: list[Callable[[], None]] = field(default_factory=list)


def build_services(simulate: Optional[bool] = None, data_dir: Optional[Path] = None) -> Services:
    """Baut alle Dienste auf. Jede Komponente fällt einzeln auf ihre Simulation zurück."""
    from battery_bms import BatteryMonitor, PowerLatch
    from camera_qr import CameraService
    from current_meter import CurrentMeter, SHUNT_FULLSCALE_V
    from database import Database
    from dual_usb_export import ExportService
    from feedback_manager import FeedbackManager
    from hart_modem import HartModem
    from input_monitor import InputMonitor
    from label_printer import PrinterService
    from loop_relays import LoopController
    from rotation_daemon import RotationDaemon
    from rtc_manager import RtcManager
    from telemetry_logger import TelemetryLogger

    if simulate:
        os.environ["HART_SIM"] = "1"
    sim = simulation_requested("app") if simulate is None else simulate
    d = Path(data_dir or config.DATA_DIR)
    d.mkdir(parents=True, exist_ok=True)

    rtc = RtcManager(simulate=simulate)
    rtc.boot_sync()
    db = Database(d / config.DB_PATH.name, clock=rtc.timestamp)
    export = ExportService(simulate=simulate, staging_dir=d / "export_staging",
                           sources={"db_path": d / config.DB_PATH.name,
                                    "telemetry_path": d / config.TELEMETRY_DB_PATH.name,
                                    "report_dir": d / "reports", "photo_dir": d / "photos",
                                    "label_dir": d / "labels"})
    export.gadget.image = d / config.Export.IMAGE_FILE.name

    def sim_battery_current() -> float:
        import random
        return 1.5 if export.dock.docked else -0.35 + random.gauss(0, 0.03)

    bms = BatteryMonitor(simulate=simulate, state_file=d / config.BMS_STATE_FILE.name,
                         sim_current_provider=sim_battery_current)
    modem = HartModem(simulate=simulate)
    shunt = config.CurrentMeter.SHUNT_OHM
    meter_probe = CurrentMeter(simulate=simulate, cal_file=d / config.CurrentMeter.CAL_FILE.name)
    if meter_probe.simulated and SHUNT_FULLSCALE_V / shunt * 1000 < config.CurrentMeter.MAX_EXPECTED_MA:
        log.warning("Simulation: True-mA mit 3,3-Ω-Shunt statt %.1f Ω, damit 4–20 mA messbar sind", shunt)
        meter_probe = CurrentMeter(simulate=True, shunt_ohm=3.3, cal_file=d / config.CurrentMeter.CAL_FILE.name)
    meter = meter_probe
    loop = LoopController(voltage_probe=lambda: meter.read().terminal_voltage_v,
                          sim_meter=meter.io if meter.simulated else None)
    telemetry = TelemetryLogger(d / config.TELEMETRY_DB_PATH.name, clock=rtc.timestamp,
                                battery_provider=lambda: bms.latest().to_telemetry() if bms.latest() else None,
                                docked_provider=lambda: export.dock.docked,
                                hart_seconds_provider=lambda: modem.active_seconds)
    s = Services(
        config=config, rtc=rtc, db=db, telemetry=telemetry, bms=bms, power=PowerLatch(simulate=simulate),
        meter=meter, loop=loop, modem=modem,
        feedback=FeedbackManager(simulate=simulate, sound_dir=d / "sounds",
                                 settings_file=d / config.FEEDBACK_SETTINGS_FILE.name),
        rotation=RotationDaemon(simulate=simulate, state_file=d / config.Display.STATE_FILE.name),
        inputs=InputMonitor(simulate=simulate),
        camera=CameraService(simulate=simulate, photo_dir=d / "photos",
                             settings_file=d / config.Camera.SETTINGS_FILE.name),
        printer=PrinterService(simulate=simulate, label_dir=d / "labels"),
        export=export, simulated=sim)
    return s


def start_services(s: Services) -> None:
    from telemetry_logger import EV_BATTERY, EV_DOCK, EV_LOOP_MODE, EV_SAFE_MODE, EV_UNDOCK
    s.telemetry.start()
    s.bms.start()
    s.meter.start()
    s.loop.start()
    s.rotation.start()
    s.inputs.start()
    s.printer.start()
    s.export.start()
    s.rtc.start()
    s.rotation.set_docked(s.export.dock.docked)
    s.export.dock.subscribe(s.rotation.set_docked)
    s.export.dock.subscribe(lambda docked: s.telemetry.event(EV_DOCK if docked else EV_UNDOCK,
                                                             "Angedockt" if docked else "Abgedockt"))
    s.modem.add_safe_mode_listener(lambda on, src: s.telemetry.event(
        EV_SAFE_MODE, f"24/7-Safe-Mode {'aktiviert' if on else 'DEAKTIVIERT'} ({src})",
        severity="INFO" if on else "WARN"))
    s.loop.add_listener(lambda mode, reason: s.telemetry.event(EV_LOOP_MODE, f"Schleife: {mode.label} ({reason})"))

    def critical(reason: str) -> None:
        s.feedback.notify("battery_critical")
        s.telemetry.event(EV_BATTERY, reason, severity="ERROR")
        s.power.shutdown(reason)
    s.bms.on_critical(critical)
    s.bms.on_fault(lambda faults: s.telemetry.event(EV_BATTERY, ", ".join(faults), severity="ERROR"))


def stop_services(s: Services, reason: str = "Programmende") -> None:
    for hook in s.stop_hooks:
        try:
            hook()
        except Exception:
            log.exception("Stop-Hook")
    for name, fn in (("loop", lambda: s.loop.close()), ("inputs", s.inputs.stop), ("rotation", s.rotation.stop),
                     ("camera", s.camera.shutdown), ("export", s.export.stop), ("printer", s.printer.stop),
                     ("meter", s.meter.stop), ("bms", s.bms.stop), ("feedback", s.feedback.close),
                     ("telemetry", lambda: s.telemetry.stop(reason)), ("modem", s.modem.close)):
        try:
            fn()
        except Exception:
            log.exception("Stoppen von %s", name)


# =============================================================================
# Ereignisverteilung (Server-Sent Events)
# =============================================================================
class EventHub:
    def __init__(self):
        self._clients: list[queue.Queue] = []
        self._lock = threading.Lock()
        self.last: dict[str, Any] = {}        # letzter Stand je Ereignistyp (für neue Clients)

    def publish(self, event: str, data: Any) -> None:
        self.last[event] = data
        msg = f"event: {event}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n"
        with self._lock:
            for q in list(self._clients):
                try:
                    q.put_nowait(msg)
                except queue.Full:            # langsamer Client -> verwerfen statt blockieren
                    pass

    def stream(self):
        q: queue.Queue = queue.Queue(maxsize=300)
        with self._lock:
            self._clients.append(q)
        try:
            for ev, data in list(self.last.items()):
                yield f"event: {ev}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n"
            while True:
                try:
                    yield q.get(timeout=15)
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with self._lock:
                self._clients.remove(q)


# =============================================================================
# Flask-App
# =============================================================================
def create_app(services: Optional[Services] = None, *, start: bool = True,
               background: bool = True) -> Flask:
    from current_meter import OverrangeError
    from database import DatabaseError
    from dual_usb_export import ExportError
    from hart_modem import SIM_BUS, SIM_SCENARIOS, HartError, SafeModeError
    from loop_relays import InterlockError, LoopMode
    from pdf_generator import generate_order_pdf
    from telemetry_logger import EV_ORDER_END, EV_ORDER_START, EV_TIME_SET, EV_EXPORT
    from workflow import Workflow, WorkflowError

    s = services or build_services()
    if start:
        start_services(s)
    wf = Workflow(s)
    hub = EventHub()
    s.stop_hooks.append(wf.shutdown)
    s.power.add_shutdown_hook(lambda reason: (wf.shutdown(), s.feedback.notify("shutdown")))

    app = Flask(__name__, template_folder=str(config.BASE_DIR / "templates"),
                static_folder=str(config.BASE_DIR / "static"))
    app.config["services"] = s
    app.config["workflow"] = wf
    app.config["hub"] = hub
    app.json.ensure_ascii = False

    # ---------------------------------------------------------------- Fehlerbehandlung
    @app.errorhandler(WorkflowError)
    @app.errorhandler(DatabaseError)
    @app.errorhandler(SafeModeError)
    @app.errorhandler(InterlockError)
    @app.errorhandler(ExportError)
    @app.errorhandler(OverrangeError)
    def user_error(exc):
        if isinstance(exc, SafeModeError):
            s.feedback.notify("safe_mode_block")
        else:
            s.feedback.notify("error")
        return jsonify(error=str(exc)), 400

    @app.errorhandler(HartError)
    def hart_error(exc):
        s.feedback.notify("error")
        return jsonify(error=f"HART: {exc}"), 502

    def body() -> dict:
        return request.get_json(silent=True) or {}

    def wf_state():
        st = wf.public()
        hub.publish("workflow", st)
        return jsonify(st)

    # ---------------------------------------------------------------- Status
    def header_status() -> dict:
        bat = s.bms.latest()
        st = s.telemetry.stats()
        inp = s.inputs.status()
        order = s.db.get_open_order()
        ts = s.rtc.timestamp()
        return {
            "time": ts["local"], "time_source": ts["source"], "time_trusted": ts["trusted"],
            "battery": None if bat is None else {"soc": round(bat.soc_percent, 1), "voltage": round(bat.pack_voltage_v, 2),
                                                 "current": round(bat.current_a, 3), "charging": bat.charging,
                                                 "level": bat.level, "drift_mv": round(bat.cell_drift_mv, 1),
                                                 "minutes_remaining": bat.minutes_remaining},
            "runtime_hours": st["total_hours"],
            "safe_mode": s.modem.safe_mode,
            "touch_blocked": inp["touch_blocked"], "touch_block_reasons": inp["touch_block_reasons"],
            "osk_enabled": inp["osk_enabled"], "keyboard_navigation": inp["keyboard_navigation"],
            "printer": s.printer.status(), "dock": s.export.dock.docked,
            "export": {"pc_published": s.export.gadget.published},
            "rotation": s.rotation.status(), "loop": s.loop.status(), "torch": s.camera.torch,
            "order": None if not order else {"id": order["id"], "order_no": order["order_no"],
                                             "customer": order["customer_name"]},
            "simulated": s.simulated, "hart_simulated": s.modem.simulated,
        }

    @app.get("/")
    def index():
        return render_template("index.html", theme=config.Theme, version=APP_VERSION, simulated=s.simulated)

    @app.get("/api/status")
    def api_status():
        return jsonify(header_status())

    @app.get("/api/events")
    def api_events():
        return Response(hub.stream(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/battery")
    def api_battery():
        bat = s.bms.latest()
        return jsonify(bat.to_dict() if bat else {})

    @app.get("/api/stats")
    def api_stats():
        return jsonify({**s.telemetry.stats(), "events": s.telemetry.events(30),
                        "meter": s.meter.status(), "rtc": s.rtc.status()})

    # ---------------------------------------------------------------- Kunden & Aufträge
    @app.get("/api/customers")
    def api_customers():
        return jsonify(s.db.customers(request.args.get("q", "")))

    @app.post("/api/customers")
    def api_customer_create():
        b = body()
        cid = s.db.create_customer(b.get("name", ""), b.get("customer_no") or None, b.get("address", ""),
                                   b.get("contact", ""))
        return jsonify(s.db.customer(cid))

    @app.get("/api/order")
    def api_order():
        o = s.db.get_open_order()
        if not o:
            return jsonify(None)
        rep = s.db.order_report(o["id"])
        return jsonify({**o, "summary": rep["summary"],
                        "entries": [{"tag": e["device"]["tag"], "name": e["device"]["display_name"],
                                     "result": e["calibration"]["result"], "case": e["calibration"]["case_type"]}
                                    for e in rep["entries"]],
                        "devices": s.db.devices(o["customer_id"])})

    @app.post("/api/order")
    def api_order_open():
        b = body()
        oid = s.db.open_order(int(b.get("customer_id") or 0), b.get("order_no", ""), b.get("technician", ""),
                              b.get("description", ""))
        o = s.db.order(oid)
        s.telemetry.event(EV_ORDER_START, f"Auftrag {o['order_no']} geöffnet ({o['customer_name']})",
                          order_no=o["order_no"])
        wf.reset()
        hub.publish("workflow", wf.public())
        hub.publish("status", header_status())
        return api_order()

    @app.post("/api/order/close")
    def api_order_close():
        o = s.db.get_open_order()
        if not o:
            raise WorkflowError("Kein offener Auftrag")
        if wf.stage == "calibrating":
            raise WorkflowError("Kalibrierung läuft – erst abschließen oder abbrechen")
        closed = s.db.close_order(o["id"])
        pdf = generate_order_pdf(s.db.order_report(o["id"]), Path(s.db.path).parent / "reports")
        s.db.set_order_pdf(o["id"], pdf["path"])
        rep = s.db.order_report(o["id"])["summary"]
        s.telemetry.event(EV_ORDER_END, f"Auftrag {o['order_no']} abgeschlossen", order_no=o["order_no"],
                          duration_sec=closed["closed_at"] - closed["opened_at"], **rep)
        s.feedback.notify("success")
        wf.reset()
        hub.publish("workflow", wf.public())
        hub.publish("status", header_status())
        return jsonify({"order": s.db.order(o["id"]), "pdf": {**pdf, "url": f"/reports/{Path(pdf['path']).name}"}})

    @app.get("/api/orders")
    def api_orders():
        return jsonify([{**o, "pdf_url": f"/reports/{Path(o['pdf_path']).name}" if o.get("pdf_path") else None}
                        for o in s.db.orders()])

    @app.get("/reports/<path:name>")
    def reports(name):
        return send_from_directory(Path(s.db.path).parent / "reports", name)

    # ---------------------------------------------------------------- Betriebsarten
    @app.post("/api/safe_mode")
    def api_safe_mode():
        b = body()
        enable = bool(b.get("enabled", True))
        if not enable and not b.get("confirmed"):
            raise WorkflowError("Deaktivieren des Safe-Mode muss bestätigt werden")
        s.modem.set_safe_mode(enable, source="Bedienung")
        hub.publish("status", header_status())
        return jsonify({"safe_mode": s.modem.safe_mode})

    @app.post("/api/loop_mode")
    def api_loop_mode():
        b = body()
        dev_pos = wf.public().get("is_positioner", False)
        s.loop.set_mode(LoopMode(b.get("mode", "PASSIVE")), confirmed=bool(b.get("confirmed")),
                        is_positioner=dev_pos, reason="Bedienung")
        hub.publish("status", header_status())
        return jsonify(s.loop.status())

    @app.post("/api/rotation/lock")
    def api_rotation_lock():
        return jsonify(s.rotation.toggle_lock())

    @app.post("/api/torch")
    def api_torch():
        return jsonify({"torch": s.camera.toggle_torch()})

    @app.post("/api/settings/feedback")
    def api_feedback_settings():
        st = s.feedback.update_settings(**body())
        s.feedback.test()
        return jsonify(st.__dict__)

    @app.post("/api/settings/block_touch_with_mouse")
    def api_block_touch():
        return jsonify(s.inputs.set_block_touch_with_mouse(bool(body().get("enabled", True))))

    @app.post("/api/time")
    def api_time():
        b = body()
        try:
            local = datetime.fromisoformat(b["local"])
        except (KeyError, ValueError) as exc:
            raise WorkflowError("Ungültiges Datum/Uhrzeit") from exc
        o = s.db.get_open_order()
        res = s.rtc.set_time_manual(local, technician=o["technician"] if o else "")
        s.telemetry.event(EV_TIME_SET, f"Uhrzeit manuell gestellt: {res['new_utc']}", severity="WARN", **res)
        return jsonify(res)

    @app.post("/api/shutdown")
    def api_shutdown():
        if not body().get("confirmed"):
            raise WorkflowError("Herunterfahren bestätigen")
        threading.Thread(target=s.power.shutdown, args=("Bedienung",), daemon=True).start()
        return jsonify({"ok": True})

    # ---------------------------------------------------------------- Workflow
    @app.get("/api/workflow")
    def api_workflow():
        return jsonify(wf.public())

    @app.post("/api/identify/hart")
    def api_identify_hart():
        wf.identify_hart(int(body().get("poll_address", 0)))
        return wf_state()

    @app.post("/api/identify/qr")
    def api_identify_qr():
        wf.identify_qr(body().get("text", ""))
        return wf_state()

    @app.post("/api/swap/confirm")
    def api_swap_confirm():
        wf.confirm_swap(int(body().get("step", 0)))
        return wf_state()

    @app.post("/api/device/register")
    def api_register():
        b = body()
        f = lambda k: None if b.get(k) in (None, "") else float(str(b[k]).replace(",", "."))
        wf.register_new(tag=b.get("tag", ""), descriptor=b.get("descriptor", ""), lrv=f("lrv"), urv=f("urv"),
                        unit_code=int(b["unit_code"]) if b.get("unit_code") not in (None, "") else None,
                        tolerance_pct=f("tolerance_pct") or 0.25, location=b.get("location", ""),
                        write_to_device=bool(b.get("write_to_device")))
        return wf_state()

    @app.post("/api/calibration/start")
    def api_cal_start():
        wf.start_calibration()
        return wf_state()

    @app.post("/api/calibration/setpoint")
    def api_cal_setpoint():
        res = wf.apply_setpoint(float(body().get("pct", 0)))
        hub.publish("workflow", wf.public())
        return jsonify(res)

    @app.post("/api/calibration/measure")
    def api_cal_measure():
        b = body()
        ref = b.get("reference_value")
        ref = None if ref in (None, "") else float(str(ref).replace(",", "."))
        point = wf.measure_point(float(b.get("pct", 0)), ref)
        hub.publish("workflow", wf.public())
        return jsonify(point)

    @app.post("/api/calibration/photo")
    def api_cal_photo():
        b = body()
        pct = b.get("pct")
        photo = wf.attach_photo(None if pct in (None, "") else float(pct), b.get("note", ""))
        hub.publish("workflow", wf.public())
        return jsonify(photo)

    @app.post("/api/calibration/finish")
    def api_cal_finish():
        wf.finish(body().get("notes", ""))
        return wf_state()

    @app.post("/api/calibration/abort")
    def api_cal_abort():
        wf.abort()
        return wf_state()

    @app.post("/api/workflow/reset")
    def api_wf_reset():
        if wf.stage == "calibrating":
            raise WorkflowError("Kalibrierung läuft – erst abschließen oder abbrechen")
        wf.reset()
        return wf_state()

    # ---------------------------------------------------------------- Etikett
    @app.get("/api/label/preview.png")
    def api_label_preview():
        return Response(s.printer.preview_png(wf.label_data()), mimetype="image/png",
                        headers={"Cache-Control": "no-store"})

    @app.post("/api/label/print")
    def api_label_print():
        return jsonify(wf.print_label(int(body().get("copies", 1))))

    # ---------------------------------------------------------------- Kamera
    @app.get("/camera/stream")
    def camera_stream():
        return Response(s.camera.mjpeg_stream(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.post("/api/camera/scan")
    def api_camera_scan():
        if body().get("active", True):
            s.camera.start_scanning()
        else:
            s.camera.stop_scanning()
        return jsonify(s.camera.status())

    @app.post("/api/camera/light")
    def api_camera_light():
        return jsonify({"light_percent": s.camera.set_light(float(body().get("percent", 60)))})

    def on_scan(res):
        hub.publish("qr", res.to_dict())
        if res.identity:
            try:
                wf.identify_qr(res.text)
                hub.publish("workflow", wf.public())
            except WorkflowError as exc:
                hub.publish("toast", {"level": "error", "text": str(exc)})
    s.camera.on_scan(on_scan)

    # ---------------------------------------------------------------- Sniffer
    @app.get("/api/sniffer")
    def api_sniffer():
        return jsonify({"events": s.modem.sniffer.snapshot(int(request.args.get("n", 200))),
                        "ocd": s.modem.ocd_level()})

    @app.post("/api/sniffer/clear")
    def api_sniffer_clear():
        s.modem.sniffer.clear()
        return jsonify({"ok": True})

    s.modem.sniffer.subscribe(lambda ev: hub.publish("sniffer", ev.to_dict()))

    # ---------------------------------------------------------------- Export
    @app.get("/api/export")
    def api_export_status():
        return jsonify(s.export.status())

    @app.post("/api/export/stick")
    def api_export_stick():
        res = s.export.export_to_stick(body().get("device"))
        s.telemetry.event(EV_EXPORT, f"Export auf USB-Stick ({res['files']} Dateien)")
        return jsonify(res)

    @app.post("/api/export/pc")
    def api_export_pc():
        res = s.export.publish_to_pc()
        s.telemetry.event(EV_EXPORT, f"Export als Laufwerk HART_EXPORT ({res['files']} Dateien)")
        return jsonify(res)

    @app.post("/api/export/unpublish")
    def api_export_unpublish():
        s.export.unpublish()
        return jsonify(s.export.status())

    s.export.subscribe(lambda e: hub.publish("export", {k: v for k, v in e.items() if k != "status"}))

    # ---------------------------------------------------------------- Simulation (nur Entwicklung)
    @app.get("/api/sim/scenarios")
    def api_sim_scenarios():
        return jsonify({"enabled": s.modem.simulated, "scenarios": list(SIM_SCENARIOS),
                        "active": getattr(SIM_BUS.active_device(), "tag", None)})

    @app.post("/api/sim/<action>")
    def api_sim(action):
        if not s.simulated:
            return jsonify(error="Nur im Simulationsmodus"), 403
        b = body()
        if action == "device":
            name = b.get("scenario")
            if name in SIM_SCENARIOS:
                SIM_BUS.connect(SIM_SCENARIOS[name]())
            else:
                SIM_BUS.disconnect_all()
        elif action == "process":
            dev = SIM_BUS.active_device()
            if dev:
                dev.set_process_percent(float(b.get("pct", 0)))
        elif action == "dock":
            s.export.dock.simulate(bool(b.get("docked")))
        elif action == "touchlock":
            s.inputs.simulate_touch_lock(bool(b.get("locked")))
        elif action == "input":
            s.inputs.simulate_device(b.get("name", "Sim-Gerät"), b.get("kind", "keyboard"),
                                     bool(b.get("connected", True)))
        elif action == "rotate":
            s.rotation.sensor.set_orientation(int(b.get("deg", 0)))
        else:
            return jsonify(error="Unbekannte Aktion"), 404
        hub.publish("status", header_status())
        return jsonify({"ok": True})

    # ---------------------------------------------------------------- Live-Ereignisse
    s.bms.subscribe(lambda st: hub.publish("battery", {"soc": round(st.soc_percent, 1),
                                                       "voltage": round(st.pack_voltage_v, 2),
                                                       "level": st.level, "charging": st.charging}))
    s.inputs.subscribe(lambda st: hub.publish("input", st))
    s.rotation.subscribe(lambda st: hub.publish("rotation", st))
    s.printer.subscribe(lambda st: hub.publish("printer", st))

    if background:
        def status_loop():
            n = 0
            while True:
                try:
                    if n % 5 == 0:
                        hub.publish("status", header_status())
                    live = wf.live()
                    if live is not None:
                        hub.publish("live", live)
                except Exception:
                    log.exception("Status-Schleife")
                n += 1
                time.sleep(1.0)
        threading.Thread(target=status_loop, name="ui-status", daemon=True).start()
    return app


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    services = build_services()
    app = create_app(services)
    log.info("HART-Communicator %s gestartet (%s) – http://%s:%s", APP_VERSION,
             "SIMULATION" if services.simulated else "Hardware", config.WEB_HOST, config.WEB_PORT)
    try:
        # Werkzeug-Server mit Threads: ausreichend für den lokalen Kiosk-Browser (1 Client)
        app.run(host=config.WEB_HOST, port=config.WEB_PORT, threaded=True, use_reloader=False)
    finally:
        stop_services(services)


if __name__ == "__main__":
    main()
