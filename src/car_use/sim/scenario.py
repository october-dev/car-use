"""Scenario files: a virtual car as TOML.

    [car]       name, vin, protocol (6 = ISO 15765 CAN 11-bit 500k), ignition
    [adapter]   profile = "genuine" | "clone" | "stn", latency_ms
    [signals]   alias = number | {value, jitter} | {wave="sine"|"square", min, max, period}
                       | {ramp_from, ramp_to, seconds}
    [dtcs]      stored, pending, permanent = ["P0420", ...]
    [monitors]  catalyst = "complete" | "incomplete", ...
    [freeze_frame]  dtc = "P0420", plus alias = value pairs
    [dids]      "F190" = "hex bytes"  (Mode 22 data identifiers)
"""
from __future__ import annotations

import math
import random
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from .. import paths


@dataclass
class Scenario:
    name: str
    title: str
    vin: str
    protocol: str = "6"
    ignition: str = "run"
    adapter: dict = field(default_factory=dict)
    signals: dict = field(default_factory=dict)
    dtcs: dict = field(default_factory=dict)
    monitors: dict = field(default_factory=dict)
    freeze_frame: dict = field(default_factory=dict)
    dids: dict = field(default_factory=dict)
    notes: str = ""
    source: str = ""

    def value(self, alias: str, t: float):
        spec = self.signals.get(alias)
        if spec is None:
            return None
        if isinstance(spec, (int, float)):
            return float(spec)
        if "wave" in spec:
            lo, hi, period = spec["min"], spec["max"], spec.get("period", 1.0)
            phase = (t % period) / period
            if spec["wave"] == "square":
                return hi if phase < 0.5 else lo
            return lo + (hi - lo) * (0.5 + 0.5 * math.sin(2 * math.pi * phase))
        if "ramp_from" in spec:
            frac = min(1.0, t / max(spec.get("seconds", 60), 1e-6))
            return spec["ramp_from"] + (spec["ramp_to"] - spec["ramp_from"]) * frac
        v = float(spec.get("value", 0))
        j = spec.get("jitter", 0)
        return v + random.uniform(-j, j) if j else v


def _search_dirs() -> list[Path]:
    dirs = [paths.home() / "scenarios"]
    try:
        pkg = resources.files("car_use") / "scenarios"
        if pkg.is_dir():
            dirs.append(Path(str(pkg)))
    except (ModuleNotFoundError, TypeError):
        pass
    dirs.append(Path(__file__).resolve().parents[3] / "scenarios")   # repo checkout
    return [d for d in dirs if d.is_dir()]


def available() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for d in reversed(_search_dirs()):          # user dir wins
        for f in sorted(d.glob("*.toml")):
            found[f.stem] = f
    return found


def load(name_or_path: str) -> Scenario:
    p = Path(name_or_path)
    if not p.suffix:
        scen = available()
        if name_or_path not in scen:
            raise FileNotFoundError(f"No scenario {name_or_path!r}. Available: "
                                    + ", ".join(sorted(scen)))
        p = scen[name_or_path]
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    return from_dict(data, name=p.stem, source=str(p))


def from_dict(data: dict, name: str, source: str = "") -> Scenario:
    car = data.get("car", {})
    return Scenario(
        name=name, title=car.get("name", name), vin=car.get("vin", "1CARUSE0000000000"),
        protocol=str(car.get("protocol", "6")), ignition=car.get("ignition", "run"),
        adapter=data.get("adapter", {}), signals=data.get("signals", {}),
        dtcs=data.get("dtcs", {}), monitors=data.get("monitors", {}),
        freeze_frame=data.get("freeze_frame", {}), dids=data.get("dids", {}),
        notes=data.get("notes", ""), source=source)


def read_raw(name_or_path: str) -> dict:
    """The scenario's TOML as a dict (for tools that layer changes on top)."""
    p = Path(name_or_path)
    if not p.suffix:
        scen = available()
        if name_or_path not in scen:
            raise FileNotFoundError(f"No scenario {name_or_path!r}")
        p = scen[name_or_path]
    return tomllib.loads(p.read_text(encoding="utf-8"))
