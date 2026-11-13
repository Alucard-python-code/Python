"""
input_monitor.py – Hotplug-Erkennung von Maus/Tastatur und Touch-Sperre.

Regeln:
  * Tastatur angeschlossen  -> On-Screen-Tastatur aus, volle Tastatursteuerung (Enter/Esc/Tab)
  * Maus angeschlossen      -> Touch gesperrt (kein versehentliches Auslösen), abschaltbar
  * Schiebeschalter GPIO16 LOW ("Putzmodus") -> Touch gesperrt, gelbes Schloss im Header

Touch-Sperre in zwei Ebenen:
  1. Kernel: exklusiver EVIOCGRAB auf den Touchscreen -> der Compositor (labwc) erhält
     KEINE Touch-Ereignisse mehr, auch nicht außerhalb des Browsers. Stürzt die App ab,
     schließt der Kernel das Handle und gibt den Touch automatisch wieder frei (fail-safe).
  2. UI: das Ereignis `touch_blocked` blendet ein Sperr-Overlay ein (für den Fall, dass
     der Grab nicht möglich ist, z.B. fehlende Rechte).

Geräteklassifizierung über evdev-Fähigkeiten (nicht über Namen):
  Tastatur     – ≥ 20 Buchstabentasten + Enter   (filtert Power-Button, HDMI-CEC usw. aus)
  Maus         – relative X/Y-Achsen + linke Taste, oder Touchpad (ABS ohne DIRECT-Flag)
  Touchscreen  – absolute Achsen + INPUT_PROP_DIRECT

Hotplug: pyudev-Netlink (sofort), zusätzlich Polling von /dev/input als Rückfallebene.
Rechte: Dienstbenutzer muss in der Gruppe `input` sein (sudo usermod -aG input hart).
"""
from __future__ import annotations

import logging
import os
import select
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

import config
from hw_compat import digital_input, simulation_requested

log = logging.getLogger(__name__)
IC = config.Input

# Linux input-event-codes.h (fest -> Klassifizierung auch ohne evdev testbar)
EV_KEY, EV_REL, EV_ABS = 0x01, 0x02, 0x03
REL_X, REL_Y = 0x00, 0x01
ABS_X, ABS_MT_POSITION_X = 0x00, 0x35
BTN_LEFT, BTN_TOOL_FINGER, BTN_TOUCH = 0x110, 0x145, 0x14A
KEY_ENTER = 28
LETTER_KEYS = frozenset(list(range(16, 26)) + list(range(30, 39)) + list(range(44, 51)))  # Q-P, A-L, Z-M
INPUT_PROP_DIRECT = 0x01

KEYBOARD, MOUSE, TOUCHSCREEN = "keyboard", "mouse", "touchscreen"


def _codes(caps: dict, ev_type: int) -> set[int]:
    """evdev liefert bei EV_ABS Tupel (code, AbsInfo) – auf Codes normieren."""
    return {c[0] if isinstance(c, tuple) else c for c in caps.get(ev_type, [])}


def classify(name: str, caps: dict, props: Iterable[int]) -> set[str]:
    """Ordnet ein Eingabegerät anhand seiner Fähigkeiten Klassen zu (auch mehrere,
    z.B. Funktastatur mit integriertem Touchpad)."""
    lname = name.lower()
    if any(ign in lname for ign in IC.IGNORE_NAMES):
        return set()
    keys, rel, absax = _codes(caps, EV_KEY), _codes(caps, EV_REL), _codes(caps, EV_ABS)
    props = set(props)
    kinds: set[str] = set()
    if len(keys & LETTER_KEYS) >= IC.MIN_LETTER_KEYS and KEY_ENTER in keys:
        kinds.add(KEYBOARD)
    if {REL_X, REL_Y} <= rel and BTN_LEFT in keys:
        kinds.add(MOUSE)
    if absax & {ABS_X, ABS_MT_POSITION_X}:
        if INPUT_PROP_DIRECT in props:
            kinds.add(TOUCHSCREEN)
        elif BTN_TOOL_FINGER in keys:
            kinds.add(MOUSE)                       # Touchpad = Zeigegerät
    return kinds


@dataclass
class DeviceInfo:
    path: str
    name: str
    kinds: set[str]
    phys: str = ""

    def to_dict(self) -> dict:
        return {"path": self.path, "name": self.name, "kinds": sorted(self.kinds)}


@dataclass
class InputState:
    devices: list[DeviceInfo] = field(default_factory=list)
    touch_lock_switch: bool = False
    block_touch_with_mouse: bool = IC.BLOCK_TOUCH_WITH_MOUSE
    grab_active: bool = False
    grab_error: Optional[str] = None

    def of_kind(self, kind: str) -> list[DeviceInfo]:
        return [d for d in self.devices if kind in d.kinds]

    @property
    def keyboard_connected(self) -> bool:
        return bool(self.of_kind(KEYBOARD))

    @property
    def mouse_connected(self) -> bool:
        return bool(self.of_kind(MOUSE))

    @property
    def touch_block_reasons(self) -> list[str]:
        r = []
        if self.touch_lock_switch:
            r.append("Putzmodus (Schiebeschalter)")
        if self.mouse_connected and self.block_touch_with_mouse:
            r.append("Maus angeschlossen")
        return r

    @property
    def touch_blocked(self) -> bool:
        return bool(self.touch_block_reasons)

    def to_dict(self) -> dict:
        return {
            "keyboards": [d.name for d in self.of_kind(KEYBOARD)],
            "mice": [d.name for d in self.of_kind(MOUSE)],
            "touchscreens": [d.name for d in self.of_kind(TOUCHSCREEN)],
            "keyboard_connected": self.keyboard_connected,
            "mouse_connected": self.mouse_connected,
            "osk_enabled": not self.keyboard_connected,          # On-Screen-Tastatur
            "keyboard_navigation": self.keyboard_connected,      # Enter/Esc/Tab-Steuerung
            "touch_lock_switch": self.touch_lock_switch,
            "touch_blocked": self.touch_blocked,
            "touch_block_reasons": self.touch_block_reasons,
            "block_touch_with_mouse": self.block_touch_with_mouse,
            "grab_active": self.grab_active,
            "grab_error": self.grab_error,
        }


# =============================================================================
# Touch-Sperre auf Kernel-Ebene
# =============================================================================
class TouchGrabber:
    """Exklusiver Grab aller Touchscreens + Leerlesen der Ereignisse."""

    def __init__(self):
        self._devs: list = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def active(self) -> bool:
        return bool(self._devs)

    def grab(self, paths: list[str]) -> Optional[str]:
        self.release()
        if not paths:
            return "Kein Touchscreen gefunden"
        import evdev
        errors = []
        for p in paths:
            try:
                dev = evdev.InputDevice(p)
                dev.grab()
                self._devs.append(dev)
            except OSError as exc:
                errors.append(f"{p}: {exc}")
        if self._devs:
            self._stop.clear()
            self._thread = threading.Thread(target=self._drain, name="touch-grab", daemon=True)
            self._thread.start()
        if errors:
            log.error("Touch-Grab fehlgeschlagen: %s", errors)
        return "; ".join(errors) or None

    def _drain(self) -> None:
        while not self._stop.is_set() and self._devs:
            try:
                r, _, _ = select.select(self._devs, [], [], 0.3)
                for dev in r:
                    for _ in dev.read():
                        pass                     # verwerfen
            except (OSError, ValueError):
                break                            # Gerät abgezogen / geschlossen

    def release(self) -> None:
        self._stop.set()
        for dev in self._devs:
            try:
                dev.ungrab()
            except OSError:
                pass
            try:
                dev.close()
            except OSError:
                pass
        self._devs = []
        if self._thread:
            self._thread.join(timeout=1)
            self._thread = None


# =============================================================================
# InputMonitor
# =============================================================================
class InputMonitor:
    def __init__(self, *, simulate: Optional[bool] = None, grab_touch: bool = IC.GRAB_TOUCH_DEVICE):
        if simulate is None:
            simulate = simulation_requested("input")
        self._evdev = None
        if not simulate:
            try:
                import evdev
                self._evdev = evdev
            except ImportError:
                log.error("python-evdev fehlt – Eingabegeräte werden simuliert")
                simulate = True
        self.simulated = simulate
        self.grab_touch = grab_touch and not simulate
        self.state = InputState()
        self._sim_devices: dict[str, DeviceInfo] = {}
        if simulate:
            self._sim_devices["/dev/input/event0"] = DeviceInfo(
                "/dev/input/event0", "Simulated Touch Display 2", {TOUCHSCREEN})
        self.grabber = TouchGrabber()
        self._lock = threading.RLock()
        self._subs: list[Callable[[dict], None]] = []
        self._stop = threading.Event()
        self._rescan_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._observer = None
        self._last_published: Optional[dict] = None

        self.switch = digital_input(config.Pins.TOUCH_LOCK, pull_up=True, bounce_time=0.05,
                                    component="input")    # pull_up -> aktiv = LOW = gesperrt
        self.switch.when_activated = lambda *_: self._on_switch(True)
        self.switch.when_deactivated = lambda *_: self._on_switch(False)
        self.state.touch_lock_switch = bool(self.switch.is_active)

    # ---------- Abos / Status ----------
    def subscribe(self, cb: Callable[[dict], None]) -> None:
        self._subs.append(cb)

    def status(self) -> dict:
        with self._lock:
            d = self.state.to_dict()
        d["simulated"] = self.simulated
        return d

    def set_block_touch_with_mouse(self, enabled: bool) -> dict:
        with self._lock:
            self.state.block_touch_with_mouse = enabled
        self._apply_policy()
        return self.status()

    # ---------- Geräteerkennung ----------
    def scan(self) -> list[DeviceInfo]:
        if self.simulated:
            return list(self._sim_devices.values())
        found = []
        for path in self._evdev.list_devices():
            try:
                dev = self._evdev.InputDevice(path)
                kinds = classify(dev.name, dev.capabilities(), dev.input_props())
                if kinds:
                    found.append(DeviceInfo(path, dev.name, kinds, dev.phys or ""))
                dev.close()
            except OSError as exc:                 # Gerät gerade abgezogen / keine Rechte
                log.debug("%s nicht lesbar: %s", path, exc)
        return found

    def rescan(self) -> dict:
        devices = self.scan()
        with self._lock:
            old = {d.path: d for d in self.state.devices}
            new = {d.path: d for d in devices}
            for p in new.keys() - old.keys():
                log.info("Eingabegerät angeschlossen: %s %s", new[p].name, sorted(new[p].kinds))
            for p in old.keys() - new.keys():
                log.info("Eingabegerät entfernt: %s", old[p].name)
            self.state.devices = sorted(devices, key=lambda d: d.path)
        self._apply_policy()
        return self.status()

    def _on_switch(self, locked: bool) -> None:
        log.warning("Touch-Lock-Schalter: %s", "GESPERRT (Putzmodus)" if locked else "frei")
        with self._lock:
            self.state.touch_lock_switch = locked
        self._apply_policy()

    def _apply_policy(self) -> None:
        with self._lock:
            want = self.state.touch_blocked
            if self.grab_touch:
                if want and not self.grabber.active:
                    paths = [d.path for d in self.state.of_kind(TOUCHSCREEN)]
                    self.state.grab_error = self.grabber.grab(paths)
                elif not want and self.grabber.active:
                    self.grabber.release()
                    self.state.grab_error = None
            self.state.grab_active = self.grabber.active if self.grab_touch else want
        self._publish()

    def _publish(self) -> None:
        st = self.status()
        if st == self._last_published:
            return
        self._last_published = st
        for cb in list(self._subs):
            try:
                cb(st)
            except Exception:
                log.exception("Input-Subscriber")

    # ---------- Simulation ----------
    def simulate_device(self, name: str, kind: str, connected: bool = True) -> dict:
        path = f"/dev/input/sim-{kind}-{abs(hash(name)) % 1000}"
        if connected:
            self._sim_devices[path] = DeviceInfo(path, name, {kind})
        else:
            self._sim_devices = {p: d for p, d in self._sim_devices.items()
                                 if not (d.name == name and kind in d.kinds)}
        return self.rescan()

    def simulate_touch_lock(self, locked: bool) -> dict:
        self.switch.simulate_level(locked)
        return self.status()

    # ---------- Hotplug ----------
    def start(self) -> "InputMonitor":
        self.rescan()
        if not self.simulated:
            try:
                import pyudev
                ctx = pyudev.Context()
                mon = pyudev.Monitor.from_netlink(ctx)
                mon.filter_by("input")
                self._observer = pyudev.MonitorObserver(mon, callback=lambda _dev: self._rescan_event.set(),
                                                        name="udev-input")
                self._observer.start()
            except Exception as exc:
                log.warning("pyudev nicht verfügbar (%s) – nur Polling", exc)
        self._thread = threading.Thread(target=self._run, name="input-monitor", daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        last_listing: Optional[list[str]] = None
        while not self._stop.is_set():
            triggered = self._rescan_event.wait(IC.POLL_INTERVAL_S)
            if self._stop.is_set():
                break
            if triggered:
                self._rescan_event.clear()
                time.sleep(0.3)          # udev legt mehrere Knoten pro Gerät an -> zusammenfassen
                self._rescan_event.clear()
                self._safe_rescan()
                continue
            if self.simulated:
                continue
            try:
                listing = sorted(os.listdir("/dev/input"))
            except OSError:
                continue
            if listing != last_listing:
                last_listing = listing
                self._safe_rescan()

    def _safe_rescan(self) -> None:
        try:
            self.rescan()
        except Exception:
            log.exception("Rescan der Eingabegeräte")

    def stop(self) -> None:
        self._stop.set()
        self._rescan_event.set()
        if self._observer is not None:
            self._observer.stop()
        if self._thread:
            self._thread.join(timeout=3)
        self.grabber.release()             # Touch NIE gesperrt zurücklassen
        self.switch.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    import sys
    sim = "--hw" not in sys.argv
    mon = InputMonitor(simulate=sim)
    mon.subscribe(lambda s: print(f"  -> UI: Tastatur={s['keyboard_connected']} OSK={s['osk_enabled']} "
                                  f"Touch gesperrt={s['touch_blocked']} {s['touch_block_reasons']}"))
    mon.start()
    if sim:
        mon.simulate_device("Logitech K120", KEYBOARD)
        mon.simulate_device("Logitech M90", MOUSE)
        mon.simulate_device("Logitech M90", MOUSE, connected=False)
        mon.simulate_touch_lock(True)
        mon.simulate_touch_lock(False)
        mon.stop()
    else:
        print("Geräte an-/abstecken, Strg+C beendet")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            mon.stop()
