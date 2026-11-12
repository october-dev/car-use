"""Shareable dongle-doctor reports: simulator fixtures, no full VIN, no invented hardware data."""
import json
import subprocess
import sys

import pytest

from car_use import config
from car_use.doctor.report import (
    PrivacyError, _dtc_modes, assert_shareable, field_soak_seconds, share_report,
)
from car_use.obd.elm import Elm327, ElmError
from car_use.sim.scenario import available
from car_use.transport.base import Transport, TransportError

VIN = "4T1BF1FK0EU300042"
EU_VIN = "WVWZZZ1KZ6W000001"   # well formed, no North American check digit


class _ScriptedTransport(Transport):
    """Canned adapter replies. A reply is bytes, an exception to raise, or a
    list of those served in order (the last one repeats)."""

    url = "fake://script"

    def __init__(self, script, default=b"?\r\r>"):
        self.script = script
        self.default = default
        self.writes = []
        self._buf = b""

    def write(self, data):
        cmd = data.decode("ascii").strip()
        self.writes.append(cmd)
        reply = self.script.get(cmd, self.default)
        if isinstance(reply, list):
            n = sum(1 for w in self.writes if w == cmd) - 1
            reply = reply[min(n, len(reply) - 1)]
        if isinstance(reply, Exception):
            raise reply
        self._buf += reply

    def _read_some(self, timeout):
        out, self._buf = self._buf, b""
        return out

    def close(self):
        pass


def _scenario_with_vin(home, name, vin):
    text = available()["p0420"].read_text(encoding="utf-8")
    d = home / "scenarios"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.toml").write_text(
        text.replace(f'vin = "{VIN}"', f'vin = "{vin}"'), encoding="utf-8")


def _report(*argv):
    return subprocess.run([sys.executable, "-m", "car_use.run", *argv],
                          capture_output=True, text=True, timeout=120)


def test_share_report_keeps_wmi_and_drops_vin(sim):
    v = sim("p0420")
    rep = share_report(v.elm, v, soak_requests=4)
    blob = json.dumps(rep)
    assert VIN not in blob
    assert rep["schema"] == 1
    assert rep["simulated"] is True
    assert rep["vehicle"]["wmi"] == "4T1"
    assert rep["vehicle"]["model_year"] == 2014
    assert rep["vehicle"]["vin_multiframe_ok"] is True
    assert rep["vehicle"]["supported_pid_count"] >= 8
    assert rep["vehicle"]["dtc_modes"] == {"03": True, "07": True, "0A": True}
    assert "15765" in rep["vehicle"]["protocol"]
    assert rep["soak"]["requests"] == 4
    assert rep["soak"]["error_rate"] == 0.0
    assert rep["soak"]["interrupted"] is False
    assert rep["ignition_off_current_ma"] is None
    assert "car-use does not measure current" in rep["ignition_off_current_note"]
    assert "current_draw" not in rep
    assert rep["fingerprint_status"] == "unvalidated"
    assert_shareable(rep)


def test_vin_without_check_digit_counts_as_a_good_read(sim, isolated_home):
    _scenario_with_vin(isolated_home, "eu-vin", EU_VIN)
    v = sim("eu-vin")
    rep = share_report(v.elm, v, soak_requests=2)
    assert EU_VIN not in json.dumps(rep)
    assert rep["vehicle"]["wmi"] == "WVW"
    assert rep["vehicle"]["vin_multiframe_ok"] is True


def test_ignition_off_report_has_no_scenario_vin(sim):
    v = sim("ignition-off")
    rep = share_report(v.elm, v, soak_requests=2)
    assert "2HGFB2F53EH500001" not in json.dumps(rep)
    assert rep["grade"] == "D"
    assert rep["simulated"] is True
    assert rep["vehicle"]["vin_multiframe_ok"] is False
    assert rep["vehicle"]["supported_pid_count"] is None
    assert rep["vehicle"]["dtc_modes"] == {"03": False, "07": False, "0A": False}


def test_garbled_indexed_frame_is_a_data_error():
    for frame in ("0:490201G", "0:490201GG"):
        t = _ScriptedTransport({"0902": f"014\r{frame}\r\r>".encode()})
        with pytest.raises(ElmError) as e:
            Elm327(t).query("0902")
        assert e.value.code == "DATA ERROR"


def test_garbled_vin_probe_gives_grade_d_not_a_refusal(sim, monkeypatch):
    v = sim("p0420")
    orig = v.elm.query_one

    def fail_vin(req):
        if req == "0902":
            raise ElmError(req, "DATA ERROR")
        return orig(req)

    monkeypatch.setattr(v.elm, "query_one", fail_vin)
    rep = share_report(v.elm, v, soak_requests=2)
    assert rep["grade"] == "D"
    assert rep["vehicle"]["vin_multiframe_ok"] is False


def test_full_vin_in_report_is_a_privacy_error():
    assert issubclass(PrivacyError, ValueError)
    with pytest.raises(PrivacyError):
        assert_shareable({"vehicle": {"wmi": VIN}})


@pytest.mark.parametrize("reply,want", [
    (b"41 0C 0C 80\r\r>", False),    # wrong service
    (b"7F 03 12\r\r>", False),        # negative response
    (b"NO DATA\r\r>", False),         # empty
    (b"43 00\r\r>", True),            # valid zero-code reply
    (b"43 01 04 20\r\r>", True),      # stored P0420
])
def test_dtc_mode_needs_its_positive_response(reply, want):
    t = _ScriptedTransport({"03": reply})
    assert _dtc_modes(Elm327(t))["03"] is want


def test_link_loss_mid_soak_gives_an_interrupted_report():
    ok_010c = b"410C0C80\r\r>"
    script = {
        "ATZ": b"ELM327 v1.5\r\r>",
        "ATE0": b"OK\r\r>", "ATL0": b"OK\r\r>", "ATS0": b"OK\r\r>",
        "ATH0": b"OK\r\r>", "ATAT1": b"OK\r\r>", "ATSP0": b"OK\r\r>",
        "AT@1": b"?\r\r>", "STI": b"?\r\r>",
        "ATRV": b"12.1V\r\r>",
        "0100": b"4100BE1FA813\r\r>",
        "ATDPN": b"A6\r\r>",
        "ATDP": b"ISO 15765-4 (CAN 11/500)\r\r>",
        "0902": (b"014\r0:49020134543142\r1:4631464B304555\r2:333030303432\r\r>"),
        "010C": [ok_010c, ok_010c, TransportError("link died")],
    }
    rep = share_report(Elm327(_ScriptedTransport(script)), None, soak_seconds=600)
    soak = rep["soak"]
    assert soak["interrupted"] is True
    assert soak["requests"] == 3
    assert soak["seconds"] < 5
    assert soak["target_seconds"] == 600
    # Near-zero errors with the marker: without it this would look excellent.
    assert soak["errors"] == 0 and soak["error_rate"] == 0.0
    assert rep["simulated"] is False
    assert_shareable(rep)


def test_soak_notice_fires_only_when_a_soak_runs(sim):
    calls = []
    ping = lambda: calls.append(1)
    share_report(sim("healthy").elm, None, soak_requests=2, notice=ping)
    assert len(calls) == 1
    share_report(sim("ignition-off").elm, None, soak_requests=2, notice=ping)
    assert len(calls) == 1


def test_timed_soak_stops_without_running_the_request_count(sim):
    v = sim("healthy")
    rep = share_report(v.elm, v, soak_requests=1000, soak_seconds=0.25)
    assert rep["soak"]["target_seconds"] == 0.25
    assert 1 <= rep["soak"]["requests"] < 1000
    assert rep["soak"]["seconds"] < 5
    assert rep["soak"]["interrupted"] is False


def test_field_soak_defaults_to_ten_minutes():
    assert field_soak_seconds(None) == 600
    assert field_soak_seconds(0) == 0


def test_report_marks_simulator_runs():
    r = _report("dongle-doctor", "--report", "--sim", "p0420", "--soak-seconds", "0")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["simulated"] is True


def test_report_marks_a_configured_sim_device():
    config.set_("device", "sim:p0420")
    r = _report("dongle-doctor", "--report", "--soak-seconds", "0")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert rep["simulated"] is True
    assert "p0420" not in json.dumps(rep)


@pytest.mark.parametrize("flag", [["--out", "x.json"], ["--soak-seconds", "30"],
                                 ["--current-ma", "5"]])
def test_report_flags_need_report(flag):
    r = _report("dongle-doctor", "--device", "tcp://127.0.0.1:1", *flag)
    assert r.returncode == 2
    assert "need --report" in r.stderr


@pytest.mark.parametrize("flag,value", [
    ("--soak-seconds", "-1"), ("--soak-seconds", "inf"), ("--soak-seconds", "nan"),
    ("--current-ma", "-5"), ("--current-ma", "inf"), ("--current-ma", "nan"),
])
def test_invalid_numbers_are_rejected_without_connecting(flag, value):
    r = _report("dongle-doctor", "--report", "--device", "tcp://127.0.0.1:1",
                flag, value)
    assert r.returncode == 2
    assert flag in r.stderr


def test_failed_out_write_keeps_stdout_json(tmp_path):
    missing = tmp_path / "nodir" / "report.json"
    r = _report("dongle-doctor", "--report", "--sim", "p0420", "--soak-seconds", "0",
                "--out", str(missing))
    assert r.returncode == 1
    rep = json.loads(r.stdout)
    assert rep["vehicle"]["wmi"] == "4T1"
    assert "could not save" in r.stderr


def test_stdout_contains_only_json():
    r = _report("dongle-doctor", "--report", "--sim", "p0420", "--soak-seconds", "3")
    assert r.returncode == 0, r.stderr
    json.loads(r.stdout)
    assert "3 seconds" in r.stderr


def test_cli_report_writes_anonymised_json(tmp_path):
    out = tmp_path / "report.json"
    r = _report("dongle-doctor", "--report",
                "--sim", "p0420", "--soak-seconds", "0",
                "--current-ma", "37", "--out", str(out))
    assert r.returncode == 0, r.stderr
    assert VIN not in r.stdout
    rep = json.loads(r.stdout)
    assert rep["vehicle"]["wmi"] == "4T1"
    assert rep["vehicle"]["model_year"] == 2014
    assert rep["ignition_off_current_ma"] == 37.0
    assert rep["simulated"] is True
    assert json.loads(out.read_text())["grade"] == rep["grade"]
