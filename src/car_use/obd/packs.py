"""Manufacturer Mode 22 packs.

A pack is YAML: which VINs it matches, which ECU header to use, and a DID
with a formula. Formulas are arithmetic on the response bytes (A, B, C…),
not Python. A contributed pack cannot call functions.

Shipped packs live in ``packs/*.yaml`` at the repo root (and inside the
wheel, if included). A user or an agent can also drop packs in
``~/.car-use/packs/``. Nothing in the default tree pretends to be a real
Hyundai, Kia, Toyota or GM identifier: those need a recorded response.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import yaml

from .. import paths
from . import vin as vinmod


class FormulaError(ValueError):
    pass


@dataclass(frozen=True)
class Did:
    ecu: str
    did: str
    name: str
    formula: str
    unit: str
    vss: str
    description: str = ""


@dataclass(frozen=True)
class Pack:
    name: str
    wmi: tuple[str, ...]
    year_from: int | None
    year_to: int | None
    dids: tuple[Did, ...]
    source: str = ""


def eval_formula(formula: str, data: bytes) -> float:
    """Evaluate ``A * 256 + B`` style formulas. No names, calls, or attributes."""
    src = "".join(formula.split())
    if not src:
        raise FormulaError("empty formula")
    pos = 0

    def peek() -> str:
        return src[pos] if pos < len(src) else ""

    def parse_expr() -> float:
        nonlocal pos
        val = parse_term()
        while peek() in {"+", "-"}:
            op = src[pos]
            pos += 1
            rhs = parse_term()
            val = val + rhs if op == "+" else val - rhs
        return val

    def parse_term() -> float:
        nonlocal pos
        val = parse_factor()
        while peek() in {"*", "/"}:
            op = src[pos]
            pos += 1
            rhs = parse_factor()
            if op == "/" and rhs == 0:
                raise FormulaError("division by zero")
            val = val * rhs if op == "*" else val / rhs
        return val

    def parse_factor() -> float:
        nonlocal pos
        if peek() == "(":
            pos += 1
            val = parse_expr()
            if peek() != ")":
                raise FormulaError("missing )")
            pos += 1
            return val
        if peek() == "-":
            pos += 1
            return -parse_factor()
        if peek().isdigit() or peek() == ".":
            start = pos
            pos += 1
            while peek().isdigit() or peek() == ".":
                pos += 1
            return float(src[start:pos])
        if peek().isalpha():
            name = src[pos]
            pos += 1
            idx = ord(name.upper()) - ord("A")
            if not 0 <= idx < len(data):
                raise FormulaError(f"{name} is past the end of the response")
            return float(data[idx])
        raise FormulaError(f"cannot read {src[pos:]!r}")

    value = parse_expr()
    if pos != len(src):
        raise FormulaError(f"trailing {src[pos:]!r}")
    return value


def decode_payload(formula: str, payload: bytes) -> float:
    """Mode 22 positive response is ``62 didHi didLo data…``. The formula sees data only."""
    if len(payload) < 3 or payload[0] != 0x62:
        raise FormulaError("not a Mode 22 response")
    return eval_formula(formula, payload[3:])


def load_packs(extra: list[Path] | None = None) -> list[Pack]:
    found: list[Pack] = []
    for directory in _pack_dirs(extra):
        for path in sorted(directory.glob("*.yaml")):
            found.append(_load_file(path))
    return found


def matching(vin: str, packs: list[Pack] | None = None) -> list[Pack]:
    info = vinmod.decode(vin or "")
    wmi = (info.get("wmi") or "") if info.get("valid_format") else ""
    year = info.get("model_year") if info.get("valid_format") else None
    out = []
    for pack in packs if packs is not None else load_packs():
        if wmi not in pack.wmi:
            continue
        if pack.year_from is not None and (year is None or year < pack.year_from):
            continue
        if pack.year_to is not None and (year is None or year > pack.year_to):
            continue
        out.append(pack)
    return out


def find_did(name: str, packs: list[Pack]) -> Did | None:
    key = name.removeprefix("pack:")
    for pack in packs:
        for did in pack.dids:
            if key in (did.name, did.vss, "pack:" + did.name):
                return did
    return None


def _pack_dirs(extra: list[Path] | None) -> list[Path]:
    dirs: list[Path] = []
    try:
        pkg = resources.files("car_use") / "packs"
        if pkg.is_dir():
            dirs.append(Path(str(pkg)))
    except (ModuleNotFoundError, TypeError):
        pass
    repo = Path(__file__).resolve().parents[3] / "packs"
    dirs.append(repo)
    dirs.append(paths.home() / "packs")
    if extra:
        dirs.extend(extra)
    return [d for d in dirs if d.is_dir()]


def _load_file(path: Path) -> Pack:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} is not a pack mapping")
    match = raw.get("match") or {}
    wmi = match.get("wmi") or []
    if isinstance(wmi, str):
        wmi = [wmi]
    dids = []
    for item in raw.get("dids") or []:
        dids.append(Did(
            ecu=str(item.get("ecu") or "7E0").upper(),
            did=str(item["id"]).replace(" ", "").upper(),
            name=str(item["name"]),
            formula=str(item["formula"]),
            unit=str(item.get("unit") or ""),
            vss=str(item.get("vss") or ""),
            description=str(item.get("description") or ""),
        ))
    return Pack(
        name=str(raw.get("name") or path.stem),
        wmi=tuple(str(w).upper() for w in wmi),
        year_from=_year(match.get("year_from")),
        year_to=_year(match.get("year_to")),
        dids=tuple(dids),
        source=str(path),
    )


def _year(value) -> int | None:
    if value is None or value == "":
        return None
    return int(value)
