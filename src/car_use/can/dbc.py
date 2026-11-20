"""A small DBC reader: turn raw CAN frames into named signals in real units.

A DBC file is the map from a CAN message id and its bytes to named values:
which bits hold the steering angle, how to scale them, which unit they are
in. This module reads the subset of the format that real car DBCs use (the
same subset opendbc's own parser reads) and has no dependencies:

    BO_  messages, standard and extended (bit 31 set) ids
    SG_  signals, Intel (@1) and Motorola (@0) byte order, signed (-) or not,
         factor/offset, min/max, unit, and simple multiplexing (M / mN)
    VAL_ value tables ("0 off 1 on")
    BA_DEF_/BA_/CM_ and everything else are skipped.

It decodes (bytes -> values) and encodes (values -> bytes). Encoding exists
for the simulator and for tests; nothing in car-use's read path sends it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_BO = re.compile(r"^BO_\s+(\d+)\s+(\w+)\s*:\s*(\d+)\s+(\w+)")
_SG = re.compile(
    r"^SG_\s+(\w+)\s*(M|m\d*)?\s*:\s*(\d+)\|(\d+)@([01])([+-])\s*"
    r"\(\s*([^,\s]+)\s*,\s*([^)\s]+)\s*\)\s*\[\s*([^|\]]*)\|([^\]]*)\]\s*\"([^\"]*)\"")
_VAL = re.compile(r"^VAL_\s+(\d+)\s+(\w+)\s+(.*);\s*$")
_VAL_PAIR = re.compile(r"(-?\d+)\s+\"([^\"]*)\"")


class DbcError(ValueError):
    pass


@dataclass
class Signal:
    name: str
    start: int
    size: int
    little_endian: bool
    signed: bool
    factor: float
    offset: float
    minimum: float
    maximum: float
    unit: str
    mux: str | None = None          # "M" for the selector, "m3" for a muxed signal
    choices: dict[int, str] = field(default_factory=dict)

    def _span(self, n: int) -> tuple[int, int]:
        """(bytes needed, shift) for a payload of n bytes.

        A few published DBCs define signals that run past the end of their
        frame; like opendbc, the missing bits read as zero.
        """
        if self.little_endian:
            need = max(n, (self.start + self.size + 7) // 8)
            return need, self.start
        # Motorola: `start` is the most significant bit, in the DBC's
        # byte-by-byte, bit-7-first numbering. Turn it into a position counted
        # from the first bit of the payload read big-endian.
        msb = (self.start // 8) * 8 + (7 - self.start % 8)
        need = max(n, (msb + self.size + 7) // 8)
        return need, need * 8 - msb - self.size

    def bits(self) -> dict[int, int]:
        """Which bits of which bytes this signal occupies: {byte index: bit mask}."""
        out: dict[int, int] = {}
        if self.little_endian:
            for b in range(self.start, self.start + self.size):
                out[b // 8] = out.get(b // 8, 0) | (1 << (b % 8))
        else:
            msb = (self.start // 8) * 8 + (7 - self.start % 8)
            for pos in range(msb, msb + self.size):
                out[pos // 8] = out.get(pos // 8, 0) | (1 << (7 - pos % 8))
        return out

    def raw(self, data: bytes) -> int:
        need, shift = self._span(len(data))
        data = bytes(data).ljust(need, b"\x00")
        order = "little" if self.little_endian else "big"
        value = (int.from_bytes(data, order) >> shift) & ((1 << self.size) - 1)
        if self.signed and value & (1 << (self.size - 1)):
            value -= 1 << self.size
        return value

    def decode(self, data: bytes) -> float:
        return self.raw(data) * self.factor + self.offset

    def put(self, data: bytearray, value: float) -> None:
        if isinstance(value, int) and isinstance(self.factor, int) and isinstance(self.offset, int):
            raw = (value - self.offset) // self.factor   # exact for wide signals
        else:
            raw = round((value - self.offset) / self.factor)
        lo, hi = (-(1 << (self.size - 1)), (1 << (self.size - 1)) - 1) if self.signed else (0, (1 << self.size) - 1)
        mask = (1 << self.size) - 1
        raw = max(lo, min(hi, raw)) & mask
        n = len(data)
        need, shift = self._span(n)
        order = "little" if self.little_endian else "big"
        ext = bytes(data).ljust(need, b"\x00")
        whole = int.from_bytes(ext, order)
        whole = (whole & ~(mask << shift)) | (raw << shift)
        data[:] = whole.to_bytes(need, order)[:n]


@dataclass
class Message:
    id: int                 # without the extended-id flag
    name: str
    size: int
    sender: str
    extended: bool
    signals: dict[str, Signal] = field(default_factory=dict)

    @property
    def hex_id(self) -> str:
        """The id the way car-use's monitor prints it: "2B0" or "18FEF100"."""
        return f"{self.id:08X}" if self.extended else f"{self.id:03X}"

    def decode(self, data: bytes, choices: bool = False) -> dict:
        data = bytes(data).ljust(self.size, b"\x00")
        selector = next((s for s in self.signals.values() if s.mux == "M"), None)
        sel = selector.raw(data) if selector else None
        out = {}
        for s in self.signals.values():
            if s.mux and s.mux != "M" and int(s.mux[1:]) != sel:
                continue
            v = s.decode(data)
            out[s.name] = s.choices.get(int(v), v) if choices and s.choices and float(v).is_integer() else v
        return out

    def encode(self, values: dict, base: bytes | None = None) -> bytes:
        data = bytearray((base or b"").ljust(self.size, b"\x00")[: self.size])
        for name, v in values.items():
            if name not in self.signals:
                raise DbcError(f"{self.name} has no signal {name!r}")
            self.signals[name].put(data, v)
        return bytes(data)


class Dbc:
    def __init__(self, name: str, messages: list[Message]):
        self.name = name
        self.messages = {m.name: m for m in messages}
        self.by_id = {m.hex_id: m for m in messages}

    def __repr__(self) -> str:
        return f"<Dbc {self.name}: {len(self.messages)} messages>"

    def message(self, key: str | int) -> Message:
        if isinstance(key, int):
            key = f"{key:03X}" if key <= 0x7FF else f"{key:08X}"
        m = self.messages.get(key) or self.by_id.get(str(key).upper())
        if m is None:
            raise DbcError(f"{self.name} has no message {key!r}")
        return m

    def decode(self, ident: str | int, data: bytes, choices: bool = False) -> dict | None:
        """Values of one frame, or None if this DBC doesn't know the id."""
        try:
            m = self.message(ident if isinstance(ident, int) else str(ident).upper())
        except DbcError:
            return None
        if m.name not in self.messages:
            return None
        return m.decode(data, choices)

    @classmethod
    def parse(cls, text: str, name: str = "dbc") -> "Dbc":
        messages: list[Message] = []
        current: Message | None = None
        vals: list[tuple[int, str, str]] = []
        for lineno, raw in enumerate(text.splitlines(), 1):
            line = raw.strip()
            if line.startswith("BO_ "):
                m = _BO.match(line)
                if not m:
                    raise DbcError(f"{name}:{lineno}: can't read message line")
                ident = int(m.group(1))
                current = Message(id=ident & 0x1FFFFFFF, name=m.group(2), size=int(m.group(3)),
                                  sender=m.group(4), extended=bool(ident & 0x80000000))
                messages.append(current)
            elif line.startswith("SG_ "):
                m = _SG.match(line)
                if not m or current is None:
                    raise DbcError(f"{name}:{lineno}: can't read signal line")
                lo, hi = m.group(9).strip(), m.group(10).strip()
                current.signals[m.group(1)] = Signal(
                    name=m.group(1), mux=m.group(2) if m.group(2) != "m" else None, start=int(m.group(3)), size=int(m.group(4)),
                    little_endian=m.group(5) == "1", signed=m.group(6) == "-",
                    factor=_num(m.group(7)), offset=_num(m.group(8)),
                    minimum=_num(lo) if lo else 0, maximum=_num(hi) if hi else 0, unit=m.group(11))
            elif line.startswith("VAL_ "):
                m = _VAL.match(line)
                if m:
                    vals.append((int(m.group(1)), m.group(2), m.group(3)))
            elif line and not line.startswith("SG_"):
                current = None if not raw.startswith((" ", "\t")) else current
        by_raw_id = {(m.id | (0x80000000 if m.extended else 0)): m for m in messages}
        for ident, sig, body in vals:
            msg = by_raw_id.get(ident)
            if msg and sig in msg.signals:
                msg.signals[sig].choices = {int(k): v for k, v in _VAL_PAIR.findall(body)}
        if not messages:
            raise DbcError(f"{name}: no messages found")
        return cls(name, messages)

    @classmethod
    def load(cls, path: str | Path) -> "Dbc":
        p = Path(path)
        return cls.parse(p.read_text(encoding="utf-8", errors="replace"), p.stem)


def _num(s: str) -> float:
    v = float(s)
    return int(v) if v.is_integer() and "." not in s and "e" not in s.lower() else v
