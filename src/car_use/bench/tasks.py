"""Benchmark tasks: TOML files with the owner's words, a virtual car and an answer key.

    id = "catalyst"
    family = "single-fault"
    canary = "..."                       # detects leakage into training data
    prompt = "My check engine light came on this morning. What's wrong?"
    answer = ["catalytic_converter"]     # full credit
    partial = ["o2_sensor_downstream"]   # half credit
    evidence = [{ need = "codes" }, { need = "watch", pid = "15", seconds = 5 }]

    [sim]                                # the virtual car
    base = "p0420"                       # start from a scenario, then override sections
    [sim.dtcs]
    stored = ["P0420"]

Task files are not shipped in the wheel: an agent under test should not find the
answers in site-packages. Run the benchmark from a checkout of the repo.
"""
from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ..sim import scenario as S
from .taxonomy import ROOT_CAUSES

SIM_SECTIONS = ("car", "adapter", "signals", "dtcs", "monitors", "freeze_frame", "dids")
NEEDS = {"codes", "pending", "permanent", "freeze_frame", "readiness", "vin", "watch", "read",
         "any_request"}


@dataclass
class Task:
    id: str
    prompt: str
    answer: list[str]
    partial: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    family: str = ""
    sim: dict = field(default_factory=dict)
    path: str = ""

    @property
    def opaque(self) -> str:
        """A name for the virtual car that says nothing about the fault."""
        return "car-" + hashlib.sha256(self.id.encode()).hexdigest()[:8]

    def scenario(self) -> S.Scenario:
        data: dict = {}
        base = self.sim.get("base")
        if base:
            data = S.read_raw(base)
        for sec in SIM_SECTIONS:
            if sec in self.sim:
                data[sec] = {**data.get(sec, {}), **self.sim[sec]}
        data.pop("notes", None)
        car = data.setdefault("car", {})
        car["name"] = car.get("name", "Car").replace(" (sim)", "")
        return S.from_dict(data, name=self.opaque)


def _check(t: Task) -> None:
    bad = [c for c in t.answer + t.partial if c not in ROOT_CAUSES]
    if bad:
        raise ValueError(f"task {t.id}: unknown root causes {bad}")
    if not t.answer:
        raise ValueError(f"task {t.id}: empty answer")
    for e in t.evidence:
        if e.get("need") not in NEEDS:
            raise ValueError(f"task {t.id}: unknown evidence need {e!r}")


def load_task(path: Path) -> Task:
    d = tomllib.loads(path.read_text(encoding="utf-8"))
    t = Task(id=d.get("id", path.stem), prompt=d["prompt"], answer=list(d["answer"]),
             partial=list(d.get("partial", [])), evidence=list(d.get("evidence", [])),
             family=d.get("family", ""), sim=d.get("sim", {}), path=str(path))
    _check(t)
    return t


def default_dir() -> Path | None:
    """bench/tasks/dev in the current directory (a clone), else next to this source tree."""
    for d in (Path.cwd() / "bench" / "tasks" / "dev",
              Path(__file__).resolve().parents[3] / "bench" / "tasks" / "dev"):
        if d.is_dir():
            return d
    return None


def load_tasks(directory: str | Path | None = None, only: list[str] | None = None) -> list[Task]:
    d = Path(directory) if directory else default_dir()
    if d is None or not d.is_dir():
        raise FileNotFoundError(
            "No task directory. Clone the repo and run from it, or pass --tasks DIR: "
            "git clone https://github.com/october-dev/car-use")
    tasks = [load_task(p) for p in sorted(d.glob("*.toml"))]
    if only:
        tasks = [t for t in tasks if t.id in only]
    return tasks
