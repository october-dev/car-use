"""Our own ELM327/STN driver.

Written for the adapters people actually own: clones that report "v1.5",
drop AT commands, answer slowly, or interleave SEARCHING... and BUS INIT
noise. Every quirk we meet in the field gets handled here and a scenario in
the emulator, not patched in user code.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field

from ..transport.base import Transport, TransportError

NOISE = ("SEARCHING...", "BUS INIT", "BUSINIT", "...OK")
ERRORS = {
    "NO DATA": "no ECU answered this request",
    "UNABLE TO CONNECT": "adapter could not talk to the car; is the ignition on?",
    "CAN ERROR": "CAN bus error; check the adapter is seated and the ignition is on",
    "BUS ERROR": "bus error",
    "BUFFER FULL": "adapter buffer overflowed (common on clone adapters)",
    "STOPPED": "request interrupted",
    "?": "adapter did not understand the command",
    "ERR": "adapter error",
    "FB ERROR": "feedback error on the bus wiring",
    "DATA ERROR": "corrupted response",
    "ACT ALERT": "adapter is entering low power",
    "LV RESET": "adapter reset on low voltage",
}

_FRAME_IDX = re.compile(r"^[0-9A-F]:")
_HEX = re.compile(r"^[0-9A-F]+$")


def _reassemble_legacy(payloads: list[bytes]) -> list[bytes]:
    """Join non-CAN multi-line replies. CAN / ISO-TP is already one payload.

    Mode 09 PID 02 arrives as several `49 02 nn` frames of four data bytes,
    with up to three leading zero pads. Mode 03/07/0A repeats the service
    byte and has no DTC count byte.
    """
    if len(payloads) < 2:
        return payloads
    if all(len(p) >= 3 and p[0] == 0x49 and p[1] == 0x02 for p in payloads):
        data = bytearray()
        for p in payloads:
            data += p[3:]
        return [bytes([0x49, 0x02, 0x01]) + bytes(data).lstrip(b"\x00")]
    head = payloads[0][0]
    if head in (0x43, 0x47, 0x4A) and all(p and p[0] == head for p in payloads):
        body = bytearray()
        for p in payloads:
            body += p[1:]
        return [bytes([head]) + body]
    return payloads


class ElmError(RuntimeError):
    def __init__(self, command: str, code: str):
        self.command, self.code = command, code
        super().__init__(f"{command}: {code} ({ERRORS.get(code, 'unexpected reply')})")


@dataclass
class AdapterInfo:
    identity: str = ""
    device: str = ""
    stn: str | None = None
    protocol: str = ""
    protocol_number: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def is_can(self) -> bool:
        # ATDPN returns e.g. "A6" (auto, protocol 6); protocols 6-9 are ISO 15765 CAN.
        n = self.protocol_number.lstrip("A")
        return n in {"6", "7", "8", "9"}


class Elm327:
    def __init__(self, transport: Transport, timeout: float = 5.0):
        self.t = transport
        self.timeout = timeout
        self.lock = threading.Lock()
        self.info = AdapterInfo()
        self.log: list[tuple[float, str, str]] = []   # (seconds, cmd, reply) for tracing

    # -- raw I/O ----------------------------------------------------------------
    def command(self, cmd: str, timeout: float | None = None) -> list[str]:
        """Send one command, return non-empty reply lines (echo and noise removed)."""
        with self.lock:
            start = time.monotonic()
            self.t.write(cmd.encode("ascii") + b"\r")
            raw = self.t.read_until(b">", self._timeout_for(timeout))
            text = raw.decode("ascii", errors="replace").replace("\n", "\r")
            lines = [ln.strip() for ln in text.split("\r")]
            lines = [ln for ln in lines if ln and ln != ">" and ln.rstrip(">") != ""]
            lines = [ln.rstrip(">").strip() for ln in lines]
            # strip echo if the adapter still echoes (some clones ignore ATE0)
            squashed = cmd.replace(" ", "").upper()
            if lines and lines[0].replace(" ", "").upper() == squashed:
                lines = lines[1:]
            lines = [ln for ln in lines if not any(ln.upper().startswith(n) for n in NOISE)]
            self.log.append((time.monotonic() - start, cmd, " | ".join(lines)))
            if len(self.log) > 2000:
                del self.log[:1000]
            return lines

    def at(self, cmd: str) -> str:
        lines = self.command(cmd)
        return lines[-1] if lines else ""

    def at_ok(self, cmd: str) -> bool:
        try:
            reply = self.at(cmd)
        except TransportError:
            return False
        return reply.upper() not in ("?", "ERROR", "") and "?" not in reply

    # -- setup ------------------------------------------------------------------
    def initialize(self, protocol: str = "0") -> AdapterInfo:
        self.t.drain()
        self.t.write(b"\r")           # flush any half-typed command
        try:
            self.t.read_until(b">", 2.0)
        except TransportError:
            pass
        ident = self.command("ATZ", timeout=5.0)
        self.info.identity = next((ln for ln in ident if "ELM" in ln.upper() or "STN" in ln.upper()
                                   or "OBD" in ln.upper()), " ".join(ident))
        for c in ("ATE0", "ATL0", "ATS0", "ATH0", "ATAT1"):
            self.at_ok(c)
        self.at_ok(f"ATSP{protocol}")
        self.info.device = self.at("AT@1") if self.at_ok("AT@1") else ""
        sti = self.at("STI") if self.at_ok("STI") else None
        self.info.stn = sti
        return self.info

    def _timeout_for(self, timeout: float | None) -> float:
        chosen = self.timeout if timeout is None else timeout
        number = self.info.protocol_number.lstrip("A")
        if number in {"1", "2", "3", "4", "5"}:
            return max(chosen, 10.0)
        return chosen

    def detect_protocol(self) -> str:
        """Find the protocol. Auto first, then ISO 14230, ISO 9141 and J1850.

        Non-CAN cars are slow to wake. The first probe and each fallback use a
        long timeout, and a failed auto search tries ATSP5, 4, 3, 2 and 1.
        """
        if not self._probe_0100(15.0):
            for proto in ("5", "4", "3", "2", "1"):
                self.at_ok(f"ATSP{proto}")
                if self._probe_0100(15.0):
                    break
        self.info.protocol_number = self.at("ATDPN")
        self.info.protocol = self.at("ATDP")
        return self.info.protocol

    def _probe_0100(self, timeout: float) -> bool:
        try:
            self.query("0100", timeout=timeout)
            return True
        except ElmError:
            return False

    # -- OBD requests -----------------------------------------------------------
    def query(self, request: str, timeout: float | None = None) -> list[bytes]:
        """Send an OBD request (hex), return one payload per responding ECU.

        Handles single-frame replies and ISO-TP multi-frame replies formatted
        by the adapter (a byte-count line followed by "0:", "1:" ... lines).
        """
        req = request.replace(" ", "").upper()
        if not _HEX.match(req) or len(req) % 2:
            raise ValueError(f"OBD request must be hex bytes, got {request!r}")
        lines = self.command(req, timeout)
        for ln in lines:
            up = ln.upper()
            for code in ERRORS:
                if up == code or up.startswith(code):
                    raise ElmError(req, code)
        payloads: list[bytes] = []
        multi: bytearray | None = None
        multi_len = 0
        for ln in lines:
            s = ln.replace(" ", "").upper()
            if _FRAME_IDX.match(s):
                if multi is None:
                    multi = bytearray()
                multi += bytes.fromhex(s[2:])
                continue
            if len(s) == 3 and _HEX.match(s):           # ISO-TP total length line
                if multi is not None and multi_len:
                    payloads.append(bytes(multi[:multi_len]))
                multi, multi_len = bytearray(), int(s, 16)
                continue
            if _HEX.match(s) and len(s) % 2 == 0:
                payloads.append(bytes.fromhex(s))
        if multi is not None:
            payloads.append(bytes(multi[:multi_len] if multi_len else multi))
        payloads = _reassemble_legacy(payloads)
        if not payloads:
            raise ElmError(req, lines[-1] if lines else "NO DATA")
        return payloads

    def query_one(self, request: str) -> bytes:
        """First payload whose service byte is the positive response (+0x40)."""
        req = request.replace(" ", "").upper()
        want = int(req[:2], 16) + 0x40
        payloads = self.query(req)
        for p in payloads:
            if p and p[0] == want:
                return p
        if payloads and payloads[0] and payloads[0][0] == 0x7F:
            raise ElmError(req, f"negative response 0x{payloads[0][2]:02X}"
                                if len(payloads[0]) > 2 else "negative response")
        return payloads[0]

    def close(self) -> None:
        self.t.close()
