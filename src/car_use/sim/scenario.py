"""Scenario files: a virtual car as TOML.

    [car]       name, vin, protocol (6 = ISO 15765 CAN 11-bit 500k),
                ignition = "run"|"off"|"accessory",
                ignition_type = "spark"|"compression"
    [adapter]   profile = "genuine" | "clone" | "stn", latency_ms
    [signals]   alias = number | {value, jitter} | {wave="sine"|"square", min, max, period}
                       | {ramp_from, ramp_to, seconds}
    [dtcs]      stored, pending, permanent = ["P0420", ...]
    [monitors]  catalyst = "complete" | "incomplete", ...
    [freeze_frame]  dtc = "P0420", plus alias = value pairs
    [dids]      "F190" = "hex bytes"  (Mode 22 data identifiers)
    [extra_ecus.7E9]  a second ECU. stored/pending/permanent, signals, dids.
                Silent unless headers are on, or ATSH selects it.
    [[bus.frames]]  broadcast traffic on the OBD port's CAN pins, heard in
                monitor mode (ATMA). Omit [bus] for a car whose gateway keeps
                the port silent. Each frame: id = "025", hz = 50,
                data = "0000000000000000", counter = 7 (byte whose low nibble
                rolls), and [[bus.frames.fields]]: byte, length (bytes,
                big-endian) or mask (bits), then value/jitter, or wave
                ("sine"|"square") with min, max, period. A field with
                action = "steering"|"brake"|"indicator" moves only while the
                simulator plays the person doing that, and sits at `rest`
                (default min) otherwise.
    [[bus.messages]]  broadcast traffic laid out by a real DBC map (see
                `car-use dbc list`): dbc = "hyundai_can_generated",
                message = "SAS11", hz = 100, and [bus.messages.signals]
                with signal = number or the same field spec as above
                (value/jitter, wave, action, rest). Signals left out are 0.
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
    compression: bool = False
    adapter: dict = field(default_factory=dict)
    signals: dict = field(default_factory=dict)
    dtcs: dict = field(default_factory=dict)
    monitors: dict = field(default_factory=dict)
    freeze_frame: dict = field(default_factory=dict)
    dids: dict = field(default_factory=dict)
    extra_ecus: dict = field(default_factory=dict)
    bus: list = field(default_factory=list)
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
        compression=car.get("ignition_type", "spark") == "compression",
        adapter=data.get("adapter", {}), signals=data.get("signals", {}),
        dtcs=data.get("dtcs", {}), monitors=data.get("monitors", {}),
        freeze_frame=data.get("freeze_frame", {}), dids=data.get("dids", {}),
        extra_ecus=_extra_ecus(data.get("extra_ecus") or {}),
        bus=_bus(data.get("bus") or {}),
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


def _extra_ecus(raw: dict) -> dict:
    out = {}
    for ecu, body in raw.items():
        if not isinstance(body, dict):
            continue
        out[str(ecu).upper()] = {
            "stored": list(body.get("stored") or []),
            "pending": list(body.get("pending") or []),
            "permanent": list(body.get("permanent") or []),
            "signals": dict(body.get("signals") or {}),
            "dids": {str(k).upper(): v for k, v in dict(body.get("dids") or {}).items()},
        }
    return out


def _bus(raw: dict) -> list[dict]:
    """[[bus.frames]] as plain dicts with the id upper-cased and data as bytes."""
    out = []
    for frame in raw.get("frames") or []:
        ident = str(frame["id"]).upper()
        int(ident, 16)                      # a bad id fails at load, not mid-stream
        if len(ident) not in (3, 8):
            raise ValueError(f"bus frame id {ident!r} must be 3 (11-bit) or 8 (29-bit) hex digits")
        data = bytes.fromhex(str(frame.get("data", "00" * 8)).replace(" ", ""))
        if len(data) > 8:
            raise ValueError(f"bus frame {ident} has more than 8 data bytes")
        out.append({"id": ident, "hz": float(frame.get("hz", 10)), "data": data,
                    "counter": frame.get("counter"),
                    "fields": [dict(f) for f in frame.get("fields") or []]})
    for msg in raw.get("messages") or []:
        from ..can.library import load
        m = load(str(msg["dbc"])).message(str(msg["message"]))
        signals = {}
        for name, spec in (msg.get("signals") or {}).items():
            if name not in m.signals:
                raise ValueError(f"bus message {m.name} in {msg['dbc']} has no signal {name!r}")
            signals[name] = dict(spec) if isinstance(spec, dict) else {"value": spec}
        out.append({"id": m.hex_id, "hz": float(msg.get("hz", 10)), "data": bytes(m.size),
                    "counter": None, "fields": [], "message": m, "signals": signals})
    return out
