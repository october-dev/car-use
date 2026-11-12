"""Parse a TunerStudio .ini (the ECU definition file every TS-compatible ECU ships).

What we read:
  [MegaTune]        signature, queryCommand
  [Constants]       endianness, nPages, pageSize, and per page: scalar / array / bits / string
  [OutputChannels]  ochGetCommand, ochBlockSize, and the live channels (scalar, bits, {expressions})

Value conversion follows the TS convention: shown = (raw + translate) * scale.
Preprocessor blocks (#if NAME / #else / #endif) take the branch for names in
`defines` (or set with #set), else the #else branch. Some names are TunerStudio
user preferences, e.g. CELSIUS for temperatures and LAMBDA for lambda vs AFR:
pass them to match how the user has TunerStudio set up. Expressions in { } are kept as text, not evaluated.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

TYPES = {"U08": "B", "S08": "b", "U16": "H", "S16": "h", "U32": "I", "S32": "i", "F32": "f"}


@dataclass
class Field:
    name: str
    kind: str                 # scalar | array | bits | string | expr
    type: str = ""            # U08, S16, F32...
    offset: int = 0
    units: str = ""
    scale: float = 1.0
    translate: float = 0.0
    shape: tuple[int, ...] = ()
    bits: tuple[int, int] | None = None
    options: list[str] = field(default_factory=list)
    lo: float | None = None
    hi: float | None = None
    page: int | None = None
    expr: str = ""

    @property
    def size(self) -> int:
        n = struct.calcsize(TYPES.get(self.type, "B"))
        count = 1
        for d in self.shape:
            count *= d
        return n * count


@dataclass
class Ini:
    signature: str = ""
    query_command: str = ""
    endianness: str = "little"
    page_sizes: list[int] = field(default_factory=list)
    constants: dict[str, Field] = field(default_factory=dict)
    channels: dict[str, Field] = field(default_factory=dict)
    och_command: str = ""
    och_block_size: int = 0
    path: str = ""

    def tables(self) -> dict[str, Field]:
        return {k: f for k, f in self.constants.items() if f.kind == "array" and len(f.shape) == 2}

    def decode_channels(self, block: bytes) -> dict[str, float | str]:
        """Turn one realtime data block (the ochGetCommand reply) into named values."""
        end = "<" if self.endianness == "little" else ">"
        out: dict[str, float | str] = {}
        for name, f in self.channels.items():
            if f.kind not in ("scalar", "bits") or f.type not in TYPES:
                continue
            fmt = end + TYPES[f.type]
            size = struct.calcsize(fmt)
            if f.offset + size > len(block):
                continue
            raw = struct.unpack_from(fmt, block, f.offset)[0]
            if f.kind == "bits" and f.bits:
                lo, hi = f.bits
                raw = (int(raw) >> lo) & ((1 << (hi - lo + 1)) - 1)
                out[name] = f.options[raw] if raw < len(f.options) else raw
            else:
                out[name] = round((raw + f.translate) * f.scale, 6)
        return out

    def summary(self) -> dict:
        tables = self.tables()
        return {
            "signature": self.signature,
            "endianness": self.endianness,
            "pages": len(self.page_sizes),
            "page_sizes": self.page_sizes,
            "constants": len(self.constants),
            "tables": {k: f"{f.shape[0]}x{f.shape[1]} {f.units}".strip() for k, f in tables.items()},
            "live_channels": len(self.channels),
            "realtime_block_bytes": self.och_block_size,
            "channels": {k: f.units for k, f in list(self.channels.items())[:40]},
        }


def _split(s: str) -> list[str]:
    """Split on commas outside quotes, [] and {}."""
    out, cur, depth, quote = [], [], 0, False
    for ch in s:
        if ch == '"':
            quote = not quote
        elif not quote and ch in "[{":
            depth += 1
        elif not quote and ch in "]}":
            depth -= 1
        if ch == "," and not quote and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur).strip())
    return out


def _unq(s: str) -> str:
    s = s.strip()
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] == '"' else s


def _num(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _strip_comment(line: str) -> str:
    out, quote = [], False
    for ch in line:
        if ch == '"':
            quote = not quote
        if ch == ";" and not quote:
            break
        out.append(ch)
    return "".join(out).strip()


def _preprocess(lines: list[str], defines: set[str]) -> list[str]:
    out, stack = [], []          # stack of (taking, any_branch_taken)
    for line in lines:
        s = line.strip()
        if s.startswith("#if"):
            name = s.split(None, 1)[1].strip() if " " in s else ""
            take = name in defines
            stack.append([take, take])
            continue
        if s.startswith("#elif"):
            name = s.split(None, 1)[1].strip() if " " in s else ""
            top = stack[-1] if stack else [False, False]
            top[0] = (not top[1]) and name in defines
            top[1] = top[1] or top[0]
            continue
        if s.startswith("#else"):
            if stack:
                stack[-1][0] = not stack[-1][1]
                stack[-1][1] = True
            continue
        if s.startswith("#endif"):
            if stack:
                stack.pop()
            continue
        if s.startswith(("#set", "#unset")) and all(t for t, _ in stack):
            parts = s.split()
            if len(parts) > 1:
                (defines.add if parts[0] == "#set" else defines.discard)(parts[1])
            continue
        if s.startswith("#"):
            continue             # #define, #include
        if all(t for t, _ in stack):
            out.append(line)
    return out


def _field(name: str, parts: list[str], page: int | None) -> Field | None:
    kind = parts[0].lower()
    if kind.startswith("{"):
        return Field(name, "expr", expr=",".join(parts).strip("{} "))
    if kind not in ("scalar", "array", "bits", "string") or len(parts) < 3:
        return None
    f = Field(name, kind, type=parts[1].upper(), page=page)
    f.offset = int(_num(parts[2]) or 0)
    rest = parts[3:]
    if kind == "array" and rest:
        dims = re.findall(r"\d+", rest[0])
        f.shape = tuple(int(d) for d in dims)
        rest = rest[1:]
    if kind == "bits" and rest:
        m = re.match(r"\[(\d+):(\d+)\]", rest[0].replace(" ", ""))
        if m:
            f.bits = (int(m.group(1)), int(m.group(2)))
        f.options = [_unq(o) for o in rest[1:]]
        return f
    if kind == "string":
        return f
    if rest:
        f.units = _unq(rest[0])
    if len(rest) > 1 and _num(rest[1]) is not None:
        f.scale = _num(rest[1])
    if len(rest) > 2 and _num(rest[2]) is not None:
        f.translate = _num(rest[2])
    if len(rest) > 3:
        f.lo = _num(rest[3])
    if len(rest) > 4:
        f.hi = _num(rest[4])
    return f


def parse(text: str, defines: set[str] | None = None, path: str = "") -> Ini:
    ini = Ini(path=path)
    section, page = "", None
    for raw in _preprocess(text.splitlines(), set(defines or ())):
        line = _strip_comment(raw)
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if "=" not in line:
            continue
        key, val = (x.strip() for x in line.split("=", 1))
        parts = _split(val)
        if section == "MegaTune":
            if key == "signature":
                ini.signature = _unq(val)
            elif key == "queryCommand":
                ini.query_command = _unq(val)
        elif section == "Constants":
            if key == "endianness":
                ini.endianness = val.strip().lower()
            elif key == "pageSize":
                ini.page_sizes = [int(_num(p) or 0) for p in parts]
            elif key == "page":
                page = int(_num(val) or 0)
            elif key not in ("nPages",):
                f = _field(key, parts, page)
                if f:
                    ini.constants[key] = f
        elif section == "OutputChannels":
            if key == "ochGetCommand":
                ini.och_command = _unq(val)
            elif key == "ochBlockSize":
                ini.och_block_size = int(_num(val) or 0)
            else:
                f = _field(key, parts, None)
                if f:
                    ini.channels[key] = f
    return ini


def load(path: str | Path, defines: set[str] | None = None) -> Ini:
    p = Path(path)
    return parse(p.read_text(encoding="utf-8", errors="replace"), defines, str(p))
