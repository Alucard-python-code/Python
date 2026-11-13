"""
label_printer.py – QR-Prüfplaketten 40 × 30 mm für den SUPVAN T50M Pro.

Wichtig: Der T50M Pro spricht Bluetooth CLASSIC (SPP/RFCOMM), nicht BLE.
Das Protokoll ist proprietär. Grundlage ist die Rekonstruktion in
https://github.com/heeen/supvan-cups (MIT, docs/PROTOCOL.md).

Architektur:
  LabelRenderer        – Etikett als 1-Bit-Bild (320 × 240 Punkte = 40 × 30 mm bei 203 dpi)
  CupsBackend          – Druck über CUPS + supvan-cups-Treiber (laut Autor mit T50M Pro
                         per Bluetooth getestet) -> EMPFOHLENER Druckweg
  FileBackend          – speichert nur das PNG (Simulation / ohne Drucker)
  SupvanStatusClient   – eigener RFCOMM-Client NUR für Status (Etiketten leer, Deckel offen,
                         Restmenge) für die Statusleiste. Byte-Layout laut PROTOCOL.md,
                         am echten Gerät noch zu verifizieren.
  PrinterService       – Fassade für app.py: Vorschau, Druck, Statusüberwachung

Ein vollständig eigener Bluetooth-Druckpfad wurde bewusst NICHT implementiert: Die
Bilddaten müssen LZMA1-komprimiert OHNE Endmarker in einem nur teilweise dokumentierten
Paketformat übertragen werden – ohne Testgerät wäre das geraten.
"""
from __future__ import annotations

import io
import logging
import re
import shutil
import socket
import struct
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Optional

import config
from camera_qr import build_qr_payload
from hw_compat import simulation_requested

log = logging.getLogger(__name__)
PC = config.Printer

WIDTH_PX = PC.LABEL_MM[0] * PC.DOTS_PER_MM      # 320
HEIGHT_PX = PC.LABEL_MM[1] * PC.DOTS_PER_MM     # 240
DPI = round(PC.DOTS_PER_MM * 25.4)              # 203


# =============================================================================
# Etiketteninhalt
# =============================================================================
@dataclass
class LabelData:
    customer_id: str | int
    tag: str
    uid: Optional[str] = None
    kind: str = "PRUEFUNG"            # PRUEFUNG | NEUAUFNAHME | GERAETETAUSCH
    passed: Optional[bool] = None     # nur bei PRUEFUNG
    test_date: date = field(default_factory=date.today)
    next_due: Optional[date] = None
    technician: str = ""
    order_no: str = ""

    @property
    def qr_payload(self) -> str:
        return build_qr_payload(self.customer_id, self.tag, self.uid)

    @property
    def headline(self) -> str:
        if self.kind == "PRUEFUNG":
            return "BESTANDEN" if self.passed else ("NICHT BESTANDEN" if self.passed is False else "GEPRÜFT")
        return {"NEUAUFNAHME": "NEUAUFNAHME", "GERAETETAUSCH": "GERÄTETAUSCH"}.get(self.kind, self.kind)


# =============================================================================
# Renderer
# =============================================================================
class LabelRenderer:
    MARGIN = 2 * PC.DOTS_PER_MM          # 2 mm Rand

    def __init__(self, font_dir: str = PC.FONT_DIR):
        self.font_dir = Path(font_dir)

    def font(self, size: int, bold: bool = False):
        from PIL import ImageFont
        name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        try:
            return ImageFont.truetype(str(self.font_dir / name), size)
        except OSError:
            return ImageFont.load_default(size)

    def _fit(self, draw, text: str, max_w: int, start: int, bold: bool = True, min_size: int = 10):
        """Größte Schrift, mit der `text` in max_w Punkte passt."""
        size = start
        while size > min_size:
            f = self.font(size, bold)
            if draw.textlength(text, font=f) <= max_w:
                return f
            size -= 1
        return self.font(min_size, bold)

    def render(self, d: LabelData):
        import qrcode
        from PIL import Image, ImageDraw
        img = Image.new("1", (WIDTH_PX, HEIGHT_PX), 1)          # 1 = weiß
        draw = ImageDraw.Draw(img)
        m = self.MARGIN

        # QR links: Fehlerkorrektur M, Modulgröße >= 4 Punkte (0,5 mm) -> sicher scanbar
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=1, border=0)
        qr.add_data(d.qr_payload)
        qr.make(fit=True)
        modules = qr.modules_count
        qr_box = HEIGHT_PX - 2 * m - 28                        # Platz für Kopfzeile unten
        scale = max(1, qr_box // modules)
        qr_img = qr.make_image(fill_color="black", back_color="white").get_image().convert("1")
        qr_img = qr_img.resize((modules * scale, modules * scale), Image.NEAREST)
        img.paste(qr_img, (m, m))
        qr_w = modules * scale

        # rechte Spalte
        x = m + qr_w + max(8, 2 * scale)          # Ruhezone ≥ 2 Module neben dem QR
        col_w = WIDTH_PX - x - m
        y = m
        f_tag = self._fit(draw, d.tag, col_w, 30)
        draw.text((x, y), d.tag, font=f_tag, fill=0)
        y += f_tag.size + 6
        lines = [f"Geprüft {d.test_date:%d.%m.%Y}"]
        if d.next_due:
            lines.append(f"Nächste {d.next_due:%m/%Y}")
        if d.technician:
            lines.append(f"Prüfer {d.technician}")
        if d.order_no:
            lines.append(f"Auftr. {d.order_no}")
        for line in lines:
            f = self._fit(draw, line, col_w, 16, bold=False)
            draw.text((x, y), line, font=f, fill=0)
            y += f.size + 3

        # Ergebniszeile über die volle Breite, invertiert bei "BESTANDEN"/Tausch
        bar_h = 26
        top = HEIGHT_PX - m - bar_h
        head = d.headline
        f_head = self._fit(draw, head, WIDTH_PX - 2 * m - 8, 20)
        invert = d.kind != "PRUEFUNG" or d.passed is not False
        if invert:
            draw.rectangle([m, top, WIDTH_PX - m - 1, HEIGHT_PX - m - 1], fill=0)
        else:  # NICHT BESTANDEN: doppelter Rahmen, gut unterscheidbar auch ohne Farbe
            draw.rectangle([m, top, WIDTH_PX - m - 1, HEIGHT_PX - m - 1], outline=0, width=3)
        tw = draw.textlength(head, font=f_head)
        draw.text(((WIDTH_PX - tw) / 2, top + (bar_h - f_head.size) / 2 - 1), head, font=f_head,
                  fill=1 if invert else 0)
        return img

    def png_bytes(self, d: LabelData) -> bytes:
        buf = io.BytesIO()
        self.render(d).save(buf, "PNG", dpi=(DPI, DPI))
        return buf.getvalue()


# =============================================================================
# Druck-Backends
# =============================================================================
class PrintError(RuntimeError):
    pass


class FileBackend:
    name = "file"

    def print_png(self, path: Path, copies: int = 1) -> str:
        log.info("[Datei] Etikett gespeichert (kein Druck): %s", path)
        return f"file:{path.name}"

    def status(self) -> dict:
        return {"state": "sim", "text": "Simulation (nur Datei)"}


class CupsBackend:
    """Druck über CUPS. Einrichtung des supvan-cups-Treibers: deploy/SETUP_PRINTER.md"""
    name = "cups"
    _JOB_RE = re.compile(r"request id is (\S+)")

    def __init__(self, queue: str = PC.CUPS_QUEUE):
        self.queue = queue

    def print_png(self, path: Path, copies: int = 1) -> str:
        if shutil.which("lp") is None:
            raise PrintError("CUPS (lp) nicht installiert")
        w, h = PC.LABEL_MM
        cmd = ["lp", "-d", self.queue, "-n", str(max(1, copies)),
               "-o", f"media=Custom.{w}x{h}mm", "-o", "print-scaling=none", str(path)]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PrintError(f"lp fehlgeschlagen: {exc}") from exc
        if res.returncode != 0:
            raise PrintError(res.stderr.strip() or "lp-Fehler")
        m = self._JOB_RE.search(res.stdout)
        return m.group(1) if m else res.stdout.strip()

    @staticmethod
    def parse_lpstat(text: str) -> dict:
        t = text.lower()
        if "disabled" in t:
            return {"state": "error", "text": "Drucker deaktiviert (CUPS)"}
        if "is idle" in t:
            return {"state": "ready", "text": "Bereit"}
        if "now printing" in t:
            return {"state": "busy", "text": "Druckt …"}
        return {"state": "unknown", "text": text.strip()[:80] or "Unbekannt"}

    def status(self) -> dict:
        if shutil.which("lpstat") is None:
            return {"state": "not_configured", "text": "CUPS nicht installiert"}
        try:
            res = subprocess.run(["lpstat", "-p", self.queue], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"state": "error", "text": str(exc)}
        if res.returncode != 0:
            return {"state": "not_configured", "text": f"Warteschlange {self.queue} fehlt"}
        return self.parse_lpstat(res.stdout)


# =============================================================================
# SUPVAN-Protokoll (Status) – Byte-Layout laut supvan-cups/docs/PROTOCOL.md
# =============================================================================
CMD_BUF_FULL, CMD_INQUIRY_STA, CMD_CHECK_DEVICE = 0x10, 0x11, 0x12
CMD_START_PRINT, CMD_STOP_PRINT, CMD_RD_DEV_NAME = 0x13, 0x14, 0x16
CMD_RETURN_MAT, CMD_READ_FWVER = 0x30, 0xC5

STATUS_BITS = {
    # (Byte-Offset im Antwortrahmen, Bitmaske): (Schlüssel, Klartext, ist Fehler)
    (14, 0x01): ("buffer_full", "Puffer voll", False),
    (14, 0x02): ("label_rw_error", "Etikettenrolle nicht lesbar", True),
    (14, 0x04): ("label_end", "Etiketten aufgebraucht", True),
    (14, 0x08): ("label_mode_error", "Falscher Etikettentyp", True),
    (14, 0x40): ("low_battery", "Druckerakku schwach", False),
    (15, 0x04): ("device_busy", "Drucker beschäftigt", False),
    (15, 0x08): ("head_temp_high", "Druckkopf zu heiß", True),
    (16, 0x08): ("cover_open", "Deckel offen", True),
    (16, 0x40): ("printing", "Druckt", False),
    (17, 0x01): ("label_not_installed", "Keine Etikettenrolle eingelegt", True),
}


def build_command(cmd: int, param: int = 0, block_count: int = 0) -> bytes:
    """16-Byte-Befehlsrahmen: 7E 5A | Länge 12 (LE) | 10 01 AA | CMD | Prüfsumme | 00 01 | Param | Blöcke.
    Prüfsumme = Summe der Bytes 10..15 (u16 LE). Laut Quelle unverifiziert – am Gerät prüfen."""
    tail = bytes([0x00, 0x01]) + struct.pack("<HH", param & 0xFFFF, block_count & 0xFFFF)
    chk = sum(tail) & 0xFFFF
    return bytes([0x7E, 0x5A, 0x0C, 0x00, 0x10, 0x01, 0xAA, cmd]) + struct.pack("<H", chk) + tail


def split_response(buf: bytearray) -> Optional[bytes]:
    """Schneidet einen vollständigen Antwortrahmen (7E 5A len_lo len_hi …) aus dem Puffer."""
    start = buf.find(b"\x7E\x5A")
    if start < 0:
        buf.clear()
        return None
    del buf[:start]
    if len(buf) < 4:
        return None
    total = 4 + struct.unpack_from("<H", buf, 2)[0]
    if total > 4096:                  # unplausibel -> resynchronisieren
        del buf[:2]
        return None
    if len(buf) < total:
        return None
    frame = bytes(buf[:total])
    del buf[:total]
    return frame


def parse_status(frame: bytes) -> dict:
    if len(frame) < 20 or frame[:2] != b"\x7E\x5A" or frame[7] != CMD_INQUIRY_STA:
        raise ValueError("Keine gültige Statusantwort")
    flags, errors, info = {}, [], []
    for (off, mask), (key, text, is_err) in STATUS_BITS.items():
        on = bool(frame[off] & mask)
        flags[key] = on
        if on:
            (errors if is_err else info).append(text)
    return {"flags": flags, "errors": errors, "info": info,
            "print_count": struct.unpack_from("<H", frame, 18)[0]}


class SupvanStatusClient:
    """Kurzlebige RFCOMM-Verbindung nur für Statusabfragen (Drucker ist sonst frei für CUPS)."""

    def __init__(self, address: str = PC.BT_ADDRESS, channel: int = PC.RFCOMM_CHANNEL, timeout: float = 4.0):
        self.address, self.channel, self.timeout = address, channel, timeout

    @staticmethod
    def available() -> bool:
        return hasattr(socket, "AF_BLUETOOTH") and hasattr(socket, "BTPROTO_RFCOMM")

    def _transact(self, sock, cmd: int, param: int = 0) -> bytes:
        sock.sendall(build_command(cmd, param))
        buf = bytearray()
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            chunk = sock.recv(512)
            if not chunk:
                break
            buf += chunk
            frame = split_response(buf)
            if frame and len(frame) > 7 and frame[7] == cmd:
                return frame
        raise TimeoutError(f"Keine Antwort auf Kommando 0x{cmd:02X}")

    def query(self) -> dict:
        if not self.address:
            return {"state": "not_configured", "text": "Drucker-Adresse nicht eingetragen"}
        if not self.available():
            return {"state": "error", "text": "Python ohne Bluetooth-Socket-Unterstützung"}
        try:
            with socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM) as s:
                s.settimeout(self.timeout)
                s.connect((self.address, self.channel))
                self._transact(s, CMD_CHECK_DEVICE)
                st = parse_status(self._transact(s, CMD_INQUIRY_STA))
        except (OSError, TimeoutError) as exc:
            return {"state": "offline", "text": f"Nicht erreichbar ({exc.__class__.__name__})"}
        except ValueError as exc:
            return {"state": "unknown", "text": f"Antwort unverständlich: {exc}"}
        if st["errors"]:
            return {"state": "error", "text": ", ".join(st["errors"]), **st}
        if st["flags"].get("printing") or st["flags"].get("device_busy"):
            return {"state": "busy", "text": "Druckt …", **st}
        return {"state": "ready", "text": "Bereit", **st}


# =============================================================================
# PrinterService
# =============================================================================
class PrinterService:
    def __init__(self, *, simulate: Optional[bool] = None, backend: Optional[str] = None,
                 label_dir: Path = PC.LABEL_DIR):
        if simulate is None:
            simulate = simulation_requested("printer")
        self.simulated = simulate
        backend = "file" if simulate else (backend or PC.BACKEND)
        self.backend = CupsBackend() if backend == "cups" else FileBackend()
        self.status_client = SupvanStatusClient() if not simulate else None
        self.renderer = LabelRenderer()
        self.label_dir = Path(label_dir)
        self._status: dict = {"state": "unknown", "text": "Noch nicht geprüft"}
        self._subs: list[Callable[[dict], None]] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def preview_png(self, data: LabelData) -> bytes:
        return self.renderer.png_bytes(data)

    def print_label(self, data: LabelData, copies: int = 1) -> dict:
        """Druckt ein Etikett. Das PNG bleibt immer gespeichert (Nachdruck/Nachweis)."""
        self.label_dir.mkdir(parents=True, exist_ok=True)
        safe_tag = re.sub(r"[^A-Za-z0-9_.-]+", "_", data.tag)[:40]
        path = self.label_dir / f"{time.strftime('%Y%m%d_%H%M%S')}_{safe_tag}.png"
        path.write_bytes(self.preview_png(data))
        with self._lock:
            try:
                job = self.backend.print_png(path, copies)
            except PrintError as exc:
                log.error("Etikettendruck fehlgeschlagen: %s", exc)
                return {"ok": False, "error": str(exc), "png": str(path), "backend": self.backend.name}
        log.info("Etikett %s %s (%s, Job %s)", data.tag,
                 "gespeichert" if self.backend.name == "file" else "an Drucker gesendet", self.backend.name, job)
        return {"ok": True, "job": job, "png": str(path), "backend": self.backend.name}

    # ---------- Status für die Statusleiste ----------
    def refresh_status(self) -> dict:
        st = self.backend.status()
        # Bluetooth-Detailstatus nur, wenn CUPS nicht gerade druckt (eine RFCOMM-Verbindung zur Zeit)
        if self.status_client and st.get("state") in ("ready", "not_configured", "unknown"):
            bt = self.status_client.query()
            if bt["state"] != "not_configured":
                st = {**bt, "cups": st}
        st["backend"] = self.backend.name
        st["checked_at"] = time.time()
        changed = st.get("state") != self._status.get("state") or st.get("text") != self._status.get("text")
        self._status = st
        if changed:
            for cb in list(self._subs):
                try:
                    cb(st)
                except Exception:
                    log.exception("Drucker-Subscriber")
        return st

    def status(self) -> dict:
        return self._status

    def subscribe(self, cb: Callable[[dict], None]) -> None:
        self._subs.append(cb)

    def start(self, interval_s: float = PC.STATUS_INTERVAL_S) -> "PrinterService":
        def loop():
            while True:
                try:
                    self.refresh_status()
                except Exception:
                    log.exception("Druckerstatus")
                if self._stop.wait(interval_s):
                    break
        self._thread = threading.Thread(target=loop, name="printer-status", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    svc = PrinterService(simulate=True, label_dir=config.DATA_DIR / "demo_labels")
    for d in (LabelData(4711, "PT-4711", "26060A1B2C", passed=True, next_due=date(2027, 11, 1),
                        technician="M. Muster", order_no="A-2026-001"),
              LabelData(4711, "FV-3001", "13091A2B3C", passed=False, technician="M. Muster"),
              LabelData(4711, "TT-0042", "260A0C0FFE", kind="GERAETETAUSCH")):
        print(svc.print_label(d))
    print("Status:", svc.refresh_status())
