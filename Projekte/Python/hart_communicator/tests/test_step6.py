"""Tests Schritt 6: Auswertung, Prüfbericht-PDF, Exportpaket, USB-Stick, PC-Abbild."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

os.environ["HART_SIM"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import calibration as cal
import dual_usb_export as ux
import pdf_generator as pg


# ------------------------------------------------------------------ Auswertung
def test_evaluate_point_ideal():
    p = cal.evaluate_point(50, lrv=0, urv=2500, tolerance_pct=0.25, hart_pv=1250, hart_ma=12.0, true_ma=12.0)
    assert p["setpoint_value"] == 1250 and p["setpoint_ma"] == 12 and p["passed"] and not p["warnings"]


def test_evaluate_point_reference_value_and_errors():
    p = cal.evaluate_point(50, lrv=0, urv=2500, tolerance_pct=0.25, hart_pv=1255, hart_ma=12.032,
                           true_ma=12.032, reference_value=1252.0)
    assert p["setpoint_value"] == 1252.0
    assert p["error_pv_pct"] == pytest.approx(0.12)
    assert p["error_ma_pct"] == pytest.approx((12.032 - 12.0128) / 16 * 100)
    assert p["passed"]


def test_evaluate_point_fail_and_da_warning():
    p = cal.evaluate_point(100, lrv=0, urv=100, tolerance_pct=0.25, hart_pv=100.0, hart_ma=20.0, true_ma=20.09)
    assert not p["passed"] and any("Digital/Analog" in w for w in p["warnings"])
    assert p["da_mismatch_pct"] == pytest.approx(0.5625)


def test_evaluate_point_negative_range():
    p = cal.evaluate_point(25, lrv=-50, urv=250, tolerance_pct=0.25, hart_pv=25.0, hart_ma=8.0, true_ma=8.0)
    assert p["setpoint_value"] == 25.0 and p["passed"]


def test_evaluate_requires_values():
    with pytest.raises(ValueError):
        cal.evaluate_point(0, lrv=0, urv=1, tolerance_pct=1, hart_pv=None, hart_ma=None, true_ma=None)


# ------------------------------------------------------------------ Demo-Auftrag + PDF
@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    from demo_data import build_demo_order
    out = tmp_path_factory.mktemp("demo")
    db, oid = build_demo_order(out)
    return out, db, oid


def test_demo_report_summary(demo):
    _, db, oid = demo
    s = db.order_report(oid)["summary"]
    assert s == {"calibrations": 4, "passed": 3, "failed": 1, "swaps": 1, "new_devices": 3, "recalibrations": 0}


def test_pdf_structure_and_toc(demo):
    out, db, oid = demo
    res = pg.generate_order_pdf(db.order_report(oid), out / "reports")
    assert res["pages"] == 6                                  # Deckblatt + 4 Geräte + Rückläufer
    assert res["device_pages"] == {"dev1": 2, "dev2": 3, "dev3": 4, "dev4": 5}
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open(res["path"])
    text = [p.get_text() for p in doc]
    assert "Inhaltsverzeichnis" in text[0] and "Seite 1 von 6" in text[0]
    assert "FT-2001" in text[1] and "NICHT BESTANDEN" in text[1]        # alphabetisch: FT vor FV, PT, TT
    assert "Gerätetausch" in text[3] and "26060A1B2C" in text[3]        # Altgerät auf PT-4711-Seite
    assert "SHA-256" in text[2]                                         # Foto auf FV-3001-Seite
    for field in ("Name in Druckbuchstaben", "Datum", "Firmenstempel", "Unterschrift"):
        assert field in text[5]
    assert "FT-2001" in text[5]                                          # nicht bestanden im Rückläufer


def test_pdf_filename_sanitized():
    rep = {"order": {"order_no": "A/2026 01"}, "customer": {"name": "Müller & Co. KG"}}
    assert pg.report_filename(rep) == "Pruefbericht_A_2026_01_M_ller_Co._KG.pdf"


def test_german_number_format():
    assert pg.num(1234.5, 1) == "1234,5" and pg.num(-0.0123, 3, True) == "-0,012" and pg.num(None) == "–"


# ------------------------------------------------------------------ Exportpaket
def test_bundle_manifest_and_db_copy(demo, tmp_path):
    out, db, oid = demo
    pg.generate_order_pdf(db.order_report(oid), out / "reports")
    m = ux.build_bundle(tmp_path / "b", db_path=out / "hart_kalibrierung.db", telemetry_path=tmp_path / "nope.db",
                        report_dir=out / "reports", photo_dir=out / "photos", label_dir=tmp_path / "nolabels")
    files = {f["path"] for f in m["files"]}
    assert {"Kalibrierungen.csv", "LIESMICH.txt", "Auf_Desktop_kopieren.bat", "Datenbank/hart_kalibrierung.db"} <= files
    assert any(f.startswith("Berichte/") and f.endswith(".pdf") for f in files)
    assert (tmp_path / "b" / "Etiketten").is_dir()
    import sqlite3
    copy = sqlite3.connect(tmp_path / "b" / "Datenbank" / "hart_kalibrierung.db")
    assert copy.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert copy.execute("SELECT COUNT(*) FROM calibrations").fetchone()[0] == 5
    bat = (tmp_path / "b" / "Auf_Desktop_kopieren.bat").read_bytes()
    assert b"\r\n" in bat and b"robocopy" in bat
    csv_text = (tmp_path / "b" / "Kalibrierungen.csv").read_text(encoding="utf-8-sig")
    assert csv_text.count("\n") == 6 and ";BESTANDEN;" in csv_text


def test_bundle_does_not_copy_itself(tmp_path):
    src = tmp_path / "reports"
    src.mkdir()
    (src / "a.pdf").write_bytes(b"%PDF")
    m = ux.build_bundle(src / "staging" / "x", db_path=tmp_path / "none.db", telemetry_path=tmp_path / "none.db",
                        report_dir=src, photo_dir=tmp_path / "p", label_dir=tmp_path / "l")
    assert "Berichte/a.pdf" in {f["path"] for f in m["files"]}
    assert not any("staging" in f["path"] for f in m["files"])


# ------------------------------------------------------------------ USB-Stick
LSBLK = {"blockdevices": [
    {"name": "mmcblk0", "path": "/dev/mmcblk0", "tran": None, "fstype": None, "children": [
        {"name": "mmcblk0p2", "path": "/dev/mmcblk0p2", "fstype": "ext4", "mountpoint": "/"}]},
    {"name": "sda", "path": "/dev/sda", "tran": "usb", "rm": True, "fstype": None, "children": [
        {"name": "sda1", "path": "/dev/sda1", "fstype": "vfat", "label": "STICK", "size": "14.9G",
         "mountpoint": None}]},
    {"name": "sdb", "path": "/dev/sdb", "tran": "usb", "fstype": "exfat", "label": None, "size": "58G",
     "mountpoint": "/media/hart/X"}]}


def test_parse_lsblk_only_usb():
    parts = ux.parse_lsblk(LSBLK)
    assert [(p.device, p.label, p.mountpoint) for p in parts] == [
        ("/dev/sda1", "STICK", None), ("/dev/sdb", "USB-STICK", "/media/hart/X")]


def test_stick_export_mount_copy_verify_eject(tmp_path):
    mnt = tmp_path / "media" / "STICK"
    mnt.mkdir(parents=True)
    calls = []

    def runner(cmd, timeout=60):
        calls.append(cmd[:2])
        out = f"Mounted /dev/sda1 at {mnt}." if cmd[:2] == ["udisksctl", "mount"] else ""
        return subprocess.CompletedProcess(cmd, 0, out, "")
    bundle = tmp_path / "20261113_120000"
    ux.build_bundle(bundle, db_path=tmp_path / "n.db", telemetry_path=tmp_path / "n.db",
                    report_dir=tmp_path / "r", photo_dir=tmp_path / "p", label_dir=tmp_path / "l")
    res = ux.UsbStickExporter(runner).export(ux.UsbPartition("/dev/sda1", "STICK", "vfat", "1G", None), bundle)
    assert res["verified"] and (mnt / "HART_EXPORT" / bundle.name / "manifest.json").exists()
    assert (mnt / "HART_EXPORT" / "Auf_Desktop_kopieren.bat").exists()
    assert calls == [["udisksctl", "mount"], ["udisksctl", "unmount"], ["udisksctl", "power-off"]]


# ------------------------------------------------------------------ PC-Abbild
@pytest.mark.skipif(not (shutil.which("mkfs.vfat") and shutil.which("mcopy")), reason="dosfstools/mtools fehlen")
def test_fat_image_contains_bundle(tmp_path):
    bundle = tmp_path / "bundle"
    ux.build_bundle(bundle, db_path=tmp_path / "n.db", telemetry_path=tmp_path / "n.db",
                    report_dir=tmp_path / "r", photo_dir=tmp_path / "p", label_dir=tmp_path / "l")
    g = ux.GadgetExporter(image=tmp_path / "x.img", simulate=True)
    g.build_image(bundle, size_mb=64)
    listing = subprocess.run(["mdir", "-b", "-i", str(tmp_path / "x.img"), "::/"], capture_output=True, text=True)
    assert "manifest.json" in listing.stdout and "Auf_Desktop_kopieren.bat" in listing.stdout
    label = subprocess.run(["mlabel", "-s", "-i", str(tmp_path / "x.img"), "::"], capture_output=True, text=True)
    assert "HART_EXPORT" in label.stdout
    g.publish()
    with pytest.raises(ux.ExportError, match="angeboten"):
        g.build_image(bundle, size_mb=64)                    # Abbild nie während des Anbietens ändern


def test_gadget_publish_command_is_read_only(tmp_path):
    calls = []
    runner = lambda cmd, timeout=60: (calls.append(cmd), subprocess.CompletedProcess(cmd, 0, "", ""))[1]
    img = tmp_path / "x.img"
    img.write_bytes(b"\0")
    g = ux.GadgetExporter(image=img, runner=runner)
    g.publish(wait_s=0)
    load = [c for c in calls if "g_mass_storage" in c and "-r" not in c][0]
    assert "ro=1" in load and "removable=1" in load and f"file={img}" in load
    g.unpublish()
    assert calls[-1][-2:] == ["-r", "g_mass_storage"] and not g.published


def test_dock_triggers_publish_and_undock_unpublishes(tmp_path):
    svc = ux.ExportService(simulate=True, staging_dir=tmp_path / "st", auto_publish_on_dock=False,
                           sources={"db_path": tmp_path / "n.db", "telemetry_path": tmp_path / "n.db",
                                    "report_dir": tmp_path / "r", "photo_dir": tmp_path / "p",
                                    "label_dir": tmp_path / "l"})
    events = []
    svc.subscribe(lambda e: events.append(e["event"]))
    svc.dock.simulate(True)
    assert svc.dock.docked and events == ["dock"]
    svc.gadget.published = True
    svc.dock.simulate(False)
    assert not svc.gadget.published and events == ["dock", "dock", "unpublished"]
