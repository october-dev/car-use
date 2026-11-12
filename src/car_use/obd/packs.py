"""Manufacturer Mode 22 packs.

A pack is YAML: which VINs it matches, which ECU header to use, and a DID
with a formula. Formulas are arithmetic on the response bytes (A, B, C…),
not Python. A contributed pack cannot call functions.

Shipped packs live in ``packs/*.yaml`` at the repo root (and inside the
wheel, if included). A user or an agent can also drop packs in
``~/.car-use/packs/``. Nothing in the default tree pretends to be a real
Hyundai, Kia, Toyota or GM identifier: those need a recorded response.

This first loader is deliberately bounded (see packs/README.md): Mode 22
only, one request header per reading, 11-bit CAN protocols 6/8, formulas
over bytes A-Z with arithmetic and no bit operations.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import yaml

from .. import paths
from . import pids as _pids
from . import vin as vinmod
from .elm import validate_header


class FormulaError(ValueError):
    pass


class PackError(ValueError):
    """A pack file is invalid. The message names the file and the field."""


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
    description: str = ""


# --- formulas: parse once (syntax), evaluate per response (data) -------------

_MAX_DEPTH = 64
_BYTE = re.compile(r"[A-Za-z]")


def _parse_formula(src: str):
    """Parse ``A * 256 + B`` grammar into nodes. Syntax errors only."""
    s = "".join(src.split())
    if not s:
        raise FormulaError("empty formula")

    def peek(pos: int) -> str:
        return s[pos] if pos < len(s) else ""

    def parse_expr(pos: int, depth: int):
        node, pos = parse_term(pos, depth)
        while peek(pos) in {"+", "-"}:
            op, pos = s[pos], pos + 1
            rhs, pos = parse_term(pos, depth)
            node = ("binop", op, node, rhs)
        return node, pos

    def parse_term(pos: int, depth: int):
        node, pos = parse_factor(pos, depth)
        while peek(pos) in {"*", "/"}:
            op, pos = s[pos], pos + 1
            rhs, pos = parse_factor(pos, depth)
            node = ("binop", op, node, rhs)
        return node, pos

    def parse_factor(pos: int, depth: int):
        if depth > _MAX_DEPTH:
            raise FormulaError("too deeply nested")
        c = peek(pos)
        if c == "(":
            node, pos = parse_expr(pos + 1, depth + 1)
            if peek(pos) != ")":
                raise FormulaError("missing )")
            return node, pos + 1
        if c == "-":
            node, pos = parse_factor(pos + 1, depth + 1)
            return ("neg", node), pos
        if c.isdigit() or c == ".":
            start = pos
            pos += 1
            while peek(pos).isdigit() or peek(pos) == ".":
                pos += 1
            try:
                return ("num", float(s[start:pos])), pos
            except ValueError:
                raise FormulaError(f"bad number {s[start:pos]!r}") from None
        if _BYTE.match(c):
            return ("byte", ord(c.upper()) - ord("A")), pos + 1
        raise FormulaError(f"cannot read {s[pos:]!r}")

    node, pos = parse_expr(0, 0)
    if pos != len(s):
        raise FormulaError(f"trailing {s[pos:]!r}")
    return node


def _eval_node(node, data: bytes) -> float:
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "byte":
        idx = node[1]
        if idx >= len(data):
            raise FormulaError(f"{chr(ord('A') + idx)} is past the end of the response")
        return float(data[idx])
    if kind == "neg":
        return -_eval_node(node[1], data)
    _, op, left, right = node
    lv, rv = _eval_node(left, data), _eval_node(right, data)
    if op == "+":
        return lv + rv
    if op == "-":
        return lv - rv
    if op == "*":
        return lv * rv
    if rv == 0:
        raise FormulaError("division by zero")
    return lv / rv


def check_formula(formula: str) -> None:
    """Syntax-check a formula without response data (for pack loading)."""
    _parse_formula(formula)


def eval_formula(formula: str, data: bytes) -> float:
    """Evaluate ``A * 256 + B`` style formulas. No names, calls, or attributes."""
    return _eval_node(_parse_formula(formula), data)


def decode_payload(formula: str, payload: bytes, expect: bytes | None = None) -> float:
    """Mode 22 positive response is ``62 didHi didLo data…``. The formula sees data only.

    ``expect`` is the two requested DID bytes; a reply for another DID is refused.
    """
    if len(payload) < 3 or payload[0] != 0x62:
        raise FormulaError("not a Mode 22 response")
    if expect is not None and bytes(payload[1:3]) != bytes(expect):
        raise FormulaError("response is for a different DID")
    return eval_formula(formula, payload[3:])


# --- loading -----------------------------------------------------------------

_DID = re.compile(r"^[0-9A-Fa-f]{4}$")
_WMI = re.compile(r"^[A-Z0-9]{3}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def load_packs(extra: list[Path] | None = None) -> list[Pack]:
    """All valid packs. An invalid file is skipped with one stderr diagnostic,
    so one bad file cannot break ordinary diagnostics."""
    found: list[Pack] = []
    for directory in _pack_dirs(extra):
        files = sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml"))
        for path in files:
            try:
                found.append(_load_file(path))
            except (PackError, yaml.YAMLError, OSError, ValueError) as e:
                print(f"car-use: skipping invalid pack {path}: {e}", file=sys.stderr)
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
            if key in (did.name, did.vss):
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

    def bad(field: str, problem: str) -> PackError:
        return PackError(f"{path}: {field}: {problem}")

    if not isinstance(raw, dict):
        raise bad("pack", "must be a mapping")
    name = raw.get("name", path.stem)
    if not isinstance(name, str):
        raise bad("name", f"must be a string, got {type(name).__name__}")
    description = raw.get("description", "")
    if not isinstance(description, str):
        raise bad("description", f"must be a string, got {type(description).__name__}")
    match = raw.get("match", {})
    if not isinstance(match, dict):
        raise bad("match", f"must be a mapping, got {type(match).__name__}")
    wmi = match.get("wmi", [])
    if isinstance(wmi, str):
        wmi = [wmi]
    if not isinstance(wmi, list) or any(not isinstance(w, str) for w in wmi):
        raise bad("match.wmi", "must be a string or a list of strings")
    wmis = []
    for w in wmi:
        w = w.upper()
        if not _WMI.match(w):
            raise bad("match.wmi", f"{w!r} is not a 3-character WMI")
        wmis.append(w)
    year_from = _year(match.get("year_from"), path, "match.year_from")
    year_to = _year(match.get("year_to"), path, "match.year_to")
    if year_from is not None and year_to is not None and year_from > year_to:
        raise bad("match.year_from", f"{year_from} is after year_to {year_to}")
    items = raw.get("dids", [])
    if not isinstance(items, list):
        raise bad("dids", f"must be a list, got {type(items).__name__}")
    dids = []
    for i, item in enumerate(items):
        dids.append(_load_did(path, i, item))
    return Pack(name=name, wmi=tuple(wmis), year_from=year_from, year_to=year_to,
                dids=tuple(dids), source=str(path), description=description)


def _load_did(path: Path, i: int, item) -> Did:
    def bad(field: str, problem: str) -> PackError:
        return PackError(f"{path}: dids[{i}].{field}: {problem}")

    if not isinstance(item, dict):
        raise PackError(f"{path}: dids[{i}]: must be a mapping, got {type(item).__name__}")
    if "ecu" not in item:
        raise bad("ecu", "is required: an explicit request header such as \"7E0\"")
    try:
        ecu = validate_header(item["ecu"])
    except ValueError as e:
        raise bad("ecu", str(e)) from None
    if "id" not in item:
        raise bad("id", "is required: a quoted four-hex-digit DID such as \"F190\"")
    raw_id = item["id"]
    if not isinstance(raw_id, str):
        raise bad("id", f"must be a quoted four-hex-digit string, got {type(raw_id).__name__} "
                        f"{raw_id!r} (quote it: unquoted 0101 is octal 65)")
    did = raw_id.replace(" ", "").upper()
    if not _DID.match(did):
        raise bad("id", f"{raw_id!r} is not four hex digits")
    name = item.get("name")
    if not isinstance(name, str) or not name:
        raise bad("name", "is required and must be a non-empty string")
    if ":" in name or _CONTROL.search(name):
        raise bad("name", f"{name!r} must not contain ':' or control characters")
    formula = item.get("formula")
    if not isinstance(formula, str) or not formula.strip():
        raise bad("formula", "is required and must be a non-empty string")
    try:
        check_formula(formula)
    except FormulaError as e:
        raise bad("formula", str(e)) from None
    unit = item.get("unit") or ""
    vss = item.get("vss") or ""
    desc = item.get("description") or ""
    for field, value in (("unit", unit), ("vss", vss), ("description", desc)):
        if not isinstance(value, str):
            raise bad(field, f"must be a string, got {type(value).__name__}")
    if _CONTROL.search(vss) or ":" in vss:
        raise bad("vss", f"{vss!r} must not contain ':' or control characters")
    for field, candidate in (("name", name), ("vss", vss)):
        if not candidate:
            continue
        try:
            _pids.resolve(candidate)
        except KeyError:
            pass
        else:
            raise bad(field, f"{candidate!r} collides with a built-in signal name; "
                             "rename the pack signal")
    return Did(ecu=ecu, did=did, name=name, formula=formula, unit=unit, vss=vss,
               description=desc)


def _year(value, path: Path, field: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise PackError(f"{path}: {field}: must be an integer year, "
                        f"got {type(value).__name__} {value!r}")
    if not 1900 <= value <= 2100:
        raise PackError(f"{path}: {field}: {value} is outside 1900..2100")
    return value
