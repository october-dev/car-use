"""Shareable dongle-doctor reports: simulator fixtures, no full VIN, no invented hardware data."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from car_use.doctor.report import (
    assert_shareable, field_soak_seconds, render_table, share_report,
)

ROOT = Path(__file__).resolve().parents[1]
VIN = "4T1BF1FK0EU300042"


def test_share_report_keeps_wmi_and_drops_vin(sim):
    v = sim("p0420")
    rep = share_report(v.elm, v, soak_requests=4)
    blob = json.dumps(rep)
    assert VIN not in blob
    assert rep["schema"] == 1
    assert rep["vehicle"]["wmi"] == "4T1"
    assert rep["vehicle"]["model_year"] == 2014
    assert rep["vehicle"]["vin_multiframe_ok"] is True
    assert rep["vehicle"]["supported_pid_count"] >= 8
    assert rep["vehicle"]["dtc_modes"] == {"03": True, "07": True, "0A": True}
    assert "15765" in rep["vehicle"]["protocol"]
    assert rep["soak"]["requests"] == 4
    assert rep["soak"]["error_rate"] == 0.0
    assert rep["ignition_off_current_ma"] is None
    assert rep["current_draw"]["measured"] is False
    assert rep["fingerprint_status"] == "unvalidated"
    assert_shareable(rep)


def test_ignition_off_report_has_no_scenario_vin(sim):
    v = sim("ignition-off")
    rep = share_report(v.elm, v, soak_requests=2)
    assert "2HGFB2F53EH500001" not in json.dumps(rep)
    assert rep["grade"] == "D"
    assert rep["vehicle"]["vin_multiframe_ok"] is False
    assert rep["vehicle"]["supported_pid_count"] is None
    assert rep["vehicle"]["dtc_modes"] == {"03": False, "07": False, "0A": False}


def test_timed_soak_stops_without_running_the_request_count(sim):
    v = sim("healthy")
    rep = share_report(v.elm, v, soak_requests=1000, soak_seconds=0.25)
    assert rep["soak"]["target_seconds"] == 0.25
    assert 1 <= rep["soak"]["requests"] < 1000
    assert rep["soak"]["seconds"] < 5


def test_field_soak_defaults_to_ten_minutes():
    assert field_soak_seconds(None) == 600
    assert field_soak_seconds(0) == 0


def test_vin_is_rejected_and_empty_table_is_not_invented():
    with pytest.raises(ValueError):
        assert_shareable({"vehicle": {"wmi": VIN}})
    table = render_table([{
        "identity": {"reported": "ELM327 v1.5", "stn": None},
        "kind": "clone",
        "grade": "C",
        "vehicle": {
            "wmi": "4T1", "model_year": 2014,
            "protocol": "ISO 15765-4 (CAN 11/500)",
            "supported_pid_count": 20, "vin_multiframe_ok": True,
        },
        "soak": {"error_rate": 0.0},
        "ignition_off_current_ma": None,
    }])
    assert VIN not in table
    assert "| ELM327 v1.5 | clone | C | 4T1 | 2014 |" in table
    assert "_no reports_" in render_table([])


def test_cli_report_writes_anonymised_json(tmp_path):
    out = tmp_path / "report.json"
    r = subprocess.run(
        [sys.executable, "-m", "car_use.run", "dongle-doctor", "--report",
         "--sim", "p0420", "--soak-seconds", "0", "--soak-requests", "4",
         "--current-ma", "37", "--out", str(out)],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert VIN not in r.stdout
    rep = json.loads(r.stdout)
    assert rep["vehicle"]["wmi"] == "4T1"
    assert rep["vehicle"]["model_year"] == 2014
    assert rep["ignition_off_current_ma"] == 37.0
    assert json.loads(out.read_text())["grade"] == rep["grade"]


def test_issue_template_and_compatibility_doc():
    template = (ROOT / ".github" / "ISSUE_TEMPLATE" / "adapter-report.yml").read_text()
    docs = (ROOT / "docs" / "compatibility.md").read_text()
    assert "dongle-doctor --report" in template
    assert "full VIN" in template
    assert "No field reports" in docs
    assert "not been checked against a physical genuine ELM327" in docs
    assert "--current-ma" in docs
    assert "600" in docs
    assert "_no reports_" in docs
