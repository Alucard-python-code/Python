"""
camera_qr.py – Rückkamera: QR-Scan von Typenschildern, Beweisfotos, LED-Ringlicht.

* QR-Format der Prüfplaketten: CUST:<id>|TAG:<tag>|UID:<uid>
  (identisch mit label_printer.make_qr_payload -> gedruckte Etiketten sind scanbar)
* Kamera: picamera2 mit zwei Streams – "main" für die Live-Vorschau / Fotos,
  "lores" (Graustufen) für die QR-Erkennung mit geringer CPU-Last
* Decoder: pyzbar (libzbar0), sonst OpenCV-QRCodeDetector
* Ringlicht/Taschenlampe an GPIO13 (Hardware-PWM, 20 kHz gegen Bildstreifen),
  geht beim Öffnen der Kamera automatisch an, Helligkeit einstellbar (Metallreflexe!)
* Beweisfotos mit SHA-256-Prüfsumme (Manipulationsnachweis im Prüfprotokoll)
* Simulation: virtuelles Typenschild des aktuell simulierten HART-Geräts
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional

import config
from hw_compat import simulation_requested

log = logging.getLogger(__name__)
CAM = config.Camera

# =============================================================================
# QR-Inhalt
# =============================================================================
_QR_FIELD = re.compile(r"\s*([A-Za-z]+)\s*:\s*([^|]*)")
_UID_RE = re.compile(r"^[0-9A-F]{10}$")


@dataclass
class QrIdentity:
    customer_id: str
    tag: str
    uid: Optional[str]
    raw: str

    def to_dict(self) -> dict:
        return asdict(self)


def build_qr_payload(customer_id: str | int, tag: str, uid: Optional[str]) -> str:
    """Erzeugt den QR-Inhalt einer Prüfplakette. '|' ist Trennzeichen und wird ersetzt."""
    clean = lambda s: str(s).replace("|", "/").strip()
    parts = [f"CUST:{clean(customer_id)}", f"TAG:{clean(tag)}"]
    if uid:
        parts.append(f"UID:{clean(uid).upper()}")
    return "|".join(parts)


def parse_qr_payload(text: str) -> Optional[QrIdentity]:
    """Tolerant: Reihenfolge, Leerzeichen und Groß/Klein der Schlüssel sind egal.
    Liefert None, wenn es kein Prüfplaketten-Code ist (z.B. Hersteller-URL)."""
    fields = {}
    for part in text.strip().split("|"):
        m = _QR_FIELD.fullmatch(part)
        if not m:
            return None
        fields[m.group(1).upper()] = m.group(2).strip()
    if "CUST" not in fields or not fields.get("TAG"):
        return None
    uid = fields.get("UID", "").upper() or None
    if uid and not _UID_RE.match(uid):
        log.warning("QR-Code mit ungültiger UID '%s' – UID wird ignoriert", uid)
        uid = None
    return QrIdentity(fields["CUST"], fields["TAG"], uid, text)


@dataclass
class ScanResult:
    timestamp: float
    text: str
    identity: Optional[QrIdentity]

    def to_dict(self) -> dict:
        return {"timestamp": self.timestamp, "text": self.text,
                "identity": self.identity.to_dict() if self.identity else None,
                "is_plaque": self.identity is not None}


# =============================================================================
# Ringlicht (PWM GPIO13)
# =============================================================================
class CameraLight:
    def __init__(self, simulate: Optional[bool] = None):
        self._pwm = None
        self._sw = None
        self.percent = 0.0
        self.simulated = simulation_requested("light") if simulate is None else simulate
        if not self.simulated:
            try:
                from rpi_hardware_pwm import HardwarePWM
                self._pwm = HardwarePWM(pwm_channel=CAM.LIGHT_PWM_CHANNEL, hz=CAM.LIGHT_PWM_HZ)
                self._pwm.start(0)
            except Exception as exc:
                log.warning("Hardware-PWM nicht verfügbar (%s) – Software-PWM (evtl. Bildstreifen)", exc)
                try:
                    from gpiozero import PWMLED
                    self._sw = PWMLED(config.Pins.CAMERA_LIGHT_PWM, frequency=1000)
                except Exception as exc2:
                    log.error("Ringlicht nicht ansteuerbar: %s", exc2)
                    self.simulated = True

    @property
    def on(self) -> bool:
        return self.percent > 0

    def set(self, percent: float) -> float:
        self.percent = max(0.0, min(100.0, float(percent)))
        if self._pwm is not None:
            self._pwm.change_duty_cycle(self.percent)
        elif self._sw is not None:
            self._sw.value = self.percent / 100.0
        return self.percent

    def off(self) -> None:
        self.set(0)

    def close(self) -> None:
        self.off()
        if self._pwm is not None:
            self._pwm.stop()
        if self._sw is not None:
            self._sw.close()


# =============================================================================
# Decoder
# =============================================================================
class QrDecoder:
    def __init__(self):
        self.backend = "none"
        self._zbar = None
        self._cv = None
        try:
            from pyzbar import pyzbar
            self._zbar = pyzbar
            self.backend = "pyzbar"
        except Exception:
            try:
                import cv2
                self._cv = cv2.QRCodeDetector()
                self.backend = "opencv"
            except Exception:
                log.warning("Weder pyzbar noch OpenCV verfügbar – QR-Erkennung nur in der Simulation")

    def decode(self, image) -> list[str]:
        """image: PIL.Image (Graustufen/RGB) oder numpy-Array."""
        info = getattr(image, "info", None)
        if isinstance(info, dict) and "sim_qr" in info and self.backend == "none":
            return [info["sim_qr"]]                       # Simulation ohne Decoder
        if self._zbar is not None:
            from pyzbar.pyzbar import ZBarSymbol
            return [r.data.decode("utf-8", "replace")
                    for r in self._zbar.decode(image, symbols=[ZBarSymbol.QRCODE])]
        if self._cv is not None:
            import numpy as np
            arr = np.asarray(image)
            text, _, _ = self._cv.detectAndDecode(arr)
            return [text] if text else []
        return []


# =============================================================================
# Kameras
# =============================================================================
class Picamera2Camera:
    simulated = False

    def __init__(self):
        from picamera2 import Picamera2
        self.cam = Picamera2()
        self.preview_cfg = self.cam.create_video_configuration(
            main={"size": CAM.PREVIEW_SIZE, "format": "RGB888"},
            lores={"size": CAM.DECODE_SIZE, "format": "YUV420"})
        self.still_cfg = self.cam.create_still_configuration()
        self.running = False

    def start(self) -> None:
        if self.running:
            return
        self.cam.configure(self.preview_cfg)
        self.cam.start()
        try:   # Camera Module 3: Dauer-Autofokus (Typenschilder aus 10–30 cm)
            self.cam.set_controls({"AfMode": 2})
        except Exception:
            pass
        self.running = True

    def stop(self) -> None:
        if self.running:
            self.cam.stop()
            self.running = False

    def decode_frame(self):
        from PIL import Image
        yuv = self.cam.capture_array("lores")
        w, h = CAM.DECODE_SIZE
        return Image.frombuffer("L", (w, h), yuv[:h].tobytes(), "raw", "L", 0, 1)

    def preview_jpeg(self) -> bytes:
        from PIL import Image
        img = Image.fromarray(self.cam.capture_array("main")[..., ::-1])   # BGR -> RGB
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=70)
        return buf.getvalue()

    def capture_still(self, path: Path) -> None:
        self.cam.switch_mode_and_capture_file(self.still_cfg, str(path))

    def close(self) -> None:
        self.stop()
        self.cam.close()


class SimulatedCamera:
    """Zeigt ein virtuelles Typenschild mit QR-Code des simulierten HART-Geräts."""
    simulated = True

    def __init__(self):
        self.running = False
        self.qr_text: Optional[str] = None      # None = aus dem SIM_BUS ableiten
        self.show_qr = True

    def _current_text(self) -> str:
        if self.qr_text:
            return self.qr_text
        from hart_modem import SIM_BUS
        dev = SIM_BUS.active_device()
        if dev is None:
            return build_qr_payload("SIM", "UNBEKANNT", None)
        return build_qr_payload("SIM", dev.tag.strip(),
                                f"{dev.device_type & 0x3FFF:04X}{dev.device_id:06X}")

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def _render(self, size: tuple[int, int]):
        from PIL import Image, ImageDraw
        img = Image.new("RGB", size, (70, 74, 80))
        d = ImageDraw.Draw(img)
        w, h = size
        d.rectangle([w * 0.08, h * 0.12, w * 0.92, h * 0.88], fill=(190, 195, 200), outline=(40, 40, 40), width=4)
        d.text((w * 0.12, h * 0.16), "SIMULATION – TYPENSCHILD", fill=(20, 20, 20))
        text = self._current_text()
        if self.show_qr:
            try:
                import qrcode
                q = qrcode.make(text, box_size=4, border=2).get_image().convert("RGB")
                side = int(min(w, h) * 0.5)
                img.paste(q.resize((side, side)), (int(w * 0.55), int(h * 0.3)))
            except ImportError:
                pass
            d.text((w * 0.12, h * 0.4), text.replace("|", "\n"), fill=(20, 20, 20))
            img.info["sim_qr"] = text
        return img

    def decode_frame(self):
        img = self._render(CAM.DECODE_SIZE)
        gray = img.convert("L")
        gray.info.update(img.info)
        return gray

    def preview_jpeg(self) -> bytes:
        buf = io.BytesIO()
        self._render(CAM.PREVIEW_SIZE).save(buf, "JPEG", quality=70)
        return buf.getvalue()

    def capture_still(self, path: Path) -> None:
        self._render((2028, 1520)).save(path, "JPEG", quality=CAM.JPEG_QUALITY)

    def close(self) -> None:
        self.running = False


# =============================================================================
# CameraService
# =============================================================================
class CameraService:
    def __init__(self, *, simulate: Optional[bool] = None, photo_dir: Path = config.PHOTO_DIR,
                 settings_file: Optional[Path] = CAM.SETTINGS_FILE):
        if simulate is None:
            simulate = simulation_requested("camera")
        self.camera = None
        if not simulate:
            try:
                self.camera = Picamera2Camera()
            except Exception as exc:
                log.error("Kamera nicht verfügbar (%s) – Simulation", exc)
        if self.camera is None:
            simulate = True
            self.camera = SimulatedCamera()
        self.simulated = simulate
        self.light = CameraLight(simulate)
        self.decoder = QrDecoder()
        self.photo_dir = Path(photo_dir)
        self.settings_file = settings_file
        self.light_percent = self._load_settings().get("light_percent", CAM.LIGHT_DEFAULT_PERCENT)
        self._lock = threading.RLock()
        self._users = 0
        self._scan_subs: list[Callable[[ScanResult], None]] = []
        self._scanning = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_code: tuple[str, float] = ("", 0.0)
        self.torch = False

    # ---------- Einstellungen ----------
    def _load_settings(self) -> dict:
        try:
            if self.settings_file and Path(self.settings_file).exists():
                return json.loads(Path(self.settings_file).read_text())
        except (OSError, ValueError):
            pass
        return {}

    def _save_settings(self) -> None:
        if self.settings_file:
            p = Path(self.settings_file)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"light_percent": self.light_percent}))

    # ---------- Kamera öffnen/schließen (Referenzzählung: Scanner + Fotoansicht) ----------
    def open(self) -> None:
        with self._lock:
            self._users += 1
            if self._users == 1:
                self.camera.start()
                # Ringlicht automatisch an (Taschenlampe behält volle Helligkeit)
                self.light.set(100 if self.torch else self.light_percent)

    def close_view(self) -> None:
        with self._lock:
            self._users = max(0, self._users - 1)
            if self._users == 0:
                self.camera.stop()
                if self.torch:
                    self.light.set(100)
                else:
                    self.light.off()

    def set_light(self, percent: float) -> float:
        """Helligkeitsregler in der Kameraansicht (wird gespeichert)."""
        with self._lock:
            self.light_percent = max(5.0, min(100.0, float(percent)))
            if self._users or self.torch:
                self.light.set(self.light_percent)
            self._save_settings()
            return self.light_percent

    def toggle_torch(self) -> bool:
        """Taschenlampen-Button in der Statusleiste."""
        with self._lock:
            self.torch = not self.torch
            if self.torch:
                self.light.set(100)
            elif self._users:
                self.light.set(self.light_percent)
            else:
                self.light.off()
            return self.torch

    # ---------- QR-Scan ----------
    def on_scan(self, cb: Callable[[ScanResult], None]) -> None:
        self._scan_subs.append(cb)

    def start_scanning(self) -> None:
        self.open()
        self._last_code = ("", 0.0)
        self._scanning.set()
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._scan_loop, name="qr-scan", daemon=True)
            self._thread.start()

    def stop_scanning(self) -> None:
        if self._scanning.is_set():
            self._scanning.clear()
            self.close_view()

    def scan_once(self) -> list[ScanResult]:
        """Ein Bild auswerten (auch für Tests). Doppelte Codes werden unterdrückt."""
        texts = self.decoder.decode(self.camera.decode_frame())
        results = []
        now = time.monotonic()
        for t in texts:
            if t == self._last_code[0] and now - self._last_code[1] < CAM.DUPLICATE_SUPPRESS_S:
                continue
            self._last_code = (t, now)
            results.append(ScanResult(time.time(), t, parse_qr_payload(t)))
        return results

    def _scan_loop(self) -> None:
        period = 1.0 / CAM.DECODE_FPS
        while not self._stop.is_set():
            if not self._scanning.wait(0.5):
                continue
            t0 = time.monotonic()
            try:
                for res in self.scan_once():
                    log.info("QR erkannt: %s", res.text)
                    for cb in list(self._scan_subs):
                        try:
                            cb(res)
                        except Exception:
                            log.exception("Scan-Subscriber")
            except Exception:
                log.exception("QR-Dekodierung")
                time.sleep(0.5)
            time.sleep(max(0.0, period - (time.monotonic() - t0)))

    # ---------- Vorschau ----------
    def mjpeg_stream(self, fps: float = 10.0) -> Iterator[bytes]:
        """Für Flask: Response(svc.mjpeg_stream(), mimetype='multipart/x-mixed-replace; boundary=frame')"""
        self.open()
        try:
            while not self._stop.is_set():
                jpg = self.camera.preview_jpeg()
                yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + \
                    str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n"
                time.sleep(1.0 / fps)
        finally:
            self.close_view()

    # ---------- Beweisfoto ----------
    def capture_photo(self, *, order_id: str | int, tag: str, note: str = "") -> dict:
        """Speichert ein Foto unter photos/<auftrag>/ und liefert Pfad + SHA-256 für die DB."""
        safe = lambda s: re.sub(r"[^A-Za-z0-9_.-]+", "_", str(s))[:40] or "x"
        folder = self.photo_dir / safe(order_id)
        folder.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = folder / f"{ts}_{safe(tag)}_{uuid.uuid4().hex[:6]}.jpg"
        self.open()
        try:
            self.camera.capture_still(path)
        finally:
            self.close_view()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        thumb = path.with_name(path.stem + "_thumb.jpg")
        try:
            from PIL import Image
            with Image.open(path) as im:
                im.thumbnail((480, 360))
                im.save(thumb, "JPEG", quality=75)
        except Exception as exc:
            log.warning("Vorschaubild fehlgeschlagen: %s", exc)
            thumb = None
        log.info("Beweisfoto gespeichert: %s", path)
        return {"path": str(path), "thumbnail": str(thumb) if thumb else None, "sha256": digest,
                "tag": tag, "order_id": str(order_id), "note": note, "captured_at": time.time()}

    def status(self) -> dict:
        return {"simulated": self.simulated, "active": self._users > 0, "scanning": self._scanning.is_set(),
                "decoder": self.decoder.backend, "light_percent": self.light.percent,
                "light_setting": self.light_percent, "torch": self.torch}

    def shutdown(self) -> None:
        self._stop.set()
        self._scanning.clear()
        if self._thread:
            self._thread.join(timeout=2)
        self.camera.close()
        self.light.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    svc = CameraService(simulate=True, photo_dir=config.DATA_DIR / "demo_photos", settings_file=None)
    svc.on_scan(lambda r: print("SCAN:", r.to_dict()))
    svc.start_scanning()
    print("Status:", svc.status())
    time.sleep(0.6)
    svc.stop_scanning()
    print("Licht nach Scan:", svc.light.percent, "% | Taschenlampe:", svc.toggle_torch(), svc.light.percent, "%")
    print("Foto:", svc.capture_photo(order_id="A-2026-001", tag="PT-4711")["sha256"][:16], "…")
    svc.shutdown()
