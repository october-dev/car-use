"""The virtual J1939 crane: can-check, record and the decoder against it, no hardware."""
import csv
import json

import pytest

from car_use.can import j1939 as J
from car_use.doctor import port
from car_use.obd.monitor import listen
from car_use.record import Recorder
from car_use.run import main
from car_use.sim.scenario import from_dict, load


def test_scenario_loads_with_j1939_groups_and_a_bam_dm1():
    s = load("crane-j1939")
    assert s.protocol == "A" and s.notes.strip()
    ids = {b["id"] for b in s.bus}
    assert {"0CF00400", "18FEEE00", "18FEFC17", "18FEF521", "18FF2080"} <= ids
    bam = [b for b in s.bus if "sequence" in b and len(b["sequence"]) > 1]
    assert len(bam) == 1
    seq = bam[0]["sequence"]
    assert seq[0][1] == "1CECFF00" and seq[0][2][0] == J.TP_BAM
    assert [d for d, _, _ in seq] == [0.0, 0.05, 0.1]          # 50 ms between packets
    single = [b for b in s.bus if "sequence" in b and len(b["sequence"]) == 1]
    assert single[0]["id"] == "18FECA03"


def test_scenario_rejects_an_spn_in_the_wrong_pgn():
    with pytest.raises(ValueError):
        from_dict({"bus": {"j1939": [{"pgn": 61444, "spns": {"110": 90}}]}}, name="bad")


def test_connects_on_protocol_a_without_obd_requests(sim):
    v = sim("crane-j1939")
    assert v.elm.info.is_j1939 and v.vin == ""
    assert "J1939" in v.describe()["protocol"]
    hexreqs = [r for _, r in v._emulator.car.requests]
    assert hexreqs == []                     # no OBD probe, no VIN request


def test_listen_and_decode_the_crane(sim):
    v = sim("crane-j1939")
    cap = listen(v.elm, 2.5)
    bus = J.recognise(cap.ids())
    assert bus["j1939"]
    snap = J.decode_frames(cap.car_frames())
    sig = {k: s["value"] for k, s in snap["signals"].items()}
    assert 1150 <= sig["engine_speed_rpm"] <= 1250
    assert sig["coolant_temp_c"] == 104 and sig["engine_hours_h"] == 6412.35
    assert sig["fuel_level_pct"] == 58.4 and sig["vehicle_speed_kph"] == 0
    assert 27.6 <= sig["battery_v"] <= 28 and 31 <= sig["ambient_temp_c"] <= 32
    assert snap["signals"]["fuel_level_pct"]["source"] == 0x17
    assert snap["dm1"]["00"]["multi_packet"] and snap["dm1"]["00"]["lamps"]["amber_warning"] == "on"
    assert [(f["spn"], f["fmi"]) for f in snap["faults"]] == [(110, 16), (100, 18)]
    assert snap["dm1"]["03"]["faults"] == []
    assert snap["transport"]["completed"] >= 1
    assert "65312" in snap["pgns"]           # proprietary: counted, not decoded


def test_can_check_against_the_crane(sim):
    v = sim("crane-j1939")
    result = port.run(v.elm, v, seconds=2.5)
    assert result["bus"] == "j1939" and result["layout"] == []
    assert result["engine_running"] is True          # from EEC1, not an OBD request
    assert "record --decode j1939" in result["next"]
    text = port.render(result)
    assert "bus: J1939" in text and "SPN 110" in text and "BAM" in text
    rep = port.share_report(result, v)
    assert rep["bus"] == "j1939" and {"spn": 110, "fmi": 16, "source": 0} in rep["j1939"]["faults"]


def test_crane_is_silent_at_the_wrong_bus_speed(sim):
    from car_use.connect import open_vehicle
    v = open_vehicle("sim:crane-j1939", protocol="6")
    try:
        result = port.run(v.elm, v, seconds=0.5)
        assert result["verdict"] == "hidden" and result["bus"] is None
        assert "--j1939" in result["next"]
    finally:
        v.elm.close()
        v._emulator.stop()


def test_record_decode_j1939_against_the_crane(sim, tmp_path):
    v = sim("crane-j1939")
    meta = Recorder(v, out_dir=tmp_path / "r", decode="j1939").run(seconds=2.5)
    assert meta["can"] and meta["decoded"]["dbc"] == "j1939"
    s = meta["summary"]["j1939"]
    assert s["signals"]["coolant_temp_c"] == 104 and len(s["faults"]) == 2
    rows = list(csv.DictReader((tmp_path / "r" / "signals.csv").open()))
    assert rows and rows[-1]["engine_hours_h"] == "6412.35"
    faults = list(csv.DictReader((tmp_path / "r" / "faults.csv").open()))
    assert {r["source"] for r in faults} == {"00", "03"}
    saved = json.loads((tmp_path / "r" / "meta.json").read_text())
    assert saved["decoded"]["faults_file"] == "faults.csv"


def test_cli_against_the_crane(tmp_path, capsys):
    assert main(["can-check", "--sim", "crane-j1939", "--seconds", "1.5"]) == 0
    out = capsys.readouterr().out
    assert "bus: J1939" in out and "engine_speed_rpm" in out
    assert main(["record", "--sim", "crane-j1939", "--decode", "j1939", "--seconds", "1.5",
                 "--out", str(tmp_path / "r")]) == 0
    assert (tmp_path / "r" / "faults.csv").exists()
    capsys.readouterr()
    assert main(["dbc", "decode", str(tmp_path / "r"), "--dbc", "j1939"]) == 0
    assert json.loads(capsys.readouterr().out)["j1939"]["signals"]["coolant_temp_c"] == 104
