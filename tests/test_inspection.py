"""OBD inspection check against the federal monitor allowance and the virtual cars."""
import subprocess
import sys

from car_use.obd.elm import ElmError
from car_use.obd.inspection import DRIVE, judge, ready_for_inspection


def _monitors(**incomplete: str):
    base = {name: "complete" for name in
            ("misfire", "fuel_system", "components", "catalyst", "evap", "o2_sensor")}
    base.update(incomplete)
    return base


def test_allowance_by_model_year():
    older = judge(mil_on=False, stored=[], model_year=1998,
                  monitors=_monitors(catalyst="incomplete", evap="incomplete"))
    assert older["ready"] and older["incomplete_allowed"] == 2
    too_many = judge(mil_on=False, stored=[], model_year=1998,
                     monitors=_monitors(catalyst="incomplete", evap="incomplete", o2_sensor="incomplete"))
    assert not too_many["ready"] and too_many["next"] == DRIVE

    one_ok = judge(mil_on=False, stored=[], model_year=2014, monitors=_monitors(evap="incomplete"))
    assert one_ok["ready"] and one_ok["incomplete_allowed"] == 1
    two_bad = judge(mil_on=False, stored=[], model_year=2001,
                    monitors=_monitors(catalyst="incomplete", evap="incomplete"))
    assert not two_bad["ready"] and "allowed 1" in two_bad["reasons"][-1]


def test_light_and_codes_fail():
    lit = judge(mil_on=True, stored=[], model_year=2014, monitors=_monitors())
    assert not lit["ready"]
    assert "check-engine" in lit["next"]
    assert DRIVE not in lit["next"]
    continuous = judge(mil_on=False, stored=[], model_year=2016,
                       monitors=_monitors(misfire="incomplete"))
    assert continuous["ready"] and continuous["next"] is None
    counted = judge(mil_on=False, stored=[], model_year=2016,
                    monitors=_monitors(misfire="incomplete", evap="incomplete"))
    assert not counted["ready"] and counted["next"] == DRIVE
    faulty = judge(mil_on=False, stored=["P0171"], model_year=2014,
                   monitors=_monitors(evap="incomplete"))
    assert not faulty["ready"] and DRIVE not in faulty["next"]
    old = judge(mil_on=False, stored=[], model_year=1990, monitors=_monitors(evap="incomplete"))
    assert not old["ready"] and old["incomplete_allowed"] is None
    assert old["next"] == "This check does not apply to that model year."


def test_unknown_year_uses_the_stricter_allowance():
    unknown = judge(mil_on=False, stored=[], model_year=None, monitors=_monitors(evap="incomplete"))
    assert unknown["ready"] and unknown["incomplete_allowed"] == 1
    assert "2001" in unknown["year_note"]


def test_healthy_virtual_car_is_ready(sim):
    report = ready_for_inspection(sim("healthy"))
    assert report["ready"] is True
    assert report["result"] == "likely to pass"
    assert report["model_year"] == 2014
    assert report["confirmed_codes"] == []
    assert report["next"] is None


def test_cleared_codes_need_a_drive_cycle(sim):
    report = ready_for_inspection(sim("cleared-codes"))
    assert report["ready"] is False
    assert report["model_year"] == 2015
    assert report["incomplete_allowed"] == 1
    assert {"catalyst", "evap", "o2_sensor"} <= set(report["incomplete"])
    assert report["next"] == DRIVE
    assert report["mil_on"] is False


def test_missing_or_unverified_vin_uses_the_stricter_allowance(sim, monkeypatch):
    car = sim("healthy")
    car._emulator.car.monitors.update(catalyst="incomplete", evap="incomplete")

    def no_vin():
        raise ElmError("0902", "NO DATA")

    monkeypatch.setattr(car, "read_vin", no_vin)
    # Second VIN decodes to 1998, but its check digit is 3 instead of 4.
    for vin in ("", "2HGFB2253WH500001"):
        car.vin = vin
        report = ready_for_inspection(car)
        assert report["model_year"] is None and report["year_note"]
        assert report["incomplete_allowed"] == 1 and not report["ready"]


def test_helper_is_loaded_into_scripts():
    r = subprocess.run([sys.executable, "-m", "car_use.run", "--sim", "cleared-codes"],
                       input="print(ready_for_inspection()['result'])\n",
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "not ready" in r.stdout
