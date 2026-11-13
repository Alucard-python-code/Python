"""
rotation_daemon.py – Automatische Display-Drehung per Lagesensor (LIS3DH @ 0x18).

Ablauf:
  LIS3DH (25 Hz, ±2 g, High-Res) -> Tiefpass -> Lagewinkel in der Displayebene
  -> Hysterese (±(45°+15°)) + Entprellung (0,6 s) + Flach-Erkennung
  -> `wlr-randr --output DSI-1 --transform …` -> Ereignis an die UI

Bedienlogik:
  * Rotation-Lock (Button in der Statusleiste): friert die aktuelle Lage ein, bleibt
    über Neustarts erhalten.
  * Dock: Im Dock wird fest auf Display.DOCK_ORIENTATION (Querformat-Dashboard)
    gedreht, beim Abdocken wieder automatisch.
  * Flach liegend (auf dem Tisch) wird nie gedreht.

Touch-Matrix:
  Unter labwc folgt der Touchscreen der Display-Transformation, wenn er per
  `mapToOutput` an den DSI-Ausgang gebunden ist (siehe deploy/labwc-rc.xml).
  Damit dreht `wlr-randr` Bild UND Touch gemeinsam – ohne Neustart.

Einbaulage kalibrieren:  python rotation_daemon.py --calibrate
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import config
from hw_compat import get_i2c_bus, simulation_requested

log = logging.getLogger(__name__)
DC = config.Display
ORIENTATIONS = (0, 90, 180, 270)

# LIS3DH-Register
WHO_AM_I, WHO_AM_I_VALUE = 0x0F, 0x33
CTRL_REG1, CTRL_REG4, OUT_X_L = 0x20, 0x23, 0x28
AUTO_INCREMENT = 0x80
CTRL1_25HZ_XYZ = 0x37          # ODR 25 Hz, Normalbetrieb, X/Y/Z aktiv
CTRL4_BDU_2G_HR = 0x88         # Block Data Update, ±2 g, High-Resolution (1 mg/digit)


# =============================================================================
# Lagesensor
# =============================================================================
class LIS3DH:
    def __init__(self, bus, addr: int = config.I2CAddr.LIS3DH):
        self.bus, self.addr = bus, addr
        who = bus.read_byte_data(addr, WHO_AM_I)
        if who != WHO_AM_I_VALUE:
            raise RuntimeError(f"LIS3DH nicht erkannt (WHO_AM_I 0x{who:02X})")
        bus.write_byte_data(addr, CTRL_REG1, CTRL1_25HZ_XYZ)
        bus.write_byte_data(addr, CTRL_REG4, CTRL4_BDU_2G_HR)

    def read_g(self) -> tuple[float, float, float]:
        raw = self.bus.read_block(self.addr, OUT_X_L | AUTO_INCREMENT, 6)
        out = []
        for i in range(3):
            v = raw[2 * i] | (raw[2 * i + 1] << 8)
            if v & 0x8000:
                v -= 0x10000
            out.append((v >> 4) / 1000.0)      # 12 Bit linksbündig, 1 mg/digit
        return out[0], out[1], out[2]


class SimulatedLIS3DH:
    """Simulierter Sensor. `set_orientation()` dreht das virtuelle Gerät."""

    def __init__(self):
        self.vector = (0.0, 1.0, 0.0)
        self.noise = 0.01

    def set_orientation(self, degrees_cw: float, tilt_deg: float = 0.0) -> None:
        r = math.radians(degrees_cw)
        inplane = math.cos(math.radians(tilt_deg))
        # Umkehrung von orientation_angle(): Winkel = -atan2(x, y)
        self.vector = (-math.sin(r) * inplane, math.cos(r) * inplane, math.sin(math.radians(tilt_deg)))

    def set_flat(self) -> None:
        self.vector = (0.0, 0.0, 1.0)

    def read_g(self) -> tuple[float, float, float]:
        import random
        return tuple(v + random.gauss(0, self.noise) for v in self.vector)


# =============================================================================
# Lageberechnung (rein funktional -> gut testbar)
# =============================================================================
def map_axes(raw: tuple[float, float, float]) -> tuple[float, float]:
    """Sensorachsen -> Displayachsen gemäß Einbaulage (config.Display.AXIS_X/Y)."""
    idx = {"x": 0, "y": 1, "z": 2}
    (ax, sx), (ay, sy) = DC.AXIS_X, DC.AXIS_Y
    return raw[idx[ax]] * sx, raw[idx[ay]] * sy


def orientation_angle(dx: float, dy: float) -> float:
    """Physische Drehung des Geräts im Uhrzeigersinn in Grad (0 = aufrecht Hochformat)."""
    return (-math.degrees(math.atan2(dx, dy))) % 360.0


def angular_distance(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def next_orientation(current: int, angle: float, hysteresis: float = DC.HYSTERESIS_DEG) -> int:
    """Bleibt bei `current`, solange der Winkel weniger als 45°+Hysterese entfernt ist."""
    if angular_distance(angle, current) < 45.0 + hysteresis:
        return current
    return min(ORIENTATIONS, key=lambda o: angular_distance(angle, o))


def layout_for(orientation: int) -> str:
    return "portrait" if orientation in (0, 180) else "landscape"


# =============================================================================
# Wayland-Ausgabe
# =============================================================================
class WlrRandr:
    def __init__(self, output: Optional[str] = DC.OUTPUT_NAME, simulate: bool = False):
        self.simulate = simulate or shutil.which("wlr-randr") is None
        self.output = output
        self.last_error: Optional[str] = None
        if not self.simulate and not self.output:
            self.output = self.detect_output()

    @staticmethod
    def _env() -> dict:
        env = dict(os.environ)
        env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        if "WAYLAND_DISPLAY" not in env:
            sockets = sorted(Path(env["XDG_RUNTIME_DIR"]).glob("wayland-[0-9]"))
            if sockets:
                env["WAYLAND_DISPLAY"] = sockets[0].name
        return env

    @staticmethod
    def parse_outputs(text: str) -> list[str]:
        """Ausgabenamen aus der Klartextausgabe von wlr-randr (Zeilen ohne Einrückung)."""
        return [m.group(1) for m in re.finditer(r"^(\S+)\s", text, re.MULTILINE)]

    def detect_output(self) -> Optional[str]:
        try:
            res = subprocess.run(["wlr-randr"], capture_output=True, text=True, timeout=5, env=self._env())
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.error("wlr-randr nicht ausführbar: %s", exc)
            return None
        outputs = self.parse_outputs(res.stdout)
        dsi = [o for o in outputs if o.upper().startswith("DSI")]
        chosen = (dsi or outputs or [None])[0]
        log.info("Wayland-Ausgänge %s -> verwende %s", outputs, chosen)
        return chosen

    def set_transform(self, transform: str) -> bool:
        if self.simulate:
            log.info("[SIM] wlr-randr --output %s --transform %s", self.output or "DSI-1", transform)
            return True
        if not self.output:
            self.last_error = "Kein Wayland-Ausgang gefunden"
            return False
        cmd = ["wlr-randr", "--output", self.output, "--transform", transform]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5, env=self._env())
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.last_error = str(exc)
            log.error("Rotation fehlgeschlagen: %s", exc)
            return False
        if res.returncode != 0:
            self.last_error = res.stderr.strip()
            log.error("wlr-randr: %s", self.last_error)
            return False
        self.last_error = None
        return True


# =============================================================================
# Daemon
# =============================================================================
@dataclass
class RotationState:
    orientation: int = 0
    locked: bool = False
    docked: bool = False
    flat: bool = False
    angle: Optional[float] = None
    error: Optional[str] = None

    @property
    def forced(self) -> Optional[int]:
        return DC.DOCK_ORIENTATION if self.docked and DC.DOCK_ORIENTATION is not None else None

    def to_dict(self) -> dict:
        return {"orientation": self.orientation, "transform": DC.TRANSFORM_FOR[self.orientation],
                "layout": layout_for(self.orientation), "locked": self.locked, "docked": self.docked,
                "forced": self.forced, "flat": self.flat,
                "angle": None if self.angle is None else round(self.angle, 1), "error": self.error}


class RotationDaemon:
    def __init__(self, *, simulate: Optional[bool] = None, state_file: Optional[Path] = DC.STATE_FILE,
                 sample_hz: float = 10.0, debounce_s: float = DC.DEBOUNCE_S):
        if simulate is None:
            simulate = simulation_requested("rotation")
        self.sensor = None
        if not simulate:
            bus = get_i2c_bus(config.I2C_BUS, component="rotation")
            if bus and bus.probe(config.I2CAddr.LIS3DH):
                try:
                    self.sensor = LIS3DH(bus)
                except (OSError, RuntimeError) as exc:
                    log.error("LIS3DH: %s – Simulation", exc)
            else:
                log.error("LIS3DH an 0x%02X nicht gefunden – Simulation", config.I2CAddr.LIS3DH)
        if self.sensor is None:
            simulate = True
            self.sensor = SimulatedLIS3DH()
        self.simulated = simulate
        self.output = WlrRandr(simulate=simulate)
        self.state_file = state_file
        self.sample_s = 1.0 / sample_hz
        self.debounce_s = debounce_s
        self.state = RotationState()
        self._filtered: Optional[tuple[float, float]] = None
        self._candidate: Optional[int] = None
        self._candidate_since = 0.0
        self._lock = threading.RLock()
        self._subs: list[Callable[[dict], None]] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._load_state()

    # ---------- Persistenz ----------
    def _load_state(self) -> None:
        if self.state_file and Path(self.state_file).exists():
            try:
                st = json.loads(Path(self.state_file).read_text())
                self.state.locked = bool(st.get("locked", False))
                if st.get("orientation") in ORIENTATIONS:
                    self.state.orientation = st["orientation"]
            except (OSError, ValueError) as exc:
                log.warning("Rotationszustand unlesbar: %s", exc)

    def _save_state(self) -> None:
        if not self.state_file:
            return
        try:
            p = Path(self.state_file)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"locked": self.state.locked, "orientation": self.state.orientation}))
        except OSError as exc:
            log.warning("Rotationszustand nicht speicherbar: %s", exc)

    # ---------- API ----------
    def subscribe(self, cb: Callable[[dict], None]) -> None:
        self._subs.append(cb)

    def status(self) -> dict:
        with self._lock:
            d = self.state.to_dict()
        d["simulated"] = self.simulated
        return d

    def set_locked(self, locked: bool) -> dict:
        with self._lock:
            self.state.locked = locked
            self._candidate = None
            self._save_state()
        log.info("Rotation %s", "gesperrt" if locked else "entsperrt")
        self._publish()
        return self.status()

    def toggle_lock(self) -> dict:
        return self.set_locked(not self.state.locked)

    def set_docked(self, docked: bool) -> dict:
        """Von dual_usb_export/Dock-Erkennung (GPIO23) aufzurufen."""
        with self._lock:
            self.state.docked = docked
            forced = self.state.forced
        if forced is not None:
            self.apply(forced, reason="Dock")
        else:
            self._candidate = None
            self._publish()
        return self.status()

    def apply(self, orientation: int, reason: str = "Sensor") -> bool:
        if orientation not in ORIENTATIONS:
            raise ValueError(orientation)
        with self._lock:
            ok = self.output.set_transform(DC.TRANSFORM_FOR[orientation])
            self.state.error = None if ok else self.output.last_error
            if ok:
                changed = orientation != self.state.orientation
                self.state.orientation = orientation
                self._save_state()
                if changed:
                    log.info("Display gedreht auf %d° (%s, %s)", orientation, layout_for(orientation), reason)
        self._publish()
        return ok

    # ---------- Auswertung ----------
    def process_sample(self, raw: tuple[float, float, float], now: Optional[float] = None) -> Optional[int]:
        """Verarbeitet einen Messwert. Gibt die neue Lage zurück, wenn gedreht wurde."""
        now = time.monotonic() if now is None else now
        dx, dy = map_axes(raw)
        if self._filtered is None:
            self._filtered = (dx, dy)
        else:  # Tiefpass gegen Erschütterungen beim Tragen
            fx, fy = self._filtered
            self._filtered = (fx + 0.35 * (dx - fx), fy + 0.35 * (dy - fy))
        fx, fy = self._filtered
        with self._lock:
            st = self.state
            st.flat = math.hypot(fx, fy) < DC.FLAT_IN_PLANE_G
            st.angle = None if st.flat else orientation_angle(fx, fy)
            if st.locked or st.forced is not None or st.flat:
                self._candidate = None
                return None
            target = next_orientation(st.orientation, st.angle)
            if target == st.orientation:
                self._candidate = None
                return None
            if self._candidate != target:
                self._candidate, self._candidate_since = target, now
                return None
            if now - self._candidate_since < self.debounce_s:
                return None
            self._candidate = None
        self.apply(target)
        return target

    def calibrate_now(self) -> dict:
        """Aktuelle Lage sofort übernehmen (z.B. nach dem Entsperren)."""
        raw = self.sensor.read_g()
        dx, dy = map_axes(raw)
        self._filtered = (dx, dy)
        if math.hypot(dx, dy) >= DC.FLAT_IN_PLANE_G and not self.state.locked:
            self.apply(min(ORIENTATIONS, key=lambda o: angular_distance(orientation_angle(dx, dy), o)),
                       reason="Start")
        return self.status()

    # ---------- Thread ----------
    def start(self) -> "RotationDaemon":
        self.apply(self.state.orientation, reason="Wiederherstellung")
        if not self.state.locked:
            self.calibrate_now()
        self._thread = threading.Thread(target=self._run, name="rotation", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.wait(self.sample_s):
            try:
                self.process_sample(self.sensor.read_g())
            except OSError as exc:
                log.warning("LIS3DH-Lesefehler: %s", exc)
                time.sleep(1.0)
            except Exception:
                log.exception("Rotation")

    def _publish(self) -> None:
        st = self.status()
        for cb in list(self._subs):
            try:
                cb(st)
            except Exception:
                log.exception("Rotation-Subscriber")


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if "--calibrate" in sys.argv:
        d = RotationDaemon(state_file=None)
        print("Gerät nacheinander aufrecht (0°), nach rechts (90°), kopfüber (180°), nach links (270°)")
        print("halten. Die angezeigte Lage muss der tatsächlichen entsprechen. Strg+C beendet.\n")
        try:
            while True:
                raw = d.sensor.read_g()
                dx, dy = map_axes(raw)
                flat = math.hypot(dx, dy) < DC.FLAT_IN_PLANE_G
                ang = orientation_angle(dx, dy)
                near = min(ORIENTATIONS, key=lambda o: angular_distance(ang, o))
                print(f"\rroh x={raw[0]:+.2f} y={raw[1]:+.2f} z={raw[2]:+.2f} g | "
                      f"{'FLACH' if flat else f'{ang:5.1f}° -> {near:3d}°'}      ", end="", flush=True)
                time.sleep(0.2)
        except KeyboardInterrupt:
            print()
        sys.exit(0)

    d = RotationDaemon(simulate=True, state_file=None, debounce_s=0.2)
    d.subscribe(lambda s: print("  -> UI:", s["orientation"], s["layout"], "Lock" if s["locked"] else ""))
    d.start()
    for deg in (90, 30, 180, 270):
        print(f"Gerät auf {deg}° gedreht")
        d.sensor.set_orientation(deg)
        time.sleep(0.8)
    d.set_docked(True)
    d.sensor.set_orientation(0)
    time.sleep(0.6)
    print("Im Dock bleibt:", d.status()["orientation"])
    d.stop()
