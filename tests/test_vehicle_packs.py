"""Mode 22 packs: validation, isolation, targeting, and helper integration."""
import json
import shutil
from pathlib import Path

import pytest

from car_use.kernel.policy import Audit
from car_use.obd import packs as P
from car_use.obd.elm import Elm327, ElmError
from car_use.obd.packs import (
    FormulaError, PackError, check_formula, decode_payload, eval_formula,
    find_did, load_packs, matching,
)
from car_use.transport.base import Transport, TransportError

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
RECORDING = FIXTURES / "mode22" / "example.json"
PACK = FIXTURES / "packs" / "example.yaml"
PACK_DEMO = str(FIXTURES / "scenarios" / "pack-demo.toml")
VIN = "4T1BF1FK0EU300042"

GOOD_PACK = """\
name: t
match:
  wmi: ["4T1"]
  year_from: 2010
  year_to: 2020
dids:
  - ecu: "7E0"
    id: "F190"
    name: pack_counter
    formula: "A * 256 + B"
    unit: count
    vss: Vehicle.Demo.Counter
"""


def _load_text(tmp_path, text, name="t.yaml"):
    p = tmp_path / name
    p.write_text(text)
    return P._load_file(p)


def _swap(text, old, new):
    assert old in text
    return text.replace(old, new)


def _install_example(home):
    dest = home / "packs"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(PACK, dest / "example.yaml")


class _ScriptedTransport(Transport):
    """Canned adapter replies: bytes, an exception to raise, or a list served
    in order (the last one repeats)."""

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


def test_recorded_response_decodes_with_the_yaml_formula():
    recorded = json.loads(RECORDING.read_text())
    packs = load_packs(extra=[FIXTURES / "packs"])
    formula = next(d.formula for p in packs if p.name == "example-counter"
                   for d in p.dids)
    payload = bytes.fromhex(recorded["response"].replace(" ", ""))
    assert decode_payload(formula, payload, bytes.fromhex("F190")) == recorded["value"]
    assert eval_formula("(A + 1) * 2", bytes([3])) == 8
    with pytest.raises(FormulaError):
        eval_formula("__import__('os')", b"\x01")
    with pytest.raises(FormulaError):
        eval_formula("A + ", b"\x01")


def test_formula_syntax_is_checked_without_data():
    check_formula("A * 256 + B")
    with pytest.raises(FormulaError):
        check_formula("A + ")
    with pytest.raises(FormulaError):
        check_formula("(A")
    # Division by zero is a data error, not a syntax error.
    check_formula("A / B")
    with pytest.raises(FormulaError):
        eval_formula("A / B", bytes([4, 0]))
    # Only ASCII A-Z are byte references; nesting is bounded; numbers parse.
    with pytest.raises(FormulaError):
        eval_formula("ß", bytes([1]))
    with pytest.raises(FormulaError):
        eval_formula("(" * 100 + "A" + ")" * 100, bytes([1]))
    with pytest.raises(FormulaError):
        eval_formula("1.2.3", bytes([1]))


def test_decode_payload_checks_the_did_echo():
    good = bytes.fromhex("62F190012C")
    assert decode_payload("A * 256 + B", good, bytes.fromhex("F190")) == 300
    with pytest.raises(FormulaError):
        decode_payload("A", bytes.fromhex("62F19100"), bytes.fromhex("F190"))
    with pytest.raises(FormulaError):
        decode_payload("A", bytes.fromhex("62F1"), bytes.fromhex("F190"))
    with pytest.raises(FormulaError):
        decode_payload("A", bytes.fromhex("7F2231"), bytes.fromhex("F190"))


def test_good_pack_loads_with_source_and_description(tmp_path):
    pack = _load_text(tmp_path, GOOD_PACK)
    assert pack.dids[0].ecu == "7E0"
    assert pack.source.endswith("t.yaml")
    for header in ("7DF", "7FF", "7e0"):
        text = _swap(GOOD_PACK, 'ecu: "7E0"', f'ecu: "{header}"')
        assert _load_text(tmp_path, text).dids[0].ecu == header.upper()


@pytest.mark.parametrize("old,new", [
    ('  - ecu: "7E0"\n    ', '  - '),
    ('ecu: "7E0"', 'ecu: "7E0\\r04"'),
    ('ecu: "7E0"', 'ecu: "XYZ"'),
    ('ecu: "7E0"', 'ecu: "7E"'),
    ('ecu: "7E0"', 'ecu: "1234"'),
    ('ecu: "7E0"', 'ecu: "FFF"'),
    ('ecu: "7E0"', 'ecu: "800"'),
    ('ecu: "7E0"', 'ecu: 123'),
    ('id: "F190"', 'id: 0101'),
    ('id: "F190"', 'id: 0x0400'),
    ('id: "F190"', 'id: "XYZ1"'),
    ('id: "F190"', 'id: "F19"'),
    ('    id: "F190"\n', ''),
    ('    name: pack_counter\n', ''),
    ('name: pack_counter', 'name: speed'),
    ('name: pack_counter', 'name: "010C"'),
    ('name: pack_counter', 'name: "0c"'),
    ('name: pack_counter', 'name: "pid:0c"'),
    ('name: pack_counter', 'name: "a:b"'),
    ('vss: Vehicle.Demo.Counter', 'vss: Vehicle.Speed'),
    ('vss: Vehicle.Demo.Counter', 'vss: "a:b"'),
    ('formula: "A * 256 + B"', 'formula: "A + "'),
    ('formula: "A * 256 + B"', 'formula: ""'),
    ('formula: "A * 256 + B"', 'formula: 42'),
])
def test_invalid_pack_fields_are_rejected_with_file_and_field(tmp_path, old, new):
    text = GOOD_PACK if old == new else _swap(GOOD_PACK, old, new)
    with pytest.raises(PackError) as e:
        _load_text(tmp_path, text, "bad.yaml")
    assert "bad.yaml" in str(e.value)


@pytest.mark.parametrize("text", [
    "- 1\n- 2\n",
    "name: t\nmatch: 42\n",
    "name: t\nmatch:\n  wmi: 42\n",
    "name: t\nmatch:\n  wmi: [\"TOOLONG\"]\n",
    "name: t\nmatch:\n  wmi: [\"4T1\"]\n  year_from: \"2014\"\n",
    "name: t\nmatch:\n  wmi: [\"4T1\"]\n  year_from: true\n",
    "name: t\nmatch:\n  wmi: [\"4T1\"]\n  year_from: 2020\n  year_to: 2010\n",
    "name: t\nmatch:\n  wmi: [\"4T1\"]\n  year_from: 1700\n",
    "name: t\ndids: 42\n",
    "name: t\ndids:\n  - 42\n",
])
def test_invalid_pack_shapes_are_rejected(tmp_path, text):
    with pytest.raises(PackError) as e:
        _load_text(tmp_path, text, "bad.yaml")
    assert "bad.yaml" in str(e.value)


def test_pack_match_uses_wmi_and_year_bounds():
    packs = load_packs(extra=[FIXTURES / "packs"])
    assert matching(VIN, packs)
    assert matching("1FADP3F26EL400017", packs) == []
    assert matching("4T1BF1FK0DU300042", packs) == []   # 2013, below year_from
    assert matching("4T1BF1FK0FU300042", packs) == []   # 2015, above year_to


def test_pack_matches_vin_and_reads_on_the_simulator(sim, isolated_home):
    _install_example(isolated_home)
    packs = load_packs()
    assert any(p.name == "example-counter" for p in packs)
    assert matching(VIN, packs)
    assert matching("1FADP3F26EL400017", packs) == []

    v = sim(PACK_DEMO)
    names = {s["alias"] for s in v.signals()}
    assert "pack_counter" in names
    reading = v.read("pack:pack_counter")
    assert reading.value == 300
    assert reading.unit == "count"
    assert v.read("Vehicle.Demo.Counter").value == 300
    # A normal Mode 01 read still works afterwards (restore is proven
    # against a stateful fake adapter below; the sim ignores headers).
    assert v.read("coolant").value == 90


def test_installed_pack_leaves_a_nonmatching_car_alone(sim, isolated_home):
    _install_example(isolated_home)
    v = sim("healthy")
    assert "pack_counter" not in {s["alias"] for s in v.signals()}
    assert v.read("coolant").value is not None
    with pytest.raises(KeyError):
        v.read("pack_counter")


def test_invalid_pack_files_do_not_break_standard_reads(sim, isolated_home, capsys):
    dest = isolated_home / "packs"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "bad-syntax.yaml").write_text("dids: [oops\n")
    (dest / "bad-keys.yaml").write_text("name: x\ndids:\n  - name: only-a-name\n")
    shutil.copy(PACK, dest / "example.yaml")

    v = sim(PACK_DEMO)
    assert v.read("coolant").value == 90
    assert v.read("pack_counter").value == 300
    assert v.dtcs()["stored"] == []
    u = sim("cleared-codes")
    assert u.read("coolant").value > 70
    assert u.dtcs()["stored"] == []
    assert u.readiness()["distance_since_clear"] == 11
    assert u.readiness()["warmups_since_clear"] == 2
    err = capsys.readouterr().err
    assert "bad-syntax.yaml" in err and "bad-keys.yaml" in err


def test_malicious_pack_cannot_inject_commands(sim, isolated_home):
    evil = _swap(GOOD_PACK, 'ecu: "7E0"', 'ecu: "7E0\\r04"')
    evil = _swap(evil, "name: pack_counter", "name: evil_counter")
    dest = isolated_home / "packs"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "evil.yaml").write_text(evil)

    v = sim("p0420")
    assert v.read("coolant").value is not None
    assert "evil_counter" not in {s["alias"] for s in v.signals()}
    assert v.dtcs()["stored"] == ["P0420"]
    cmds = [cmd for _, cmd, _ in v.elm.log]
    assert "04" not in cmds
    assert not any(c.startswith("ATSH") for c in cmds)
    path = Audit().path
    entries = [json.loads(line) for line in path.read_text().splitlines()
               if line.strip()] if path.exists() else []
    assert not any(e["kind"] in ("allow", "effect") for e in entries)


def _targeted_elm(t, proto="A6"):
    elm = Elm327(t)
    elm.info.protocol_number = proto
    return elm


def test_targeted_read_sends_set_request_restore():
    t = _ScriptedTransport({
        "ATSH7E0": b"OK\r\r>",
        "22F190": b"62 F1 90 01 2C\r\r>",
        "ATSH7DF": b"OK\r\r>",
        "010C": b"41 0C 0C 80\r\r>",
    })
    elm = Elm327(t)
    elm.info.protocol_number = "A6"
    assert elm.query_targeted("7E0", "22F190") == [bytes.fromhex("62F190012C")]
    assert [cmd for _, cmd, _ in elm.log] == ["ATSH7E0", "22F190", "ATSH7DF"]
    assert elm.query_one("010C") == bytes.fromhex("410C0C80")
    assert t.writes[-1] == "010C"


@pytest.mark.parametrize("proto", ["A7", "7", "A4", ""])
def test_targeted_read_refuses_unsupported_protocols_before_io(proto):
    t = _ScriptedTransport({})
    with pytest.raises(ElmError):
        _targeted_elm(t, proto).query_targeted("7E0", "22F190")
    assert t.writes == []


@pytest.mark.parametrize("header", ["7E0\r04", "XYZ", "7E", "", "1234", "18DA10F1", "FFF"])
def test_targeted_read_rejects_bad_headers_before_io(header):
    t = _ScriptedTransport({})
    with pytest.raises(ValueError):
        _targeted_elm(t).query_targeted(header, "22F190")
    assert t.writes == []


def test_targeted_read_sends_nothing_after_a_refused_target():
    t = _ScriptedTransport({"ATSH7E0": b"?\r\r>"})
    with pytest.raises(ElmError):
        _targeted_elm(t).query_targeted("7E0", "22F190")
    assert t.writes == ["ATSH7E0"]


def test_targeted_read_restores_after_a_failed_query():
    t = _ScriptedTransport({
        "ATSH7E0": b"OK\r\r>",
        "22F190": b"NO DATA\r\r>",
        "ATSH7DF": b"OK\r\r>",
    })
    with pytest.raises(ElmError):
        _targeted_elm(t).query_targeted("7E0", "22F190")
    assert t.writes == ["ATSH7E0", "22F190", "ATSH7DF"]


def test_failed_restore_fails_the_connection_until_reinit():
    script = {
        "ATSH7E0": b"OK\r\r>",
        "22F190": b"62 F1 90 01 2C\r\r>",
        "ATSH7DF": b"?\r\r>",
        "ATZ": b"ELM327 v1.5\r\r>",
        "ATE0": b"OK\r\r>", "ATL0": b"OK\r\r>", "ATS0": b"OK\r\r>",
        "ATH0": b"OK\r\r>", "ATAT1": b"OK\r\r>", "ATSP0": b"OK\r\r>",
        "AT@1": b"?\r\r>", "STI": b"?\r\r>",
        "010C": b"41 0C 0C 80\r\r>",
    }
    t = _ScriptedTransport(script)
    elm = Elm327(t)
    elm.info.protocol_number = "A6"
    with pytest.raises(ElmError):
        elm.query_targeted("7E0", "22F190")
    assert t.writes == ["ATSH7E0", "22F190", "ATSH7DF"]
    with pytest.raises(ElmError):
        elm.query_one("010C")
    assert t.writes == ["ATSH7E0", "22F190", "ATSH7DF"]
    elm.initialize()
    assert elm.query_one("010C") == bytes.fromhex("410C0C80")


def test_restore_timeout_fails_the_connection():
    t = _ScriptedTransport({
        "ATSH7E0": b"OK\r\r>",
        "22F190": b"62 F1 90 01 2C\r\r>",
        "ATSH7DF": TransportError("write failed"),
    })
    elm = _targeted_elm(t)
    with pytest.raises(ElmError):
        elm.query_targeted("7E0", "22F190")
    with pytest.raises(ElmError):
        elm.query_one("010C")
    assert t.writes == ["ATSH7E0", "22F190", "ATSH7DF"]


def test_pack_connection_failure_is_visible(sim, isolated_home, monkeypatch):
    _install_example(isolated_home)
    v = sim(PACK_DEMO)
    monkeypatch.setattr(v.elm, "query_targeted",
                        lambda header, req: (_ for _ in ()).throw(
                            ElmError(req, "UNABLE TO CONNECT")))
    with pytest.raises(ElmError):
        v.read("pack_counter")


def test_pack_no_data_and_did_mismatch_are_none_readings(sim, isolated_home, monkeypatch):
    _install_example(isolated_home)
    v = sim(PACK_DEMO)
    monkeypatch.setattr(v.elm, "query_targeted",
                        lambda header, req: (_ for _ in ()).throw(
                            ElmError(req, "NO DATA")))
    assert v.read("pack_counter").value is None
    monkeypatch.setattr(v.elm, "query_targeted",
                        lambda header, req: [bytes.fromhex("62F19100")])
    assert v.read("pack_counter").value is None


def test_read_many_mixes_standard_and_pack_signals(sim, isolated_home):
    _install_example(isolated_home)
    v = sim(PACK_DEMO)
    vals = v.read_many(["coolant", "pack_counter"])
    assert vals["coolant"].value == 90
    assert vals["pack_counter"].value == 300
    vals = v.read_many(["pack:pack_counter", "Vehicle.Demo.Counter", "rpm"])
    assert vals["pack:pack_counter"].value == 300
    assert vals["Vehicle.Demo.Counter"].value == 300
    assert vals["rpm"].value == 750


def test_read_many_still_batches_standard_pids(sim, isolated_home):
    _install_example(isolated_home)
    v = sim(PACK_DEMO)
    v.read_many(["rpm", "coolant"])
    assert "010C05" in [cmd for _, cmd, _ in v.elm.log]


def test_watch_and_manifest_see_pack_signals(sim, isolated_home):
    _install_example(isolated_home)
    v = sim(PACK_DEMO)
    from car_use import helpers
    helpers._state["vehicle"] = v
    try:
        s = helpers.watch(["coolant", "pack_counter"], seconds=0.3, hz=20)
    finally:
        helpers._state["vehicle"] = None
    assert s.units["pack_counter"] == "count"
    assert s.column("pack_counter") and all(x == 300 for x in s.column("pack_counter"))
    assert "Vehicle.Demo.Counter" in v.manifest().signals


def test_signals_pack_prefix_selects_packs(sim, isolated_home):
    _install_example(isolated_home)
    v = sim(PACK_DEMO)
    assert "pack_counter" in {s["alias"] for s in v.signals("pack:")}


def test_find_did_rejects_double_prefix(isolated_home):
    _install_example(isolated_home)
    packs = load_packs()
    assert find_did("pack:pack:pack_counter", packs) is None
    assert find_did("pack:pack_counter", packs).name == "pack_counter"
