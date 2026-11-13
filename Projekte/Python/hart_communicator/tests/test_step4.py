"""Tests Schritt 4: QR-Scan, Kamera, Ringlicht, Etiketten, Druckerstatus – ohne Hardware."""
import os
import socket
import struct
import sys
import threading
from datetime import date
from pathlib import Path

os.environ["HART_SIM"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import camera_qr as cq
import label_printer as lp


# ============================================================ QR-Format
def test_qr_roundtrip():
    text = cq.build_qr_payload(4711, "PT-4711", "26060a1b2c")
    assert text == "CUST:4711|TAG:PT-4711|UID:26060A1B2C"
    q = cq.parse_qr_payload(text)
    assert (q.customer_id, q.tag, q.uid) == ("4711", "PT-4711", "26060A1B2C")


def test_qr_tolerant_parsing():
    q = cq.parse_qr_payload(" uid: 26060A1B2C | tag : FT 2001 |cust:K-17 ")
    assert (q.customer_id, q.tag, q.uid) == ("K-17", "FT 2001", "26060A1B2C")
    assert cq.parse_qr_payload("CUST:1|TAG:X").uid is None


@pytest.mark.parametrize("text", ["https://www.emerson.com/3051", "TAG:PT-1", "CUST:1|TAG:", "", "CUST:1|TAG:A|xyz"])
def test_qr_foreign_codes_rejected(text):
    assert cq.parse_qr_payload(text) is None


def test_qr_invalid_uid_dropped():
    assert cq.parse_qr_payload("CUST:1|TAG:A|UID:XYZ").uid is None


def test_separator_in_tag_is_escaped():
    assert cq.parse_qr_payload(cq.build_qr_payload(1, "A|B", None)).tag == "A/B"


# ============================================================ Kamera-Dienst
@pytest.fixture
def cam(tmp_path):
    svc = cq.CameraService(simulate=True, photo_dir=tmp_path / "photos", settings_file=tmp_path / "cam.json")
    yield svc
    svc.shutdown()


def test_scan_sim_device_and_duplicate_suppression(cam):
    cam.open()
    first = cam.scan_once()
    assert len(first) == 1 and first[0].identity.tag == "PT-4711"
    assert cam.scan_once() == []                       # gleicher Code sofort danach
    cam.close_view()


def test_light_follows_camera_and_torch(cam):
    assert cam.light.percent == 0
    cam.start_scanning()
    assert cam.light.percent == cam.light_percent
    cam.set_light(25)
    assert cam.light.percent == 25
    cam.stop_scanning()
    assert cam.light.percent == 0
    assert cam.toggle_torch() and cam.light.percent == 100
    cam.capture_photo(order_id="A1", tag="PT-1")       # Foto bei eingeschalteter Taschenlampe
    assert cam.light.percent == 100
    assert not cam.toggle_torch() and cam.light.percent == 0


def test_light_setting_persists(tmp_path):
    a = cq.CameraService(simulate=True, photo_dir=tmp_path, settings_file=tmp_path / "c.json")
    a.set_light(35)
    b = cq.CameraService(simulate=True, photo_dir=tmp_path, settings_file=tmp_path / "c.json")
    assert b.light_percent == 35


def test_photo_with_hash_and_thumbnail(cam):
    import hashlib
    res = cam.capture_photo(order_id="A-2026/001", tag="PT 4711", note="Punkt 50 %")
    p = Path(res["path"])
    assert p.exists() and p.parent.name == "A-2026_001"            # Pfad bereinigt
    assert res["sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert Path(res["thumbnail"]).exists()


def test_mjpeg_stream_frame(cam):
    gen = cam.mjpeg_stream(fps=100)
    chunk = next(gen)
    assert chunk.startswith(b"--frame\r\nContent-Type: image/jpeg") and b"\xff\xd8" in chunk
    gen.close()
    assert cam.status()["active"] is False


# ============================================================ Etiketten
def make_label(**kw):
    base = dict(customer_id=4711, tag="PT-4711", uid="26060A1B2C", passed=True,
                next_due=date(2027, 11, 1), technician="M. Muster", order_no="A-1")
    base.update(kw)
    return lp.LabelData(**base)


def test_label_geometry_and_mode():
    img = lp.LabelRenderer().render(make_label())
    assert img.size == (320, 240) and img.mode == "1"


@pytest.mark.parametrize("kw,head", [({"passed": True}, "BESTANDEN"), ({"passed": False}, "NICHT BESTANDEN"),
                                     ({"kind": "NEUAUFNAHME"}, "NEUAUFNAHME"),
                                     ({"kind": "GERAETETAUSCH"}, "GERÄTETAUSCH")])
def test_headlines(kw, head):
    assert make_label(**kw).headline == head


def test_long_tag_fits():
    r = lp.LabelRenderer()
    img = r.render(make_label(tag="FIC-12345-A/B-LONGTAG"))
    assert img.size == (320, 240)


def test_label_qr_is_scannable():
    cv2 = pytest.importorskip("cv2")
    import numpy as np
    from PIL import Image
    img = lp.LabelRenderer().render(make_label()).convert("L")
    arr = np.array(img.resize((960, 720), Image.NEAREST))
    text, _, _ = cv2.QRCodeDetector().detectAndDecode(arr)
    assert cq.parse_qr_payload(text).uid == "26060A1B2C"


def test_print_saves_png_in_sim(tmp_path):
    svc = lp.PrinterService(simulate=True, label_dir=tmp_path)
    res = svc.print_label(make_label())
    assert res["ok"] and Path(res["png"]).read_bytes()[:4] == b"\x89PNG"


def test_cups_failure_keeps_png(tmp_path):
    class Broken:
        name = "cups"

        def print_png(self, path, copies=1):
            raise lp.PrintError("Warteschlange fehlt")
    svc = lp.PrinterService(simulate=True, label_dir=tmp_path)
    svc.backend = Broken()
    res = svc.print_label(make_label())
    assert not res["ok"] and Path(res["png"]).exists()


def test_lpstat_parsing():
    assert lp.CupsBackend.parse_lpstat("printer SUPVAN_T50M is idle.  enabled since …")["state"] == "ready"
    assert lp.CupsBackend.parse_lpstat("printer SUPVAN_T50M disabled since …")["state"] == "error"
    assert lp.CupsBackend.parse_lpstat("printer SUPVAN_T50M now printing SUPVAN_T50M-12.")["state"] == "busy"


# ============================================================ SUPVAN-Protokoll
def test_command_frame_layout():
    f = lp.build_command(lp.CMD_INQUIRY_STA)
    assert len(f) == 16 and f[:8] == bytes([0x7E, 0x5A, 0x0C, 0x00, 0x10, 0x01, 0xAA, 0x11])
    assert struct.unpack_from("<H", f, 8)[0] == sum(f[10:16])
    f2 = lp.build_command(0x5C, param=512, block_count=3)
    assert f2[12:16] == bytes([0x00, 0x02, 0x03, 0x00])


def status_frame(msta_lo=0, msta_hi=0, fsta_lo=0, fsta_hi=0, count=0):
    body = bytes([0x10, 0x03, 0x55, lp.CMD_INQUIRY_STA, 0, 0, 0, 0, 0, 0,
                  msta_lo, msta_hi, fsta_lo, fsta_hi]) + struct.pack("<H", count) + bytes(6)
    return b"\x7E\x5A" + struct.pack("<H", len(body)) + body


def test_split_response_handles_garbage_and_fragments():
    buf = bytearray(b"\x00\x13" + status_frame()[:9])
    assert lp.split_response(buf) is None
    buf += status_frame()[9:] + b"\x7E"
    frame = lp.split_response(buf)
    assert frame == status_frame() and buf == bytearray(b"\x7E")


def test_parse_status_flags():
    st = lp.parse_status(status_frame(msta_lo=0x04, fsta_lo=0x08 | 0x40, count=17))
    assert st["flags"]["label_end"] and st["flags"]["cover_open"] and st["flags"]["printing"]
    assert "Etiketten aufgebraucht" in st["errors"] and "Deckel offen" in st["errors"]
    assert st["print_count"] == 17


def test_status_client_over_fake_rfcomm():
    a, b = socket.socketpair()

    def printer():
        for reply in (bytes([0x7E, 0x5A, 0x06, 0x00, 0x10, 0x03, 0x55, lp.CMD_CHECK_DEVICE, 0, 0]),
                      status_frame(fsta_hi=0x01)):
            b.recv(16)
            b.sendall(reply)
    t = threading.Thread(target=printer)
    t.start()
    c = lp.SupvanStatusClient(address="00:00:00:00:00:00", timeout=2)
    c._transact(a, lp.CMD_CHECK_DEVICE)
    st = lp.parse_status(c._transact(a, lp.CMD_INQUIRY_STA))
    t.join()
    a.close(), b.close()
    assert st["errors"] == ["Keine Etikettenrolle eingelegt"]


def test_status_client_without_address():
    assert lp.SupvanStatusClient(address="").query()["state"] == "not_configured"
