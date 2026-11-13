"""Used-car scan: verdicts, failures, flags, and output formats."""
import argparse
import subprocess
import sys
import types

import pytest

from car_use import config
from car_use.inspection_report import build, render_html, render_markdown
from car_use.obd.elm import ElmError
from car_use.sim.scenario import available
from car_use.transport.base import TransportError

HEALTHY_VIN = "2HGFB2F53EH500001"
OTHER_VIN = "2HGFB2F53EH500002"   # valid format, differs from the healthy car


class _Reading:
    def __init__(self, value):
        self.value = value


class _StubElm:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _stub_vehicle(*, vin=HEALTHY_VIN, stored=(), pending=(), permanent=(),
                  descriptions=None, codes_mil=False, ready_mil=False,
                  incomplete=(), distance=500, warmups=40,
                  battery=14.1, rpm=750, fail=None):
    """A vehicle-shaped object. fail=exception makes dtcs() and readiness() raise it."""
    v = types.SimpleNamespace()
    v.vin = vin
    v.scenario = None
    v.elm = _StubElm()
    codes = {"stored": list(stored), "pending": list(pending),
             "permanent": list(permanent),
             "descriptions": dict(descriptions or {})}
    if codes_mil is not None:      # None = the first readiness read failed
        codes["mil_on"] = codes_mil
    ready = {"mil_on": ready_mil, "incomplete": list(incomplete),
             "distance_since_clear": distance, "warmups_since_clear": warmups}
    if fail is not None:
        def dtcs():
            raise fail
    else:
        def dtcs():
            return dict(codes)
    v.dtcs = dtcs
    if fail is not None:
        def readiness():
            raise fail
        v.readiness = readiness      # a car that fails, fails every request
    else:
        v.readiness = lambda: dict(ready)
    v.read = lambda name: _Reading({"battery": battery, "rpm": rpm}[name])
    return v


def _healthy_variant(home, name, old, new):
    text = available()["healthy"].read_text(encoding="utf-8")
    assert old in text
    d = home / "scenarios"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.toml").write_text(text.replace(old, new), encoding="utf-8")


def _inspect(*argv):
    return subprocess.run([sys.executable, "-m", "car_use.run", *argv],
                          capture_output=True, text=True, timeout=60)


def test_cleared_codes_is_a_red_scan(sim):
    report = build(sim("cleared-codes"), expect_vin="1G1PE5SB7F7000999")
    assert report["verdict"] == "red"
    titles = " ".join(item["title"] for item in report["items"])
    assert "cleared" in titles.lower()
    red = next(item for item in report["items"] if item["level"] == "red")
    assert "11" in red["detail"]
    text = render_markdown(report)
    assert "Do not treat this car as clean" in text
    assert "## Red" in text
    assert "oxygen sensor" in text and "o2_sensor" not in text
    assert "None km" not in text


def test_matching_vin_on_a_healthy_car_has_no_red(sim):
    v = sim("healthy")
    report = build(v, expect_vin=v.vin)
    assert report["verdict"] != "red"
    vin_item = next(i for i in report["items"] if "VIN matches" in i["title"])
    assert vin_item["level"] == "green"
    assert "Honda" in vin_item["detail"]
    assert any("Odometer" in item["title"] for item in report["items"])
    assert "car-use does not yet compare odometer readings across modules" in \
        render_markdown(report)


def test_report_uses_code_descriptions(sim):
    text = render_markdown(build(sim("p0420")))
    assert "P0420 (Catalyst system efficiency below threshold, bank 1)" in text


def test_report_marks_simulation_and_scan_time(sim):
    report = build(sim("healthy"))
    assert report["simulated"] == "2014 Honda Civic 1.8 (sim)"
    assert report["scanned_at"]
    text = render_markdown(report)
    assert "Scanned" in text and "simulated car: 2014 Honda Civic 1.8 (sim)" in text
    page = render_html(build(sim("cleared-codes")))
    assert 'lang="en"' in page and "viewport" in page
    assert page.index(">red:") < page.index(">amber:")


def test_html_escapes_text_and_the_cli_writes_it(tmp_path, sim):
    report = build(sim("cleared-codes"))
    report["items"][0]["detail"] = "<script>alert(1)</script>"
    page = render_html(report)
    assert "<script>" not in page
    assert "&lt;script&gt;" in page

    out = tmp_path / "scan.html"
    md = tmp_path / "scan.md"
    proc = _inspect("inspect", "--sim", "cleared-codes", "--html", str(out),
                    "--md", str(md))
    assert proc.returncode == 0, proc.stderr
    assert "Do not treat this car as clean" in proc.stdout
    assert out.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    assert md.read_text(encoding="utf-8").startswith("# Used-car scan:")
    assert "wrote" in proc.stderr


def test_failed_save_keeps_the_printed_report(tmp_path):
    missing = tmp_path / "nodir" / "scan.md"
    proc = _inspect("--sim", "healthy", "inspect", "--md", str(missing))
    assert proc.returncode == 1
    assert "# Used-car scan:" in proc.stdout
    assert "could not save" in proc.stderr


@pytest.mark.parametrize("exc", [
    TransportError("simulated timeout"),
    ElmError("03", "UNABLE TO CONNECT"),
    OSError("simulated I/O failure"),
])
def test_scan_failure_returns_useful_text_and_closes(monkeypatch, capsys, exc):
    import car_use.connect
    from car_use import run as runmod
    v = _stub_vehicle(fail=exc)
    monkeypatch.setattr(car_use.connect, "open_vehicle", lambda device=None, kernel=None: v)
    args = argparse.Namespace(sim="whatever", device=None, expect_vin=None,
                              html=None, md=None)
    assert runmod.cmd_inspect(args) == 1
    cap = capsys.readouterr()
    assert "cannot scan" in cap.err and "Traceback" not in cap.out + cap.err
    assert v.elm.closed


def test_ignition_off_scan_fails_cleanly():
    for argv in (["--sim", "ignition-off", "inspect"],
                ["inspect", "--sim", "ignition-off"]):
        proc = _inspect(*argv)
        assert proc.returncode == 1, argv
        assert "ignition" in proc.stderr.lower(), argv
        assert "Traceback" not in proc.stdout + proc.stderr, argv


def test_unreadable_vin_is_amber_not_red():
    for car_vin in ("", "1"):
        report = build(_stub_vehicle(vin=car_vin), expect_vin=OTHER_VIN)
        assert report["verdict"] == "amber"
        assert not any(i["level"] == "red" for i in report["items"])
        item = next(i for i in report["items"] if "VIN could not be read" in i["title"])
        assert item["level"] == "amber"
        assert "windshield" in item["detail"]


def test_unusable_typed_vin_is_amber():
    report = build(_stub_vehicle(), expect_vin="1")
    assert report["verdict"] != "red"
    item = next(i for i in report["items"] if "not usable" in i["title"])
    assert item["level"] == "amber"


def test_valid_vin_mismatch_is_red():
    report = build(_stub_vehicle(), expect_vin=OTHER_VIN)
    assert report["verdict"] == "red"
    item = next(i for i in report["items"] if "does not match" in i["title"])
    assert item["level"] == "red"


def test_light_on_in_second_sample_is_red():
    v = _stub_vehicle(codes_mil=None, ready_mil=True)
    report = build(v)
    assert report["verdict"] == "red"
    text = render_markdown(report)
    assert "commanded on." in text
    assert "not commanded on" not in text


def test_permanent_only_is_an_amber_caution():
    v = _stub_vehicle(permanent=["P0420"],
                      descriptions={"P0420": "Catalyst system efficiency below threshold, bank 1"},
                      incomplete=("catalyst",), distance=11, warmups=2)
    report = build(v)
    assert report["verdict"] == "red"   # from the readiness evidence, not the codes
    assert sum(i["level"] == "red" for i in report["items"]) == 1
    item = next(i for i in report["items"] if "Permanent codes" in i["title"])
    assert item["level"] == "amber"
    assert "repair has not been verified" in item["detail"]
    assert "repair history" in item["detail"]


def test_stored_and_permanent_together_add_no_second_item(sim):
    report = build(sim("p0420"))
    assert not any("Permanent" in i["title"] for i in report["items"])
    assert any(i["level"] == "red" for i in report["items"])


@pytest.mark.parametrize("distance,warmups,level", [
    (300, 50, "amber"), (299, 50, "red"),
    (500, 10, "amber"), (500, 9, "red"),
    (None, None, "amber"), (None, 3, "red"), (50, None, "red"),
])
def test_recent_clear_boundaries(distance, warmups, level):
    v = _stub_vehicle(incomplete=("catalyst",), distance=distance, warmups=warmups)
    report = build(v)
    item = next(i for i in report["items"] if "onitor" in i["title"])
    assert item["level"] == level


def test_missing_distance_and_warmups_read_clearly():
    v = _stub_vehicle(distance=None, warmups=None)
    report = build(v)
    item = next(i for i in report["items"] if "Readiness monitors are complete" in i["title"])
    assert "not reported" in item["detail"]
    assert "None" not in render_markdown(report)


@pytest.mark.parametrize("volts,word", [(12.8, "low"), (15.4, "high")])
def test_extreme_charging_readings_are_amber_observations(sim, isolated_home, volts, word):
    _healthy_variant(isolated_home, f"charge-{word}",
                     "battery = { value = 14.2, jitter = 0.05 }", f"battery = {volts}")
    report = build(sim(f"charge-{word}"))
    assert not any(i["level"] == "red" and "Charging" in i["title"]
                   for i in report["items"])
    item = next(i for i in report["items"] if f"reads {word}" in i["title"])
    assert item["level"] == "amber"
    assert "charging system tested" in item["detail"]


def test_missing_voltage_and_rpm_are_explained(sim, isolated_home):
    _healthy_variant(isolated_home, "no-volt",
                     "battery = { value = 14.2, jitter = 0.05 }\n", "")
    report = build(sim("no-volt"))
    assert any(i["level"] == "amber" and "not reported" in i["title"]
               for i in report["items"])
    _healthy_variant(isolated_home, "no-rpm", "rpm = { value = 750, jitter = 15 }\n", "")
    report = build(sim("no-rpm"))
    item = next(i for i in report["items"] if "Engine state is unknown" in i["title"])
    assert item["level"] == "amber"


def test_dying_battery_stays_red_from_its_code(sim):
    report = build(sim("dying-battery"))
    assert report["verdict"] == "red"
    assert any(i["level"] == "red" and "P0562" in i["detail"] for i in report["items"])
    item = next(i for i in report["items"] if "Charging" in i["title"])
    assert item["level"] == "amber"


def test_sim_flag_wins_in_either_position():
    config.set_("device", "sim:p0420")
    for argv in (["inspect", "--sim", "healthy"], ["--sim", "healthy", "inspect"]):
        proc = _inspect(*argv)
        assert proc.returncode == 0, (argv, proc.stderr)
        assert "Honda Civic" in proc.stdout, argv
    proc = _inspect("inspect")
    assert proc.returncode == 0, proc.stderr
    assert "Toyota Corolla" in proc.stdout


def test_parent_sim_flag_survives_for_doctor():
    config.set_("device", "sim:p0420")
    proc = _inspect("--sim", "healthy", "doctor")
    assert proc.returncode == 0, proc.stderr
    assert "Honda Civic" in proc.stdout


def test_one_unsupported_section_does_not_cost_the_scan():
    from car_use.inspection_report import build
    v = _stub_vehicle()
    def no_mode(*a, **k):
        raise ElmError("0101", "?")
    v.readiness = no_mode
    rep = build(v)
    titles = [i["title"] for i in rep["items"]]
    assert "Readiness monitors were not reported" in titles
    assert "Readiness monitors are complete" not in titles
