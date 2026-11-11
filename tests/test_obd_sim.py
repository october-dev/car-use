import json
import subprocess
import sys

import pytest

from car_use.kernel import policy
from car_use.kernel.policy import Audit
from car_use.obd import pids as P
from car_use.obd.vin import decode as vin_decode
from car_use.model.capability import Altitude


def test_pid_roundtrip():
    for pid in P.PIDS.values():
        vals = tuple(3.0 if "trim" in s.alias else 0.5 if s.unit == "V" and "o2" in s.alias
                     else 50.0 for s in pid.signals)
        if pid.pid in (0x05, 0x0F, 0x46, 0x5C):
            vals = (90.0,)
        dec = pid.decode(pid.encode(vals))
        for sig, a, b in zip(pid.signals, vals, dec):
            tol = 0.01 if sig.alias in ("o2_b1s1", "o2_b1s2") else 1.0
            assert abs(a - b) <= tol, (hex(pid.pid), a, b)


def test_dtc_codec():
    for code in ["P0420", "P0171", "C0035", "B1000", "U0100", "P2A00"]:
        enc = P.encode_dtc(code)
        assert P.decode_dtc(enc[0], enc[1]) == code


def test_monitor_codec():
    mons = {"misfire": "complete", "catalyst": "incomplete", "evap": "complete"}
    out = P.decode_monitor_status(P.encode_monitor_status(True, 2, mons))
    assert out["mil_on"] and out["dtc_count"] == 2 and out["monitors"] == mons


def test_vin_decode():
    d = vin_decode("4T1BF1FK0EU300042")
    assert d["check_digit_ok"] and d["model_year"] == 2014 and "Toyota" in d["manufacturer"]
    assert not vin_decode("4T1BF1FK0EU30004")["valid_format"]


def test_p0420_diagnosis_signals(sim):
    v = sim("p0420")
    assert v.vin == "4T1BF1FK0EU300042"
    codes = v.dtcs()
    assert codes["stored"] == ["P0420"] and codes["permanent"] == ["P0420"]
    assert codes["mil_on"] is True
    ff = v.freeze_frame()
    assert ff["dtc"] == "P0420" and ff["values"]["speed"]["value"] == 72
    from car_use import helpers
    helpers._state["vehicle"] = v
    s = helpers.watch(["o2_b1s1", "o2_b1s2"], seconds=3, hz=20).summary()
    helpers._state["vehicle"] = None
    # the bad-catalyst signature: downstream swings almost as much as upstream
    assert s["o2_b1s2"]["max"] - s["o2_b1s2"]["min"] > 0.4
    assert s["o2_b1s2"]["switches"] >= 2


def test_healthy_cat_downstream_steady(sim):
    v = sim("healthy")
    from car_use import helpers
    helpers._state["vehicle"] = v
    s = helpers.watch(["o2_b1s1", "o2_b1s2"], seconds=2, hz=20).summary()
    helpers._state["vehicle"] = None
    assert s["o2_b1s2"]["max"] - s["o2_b1s2"]["min"] < 0.1
    assert v.dtcs()["stored"] == []


def test_cleared_codes_red_flag(sim):
    r = sim("cleared-codes").readiness()
    assert r["mil_on"] is False
    assert {"catalyst", "evap", "o2_sensor"} <= set(r["incomplete"])
    assert r["distance_since_clear"] == 11


def test_read_many_and_signals(sim):
    v = sim("p0171")
    vals = v.read_many(["rpm", "ltft1", "coolant", "speed", "Vehicle.Speed"])
    assert 15 < vals["ltft1"].value < 22
    assert vals["speed"].value == 0
    assert any(s["alias"] == "ltft1" for s in v.signals())
    assert v.elm.info.stn            # p0171 uses the STN profile


def test_many_dtcs_multiframe(sim):
    v = sim("p0300")                 # clone profile, 2 pending codes
    assert v.dtcs()["pending"] == ["P0302", "P0304"]


def test_ignition_off_fails_cleanly(sim):
    v = sim("ignition-off")
    from car_use.obd.elm import ElmError
    with pytest.raises(ElmError) as e:
        v.read("rpm")
    assert "ignition" in str(e.value).lower()


def test_raw_obd_allowlist(sim):
    v = sim("p0420")
    assert v.raw_obd("010C")[0].startswith("41 0C")
    for bad in ("04", "2E F1 90 00", "3101FF00", "27 01", "10 03"):
        d = v.raw_obd(bad)
        assert not d and d.status == "denied"
    assert v.dtcs()["stored"] == ["P0420"]    # nothing was cleared


def test_clear_dtcs_needs_tier_and_confirmation(sim):
    v = sim("p0420")
    d = v.clear_dtcs()
    assert d.status == "denied" and "T1D" in d.reason
    # enable T1D the way the owner would (bypassing the TTY check for the test)
    pol = {"vehicles": {v.vin: {"tiers": ["T1D"]}}}
    policy._write_policy(pol)
    d = v.clear_dtcs()                         # confirm callback says no
    assert d.status == "awaiting_owner"
    assert v.dtcs()["stored"] == ["P0420"]

    asked = []
    v2 = sim("p0420", confirm=lambda q, e: asked.append(q) or True)
    d = v2.clear_dtcs()
    assert d.allowed and "readiness" in asked[0]
    after = v2.dtcs()
    assert after["stored"] == [] and after["permanent"] == ["P0420"]
    assert set(v2.readiness()["incomplete"]) >= {"catalyst", "evap"}


def test_policy_enable_refuses_without_tty(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert "Refusing" in policy.set_tier("4T1BF1FK0EU300042", "T1D", True)
    assert "cannot be enabled" in policy.set_tier("4T1BF1FK0EU300042", "T4", True)


def test_audit_chain_detects_tampering(sim):
    v = sim("p0420")
    v.raw_obd("04")
    v.clear_dtcs()
    a = Audit()
    ok, msg = a.verify()
    assert ok, msg
    lines = a.path.read_text().splitlines()
    e = json.loads(lines[0])
    e["reason"] = "nothing to see here"
    lines[0] = json.dumps(e, sort_keys=True)
    a.path.write_text("\n".join(lines) + "\n")
    assert not a.verify()[0]


def test_manifest(sim):
    m = sim("p0420").manifest()
    assert "Vehicle.Speed" in m.signals
    assert [c.name for c in m.by_altitude(Altitude.ACT)] == ["obd.clear_dtcs"]


def test_dongle_doctor_grades(sim):
    from car_use.doctor import dongle
    clone = dongle.run(sim("p0300").elm, soak_requests=10)
    assert clone["kind"] == "clone" and clone["steps"]["fingerprint"]["missing"]
    assert clone["grade"] in ("B", "C")
    stn = dongle.run(sim("p0171").elm, soak_requests=10)
    assert stn["kind"] == "stn" and stn["grade"] == "A"
    off = dongle.run(sim("ignition-off").elm, soak_requests=5)
    assert off["grade"] == "D"


def test_cli_script_end_to_end():
    code = "print(json.dumps(dtcs()['stored']))\nprint(read('coolant').unit)\n"
    r = subprocess.run([sys.executable, "-m", "car_use.run", "--sim", "p0420"],
                       input=code, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert '["P0420"]' in r.stdout and "celsius" in r.stdout


def test_cli_reports_script_errors():
    r = subprocess.run([sys.executable, "-m", "car_use.run", "--sim", "healthy"],
                       input="read('nope')\n", capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and "script line 1" in r.stderr and "Unknown signal" in r.stderr
