"""Tests Schritt 3: Display-Rotation und Eingabegeräte – ohne Hardware."""
import os
import sys
from pathlib import Path

os.environ["HART_SIM"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import input_monitor as im
import rotation_daemon as rd


# ============================================================ Rotation: Mathematik
@pytest.mark.parametrize("deg", [0, 90, 180, 270])
def test_angle_roundtrip(deg):
    s = rd.SimulatedLIS3DH()
    s.noise = 0
    s.set_orientation(deg)
    assert rd.angular_distance(rd.orientation_angle(*rd.map_axes(s.read_g())), deg) < 0.01


def test_hysteresis():
    assert rd.next_orientation(0, 50) == 0          # über 45°, aber innerhalb Hysterese
    assert rd.next_orientation(0, 59) == 0
    assert rd.next_orientation(0, 61) == 90
    assert rd.next_orientation(90, 35) == 90        # zurück erst unter 30°
    assert rd.next_orientation(90, 29) == 0
    assert rd.next_orientation(0, 185) == 180
    assert rd.next_orientation(270, 320) == 270     # 50° entfernt -> bleibt (über 0°/360° hinweg)
    assert rd.next_orientation(270, 335) == 0       # 65° entfernt -> wechselt


def test_layout():
    assert rd.layout_for(0) == rd.layout_for(180) == "portrait"
    assert rd.layout_for(90) == rd.layout_for(270) == "landscape"


def test_lis3dh_conversion():
    class FakeBus:
        def read_byte_data(self, a, r):
            return 0x33

        def write_byte_data(self, a, r, v):
            self.last = (r, v)

        def read_block(self, a, r, n):
            assert r == 0x28 | 0x80                 # Auto-Inkrement-Bit gesetzt
            vals = [1000 << 4, (-1000 << 4) & 0xFFFF, 250 << 4]   # +1 g, -1 g, +0,25 g
            return [b for v in vals for b in (v & 0xFF, v >> 8)]
    assert rd.LIS3DH(FakeBus()).read_g() == (1.0, -1.0, 0.25)


def test_lis3dh_wrong_chip():
    class FakeBus:
        def read_byte_data(self, a, r):
            return 0x44
    with pytest.raises(RuntimeError):
        rd.LIS3DH(FakeBus())


def test_parse_wlr_randr_outputs():
    text = 'DSI-1 "DSI-1"\n  Enabled: yes\n  Modes:\n    720x1280 px\nHDMI-A-1 "Dell"\n  Enabled: no\n'
    assert rd.WlrRandr.parse_outputs(text) == ["DSI-1", "HDMI-A-1"]


# ============================================================ Rotation: Daemon
@pytest.fixture
def daemon():
    d = rd.RotationDaemon(simulate=True, state_file=None, debounce_s=0.5)
    d.sensor.noise = 0
    d.applied = []
    orig = d.output.set_transform
    d.output.set_transform = lambda t: (d.applied.append(t), orig(t))[1]
    return d


def feed(d, deg, t0, seconds, tilt=0.0):
    d.sensor.set_orientation(deg, tilt)
    t, result = t0, None
    while t < t0 + seconds:
        r = d.process_sample(d.sensor.read_g(), now=t)
        result = r if r is not None else result
        t += 0.1
    return t, result


def test_debounce_requires_stable_position(daemon):
    t, r = feed(daemon, 90, 0.0, 0.3)
    assert r is None and daemon.state.orientation == 0     # zu kurz
    t, r = feed(daemon, 90, t, 1.0)
    assert r == 90 and daemon.applied[-1] == "90"


def test_shake_does_not_rotate(daemon):
    t = 0.0
    for _ in range(10):                        # Wackeln zwischen 0° und 90°
        t, _ = feed(daemon, 90, t, 0.2)
        t, _ = feed(daemon, 0, t, 0.2)
    assert daemon.state.orientation == 0 and not daemon.applied


def test_flat_and_lock(daemon):
    daemon.sensor.set_flat()
    for i in range(20):
        daemon.process_sample(daemon.sensor.read_g(), now=i * 0.1)
    assert daemon.state.flat and daemon.state.orientation == 0
    daemon.set_locked(True)
    t, r = feed(daemon, 180, 10.0, 3.0)
    assert r is None and daemon.state.orientation == 0
    daemon.set_locked(False)
    t, r = feed(daemon, 180, t, 3.0)
    assert daemon.state.orientation == 180


def test_dock_forces_landscape(daemon):
    daemon.set_docked(True)
    assert daemon.state.orientation == rd.DC.DOCK_ORIENTATION
    t, r = feed(daemon, 0, 0.0, 3.0)
    assert daemon.state.orientation == rd.DC.DOCK_ORIENTATION
    daemon.set_docked(False)
    t, r = feed(daemon, 0, t, 3.0)
    assert daemon.state.orientation == 0


def test_lock_persists(tmp_path):
    f = tmp_path / "rot.json"
    d = rd.RotationDaemon(simulate=True, state_file=f)
    d.apply(270)
    d.set_locked(True)
    d2 = rd.RotationDaemon(simulate=True, state_file=f)
    assert d2.state.locked and d2.state.orientation == 270


# ============================================================ Eingabe: Klassifizierung
LETTERS = sorted(im.LETTER_KEYS)
ABS_INFO = object()      # Platzhalter für evdev.AbsInfo


def caps(**kw):
    return {k: v for k, v in kw.items()}


def test_classify_keyboard():
    c = {im.EV_KEY: LETTERS + [im.KEY_ENTER, 1, 57]}
    assert im.classify("Logitech USB Keyboard", c, []) == {im.KEYBOARD}


def test_classify_mouse():
    c = {im.EV_KEY: [im.BTN_LEFT, 0x111, 0x112], im.EV_REL: [im.REL_X, im.REL_Y, 8]}
    assert im.classify("PixArt USB Optical Mouse", c, []) == {im.MOUSE}


def test_classify_touchscreen_with_absinfo_tuples():
    c = {im.EV_KEY: [im.BTN_TOUCH],
         im.EV_ABS: [(im.ABS_X, ABS_INFO), (1, ABS_INFO), (im.ABS_MT_POSITION_X, ABS_INFO)]}
    assert im.classify("generic ft5x06 (79)", c, [im.INPUT_PROP_DIRECT]) == {im.TOUCHSCREEN}


def test_classify_touchpad_counts_as_mouse():
    c = {im.EV_KEY: [im.BTN_LEFT, im.BTN_TOOL_FINGER, im.BTN_TOUCH], im.EV_ABS: [(im.ABS_X, ABS_INFO)]}
    assert im.classify("SynPS/2 Touchpad", c, [0x00]) == {im.MOUSE}


def test_classify_combo_keyboard_with_touchpad():
    c = {im.EV_KEY: LETTERS + [im.KEY_ENTER, im.BTN_LEFT], im.EV_REL: [im.REL_X, im.REL_Y]}
    assert im.classify("Logitech K400", c, []) == {im.KEYBOARD, im.MOUSE}


def test_classify_ignores_power_button_cec_and_numpad():
    assert im.classify("pwr_button", {im.EV_KEY: [116]}, []) == set()
    assert im.classify("vc4-hdmi-0", {im.EV_KEY: LETTERS + [im.KEY_ENTER]}, []) == set()
    numpad = {im.EV_KEY: list(range(71, 84)) + [96, im.KEY_ENTER]}
    assert im.classify("USB Numpad", numpad, []) == set()


# ============================================================ Eingabe: Regeln
class FakeGrabber:
    def __init__(self):
        self.active, self.calls = False, []

    def grab(self, paths):
        self.calls.append(("grab", paths))
        self.active = True

    def release(self):
        self.calls.append(("release",))
        self.active = False


@pytest.fixture
def monitor():
    m = im.InputMonitor(simulate=True)
    m.grab_touch = True                     # Policy inkl. Grab prüfen
    m.grabber = FakeGrabber()
    m.events = []
    m.subscribe(m.events.append)
    m.rescan()
    return m


def test_keyboard_hides_osk(monitor):
    assert monitor.status()["osk_enabled"]
    st = monitor.simulate_device("USB Keyboard", im.KEYBOARD)
    assert not st["osk_enabled"] and st["keyboard_navigation"] and not st["touch_blocked"]


def test_mouse_blocks_touch_and_grabs(monitor):
    st = monitor.simulate_device("USB Mouse", im.MOUSE)
    assert st["touch_blocked"] and st["touch_block_reasons"] == ["Maus angeschlossen"]
    assert monitor.grabber.calls[-1] == ("grab", ["/dev/input/event0"])
    st = monitor.simulate_device("USB Mouse", im.MOUSE, connected=False)
    assert not st["touch_blocked"] and monitor.grabber.calls[-1] == ("release",)


def test_mouse_rule_can_be_disabled(monitor):
    monitor.set_block_touch_with_mouse(False)
    assert not monitor.simulate_device("USB Mouse", im.MOUSE)["touch_blocked"]


def test_touch_lock_switch(monitor):
    st = monitor.simulate_touch_lock(True)
    assert st["touch_blocked"] and "Putzmodus" in st["touch_block_reasons"][0]
    monitor.simulate_device("USB Mouse", im.MOUSE)
    monitor.simulate_touch_lock(False)
    assert monitor.status()["touch_blocked"]            # Maus sperrt weiterhin
    assert monitor.grabber.calls.count(("release",)) == 0


def test_events_only_on_change(monitor):
    n = len(monitor.events)
    monitor.rescan()
    monitor.rescan()
    assert len(monitor.events) == n


def test_stop_releases_touch(monitor):
    monitor.simulate_touch_lock(True)
    monitor.stop()
    assert monitor.grabber.calls[-1] == ("release",) and not monitor.grabber.active
