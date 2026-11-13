"""
dual_usb_export.py – Air-Gap-Export über USB-C: USB-Stick ODER direkt an einen PC.

Dock-Erkennung: GPIO23 = CH224K "PG" (Open-Drain, LOW = USB-PD-Versorgung ausgehandelt).

Exportpaket (immer gleich aufgebaut, mit Prüfsummen):
  Berichte/      Prüfberichte (PDF)
  Fotos/         Beweisfotos je Auftrag
  Etiketten/     gedruckte Prüfplaketten (PNG)
  Datenbank/     Konsistente Kopien beider SQLite-DBs (Backup-API, auch während des Betriebs)
  Kalibrierungen.csv, manifest.json (SHA-256 je Datei), LIESMICH.txt
  Auf_Desktop_kopieren.bat / auf_desktop_kopieren.sh  (Desktop-Kopierskript)

Ziel 1 – USB-Stick (Host-Modus):
  Erkennung über `lsblk` (Transport usb). Einhängen per udisks2 (ohne root), Kopie nach
  <Stick>/HART_EXPORT/<Zeitstempel>/, `sync`, Aushängen + Stromlos schalten -> sicher abziehen.

Ziel 2 – PC per Kabel (Device-Modus, g_mass_storage):
  Das Paket wird OHNE root in ein FAT32-Abbild "HART_EXPORT" geschrieben (mkfs.vfat + mtools)
  und SCHREIBGESCHÜTZT (ro=1) als Wechseldatenträger angeboten. Der PC kann nur lesen ->
  kein Dateisystemschaden, wenn das Kabel ohne Auswerfen gezogen wird. Das Abbild wird nie
  verändert, solange es angeboten wird.
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import config
from hw_compat import digital_input, simulation_requested

log = logging.getLogger(__name__)
EX = config.Export

Runner = Callable[[list[str], float], subprocess.CompletedProcess]


def _default_runner(cmd: list[str], timeout: float = 60.0) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


class ExportError(RuntimeError):
    pass


# =============================================================================
# Dock-Erkennung
# =============================================================================
class DockMonitor:
    def __init__(self, simulate: Optional[bool] = None):
        sim = simulation_requested("dock") if simulate is None else simulate
        # pull_up=True -> "aktiv" bedeutet LOW = Power Good = angedockt
        self.pin = digital_input(config.Pins.DOCK_DETECT, pull_up=True, bounce_time=0.2,
                                 component="dock" if not sim else "dock_sim")
        if sim and not getattr(self.pin, "simulated", False):
            self.pin.close()
            from hw_compat import MockDigitalInput
            self.pin = MockDigitalInput(config.Pins.DOCK_DETECT)
        self._subs: list[Callable[[bool], None]] = []
        self.pin.when_activated = lambda *_: self._changed(True)
        self.pin.when_deactivated = lambda *_: self._changed(False)

    @property
    def docked(self) -> bool:
        return bool(self.pin.is_active)

    def subscribe(self, cb: Callable[[bool], None]) -> None:
        self._subs.append(cb)

    def _changed(self, docked: bool) -> None:
        log.info("Dock: %s", "angedockt" if docked else "abgedockt")
        for cb in list(self._subs):
            try:
                cb(docked)
            except Exception:
                log.exception("Dock-Subscriber")

    def simulate(self, docked: bool) -> None:
        self.pin.simulate_level(docked)

    def close(self) -> None:
        self.pin.close()


# =============================================================================
# Exportpaket
# =============================================================================
WIN_SCRIPT = r"""@echo off
REM Kopiert den HART-Export auf den Desktop (Ordner HART_Export\<Datum_Uhrzeit>)
setlocal
for /f "tokens=2 delims==" %%i in ('wmic os get localdatetime /value ^| find "="') do set DT=%%i
set ZIEL=%USERPROFILE%\Desktop\HART_Export\%DT:~0,8%_%DT:~8,6%
echo Kopiere nach %ZIEL% ...
robocopy "%~dp0." "%ZIEL%" /E /NFL /NDL /NJH /NJS /XF "Auf_Desktop_kopieren.bat" "auf_desktop_kopieren.sh"
if %ERRORLEVEL% GEQ 8 (echo FEHLER beim Kopieren! & pause & exit /b 1)
echo Fertig. Der Datentraeger kann jetzt entfernt werden.
explorer "%ZIEL%"
pause
"""

SH_SCRIPT = """#!/bin/sh
# Kopiert den HART-Export auf den Desktop (Ordner HART_Export/<Datum_Uhrzeit>)
SRC="$(cd "$(dirname "$0")" && pwd)"
DESK="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
ZIEL="$DESK/HART_Export/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$ZIEL"
rsync -a --exclude 'Auf_Desktop_kopieren.bat' --exclude 'auf_desktop_kopieren.sh' "$SRC/" "$ZIEL/" 2>/dev/null \\
  || cp -R "$SRC/." "$ZIEL/"
echo "Fertig: $ZIEL"
"""

README = """HART-Feldcommunicator – Datenexport
===================================
Erstellt: {created}
Geraet:   {host}

Inhalt
  Berichte/        Pruefberichte als PDF (inkl. Kunden-Ruecklaeufer)
  Fotos/           Beweisfotos (SHA-256 im Pruefbericht und in manifest.json)
  Etiketten/       gedruckte Pruefplaketten
  Datenbank/       hart_kalibrierung.db, telemetry_logs.db (fuer Grafana: SQLite-Plugin)
  Kalibrierungen.csv  Uebersicht aller Pruefungen (Excel: Trennzeichen Semikolon)
  manifest.json    Pruefsummen aller Dateien (Integritaetsnachweis)

Auf den Desktop kopieren
  Windows:      Auf_Desktop_kopieren.bat doppelklicken
  Linux/macOS:  sh auf_desktop_kopieren.sh
"""


def sqlite_backup(src: Path, dst: Path) -> None:
    """Konsistente Kopie einer laufenden SQLite-DB (Online-Backup-API, inkl. WAL-Inhalt)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as s, sqlite3.connect(dst) as d:
        s.backup(d)
    with sqlite3.connect(dst) as d:
        d.execute("PRAGMA journal_mode = DELETE")    # Einzeldatei ohne -wal/-shm


def write_calibrations_csv(db_path: Path, out: Path) -> int:
    sql = """SELECT o.order_no, cu.name AS kunde, d.tag, d.display_name, d.hart_unique_id, c.case_type,
                    c.result, ROUND(c.max_error_pct, 4) AS max_abweichung_pct, c.tolerance_pct AS toleranz_pct,
                    c.lrv, c.urv, c.unit, c.technician,
                    datetime(c.started_at,'unixepoch','localtime') AS beginn, ROUND(c.duration_s, 0) AS dauer_s,
                    c.time_source
             FROM calibrations c JOIN orders o ON o.id=c.order_id JOIN devices d ON d.id=c.device_id
             JOIN customers cu ON cu.id=o.customer_id ORDER BY c.started_at"""
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        cur = conn.execute(sql)
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
    with out.open("w", newline="", encoding="utf-8-sig") as f:      # BOM -> Excel erkennt UTF-8
        w = csv.writer(f, delimiter=";")
        w.writerow(cols)
        for r in rows:
            w.writerow([str(v).replace(".", ",") if isinstance(v, float) else v for v in r])
    return len(rows)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_bundle(dest: Path, *, db_path: Path = config.DB_PATH, telemetry_path: Path = config.TELEMETRY_DB_PATH,
                 report_dir: Path = config.REPORT_DIR, photo_dir: Path = config.PHOTO_DIR,
                 label_dir: Path = config.Printer.LABEL_DIR) -> dict:
    """Erzeugt das Exportpaket in `dest` (wird neu angelegt)."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    copied = {"Berichte": report_dir, "Fotos": photo_dir, "Etiketten": label_dir}
    dest_abs = dest.resolve()

    def ignore(dirname: str, names: list[str]) -> set[str]:
        # *.tmp und – falls das Ziel innerhalb einer Quelle liegt – das Ziel selbst auslassen
        skip = {n for n in names if n.endswith(".tmp")}
        for n in names:
            p = (Path(dirname) / n).resolve()
            if p == dest_abs or dest_abs.is_relative_to(p):
                skip.add(n)
        return skip

    for name, src in copied.items():
        if Path(src).exists():
            shutil.copytree(src, dest / name, ignore=ignore)
        else:
            (dest / name).mkdir()
    n_cal = 0
    if Path(db_path).exists():
        sqlite_backup(Path(db_path), dest / "Datenbank" / "hart_kalibrierung.db")
        n_cal = write_calibrations_csv(dest / "Datenbank" / "hart_kalibrierung.db", dest / "Kalibrierungen.csv")
    if Path(telemetry_path).exists():
        sqlite_backup(Path(telemetry_path), dest / "Datenbank" / "telemetry_logs.db")
    created = time.strftime("%d.%m.%Y %H:%M:%S")
    (dest / "LIESMICH.txt").write_text(README.format(created=created, host=os.uname().nodename), encoding="utf-8")
    (dest / "Auf_Desktop_kopieren.bat").write_bytes(WIN_SCRIPT.replace("\n", "\r\n").encode("cp1252"))
    sh = dest / "auf_desktop_kopieren.sh"
    sh.write_text(SH_SCRIPT, encoding="utf-8")
    sh.chmod(0o755)
    files, total = [], 0
    for p in sorted(dest.rglob("*")):
        if p.is_file():
            size = p.stat().st_size
            total += size
            files.append({"path": p.relative_to(dest).as_posix(), "size": size, "sha256": sha256_file(p)})
    manifest = {"created": created, "created_unix": time.time(), "device": os.uname().nodename,
                "calibrations": n_cal, "file_count": len(files), "total_bytes": total, "files": files}
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Exportpaket erstellt: %d Dateien, %.1f MB", len(files), total / 1e6)
    return manifest


# =============================================================================
# Ziel 1: USB-Stick
# =============================================================================
@dataclass
class UsbPartition:
    device: str           # /dev/sda1
    label: str
    fstype: str
    size: str
    mountpoint: Optional[str]

    def to_dict(self) -> dict:
        return self.__dict__.copy()


SUPPORTED_FS = {"vfat", "exfat", "ntfs", "ext4"}


def parse_lsblk(data: dict) -> list[UsbPartition]:
    """Partitionen auf USB-Massenspeichern aus `lsblk -J -o NAME,PATH,TRAN,RM,FSTYPE,LABEL,SIZE,MOUNTPOINT`."""
    out = []

    def walk(node: dict, tran: Optional[str]) -> None:
        tran = node.get("tran") or tran
        if node.get("fstype") in SUPPORTED_FS and tran == "usb":
            out.append(UsbPartition(node.get("path") or f"/dev/{node['name']}", node.get("label") or "USB-STICK",
                                    node["fstype"], node.get("size") or "", node.get("mountpoint")))
        for ch in node.get("children") or []:
            walk(ch, tran)

    for dev in data.get("blockdevices", []):
        walk(dev, None)
    return out


class UsbStickExporter:
    def __init__(self, runner: Runner = _default_runner):
        self.run = runner

    def partitions(self) -> list[UsbPartition]:
        try:
            res = self.run(["lsblk", "-J", "-o", "NAME,PATH,TRAN,RM,FSTYPE,LABEL,SIZE,MOUNTPOINT"], 10)
            return parse_lsblk(json.loads(res.stdout or "{}"))
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            log.warning("lsblk fehlgeschlagen: %s", exc)
            return []

    def _mount(self, part: UsbPartition) -> str:
        if part.mountpoint:
            return part.mountpoint
        res = self.run(["udisksctl", "mount", "-b", part.device, "--no-user-interaction"], 30)
        # Ausgabe: "Mounted /dev/sda1 at /media/hart/STICK"
        if res.returncode != 0 or " at " not in res.stdout:
            raise ExportError(f"Stick konnte nicht eingehängt werden: {res.stderr.strip() or res.stdout.strip()}")
        return res.stdout.strip().split(" at ", 1)[1].rstrip(".")

    def export(self, part: UsbPartition, bundle: Path, eject: bool = True) -> dict:
        mnt = Path(self._mount(part))
        target = mnt / EX.LABEL / bundle.name
        free = shutil.disk_usage(mnt).free
        need = sum(p.stat().st_size for p in bundle.rglob("*") if p.is_file())
        if need * 1.05 > free:
            raise ExportError(f"Zu wenig Platz auf dem Stick ({free / 1e6:.0f} MB frei, {need / 1e6:.0f} MB nötig)")
        shutil.copytree(bundle, target)
        for script in ("Auf_Desktop_kopieren.bat", "auf_desktop_kopieren.sh", "LIESMICH.txt"):
            shutil.copy2(bundle / script, mnt / EX.LABEL / script)      # oberste Ebene: neuester Export
        os.sync()
        bad = [f["path"] for f in json.loads((bundle / "manifest.json").read_text())["files"]
               if sha256_file(target / f["path"]) != f["sha256"]]
        if bad:
            raise ExportError(f"Prüfsummenfehler nach dem Kopieren: {bad[:3]}")
        if eject:
            self.run(["udisksctl", "unmount", "-b", part.device, "--no-user-interaction"], 30)
            self.run(["udisksctl", "power-off", "-b", part.device, "--no-user-interaction"], 30)
        return {"target": str(target), "bytes": need, "verified": True, "ejected": eject}


# =============================================================================
# Ziel 2: PC per USB-C (g_mass_storage, schreibgeschützt)
# =============================================================================
class GadgetExporter:
    def __init__(self, image: Path = EX.IMAGE_FILE, runner: Runner = _default_runner, simulate: bool = False):
        self.image = Path(image)
        self.run = runner
        self.simulate = simulate
        self.published = False

    def build_image(self, bundle: Path, size_mb: int = EX.IMAGE_SIZE_MB) -> dict:
        if self.published:
            raise ExportError("Abbild wird gerade am PC angeboten – erst trennen")
        need = sum(p.stat().st_size for p in bundle.rglob("*") if p.is_file())
        if need > size_mb * 1e6 * 0.95:
            raise ExportError(f"Export ({need / 1e6:.0f} MB) passt nicht ins Abbild ({size_mb} MB)")
        for tool in ("mkfs.vfat", "mcopy"):
            if shutil.which(tool) is None:
                raise ExportError(f"Werkzeug '{tool}' fehlt (sudo apt install dosfstools mtools)")
        self.image.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.image.with_suffix(".tmp")
        tmp.unlink(missing_ok=True)
        res = self.run(["mkfs.vfat", "-C", "-F", "32", "-n", EX.LABEL, str(tmp), str(size_mb * 1024)], 60)
        if res.returncode != 0:
            raise ExportError(f"mkfs.vfat: {res.stderr.strip()}")
        items = [str(p) for p in sorted(bundle.iterdir())]
        res = self.run(["mcopy", "-s", "-Q", "-i", str(tmp), *items, "::/"], 300)
        if res.returncode != 0:
            raise ExportError(f"mcopy: {res.stderr.strip()}")
        tmp.replace(self.image)
        return {"image": str(self.image), "size_mb": size_mb, "content_bytes": need}

    @staticmethod
    def udc_state(udc_dir: Path = EX.UDC_DIR) -> Optional[str]:
        """'configured' = ein PC hat den Datenträger übernommen."""
        try:
            for udc in udc_dir.iterdir():
                return (udc / "state").read_text().strip()
        except OSError:
            return None
        return None

    def publish(self, wait_s: float = EX.GADGET_CONNECT_TIMEOUT_S) -> dict:
        if not self.image.exists():
            raise ExportError("Kein Exportabbild vorhanden")
        if self.simulate:
            self.published = True
            return {"published": True, "pc_connected": False, "simulated": True}
        self.unpublish()
        res = self.run(["sudo", "-n", "/usr/sbin/modprobe", "g_mass_storage", f"file={self.image}",
                        "removable=1", "ro=1", "stall=0", "iManufacturer=HART-Communicator",
                        "iProduct=HART_EXPORT"], 20)
        if res.returncode != 0:
            raise ExportError(f"g_mass_storage: {res.stderr.strip()}")
        self.published = True
        deadline = time.monotonic() + wait_s
        state = None
        while time.monotonic() < deadline:
            state = self.udc_state()
            if state == "configured":
                break
            time.sleep(0.5)
        return {"published": True, "pc_connected": state == "configured", "udc_state": state}

    def unpublish(self) -> None:
        if self.simulate:
            self.published = False
            return
        self.run(["sudo", "-n", "/usr/sbin/modprobe", "-r", "g_mass_storage"], 20)
        self.published = False


# =============================================================================
# Fassade
# =============================================================================
class ExportService:
    def __init__(self, *, simulate: Optional[bool] = None, runner: Runner = _default_runner,
                 staging_dir: Path = EX.STAGING_DIR, sources: Optional[dict] = None,
                 auto_publish_on_dock: bool = True):
        self.simulated = simulation_requested("export") if simulate is None else simulate
        self.dock = DockMonitor(self.simulated)
        self.stick = UsbStickExporter(runner)
        self.gadget = GadgetExporter(runner=runner, simulate=self.simulated)
        self.staging_dir = Path(staging_dir)
        self.sources = sources or {}
        self.auto_publish_on_dock = auto_publish_on_dock
        self._lock = threading.Lock()
        self._subs: list[Callable[[dict], None]] = []
        self.last_export: Optional[dict] = None
        self._known_sticks: set[str] = set()
        self._stop = threading.Event()
        self.dock.subscribe(self._on_dock)

    def subscribe(self, cb: Callable[[dict], None]) -> None:
        self._subs.append(cb)

    def _emit(self, event: str, **data) -> None:
        payload = {"event": event, **data, "status": self.status()}
        for cb in list(self._subs):
            try:
                cb(payload)
            except Exception:
                log.exception("Export-Subscriber")

    def status(self) -> dict:
        return {"docked": self.dock.docked, "pc_published": self.gadget.published,
                "pc_connected": (not self.simulated) and self.gadget.udc_state() == "configured",
                "sticks": [p.to_dict() for p in self.stick.partitions()] if not self.simulated else [],
                "last_export": self.last_export, "simulated": self.simulated}

    def _bundle(self) -> tuple[Path, dict]:
        dest = self.staging_dir / time.strftime("%Y%m%d_%H%M%S")
        if self.staging_dir.exists():                    # nur das jüngste Paket behalten
            shutil.rmtree(self.staging_dir)
        return dest, build_bundle(dest, **self.sources)

    def export_to_stick(self, device: Optional[str] = None) -> dict:
        with self._lock:
            parts = self.stick.partitions()
            if device:
                parts = [p for p in parts if p.device == device]
            if not parts:
                raise ExportError("Kein USB-Stick gefunden")
            bundle, manifest = self._bundle()
            res = self.stick.export(parts[0], bundle)
            self.last_export = {"target": "stick", "at": time.time(), "files": manifest["file_count"], **res}
        self._emit("exported", **self.last_export)
        return self.last_export

    def publish_to_pc(self) -> dict:
        with self._lock:
            self.gadget.unpublish()
            bundle, manifest = self._bundle()
            img = self.gadget.build_image(bundle)
            pub = self.gadget.publish()
            self.last_export = {"target": "pc", "at": time.time(), "files": manifest["file_count"], **img, **pub}
        self._emit("published", **self.last_export)
        return self.last_export

    def unpublish(self) -> None:
        with self._lock:
            self.gadget.unpublish()
        self._emit("unpublished")

    def _on_dock(self, docked: bool) -> None:
        self._emit("dock", docked=docked)
        if not docked and self.gadget.published:
            self.unpublish()
        elif docked and self.auto_publish_on_dock:
            threading.Thread(target=self._auto_publish, name="export-auto", daemon=True).start()

    def _auto_publish(self) -> None:
        try:
            self.publish_to_pc()
        except ExportError as exc:
            log.warning("Automatischer PC-Export nicht möglich: %s", exc)
            self._emit("error", message=str(exc))

    # ---------- Stick-Hotplug (Hinweis in der UI) ----------
    def start(self, interval_s: float = 3.0) -> "ExportService":
        def loop():
            while not self._stop.wait(interval_s):
                if self.simulated:
                    continue
                current = {p.device for p in self.stick.partitions()}
                for dev in current - self._known_sticks:
                    self._emit("stick_inserted", device=dev)
                for dev in self._known_sticks - current:
                    self._emit("stick_removed", device=dev)
                self._known_sticks = current
        threading.Thread(target=loop, name="usb-sticks", daemon=True).start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self.gadget.published:
            self.gadget.unpublish()
        self.dock.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    demo = config.DATA_DIR / "demo"
    if not (demo / "hart_kalibrierung.db").exists():
        print("Zuerst: python demo_data.py")
        raise SystemExit(1)
    svc = ExportService(simulate=True, staging_dir=demo / "export_staging",
                        sources={"db_path": demo / "hart_kalibrierung.db", "telemetry_path": demo / "none.db",
                                 "report_dir": demo / "reports", "photo_dir": demo / "photos",
                                 "label_dir": demo / "labels"})
    svc.gadget.image = demo / "hart_export.img"
    svc.subscribe(lambda e: print("EVENT:", e["event"], {k: v for k, v in e.items() if k not in ("status",)}))
    svc.dock.simulate(True)
    time.sleep(3)
    res = subprocess.run(["mdir", "-i", str(svc.gadget.image), "::/"], capture_output=True, text=True)
    print(res.stdout)
