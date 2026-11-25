"""DBC decoding (maps bundled from opendbc) and motion control (tier T4)."""
import csv
import json
import random
import sys
import time

import pytest

from car_use.can import library as L
from car_use.can.dbc import Dbc, DbcError
from car_use.control import ACKNOWLEDGEMENT, ControlError, open_session
from car_use.control import session as S
from car_use.control.sim import SimRunner
from car_use.doctor import port
from car_use.kernel import policy
from car_use.kernel.policy import Audit, Kernel
from car_use.record import Recorder, decode_folder
from car_use.run import main


def _audit() -> list[dict]:
    p = Audit().path
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


# -- the DBC reader ---------------------------------------------------------------

# Values computed by opendbc's own parser for the same bytes.
GOLDEN = [
    ("hyundai_can_generated", "SAS11", "SAS_Angle", "8cff0000ff", -11.6),
    ("toyota_nodsu_pt_generated", "STEER_ANGLE_SENSOR", "STEER_ANGLE", "0f3c000000000000", -294.0),
    ("honda_civic_hatchback_ex_2017_can_generated", "STEERING_SENSORS", "STEER_ANGLE", "fe0c000000000000", 50.0),
    ("vw_mqb", "LWI_01", "LWI_Lenkradwinkel", "0000a00f20000000", 400.0),
    ("tesla_model3_party", "DI_speed", "DI_vehicleSpeed", "0000e10100000000", 248.0),
    ("gm_global_a_powertrain_generated", "ECMVehicleSpeed", "VehicleSpeed", "1388000000000000", 50.0),
]


@pytest.mark.parametrize("dbc,msg,sig,data,want", GOLDEN)
def test_decodes_like_opendbc(dbc, msg, sig, data, want):
    m = L.load(dbc).message(msg)
    assert m.decode(bytes.fromhex(data))[sig] == pytest.approx(want)


def test_every_bundled_message_round_trips():
    rnd = random.Random(7)
    for name in L.names():
        for m in L.load(name).messages.values():
            data = bytes(rnd.getrandbits(8) for _ in range(m.size))
            vals = m.decode(data)
            assert m.decode(m.encode(vals, base=data)) == vals, (name, m.name)


def test_parser_handles_extended_ids_mux_and_value_tables():
    d = Dbc.parse('''
BO_ 2566844926 ENGINE: 8 ECU
 SG_ RPM : 24|16@1+ (0.125,0) [0|8031.875] "rpm" X
BO_ 300 MUXED: 8 ECU
 SG_ SEL M : 0|8@1+ (1,0) [0|255] "" X
 SG_ A m1 : 8|8@1+ (1,0) [0|255] "" X
 SG_ B m2 : 8|8@1- (1,0) [-128|127] "" X
VAL_ 300 SEL 1 "first" 2 "second" ;
''', "t")
    eng = d.message("ENGINE")
    assert eng.extended and eng.hex_id == "18FEF1FE"
    assert d.decode("18FEF1FE", bytes.fromhex("000000401f000000"))["RPM"] == 1000.0
    assert d.decode("12C", bytes([1, 200]) + bytes(6)) == {"SEL": 1, "A": 200}
    assert d.decode("12C", bytes([2, 200]) + bytes(6)) == {"SEL": 2, "B": -56}
    assert d.decode("12C", bytes([1, 0]) + bytes(6), choices=True)["SEL"] == "first"
    assert d.decode("7FF", bytes(8)) is None
    with pytest.raises(DbcError):
        Dbc.parse("VERSION \"\"\n", "empty")


def test_every_semantic_signal_exists_in_its_dbc():
    for name, spec in L.SIGNALS.items():
        d = L.load(name)
        for col, s in spec.items():
            s = {"sig": s} if isinstance(s, str) else s
            for key in ("sig", "plus", "sign"):
                if key in s:
                    msg, sig = s[key].split(".")
                    assert sig in d.messages[msg].signals, (name, col, s[key])


def test_bundled_maps_carry_opendbc_licence():
    from importlib import resources
    root = resources.files("car_use.can") / "dbcs"
    assert "Comma.ai" in (root / "LICENSE.opendbc").read_text()
    assert "commit" in (root / "SOURCE.md").read_text()


# -- which car is this ------------------------------------------------------------

def test_match_names_the_layout_from_ids_and_lengths():
    d = L.load("hyundai_can_generated")
    heard = {d.messages[m].hex_id: d.messages[m].size for m in ("SAS11", "MDPS12", "TCS13", "CGW1", "WHL_SPD11", "EMS12")}
    top = L.match(heard)[0]
    assert top.dbc == "hyundai_can_generated" and top.confidence == "strong"
    assert "steering_angle_deg" in top.signals and "brake_pressed" in top.signals


def test_a_few_shared_ids_are_only_a_weak_match():
    # Mostly ids no bundled map defines, plus two that happen to be Toyota's.
    heard = {"025": 8, "0AA": 8, "7A1": 8, "7A2": 8, "7A3": 8, "7A4": 8, "7A5": 8}
    assert all(m.confidence == "weak" for m in L.match(heard))


def test_which_signal_names_the_bytes_a_guided_find_points_at():
    hit = L.which_signal("hyundai_can_generated", "2B0", 0, 1)
    assert hit["message"] == "SAS11" and hit["signal"] == "SAS_Angle" and hit["column"] == "steering_angle_deg"
    assert L.which_signal("hyundai_can_generated", "7FF", 0, 1) is None


def test_decoder_applies_sign_bits_and_lamp_values():
    vw = L.Decoder("vw_mqb")
    m = vw.dbc.message("LWI_01")
    vw.feed(m.hex_id, m.encode({"LWI_Lenkradwinkel": 90.0, "LWI_VZ_Lenkradwinkel": 1}))
    assert vw.row()["steering_angle_deg"] == -90.0
    hy = L.Decoder("hyundai_can_generated")
    cgw = hy.dbc.message("CGW1")
    hy.feed(cgw.hex_id, cgw.encode({"CF_Gway_TurnSigLh": 3}))
    assert hy.row()["left_blinker"] == 1 and hy.row()["speed_kph"] is None


# -- against the Hyundai-layout virtual car ----------------------------------------

def test_can_check_names_the_hyundai_layout_and_its_signals(sim):
    v = sim("hyundai-bus")
    result = port.run(v.elm, v, seconds=0.5, find=["steering", "brake"], still_seconds=3.0,
                      action_seconds=2.5, ready_seconds=0, act=v._emulator.car.act)
    assert result["layout"][0]["dbc"] == "hyundai_can_generated"
    # Both the angle sensor (SAS11) and the column torque (MDPS12) move with the
    # wheel; either may rank first, and both must be named from the DBC.
    steer = {c["id"]: c["dbc_signal"]["signal"] for c in result["found"]["steering"]["candidates"]}
    top = result["found"]["steering"]["candidates"][0]["id"]
    assert top in ("2B0", "251") and steer.get("2B0") == "SAS_Angle"
    assert steer.get("251", "CR_Mdps_StrColTq") == "CR_Mdps_StrColTq"
    brake = result["found"]["brake"]["candidates"][0]
    assert brake["dbc_signal"]["signal"] == "DriverBraking"
    text = port.render(result)
    assert "looks like Hyundai / Kia" in text and "record --decode hyundai_can_generated" in text
    shared = port.share_report(result, v, model="Creta 2019")
    assert shared["layout"][0]["dbc"] == "hyundai_can_generated"
    assert {c["dbc_signal"]["message"] for c in shared["found"]["steering"]} >= {"SAS11"}


def test_open_bus_invented_ids_are_not_claimed_as_a_real_car(sim):
    v = sim("open-bus")
    result = port.run(v.elm, v, seconds=0.5)
    assert all(x["confidence"] == "weak" for x in result["layout"])


def test_record_decode_writes_real_units(sim, tmp_path):
    v = sim("hyundai-bus")
    car = v._emulator.car
    car.act("steering")
    car.act("brake")
    meta = Recorder(v, out_dir=tmp_path / "r", decode="hyundai_can_generated").run(seconds=1.2)
    assert meta["decoded"]["dbc"] == "hyundai_can_generated"
    assert set(meta["can"]["ids_filter"]) >= {"2B0", "394"}
    rows = list(csv.DictReader((tmp_path / "r" / "signals.csv").open()))
    angles = {float(r["steering_angle_deg"]) for r in rows if r["steering_angle_deg"]}
    assert len(angles) > 5 and max(abs(a) for a in angles) > 20
    assert "1" in {r["brake_pressed"] for r in rows}
    again = decode_folder(tmp_path / "r", "hyundai_can_generated")
    assert again["decoded_frames"] == meta["summary"]["decoded_frames"]


def test_dbc_cli(capsys):
    assert main(["dbc", "list"]) == 0
    assert "hyundai_can_generated" in capsys.readouterr().out
    assert main(["dbc", "show", "vw_pq"]) == 0
    assert "Lenkhilfe_3.LH3_BLW" in capsys.readouterr().out
    assert main(["dbc", "show", "nope"]) == 1


# -- turning motion control on ------------------------------------------------------

VIN = "1CARUSE09K0HKB001"


def test_t4_needs_a_terminal_the_vin_and_the_typed_acknowledgement(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert policy.set_tier(VIN, "T4", True).startswith("Refusing")

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    asked = []

    def person(answers):
        def ask(question, expect):
            asked.append(expect)
            return answers.pop(0) == expect
        return ask

    msg = policy.set_tier(VIN, "T4", True, ask=person([VIN[-6:], "i accept"]))
    assert "didn't match" in msg and "T4" not in policy.enabled_tiers(VIN)
    assert asked[-1] == ACKNOWLEDGEMENT

    msg = policy.set_tier(VIN, "T4", True, ask=person([VIN[-6:], ACKNOWLEDGEMENT]))
    assert msg.startswith("T4 enabled") and "T4" in policy.enabled_tiers(VIN)
    kinds = [(e["kind"], e.get("tier")) for e in _audit()]
    assert ("acknowledge", "T4") in kinds and ("policy", "T4") in kinds
    assert policy.set_tier(VIN, "T4", False).startswith("T4 disabled")
    assert "T4" not in policy.enabled_tiers(VIN)


def test_t3_is_still_unavailable():
    assert "cannot be enabled" in policy.set_tier(VIN, "T3", True)


class FakePanda:
    """Stands in for control.panda.PandaCar: an identified, supported car."""
    car = "HYUNDAI HYUNDAI_KONA_EV"
    vin = VIN
    simulated = False
    steer_mode = "torque"
    can_accel = False

    def __init__(self):
        self.closed = False
        self.sent = []

    def read(self):
        return S.State(speed_kph=50, controls_allowed=True, cruise_engaged=True)

    def write(self, cmd):
        self.sent.append(cmd)

    def close(self):
        self.closed = True


@pytest.fixture
def fake_panda(monkeypatch):
    import car_use.control.panda as P
    made = []

    def make():
        made.append(FakePanda())
        return made[-1]
    monkeypatch.setattr(P, "PandaCar", make)
    return made


def test_a_real_car_session_is_refused_until_t4_is_on(fake_panda):
    with pytest.raises(ControlError, match="needs tier T4"):
        open_session("panda", kernel=Kernel(confirm=lambda q, e: True))
    assert fake_panda[0].closed


def test_a_real_car_session_needs_this_sessions_yes(fake_panda, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    answers = iter([VIN[-6:], ACKNOWLEDGEMENT])
    policy.set_tier(VIN, "T4", True, ask=lambda q, e: next(answers) == e)
    with pytest.raises(ControlError, match="confirm"):
        open_session("panda", kernel=Kernel(confirm=lambda q, e: False))
    assert fake_panda[-1].closed
    with open_session("panda", kernel=Kernel(confirm=lambda q, e: True)) as c:
        assert c.status().car == FakePanda.car
        c.arm()
        c.steer(torque=0.2)
        time.sleep(0.1)
        with pytest.raises(ControlError, match="gas and brake"):
            c.accel(1.0)
    car = fake_panda[-1]
    assert car.closed and any(cmd.enabled and cmd.torque == 0.2 for cmd in car.sent)
    assert not car.sent[-1].enabled


def test_an_elm327_cannot_be_used_for_control():
    with pytest.raises(ControlError, match="panda"):
        open_session("tcp://127.0.0.1:35000")


def test_missing_comma_packages_say_how_to_install(monkeypatch):
    import builtins
    import car_use.control.panda as P
    real = builtins.__import__

    def no_panda(name, *a, **k):
        if name in ("panda", "opendbc") or name.startswith("opendbc."):
            raise ImportError(name=name)
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_panda)
    monkeypatch.setattr(sys, "version_info", (3, 12, 0))
    with pytest.raises(ControlError, match="pandacan"):
        P._imports()


# -- the control loop, on the virtual car -------------------------------------------

@pytest.fixture
def practice():
    sessions = []

    def _open(**kw):
        sessions.append(open_session("sim", **kw))
        return sessions[-1]
    yield _open
    for s in sessions:
        s.close()


def test_commands_only_flow_while_armed_fresh_and_allowed(practice):
    c = practice()
    sim = c.runner
    c.steer(torque=0.5)                      # not armed yet
    time.sleep(0.1)
    assert sim.commands == 0
    c.arm()
    c.hold(0.4, torque=0.5)
    assert sim.wheel > 30 and c.status().engaged
    before = sim.commands
    time.sleep(S.STALE_AFTER + 0.2)          # no fresh target: hands off
    stale = sim.commands
    time.sleep(0.2)
    assert sim.commands == stale and stale - before < 60
    assert "fresh command" in c.status().reason


def test_driver_inputs_disarm_and_stay_disarmed(practice):
    for kind in ("brake", "gas", "grab"):
        c = practice()
        c.arm()
        c.steer(torque=0.3)
        c.runner.driver(**{kind: True})
        time.sleep(0.1)
        st = c.status()
        assert not st.armed and "disarmed: driver" in st.reason
        c.runner.driver(**{kind: False})
        c.steer(torque=0.3)
        time.sleep(0.1)
        assert not c.status().armed


def test_no_commands_until_the_driver_engages_cruise(practice):
    c = practice()
    c.runner.driver(cruise=False)
    c.arm()
    c.hold(0.3, torque=0.5)
    assert c.runner.commands == 0 and "engage cruise" in c.status().reason
    c.runner.driver(cruise=True)
    c.hold(0.3, torque=0.5)
    assert c.runner.commands > 0


def test_gas_is_capped_at_the_owners_speed(practice):
    c = practice(max_kph=31)
    c.arm()
    c.hold(1.5, torque=0.0, accel=2.0)
    assert c.runner.speed * 3.6 < 33
    with pytest.raises(ControlError):
        c.steer(torque=0.1, angle=3)


def test_closing_lets_go_and_is_audited(practice):
    c = practice()
    c.arm()
    c.hold(0.2, torque=0.4)
    c.close()
    assert c.runner.closed and not c.status().armed
    events = [e.get("event") for e in _audit() if e["kind"] == "control"]
    assert events[0] == "session.start" and "armed" in events and events[-1] == "session.end"
    with pytest.raises(ControlError, match="closed"):
        c.steer(torque=0.1)


def test_control_cli_check_and_demo(capsys):
    assert main(["control", "check"]) == 0
    out = capsys.readouterr().out
    assert "T4 (motion control) enabled for: no car" in out
    assert main(["control", "demo"]) == 2
    assert main(["control", "demo", "--sim"]) == 0
    out = capsys.readouterr().out
    assert "disarmed: driver pressed the brake" in out


def test_t4_written_into_policy_by_hand_is_not_enough(fake_panda):
    # An agent editing policy.toml directly skips the prompts, so no acknowledgement is logged.
    policy._write_policy({"vehicles": {VIN: {"tiers": ["T4"]}}})
    assert "T4" in policy.enabled_tiers(VIN)
    with pytest.raises(ControlError, match="never acknowledged"):
        open_session("panda", kernel=Kernel(confirm=lambda q, e: True))
    assert fake_panda[-1].closed
