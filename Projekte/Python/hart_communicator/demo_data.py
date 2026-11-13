"""
demo_data.py – Realistischer Beispielauftrag aus den simulierten Feldgeräten.

Für Entwicklung, Tests, Schulung und PDF-Vorschau:
  python demo_data.py            -> data/demo/hart_kalibrierung.db + Prüfbericht-PDF

Inhalt: 1 Kunde, 1 Auftrag, 4 Messstellen
  PT-4711  Rosemount 3051    – Neuaufnahme, danach GERÄTETAUSCH (neue Unique-ID), bestanden
  FT-2001  Micro Motion 5700 – Neuaufnahme, NICHT bestanden (Analogfehler ~90 µA)
  FV-3001  Fisher DVC6200    – Stellungsregler, Sollwert per Command 40, bestanden
  TT-0042  Rosemount 644     – Neuaufnahme, bestanden, mit Beweisfoto
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("HART_SIM", "1")

import config
from calibration import CAL_POINTS, evaluate_point
from database import CASE_NEW, CASE_RECAL, Database


def _measure(sim_device, meter, modem, ident, pct: float, positioner: bool) -> dict:
    if positioner:
        modem.set_fixed_current(ident, 4.0 + 16.0 * pct / 100.0)
    else:
        sim_device.set_process_percent(pct)
    dyn = modem.read_dynamic_variables(ident)
    true_ma = meter.read().current_ma
    return {"hart_pv": dyn["pv"]["value"], "hart_ma": dyn["loop_current_ma"], "true_ma": true_ma}


def build_demo_order(out_dir: Path | str, with_photos: bool = True) -> tuple[Database, int]:
    from camera_qr import CameraService
    from current_meter import CurrentMeter
    from device_catalog import describe
    from hart_modem import SIM_SCENARIOS, HartModem, SimulatedHartBus

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    db_path = out / "hart_kalibrierung.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)
    db = Database(db_path)
    bus = SimulatedHartBus()
    modem = HartModem(simulate=True, sim_bus=bus, safe_mode=False)
    modem.transport.latency_s = 0
    meter = CurrentMeter(simulate=True, shunt_ohm=3.3, cal_file=None,
                         sim_current_source=lambda: bus.loop_current_ma())
    meter.calibration.calibrated_at = "2026-03-02T09:00:00+00:00"
    meter.calibration.reference = "Fluke 726 (Demo)"
    camera = CameraService(simulate=True, photo_dir=out / "photos", settings_file=None) if with_photos else None
    meter_info = {"name": "INA226 True-mA (Shunt 3,3 Ω)", **meter.calibration.to_dict()}

    cust = db.create_customer("Chemiepark Nord GmbH", "K-1001", "Werkstraße 1, 12345 Musterstadt",
                              "Hr. Beispiel, Betriebstechnik")
    oid = db.open_order(cust, "A-2026-0815", "M. Muster", "Jahresprüfung HART-Messstellen Kolonne K1")
    order_no = "A-2026-0815"

    def run(scenario: str, case: str, existing: int | None = None, photo_point: float | None = None) -> int:
        dev = bus.connect(SIM_SCENARIOS[scenario]())
        info = modem.identify(0)
        ident = info["identity"]
        cat = describe(ident.manufacturer_id, ident.device_type, info["dynamic"]["pv"]["unit_code"])
        rng = info["range"]
        dev_info = {"manufacturer_id": ident.manufacturer_id, "device_type": ident.device_type,
                    "display_name": cat.display_name, "device_class": cat.profile.device_class.value,
                    "is_positioner": cat.profile.is_positioner, "descriptor": info["descriptor"],
                    "lrv": rng["lower_range"], "urv": rng["upper_range"], "unit_code": rng["unit_code"],
                    "unit": rng["unit"], "universal_rev": ident.universal_rev, "software_rev": ident.software_rev,
                    "location": "Kolonne K1"}
        device_id = existing
        if device_id is None:
            match = db.match_device(cust, ident.unique_id, info["tag"])
            if match.case == "GERAETETAUSCH":
                device_id = db.confirm_device_swap(match.swap_token, True, dev_info, oid, "M. Muster")
                case = "GERAETETAUSCH"
            elif match.case == "NACHKALIBRIERUNG":
                device_id = match.device["id"]
            else:
                device_id = db.create_device(cust, info["tag"], ident.unique_id, dev_info, oid, "M. Muster")
        d = db.device(device_id)
        cid = db.start_calibration(oid, device_id, case, "M. Muster", meter_info)
        for pct in CAL_POINTS:
            m = _measure(dev, meter, modem, ident, pct, bool(d["is_positioner"]))
            db.add_point(cid, evaluate_point(pct, lrv=d["lrv"], urv=d["urv"], tolerance_pct=d["tolerance_pct"], **m))
            if camera and photo_point == pct:
                db.add_photo(camera.capture_photo(order_id=order_no, tag=d["tag"], note=f"Punkt {pct:.0f} %"),
                             oid, device_id, cid, pct)
        if d["is_positioner"]:
            modem.exit_fixed_current(ident)
        db.finish_calibration(cid)
        return device_id

    run("rosemount_3051", CASE_NEW)
    run("rosemount_3051_replaced", CASE_RECAL, photo_point=50.0)       # wird als Tausch erkannt
    run("micromotion_5700", CASE_NEW)
    run("fisher_dvc6200", CASE_NEW, photo_point=100.0)
    run("rosemount_644", CASE_NEW, photo_point=0.0)
    db.close_order(oid)
    if camera:
        camera.shutdown()
    return db, oid


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)
    from pdf_generator import generate_order_pdf
    db, oid = build_demo_order(config.DATA_DIR / "demo")
    rep = db.order_report(oid)
    print("Zusammenfassung:", rep["summary"])
    print(generate_order_pdf(rep, config.DATA_DIR / "demo" / "reports"))
