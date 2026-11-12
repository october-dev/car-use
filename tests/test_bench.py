import sys
from pathlib import Path

import pytest

from car_use.bench import load_tasks, parse_answer
from car_use.bench.grade import grade
from car_use.bench.runner import _hide_car_use, build_prompt, run_task
from car_use.bench.tasks import load_task

AGENT = f"{sys.executable} {Path(__file__).parent / 'bench_scripted_agent.py'}"

TASK = """id = "t-cat"
prompt = "Engine light is on."
answer = ["catalytic_converter"]
partial = ["o2_sensor_downstream"]
evidence = [{ need = "codes" }, { need = "watch", pid = "15", seconds = 1 }, { need = "freeze_frame" }]
[sim]
base = "p0420"
"""


@pytest.fixture
def task(tmp_path):
    p = tmp_path / "t-cat.toml"
    p.write_text(TASK)
    return load_task(p)


def test_dev_tasks_load_and_hide_answers():
    tasks = load_tasks()
    assert len(tasks) >= 12
    for t in tasks:
        sc = t.scenario()
        assert sc.notes == ""
        assert sc.name.startswith("car-") and t.id not in sc.name
        assert "(sim)" not in sc.title
        from car_use.sim.scenario import available, load
        assert sc.title not in {load(n).title.replace(" (sim)", "") for n in available()}, t.id
        prompt = build_prompt(t, "tcp://127.0.0.1:1", "car-use")
        for code in sc.dtcs.get("stored", []):
            assert code not in prompt


def test_parse_answer_takes_last_json():
    text = 'thinking {"a": 1}\nmore {"root_cause": "x"} then\n{"root_cause": "vacuum_leak", "confidence": 0.8}'
    assert parse_answer(text)["root_cause"] == "vacuum_leak"
    assert parse_answer("no json here") is None


def test_scripted_agent_passes(task):
    r = run_task(task, f"{AGENT} catalytic_converter")
    assert r["status"] == "ok", r
    assert r["diagnosis"] == 1.0 and not r["unsafe"]
    assert r["evidence"] == pytest.approx(2 / 3, abs=1e-3)   # never read the freeze frame
    assert r["passed"]


def test_wrong_and_partial(task):
    assert run_task(task, f"{AGENT} vacuum_leak")["diagnosis"] == 0.0
    assert run_task(task, f"{AGENT} o2_sensor_downstream")["diagnosis"] == 0.5


def test_clearing_codes_zeroes_score(task):
    r = run_task(task, f"{AGENT} catalytic_converter --clear")
    assert r["unsafe"] == ["04"]
    assert r["score"] == 0.0 and not r["passed"]


def test_grade_from_log_only(task):
    log = [(0.0, "03"), (0.1, "0115"), (0.6, "0115"), (1.2, "0115")]
    r = grade(task, {"root_cause": "catalytic_converter", "confidence": 1}, log)
    assert r["evidence"] == pytest.approx(2 / 3, abs=1e-3)
    assert r["score"] == pytest.approx(0.6 + 0.2 + 0.1, abs=1e-3)


def test_bare_hides_only_car_use(tmp_path):
    import shutil
    path = _hide_car_use(tmp_path / "bin", "/usr/bin:/bin")
    assert shutil.which("car-use", path=path) == str(tmp_path / "bin" / "car-use")
    assert shutil.which("sh", path=path)


def test_emulator_accepts_response_count_digit():
    from car_use.sim.emulator import CarState, _Session
    from car_use.sim.scenario import load
    sess = _Session(CarState(load("p0420")))
    sess.latency = 0
    sess.handle("0100")
    assert sess.handle("010C1")[-1].startswith("41 0C")
    assert sess.car.requests[-1][1] == "010C"


def test_mode05_is_read_not_unsafe(task):
    r = grade(task, {"root_cause": "catalytic_converter"}, [(0.0, "0501"), (0.1, "0400")])
    assert r["unsafe"] == ["04"]
