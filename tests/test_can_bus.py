"""Listening to the OBD port's CAN bus: can-check and record, against virtual cars."""
import csv
import json

import pytest

from car_use.doctor import port
from car_use.doctor.report import PrivacyError
from car_use.obd.elm import Elm327
from car_use.obd.monitor import is_diagnostic, listen, mask_for, parse_line, validate_id
from car_use.obd.vehicle import ObdVehicle
from car_use.record import Recorder, RecordError
from car_use.run import main
from car_use.sim.emulator import Emulator
from car_use.sim.scenario import from_dict, load, read_raw
from car_use.transport.base import open_transport


@pytest.fixture
def bus_car():
    """open-bus with a chosen adapter profile (genuine overflows, clone cannot listen)."""
    opened = []

    def _open(profile="stn"):
        raw = read_raw("open-bus")
        raw["adapter"]["profile"] = profile
        emu = Emulator(from_dict(raw, name="open-bus")).start()
        v = ObdVehicle(Elm327(open_transport(emu.url)), emu.url, scenario=emu.scenario)
        v._emulator = emu
        opened.append(v)
        return v.connect()
    yield _open
    for v in opened:
        v.elm.close()
        v._emulator.stop()


# -- parsing ---------------------------------------------------------------------

def test_parse_line_reads_spaced_and_compact_11_and_29_bit_frames():
    assert parse_line("025 08 00 11 22 33 44 55 66") == ("025", bytes.fromhex("0800112233445566"))
    assert parse_line("0250800112233445566") == ("025", bytes.fromhex("0800112233445566"))
    assert parse_line("18 FE F1 00 01 02 03") == ("18FEF100", bytes.fromhex("010203"))
    assert parse_line("18FEF100010203") == ("18FEF100", bytes.fromhex("010203"))
    assert parse_line("1A0") == ("1A0", b"")
    for junk in ("BUFFER FULL", "STOPPED", "<DATA ERROR", "?", "", "FFF 00", "25 00",
                 "025 00 11 22 33 44 55 66 77 88"):
        assert parse_line(junk) is None, junk


def test_diagnostic_ids_are_not_the_cars_own_traffic():
    for ident in ("7DF", "7E0", "7E8", "7EF", "18DB33F1", "18DAF110"):
        assert is_diagnostic(ident)
    for ident in ("025", "1A0", "7A0", "18FEF100"):
        assert not is_diagnostic(ident)


def test_mask_passes_every_chosen_id():
    ids = ["025", "1A0", "3B7"]
    filt, mask = mask_for(ids)
    f, m = int(filt, 16), int(mask, 16)
    assert all(int(i, 16) & m == f & m for i in ids)
    filt, mask = mask_for(["025"])
    assert (filt, mask) == ("025", "7FF")
    with pytest.raises(ValueError):
        mask_for(["025", "18FEF100"])
    assert validate_id("25") == "025"
    for bad in ("800", "XYZ", "12345"):
        with pytest.raises(ValueError):
            validate_id(bad)


# -- verdicts ----------------------------------------------------------------------

def test_open_bus_is_open_and_ordinary_obd_still_works_after(sim):
    v = sim("open-bus")
    cap = listen(v.elm, 0.6)
    s = cap.summary()
    assert s["verdict"] == "open"
    assert {"025", "1A0", "3B7", "0C9"} <= set(s["ids"])
    assert not any(is_diagnostic(i) for i in s["ids"])
    assert s["buffer_full"] == 0           # an STN-class adapter keeps up
    # Headers, spaces and auto-formatting are back: normal requests parse again.
    assert v.read("rpm").value > 500
    assert v.dtcs()["stored"] == []
    assert v.vin_info()["model_year"] == 2015


def test_a_car_with_a_gateway_is_silent(sim):
    cap = listen(sim("healthy").elm, 0.4)
    assert cap.summary()["verdict"] == "hidden"
    assert cap.frames == []


def test_a_non_can_car_has_nothing_to_hear(sim):
    cap = listen(sim("kwp2000").elm, 0.4)
    assert cap.traffic()[0] == "not_can"


def test_a_clone_without_monitor_mode_says_so(bus_car):
    v = bus_car("clone")
    cap = listen(v.elm, 0.4)
    assert cap.traffic()[0] == "adapter_cannot_listen"
    assert v.read("rpm").value > 500


def test_a_slow_adapter_overflows_and_samples_the_bus(bus_car):
    v = bus_car("genuine")
    cap = listen(v.elm, 1.0)
    s = cap.summary()
    assert s["buffer_full"] >= 1 and s["sampled"]
    assert s["verdict"] == "open"
    assert v.read("rpm").value > 500


def test_listening_to_chosen_ids_only_hears_those(bus_car):
    v = bus_car("genuine")
    cap = listen(v.elm, 0.6, ids=["025", "1A0"])
    assert set(cap.ids()) == {"025", "1A0"}
    assert cap.buffer_full == 0            # the filter keeps a slow adapter from overflowing
    assert cap.traffic()[0] == "filtered"
    assert v.read("rpm").value > 500       # the filter was cleared


# -- guided find -----------------------------------------------------------------------

def test_guided_find_points_at_steering_brake_and_indicator(sim):
    v = sim("open-bus")
    result = port.run(v.elm, v, seconds=0.4, find=["steering", "brake", "indicator"],
                      still_seconds=1.5, action_seconds=1.2, ready_seconds=0,
                      act=v._emulator.car.act)
    assert result["verdict"] == "open"
    assert result["engine_running"] is True
    steering = result["found"]["steering"]["candidates"][0]
    assert steering["id"] == "025" and steering["bytes"] == [0, 1]
    brake = result["found"]["brake"]["candidates"]
    assert brake[0]["id"] == "1A0" and brake[0]["bytes"] == [2] and brake[0]["bits"] == ["0x01"]
    indicator = result["found"]["indicator"]["candidates"][0]
    assert indicator["id"] == "3B7" and indicator["bits"] == ["0x20"]
    # Rolling counters change while still, so they are never a candidate.
    for body in result["found"].values():
        assert all(7 not in c["bytes"] for c in body["candidates"])
    text = port.render(result)
    assert "id 025 bytes 0-1" in text and "next:" in text


def test_find_is_skipped_when_the_port_is_hidden(sim):
    v = sim("healthy")
    result = port.run(v.elm, v, seconds=0.3, find=["steering"], ready_seconds=0)
    assert result["verdict"] == "hidden"
    assert result["found"] == {}
    assert "Mode 22" in result["next"]


def test_unknown_action_is_refused(sim):
    with pytest.raises(ValueError):
        port.run(sim("open-bus").elm, None, seconds=0.1, find=["wipers"])


def test_share_report_has_no_vin(sim):
    v = sim("open-bus")
    result = port.run(v.elm, v, seconds=0.4)
    rep = port.share_report(result, v, model="Hatchback 1.2 petrol")
    text = json.dumps(rep)
    assert v.vin not in text
    assert rep["vehicle"]["wmi"] == "1CA" and rep["vehicle"]["model_year"] == 2015
    assert rep["simulated"] is True and rep["verdict"] == "open"
    assert "025" in rep["ids"]
    with pytest.raises(PrivacyError):
        port.share_report(result, v, model=f"my car {v.vin}")


# -- record ----------------------------------------------------------------------------

def _rows(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_record_obd_and_chosen_can_ids(sim, tmp_path):
    v = sim("open-bus")
    out = tmp_path / "drive"
    meta = Recorder(v, out_dir=out, pids=["speed", "rpm"], can_ids=["025", "1a0"],
                    label="car-3").run(seconds=1.2)
    assert meta["ended"] == "time limit" and meta["error"] is None
    obd = _rows(out / "obd.csv")
    can = _rows(out / "can.csv")
    assert obd and set(obd[0]) == {"t_unix", "t_since_start", "speed", "rpm"}
    assert float(obd[0]["rpm"]) > 500
    assert can and {r["id"] for r in can} == {"025", "1A0"}
    assert all(len(r["data"]) == 16 for r in can)
    saved = json.loads((out / "meta.json").read_text())
    assert saved["summary"]["obd_rows"] == len(obd)
    assert saved["summary"]["can_frames"] == len(can)
    assert saved["label"] == "car-3" and saved["vehicle"]["wmi"] == "1CA"
    assert v.vin not in (out / "meta.json").read_text()
    assert float(can[-1]["t_unix"]) >= float(can[0]["t_unix"])


def test_record_whole_bus_counts_overflows(bus_car, tmp_path):
    v = bus_car("genuine")
    meta = Recorder(v, out_dir=tmp_path / "bus", can=True).run(seconds=1.0)
    s = meta["summary"]
    assert s["can_frames"] > 0 and s["can_buffer_full"] >= 1
    assert meta["obd"] is None and not (tmp_path / "bus" / "obd.csv").exists()


def test_record_obd_only_skips_signals_the_car_lacks(sim, tmp_path):
    v = sim("obd-2b")
    meta = Recorder(v, out_dir=tmp_path / "scooter").run(seconds=0.5)
    assert "speed" in meta["obd"]["signals"] and "maf" not in meta["obd"]["signals"]
    assert "maf" in meta["skipped_signals"]


def test_record_refuses_can_on_a_non_can_car_and_unknown_signals(sim, tmp_path):
    with pytest.raises(RecordError):
        Recorder(sim("kwp2000"), out_dir=tmp_path / "x", can=True)
    with pytest.raises(RecordError):
        Recorder(sim("healthy"), out_dir=tmp_path / "y", pids=["warp_drive"])


def test_record_says_when_the_adapter_cannot_listen(bus_car, tmp_path):
    meta = Recorder(bus_car("clone"), out_dir=tmp_path / "c", can=True).run(seconds=0.5)
    assert meta["ended"] == "error" and "cannot listen" in meta["error"]


# -- CLI ---------------------------------------------------------------------------------

def test_can_check_cli(capsys):
    assert main(["can-check", "--sim", "open-bus", "--seconds", "0.4"]) == 0
    out = capsys.readouterr().out
    assert "verdict: open" in out and "--find" in out
    assert main(["can-check", "--sim", "open-bus", "--seconds", "0.3", "--report",
                 "--model", "test hatch"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["source"] == "car-use can-check --report" and rep["vehicle"]["model"] == "test hatch"
    assert main(["can-check", "--sim", "open-bus", "--find", "wipers"]) == 2
    assert main(["can-check", "--sim", "open-bus", "--seconds", "0"]) == 2


def test_record_cli(tmp_path, capsys):
    out = tmp_path / "rec"
    assert main(["record", "--sim", "healthy", "--seconds", "0.5", "--pids", "rpm",
                 "--out", str(out)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["summary"]["obd_rows"] > 0 and (out / "obd.csv").exists()
    assert main(["record", "--sim", "kwp2000", "--seconds", "0.5", "--can"]) == 2
    assert main(["record", "--sim", "healthy", "--seconds", "-1"]) == 2


def test_helper_listen_in_a_script(capsys):
    from car_use.run import run_script
    code = "cap = listen(0.3)\nprint(cap.summary()['verdict'], len(cap.ids()))\n"
    assert run_script(code, "sim:open-bus") == 0
    assert capsys.readouterr().out.split()[0] == "open"


def test_open_bus_scenario_is_explained():
    s = load("open-bus")
    assert "invented" in s.notes and "gateway" in s.notes
    assert {f["id"] for f in s.bus} >= {"025", "1A0", "3B7"}
