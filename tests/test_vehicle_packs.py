"""Mode 22 packs: formula, VIN match, and a recorded synthetic response."""
import json
import shutil
from pathlib import Path

import pytest

from car_use.obd.packs import FormulaError, decode_payload, eval_formula, load_packs, matching

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "mode22" / "example.json"
PACK = ROOT / "tests" / "fixtures" / "packs" / "example.yaml"


def test_recorded_response_decodes_and_formulas_cannot_call_code():
    recorded = json.loads(FIXTURE.read_text())
    payload = bytes.fromhex(recorded["response"].replace(" ", ""))
    assert decode_payload(recorded["formula"], payload) == recorded["value"]
    assert eval_formula("(A + 1) * 2", bytes([3])) == 8
    with pytest.raises(FormulaError):
        eval_formula("__import__('os')", b"\x01")
    with pytest.raises(FormulaError):
        eval_formula("A + ", b"\x01")


def test_pack_matches_vin_and_reads_on_the_simulator(sim):
    from car_use import paths
    dest = paths.home() / "packs"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(PACK, dest / "example.yaml")

    packs = load_packs()
    assert any(p.name == "example-counter" for p in packs)
    assert matching("4T1BF1FK0EU300042", packs)
    assert matching("1FADP3F26EL400017", packs) == []

    v = sim("pack-demo")
    names = {s["alias"] for s in v.signals()}
    assert "pack_counter" in names
    reading = v.read("pack:pack_counter")
    assert reading.value == 300
    assert reading.unit == "count"
    assert v.read("Vehicle.Demo.Counter").value == 300
    # header restored: a normal Mode 01 read still works afterwards
    assert v.read("coolant").value == 90


def test_unmatched_car_has_no_pack_signals(sim):
    v = sim("pack-demo")
    assert "pack_counter" not in {s["alias"] for s in v.signals()}
    with pytest.raises(KeyError):
        v.read("pack_counter")
