"""Tests der Kernmodule – laufen komplett ohne Hardware:  pytest -q"""
import os
import sys
from pathlib import Path

os.environ["HART_SIM"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import battery_bms as bms
import hart_modem as hm
from device_catalog import DeviceCatalog, DeviceClass


# ----------------------------------------------------------------- HART-Codec
def test_packed_ascii_roundtrip():
    packed = hm.pack_ascii("pt-4711", 8)
    assert len(packed) == 6
    assert hm.unpack_ascii(packed) == "PT-4711 "


def test_packed_ascii_umlaut_and_invalid():
    assert hm.unpack_ascii(hm.pack_ascii("Küh{er", 8)).rstrip() == "KUEH?ER"


def test_frame_roundtrip_and_checksum():
    fr = hm.build_request(bytes([0x26, 0x06, 0x0A, 0x1B, 0x2C]), 3)
    raw = fr.encode()
    assert raw[:5] == b"\xFF" * 5 and raw[5] == 0x82
    parsed = hm.FrameParser().feed(b"\x00\x13" + raw)       # Störbytes davor
    assert len(parsed) == 1 and parsed[0].command == 3
    bad = bytearray(raw)
    bad[-1] ^= 0xFF
    p = hm.FrameParser()
    assert p.feed(bytes(bad)) == [] and p.errors


def test_parser_handles_fragmented_input():
    raw = hm.build_request(b"\x00", 0).encode()
    p = hm.FrameParser()
    frames = []
    for b in raw:
        frames += p.feed(bytes([b]))
    assert len(frames) == 1


# ----------------------------------------------------------------- HART-Modem
@pytest.fixture
def modem():
    bus = hm.SimulatedHartBus()
    bus.connect(hm.SIM_SCENARIOS["rosemount_3051"]())
    m = hm.HartModem(simulate=True, sim_bus=bus)
    m.transport.latency_s = 0
    return m


def test_identify(modem):
    info = modem.identify(0)
    assert info["tag"] == "PT-4711"
    assert info["unique_id"] == "26060A1B2C"
    assert "Rosemount 3051" in info["display_name"]
    assert info["range"]["upper_range"] == pytest.approx(2500)


def test_no_device_on_other_poll_address(modem):
    assert modem.poll(5) is None


def test_safe_mode_blocks_all_writes(modem):
    ident = modem.poll(0)
    assert modem.safe_mode
    for call in (lambda: modem.write_pv_unit(ident, 7),
                 lambda: modem.write_range(ident, 7, 0, 10),
                 lambda: modem.set_fixed_current(ident, 12.0),
                 lambda: modem.send(130, identity=ident)):       # gerätespezifisch
        with pytest.raises(hm.SafeModeError):
            call()


def test_writes_when_safe_mode_off(modem):
    ident = modem.poll(0)
    modem.set_safe_mode(False)
    rng = modem.write_range(ident, 7, -1.0, 5.0)
    assert rng["unit"] == "bar" and rng["lower_range"] == pytest.approx(-1.0)
    tags = modem.write_tag_info(ident, "PT-4712", "NEUER TEXT")
    assert tags["tag"] == "PT-4712"
    assert modem.set_fixed_current(ident, 12.0) == pytest.approx(12.0)
    assert modem.read_dynamic_variables(ident)["loop_current_ma"] == pytest.approx(12.0)
    modem.exit_fixed_current(ident)


def test_device_swap_changes_unique_id():
    bus = hm.SimulatedHartBus()
    m = hm.HartModem(simulate=True, sim_bus=bus)
    m.transport.latency_s = 0
    bus.connect(hm.SIM_SCENARIOS["rosemount_3051"]())
    a = m.identify()
    bus.connect(hm.SIM_SCENARIOS["rosemount_3051_replaced"]())
    b = m.identify()
    assert a["tag"] == b["tag"] and a["unique_id"] != b["unique_id"]


def test_positioner_detection_and_cmd40():
    bus = hm.SimulatedHartBus()
    dev = bus.connect(hm.SIM_SCENARIOS["siemens_sipart_ps2"]())
    m = hm.HartModem(simulate=True, sim_bus=bus, safe_mode=False)
    m.transport.latency_s = 0
    info = m.identify()
    assert info["is_positioner"] and info["universal_rev"] == 5
    m.set_fixed_current(info["identity"], 12.0)
    assert dev.process_percent == pytest.approx(50.0)


def test_analog_mismatch_visible():
    bus = hm.SimulatedHartBus()
    dev = bus.connect(hm.SIM_SCENARIOS["micromotion_5700"]())
    assert abs(dev.loop_current_ma() - dev.digital_current()) > 0.05


# ----------------------------------------------------------------- Katalog
def test_catalog_fallbacks(tmp_path):
    cat = DeviceCatalog(tmp_path / "user.json")
    assert cat.lookup(0x26, 0x2606).confidence == "exact"
    m = cat.lookup(0x13, 0x13FE)
    assert m.confidence == "manufacturer" and m.profile.is_positioner
    m = cat.lookup(0x99, 0x1234, pv_unit=57)
    assert m.confidence == "heuristic" and m.profile.is_positioner


def test_catalog_learn_persists(tmp_path):
    f = tmp_path / "user.json"
    DeviceCatalog(f).learn(0x2A, 0x2A77, model="SITRANS LR250", device_class=DeviceClass.LEVEL)
    m = DeviceCatalog(f).lookup(0x2A, 0x2A77)
    assert m.confidence == "user" and m.profile.model == "SITRANS LR250"


# ----------------------------------------------------------------- BMS
def test_crc8_reference_vector():
    assert bms.crc8(b"123456789") == 0xF4      # CRC-8/SMBUS Prüfwert


def test_bq_conversions_match_simulation():
    sim = bms.SimulatedBQ76930(start_soc=50)
    bq = bms.BQ76930(sim)
    bq.initialize()
    assert bq.gain_uv == 380 and bq.offset_mv == 12
    cells = bq.read_cells_v()
    assert len(cells) == 8 and all(3.0 < v < 3.4 for v in cells)
    assert bq.read_pack_v() == pytest.approx(sum(cells), abs=0.01)
    assert bq.read_temperatures_c()[0] == pytest.approx(24.0, abs=0.5)


def test_protection_registers():
    sim = bms.SimulatedBQ76930()
    bq = bms.BQ76930(sim)
    bq.initialize()
    ov_adc = 0x2008 | (sim.regs[bms.OV_TRIP] << 4)
    uv_adc = 0x1000 | (sim.regs[bms.UV_TRIP] << 4)
    assert (ov_adc * 380 + 12000) / 1e6 == pytest.approx(3.65, abs=0.01)
    assert (uv_adc * 380 + 12000) / 1e6 == pytest.approx(2.50, abs=0.01)
    assert sim.regs[bms.PROTECT1] & 0x80                    # RSNS


def test_balancing_rejects_adjacent_cells():
    sim = bms.SimulatedBQ76930()
    bq = bms.BQ76930(sim)
    assert bq.set_balancing({0, 1, 2}) == {0, 2}
    # Z4 (phys. 4) und Z5 (phys. 5) liegen in verschiedenen Gruppen -> erlaubt
    assert bq.set_balancing({3, 4}) == {3, 4}


def test_soc_ocv_curve_monotonic():
    vals = [bms.ocv_to_soc(2.4 + i * 0.01) for i in range(130)]
    assert vals == sorted(vals)
    assert bms.ocv_to_soc(bms.soc_to_ocv(50)) == pytest.approx(50, abs=0.5)


def test_monitor_publishes_status():
    import time
    mon = bms.BatteryMonitor(simulate=True, state_file=None, poll_interval_s=0.2).start()
    try:
        time.sleep(0.8)
        st = mon.latest()
        assert st is not None and st.current_a < 0 and 0 < st.soc_percent <= 100
        assert set(st.to_telemetry()) >= {"pack_voltage_v", "cell_8_v", "cell_drift_mv"}
    finally:
        mon.stop()
