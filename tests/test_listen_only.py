"""Listen-only sessions: nothing reaches the bus, every transmit path is refused, the mode is audited."""
import json

import pytest

from car_use import helpers
from car_use.connect import open_vehicle
from car_use.doctor import port
from car_use.kernel.policy import Audit, Kernel, listen_only_default, load_policy, _write_policy
from car_use.obd.elm import ListenOnlyError, silent_command
from car_use.record import Recorder, RecordError
from car_use.run import main
from car_use.sim.emulator import Emulator
from car_use.sim.scenario import from_dict, read_raw


@pytest.fixture
def lo():
    opened = []

    def _open(name, **kw):
        v = open_vehicle(f"sim:{name}", listen_only=True, kernel=Kernel(confirm=lambda q, e: True), **kw)
        opened.append(v)
        return v
    yield _open
    for v in opened:
        v.elm.close()
        v._emulator.stop()


def _audit():
    return [json.loads(x) for x in Audit().path.read_text().splitlines()]


def test_silent_command_allowlist():
    for ok in ("ATZ", "ATE0", "ATH1", "ATS0", "ATAT1", "ATSP6", "ATSPA", "ATTPA6", "ATDPN", "ATDP",
               "ATCAF0", "ATCSM1", "ATCF7E8", "ATCM18FECA00", "ATCRA", "ATAR", "ATRV", "AT@1",
               "STI", "STDI", "STCMM0", "ATI"):
        assert silent_command(ok), ok
    for bad in ("0100", "0902", "04", "2E F190 00", "ATSP0", "ATTP0", "ATCSM0", "STCMM1", "STCMM2",
                "ATSH7E0", "ATRTR", "ATFI", "ATSI", "ATBI", "ATWM8113F13E", "STPX h:7E0 d:0104",
                "ATMA"):
        assert not silent_command(bad), bad


def test_listen_only_connect_sends_no_obd_request(lo):
    v = lo("open-bus")
    assert v.listen_only["on"] and v.listen_only["adapter_silent"] is True
    assert v.elm.info.is_can and v.vin == ""
    cap = helpers_listen(v)
    assert cap.ids()
    assert v._emulator.car.requests == []              # the virtual car saw no request at all


def helpers_listen(v):
    from car_use.obd.monitor import listen
    return listen(v.elm, 0.4)


def test_every_transmit_path_is_refused(lo):
    v = lo("p0420")
    for call in (lambda: v.read("rpm"), lambda: v.dtcs(), lambda: v.raw_obd("0105"),
                 lambda: v.clear_dtcs(), lambda: v.read_vin(), lambda: v.elm.at("ATCSM0"),
                 lambda: v.elm.command("STCMM1"), lambda: v.elm.at("ATSP0")):
        with pytest.raises(ListenOnlyError):
            call()
    assert v._emulator.car.requests == []
    assert v._emulator.car.stored == ["P0420"]            # nothing cleared
    assert "04" in v.elm.refused or any(r.startswith("01") for r in v.elm.refused)


def test_clone_that_rejects_csm_is_software_only():
    raw = read_raw("open-bus")
    raw["adapter"]["profile"] = "clone"
    emu = Emulator(from_dict(raw, name="open-bus")).start()
    from car_use.obd.elm import Elm327
    from car_use.obd.vehicle import ObdVehicle
    from car_use.transport.base import open_transport
    v = ObdVehicle(Elm327(open_transport(emu.url)), emu.url, scenario=emu.scenario)
    try:
        v.connect(protocol="6", listen_only=True)
        assert v.listen_only["adapter_silent"] is None and v.listen_only["adapter_commands"] == []
        assert "cannot confirm" in v.listen_only["note"]
        assert "car-use only" in port.render({"verdict": "hidden", "why": "", "next": "",
                                               "listen_only": v.listen_only})
    finally:
        v.elm.close()
        emu.stop()


def test_listen_only_needs_a_protocol_number():
    with pytest.raises(ValueError):
        open_vehicle("sim:healthy", protocol="0", listen_only=True)


def test_can_check_listen_only_skips_the_rpm_request(lo):
    v = lo("open-bus")
    result = port.run(v.elm, v, seconds=0.4)
    assert result["listen_only"]["on"] and result["engine_running"] is None
    assert v._emulator.car.requests == []
    assert "mode: listen-only" in port.render(result)
    assert port.share_report(result, v)["listen_only"] is True


def test_recorder_refuses_obd_in_listen_only(lo, tmp_path):
    v = lo("open-bus")
    with pytest.raises(RecordError):
        Recorder(v, out_dir=tmp_path / "x", pids=["rpm"], can=True)
    meta = Recorder(v, out_dir=tmp_path / "r", can=True).run(seconds=0.5)
    assert meta["mode"] == "listen-only" and meta["summary"]["can_frames"] > 0
    assert v._emulator.car.requests == []


def test_policy_default_and_owner_override():
    assert listen_only_default() is True
    _write_policy({"can": {"listen_only": False}, "vehicles": {"VIN1": {"tiers": ["T1D"]}}})
    assert listen_only_default() is False
    assert load_policy()["vehicles"]["VIN1"]["tiers"] == ["T1D"]


def test_cli_defaults_and_audit(tmp_path, capsys):
    assert main(["can-check", "--sim", "open-bus", "--seconds", "0.3"]) == 0
    assert "mode: listen-only" in capsys.readouterr().out
    assert main(["can-check", "--sim", "open-bus", "--seconds", "0.3", "--no-listen-only"]) == 0
    assert "mode: listen-only" not in capsys.readouterr().out
    assert main(["record", "--sim", "open-bus", "--can", "--seconds", "0.3",
                 "--out", str(tmp_path / "a")]) == 0
    assert main(["record", "--sim", "healthy", "--pids", "rpm", "--seconds", "0.3",
                 "--out", str(tmp_path / "b")]) == 0
    assert main(["record", "--sim", "healthy", "--pids", "rpm", "--listen-only"]) == 2
    sessions = [e for e in _audit() if e["kind"] == "session"]
    assert [(e["intent"], e["mode"]) for e in sessions] == [
        ("can-check", "listen-only"), ("can-check", "obd-requests"),
        ("record", "listen-only"), ("record", "obd-requests")]
    assert sessions[0]["adapter_silent"] is True
    assert Audit().verify()[0]
    meta = json.loads((tmp_path / "a" / "meta.json").read_text())
    assert meta["mode"] == "listen-only"


def test_scripts_with_listen_only_refuse_requests_and_control(capsys):
    import io, sys
    code = ("print(car().describe()['listen_only'])\n"
            "try:\n    read('rpm')\nexcept Exception as e:\n    print(type(e).__name__)\n"
            "try:\n    control(device='sim')\nexcept PermissionError:\n    print('control refused')\n")
    from car_use.run import run_script
    assert run_script(code, "sim:healthy", listen_only=True) == 0
    out = capsys.readouterr().out
    assert "True" in out and "ListenOnlyError" in out and "control refused" in out
    assert helpers._state["listen_only"] is True
    helpers._configure(None)
