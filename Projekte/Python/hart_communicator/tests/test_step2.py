"""Tests Schritt 2: INA226, Schleifenrelais, RTC, Feedback – ohne Hardware."""
import os
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

os.environ["HART_SIM"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import current_meter as cm
import feedback_manager as fm
import rtc_manager as rm
from loop_relays import InterlockError, LoopController, LoopMode


# ----------------------------------------------------------------- INA226
def meter(ma, shunt=3.3, tmp=None):
    src = {"ma": ma}
    m = cm.CurrentMeter(simulate=True, shunt_ohm=shunt, cal_file=tmp, sample_interval_s=0.01,
                        sim_current_source=lambda: src["ma"])
    return m, src


def test_config_register():
    assert cm.DEFAULT_CONFIG == 0x4727


def test_current_conversion_and_namur():
    m, src = meter(12.0)
    r = m.read()
    assert r.current_ma == pytest.approx(12.0, abs=0.001)
    assert r.percent == pytest.approx(50.0, abs=0.01)
    src["ma"] = 3.2
    assert m.read().namur_state.startswith("AUSFALL")


def test_10_ohm_shunt_overrange_detected():
    m, _ = meter(20.0, shunt=10.0)
    r = m.read()
    assert r.overrange and r.current_ma is None
    assert m.status()["range_ok"] is False
    with pytest.raises(cm.OverrangeError):
        m.read_stable(window_s=0.05, timeout_s=0.5)


def test_read_stable_and_timeout():
    m, src = meter(16.0)
    val, span = m.read_stable(window_s=0.06, timeout_s=2)
    assert val == pytest.approx(16.0, abs=0.001) and span < 0.001
    noisy = iter(range(10**6))
    src_fn = lambda: 10.0 + (next(noisy) % 2) * 0.05      # 50 µA Sprünge
    m2 = cm.CurrentMeter(simulate=True, shunt_ohm=3.3, cal_file=None, sample_interval_s=0.01,
                         sim_current_source=src_fn)
    with pytest.raises(TimeoutError):
        m2.read_stable(window_s=0.05, timeout_s=0.3)


def test_two_point_calibration_persists(tmp_path):
    f = tmp_path / "cal.json"
    m, _ = meter(4.0, tmp=f)
    cal = m.calibrate_two_point(4.0, 4.010, 20.0, 20.002, reference="Fluke 726")
    assert cal.apply(4.010) == pytest.approx(4.0) and cal.apply(20.002) == pytest.approx(20.0)
    assert not cal.is_due
    m2, _ = meter(4.0, tmp=f)
    assert m2.calibration.reference == "Fluke 726"
    with pytest.raises(ValueError):
        m.calibrate_two_point(4.0, 4.5, 20.0, 21.5)          # unplausibel


def test_uncalibrated_meter_is_due():
    m, _ = meter(4.0)
    assert m.calibration.is_due


def test_digital_analog_compare():
    assert cm.compare_digital_analog(12.0, 12.03)["ok"]
    res = cm.compare_digital_analog(12.0, 12.09)
    assert not res["ok"] and "Abweichung" in res["message"]


# ----------------------------------------------------------------- Relais
def test_loop_starts_passive_and_requires_confirmation():
    lc = LoopController(voltage_probe=lambda: 0.0)
    assert lc.mode == LoopMode.PASSIVE and not lc.k1_power.is_active
    with pytest.raises(InterlockError):
        lc.set_mode(LoopMode.ACTIVE_24V)
    lc.set_mode(LoopMode.ACTIVE_24V, confirmed=True)
    assert lc.k1_power.is_active and lc.k2_source.is_active and lc.k3_res.is_active
    lc.close()
    assert not lc.k1_power.is_active


def test_loop_interlocks():
    lc = LoopController(voltage_probe=lambda: 22.5)
    with pytest.raises(InterlockError, match="Fremdspannung"):
        lc.set_mode(LoopMode.ACTIVE_24V, confirmed=True)
    lc2 = LoopController(voltage_probe=lambda: 0.0)
    with pytest.raises(InterlockError, match="Stellungsregler"):
        lc2.set_mode(LoopMode.ACTIVE_24V, confirmed=True, is_positioner=True)
    assert lc.mode == lc2.mode == LoopMode.PASSIVE


def test_loop_break_before_make_order():
    lc = LoopController(voltage_probe=lambda: 0.0)
    log = []
    for name in ("k1_power", "k2_source", "k3_res"):
        r = getattr(lc, name)
        orig_on, orig_off = r.on, r.off
        r.on = lambda n=name, f=orig_on: (log.append(f"{n}+"), f())
        r.off = lambda n=name, f=orig_off: (log.append(f"{n}-"), f())
    lc.set_mode(LoopMode.ACTIVE_24V, confirmed=True)
    assert log[0] == "k1_power-" and log[-1] == "k1_power+"


def test_loop_auto_passive():
    lc = LoopController(voltage_probe=lambda: 0.0, auto_passive_min=1)
    lc.set_mode(LoopMode.PASSIVE_250R)
    assert not lc.check_auto_passive()
    lc._last_activity -= 61
    assert lc.check_auto_passive() and lc.mode == LoopMode.PASSIVE


# ----------------------------------------------------------------- RTC
@pytest.mark.parametrize("dt", [datetime(2026, 11, 13, 23, 59, 58, tzinfo=timezone.utc),
                                datetime(2099, 12, 31, 7, 5, 0, tzinfo=timezone.utc),
                                datetime(2101, 1, 1, 0, 0, 1, tzinfo=timezone.utc)])
def test_ds3231_bcd_roundtrip(dt):
    assert rm.decode_ds3231(rm.encode_ds3231(dt)) == dt


def test_ds3231_12h_mode():
    regs = rm.encode_ds3231(datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc))
    regs[2] = 0x40 | 0x20 | 0x03          # 12-h-Modus, PM, 3 Uhr -> 15 Uhr
    assert rm.decode_ds3231(regs).hour == 15


def test_rtc_sim_timestamp_and_manual_set():
    rtc = rm.RtcManager(simulate=True)
    ts = rtc.timestamp()
    assert ts["source"] in ("NTP", "RTC") and ts["trusted"]
    target = datetime(2030, 1, 2, 3, 4, 5)
    assert rtc.set_time_manual(target)["ok"]
    assert rtc.read_rtc().year == 2030


# ----------------------------------------------------------------- Feedback
def test_sound_synthesis(tmp_path):
    p = tmp_path / "beep.wav"
    fm.write_wav(p, fm.synthesize(fm.SOUNDS["beep"], 0.5))
    with wave.open(str(p)) as w:
        assert w.getframerate() == fm.SAMPLE_RATE
        assert 0.1 < w.getnframes() / w.getframerate() < 0.2


def test_feedback_priority_and_settings(tmp_path):
    f = fm.FeedbackManager(simulate=True, sound_dir=tmp_path, settings_file=tmp_path / "s.json")
    f._stop.set()                 # Worker anhalten, Queue-Reihenfolge prüfen
    time.sleep(0.6)
    for e in ("scan_ok", "touch", "alarm", "warning"):
        f.notify(e)
    order = [f._queue.get_nowait()[2] for _ in range(4)]
    assert order == ["alarm", "warning", "scan_ok", "touch"]
    f.update_settings(volume=150, sound_enabled=False)
    assert f.settings.volume == 100
    assert fm.FeedbackSettings.load(tmp_path / "s.json").sound_enabled is False


def test_all_events_reference_valid_sounds():
    for name, ev in fm.EVENTS.items():
        assert ev.sound is None or ev.sound in fm.SOUNDS, name
        assert len(ev.haptic) <= 8
