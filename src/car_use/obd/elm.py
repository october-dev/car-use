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
    """Join a non-CAN Mode 09 PID 02 reply into one CAN-shaped payload.

    It arrives as several `49 02 nn` frames of four data bytes, with up to
    three leading zero pads. Mode 03/07/0A needs no joining: each line is its
    own payload and `ObdVehicle._dtc_list` reads them one by one.
    """
    if len(payloads) < 2:
        return payloads
    if all(len(p) >= 3 and p[0] == 0x49 and p[1] == 0x02 for p in payloads):
        data = bytearray()
        for p in payloads:
            data += p[3:]
        return [bytes([0x49, 0x02, 0x01]) + bytes(data).lstrip(b"\x00")]
    return payloads


_11BIT_ECUS = {f"7E{d}" for d in "89ABCDEF"}


def assemble_headers(lines: list[str]) -> dict[str, bytes]:
    """ATH1 lines to one payload per sender. 11-bit ids are 3 hex digits, 29-bit are 8."""
    pending: dict[str, dict] = {}
    done: dict[str, bytes] = {}
    for ln in lines:
        s = ln.replace(" ", "").upper()
        if not s or not _HEX.match(s):
            continue
        ident, rest = _split_can_id(s)
        if ident is None or len(rest) < 2:
            continue
        pci = int(rest[:2], 16)
        data = bytes.fromhex(rest[2:]) if rest[2:] else b""
        kind = pci >> 4
        if kind == 0:
            done[ident] = data[:pci & 0x0F]
            pending.pop(ident, None)
        elif kind == 1 and data:
            total = ((pci & 0x0F) << 8) | data[0]
            pending[ident] = {"need": total, "buf": bytearray(data[1:]), "next": 1}
        elif kind == 2 and ident in pending and (pci & 0x0F) == pending[ident]["next"]:
            pending[ident]["buf"] += data
            pending[ident]["next"] = (pending[ident]["next"] + 1) & 0xF
            if len(pending[ident]["buf"]) >= pending[ident]["need"]:
                done[ident] = bytes(pending[ident]["buf"][:pending[ident]["need"]])
                pending.pop(ident, None)
    return done


def _split_can_id(line: str) -> tuple[str | None, str]:
    if len(line) >= 5 and line[:3] in _11BIT_ECUS:
        return line[:3], line[3:]
    if len(line) >= 10 and line[:2] in {"18", "19"}:
        return line[:8], line[8:]
    return None, line


class ListenOnlyError(RuntimeError):
    """A command that would put a frame on the bus, refused because the session is listen-only."""


# Adapter commands that never put a frame on the bus: reset, formatting,
# choosing a protocol by number (not auto search, which sends OBD requests),
# reading the protocol or the battery voltage, receive filters, silent
# monitoring on, and the STN identity and receive-only monitor mode. In a
# listen-only session everything else is refused before it reaches the
# adapter, including every OBD request, ATSP0, AT CSM0 and STCMM 1.
_SILENT_COMMANDS = re.compile(
    r"^(AT(Z|WS|D|I|@1|[ELSH][01]|AT[0-2]|[ST]PA?[1-9A-C]|DPN?|CAF[01]|CSM1|"
    r"C[FM][0-9A-F]{3}|C[FM][0-9A-F]{8}|CRA[0-9A-F]*|AR|RV|JHF[01]|J[SE])"
    r"|ST(I|DI|CMM0))$")


def silent_command(cmd: str) -> bool:
    """True if `cmd` cannot make the adapter transmit on the bus."""
    return bool(_SILENT_COMMANDS.match(cmd.replace(" ", "").upper()))


class ElmError(RuntimeError):
    def __init__(self, command: str, code: str, detail: str | None = None):
        self.command, self.code = command, code
        super().__init__(f"{command}: {code} ({detail or ERRORS.get(code, 'unexpected reply')})")


_HEADER_11 = re.compile(r"^[0-9A-Fa-f]{3}$")


def validate_header(value: str) -> str:
    """An 11-bit CAN request header: three hex digits, at most 0x7FF."""
    if not isinstance(value, str) or not _HEADER_11.match(value) or int(value, 16) > 0x7FF:
        raise ValueError(f"request header must be three hex digits up to 7FF, got {value!r}")
    return value.upper()


@dataclass
class AdapterInfo:
    identity: str = ""
    device: str = ""
    stn: str | None = None
    protocol: str = ""
    protocol_number: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def number(self) -> str:
        """The protocol without the auto marker: ATDPN "A6" (found by auto search) is 6.
        "A" alone is protocol A, SAE J1939, which auto search never picks."""
        return protocol_digit(self.protocol_number)

    @property
    def is_can(self) -> bool:
        # Protocols 6-9 are ISO 15765 CAN; A is SAE J1939 (29-bit, 250 kbit/s).
        return self.number in {"6", "7", "8", "9", "A"}

    @property
    def is_j1939(self) -> bool:
        return self.number == "A"


def protocol_digit(number: str) -> str:
    n = (number or "").strip().upper()
    return n[1:] if len(n) == 2 and n[0] == "A" else n


class Elm327:
    def __init__(self, transport: Transport, timeout: float = 5.0):
        self.t = transport
        self.timeout = timeout
        self.lock = threading.Lock()
        self.info = AdapterInfo()
        self.log: list[tuple[float, str, str]] = []   # (seconds, cmd, reply) for tracing
        self._target_broken = False
        # Listen-only: refuse every command that could put a frame on the bus.
        # Set before initialize() so not even the protocol search transmits.
        self.listen_only = False
        self.refused: list[str] = []

    # -- raw I/O ----------------------------------------------------------------
    def command(self, cmd: str, timeout: float | None = None) -> list[str]:
        """Send one command, return non-empty reply lines (echo and noise removed)."""
        if self.listen_only and not silent_command(cmd):
            self.refused.append(cmd)
            raise ListenOnlyError(
                f"{cmd!r} refused: this session is listen-only, and that command could make "
                "the adapter transmit on the bus. Reconnect without --listen-only for OBD "
                "requests (reads only), or keep listening.")
        if self._target_broken:
            raise ElmError(cmd, "NOT RESTORED",
                           "adapter addressing unknown after a failed restore; "
                           "call initialize() first")
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
        self._target_broken = False
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
        # ATSP<n> saves n as the adapter's default in EEPROM (ELM327 datasheet,
        # "SP h"), so a J1939 session would leave other OBD apps stuck on it.
        # ATTP selects it for this session only; ATSP0 (automatic) is safe.
        self.at_ok("ATSP0" if protocol == "0" else f"ATTP{protocol}")
        self.info.device = self.at("AT@1") if self.at_ok("AT@1") else ""
        sti = self.at("STI") if self.at_ok("STI") else None
        self.info.stn = sti
        return self.info

    def _timeout_for(self, timeout: float | None) -> float:
        chosen = self.timeout if timeout is None else timeout
        number = self.info.number
        if number in {"1", "2", "3", "4", "5"}:
            return max(chosen, 10.0)
        return chosen

    def detect_protocol(self) -> str:
        """Find the protocol. Auto first, then ISO 14230, ISO 9141 and J1850.

        Non-CAN cars are slow to wake. The first probe and each fallback use a
        long timeout. A failed auto search tries protocols 5, 4, 3, 2 and 1
        with ATTP, which does not rewrite the adapter's saved default the way
        ATSP does. If none answers, the adapter goes back to automatic.
        """
        if not self._probe_0100(15.0):
            for proto in ("5", "4", "3", "2", "1"):
                self.at_ok(f"ATTP{proto}")
                if self._probe_0100(15.0):
                    break
            else:
                self.at_ok("ATSP0")
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
                try:
                    multi += bytes.fromhex(s[2:])
                except ValueError:
                    raise ElmError(req, "DATA ERROR") from None
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
        if not self.info.is_can:
            payloads = _reassemble_legacy(payloads)
        if not payloads:
            raise ElmError(req, lines[-1] if lines else "NO DATA")
        return payloads

    def query_targeted(self, header: str, request: str) -> list[bytes]:
        """Send one request to a physical 11-bit CAN header, then restore 7DF.

        Only CAN protocols 6 and 8 for now: other protocols use different
        header formats (documented in packs/README.md). The target and the
        restore must both be acknowledged; a failed restore fails the
        connection until initialize() runs again. ``header`` is the request
        header (e.g. 7E0); the replying ECU's response ID (e.g. 7E8) is a
        different number.
        """
        target = validate_header(header)
        number = self.info.number
        if number not in ("6", "8"):
            raise ElmError(request, "NOT SUPPORTED",
                           f"physical addressing needs CAN protocol 6 or 8 "
                           f"(adapter reports {number or 'none'})")
        if not self.at_ok("ATSH" + target):
            raise ElmError(request, "NOT TARGETED",
                           f"adapter refused ATSH{target}")
        try:
            return self.query(request)
        finally:
            if not self.at_ok("ATSH7DF"):
                self._target_broken = True
                raise ElmError(request, "NOT RESTORED",
                               "adapter did not restore ATSH7DF; call initialize() "
                               "before further diagnostics")

    def query_by_ecu(self, request: str) -> dict[str, bytes]:
        """ATH1 for this request, then one payload per CAN id. Restores ATH0.

        CAN only: older protocols have no CAN ids, so this returns {} there
        and callers fall back to the merged reply.
        """
        if not self.info.is_can:
            return {}
        self.at_ok("ATH1")
        try:
            lines = self.command(request)
        finally:
            self.at_ok("ATH0")
        return assemble_headers(lines)

    def query_ecu(self, response_id: str, request: str) -> list[bytes]:
        """Ask the ECU that answers as `response_id` (e.g. 7E9) directly.

        Goes through query_targeted, so the header change and the restore are
        both checked. 11-bit ids only (7E8-7EF -> request 7E0-7E7); 29-bit
        physical addressing is refused rather than guessed.
        """
        resp = response_id.replace(" ", "").upper()
        if resp not in _11BIT_ECUS:
            raise ElmError(request, "NOT SUPPORTED",
                           f"per-ECU requests need an 11-bit CAN id 7E8-7EF (got {resp})")
        return self.query_targeted(f"{int(resp, 16) - 8:03X}", request)

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

    def enter_listen_only(self) -> dict:
        """Ask the adapter not to acknowledge frames while it monitors.

        ELM327 v1.4b and newer: AT CSM1 (silent monitoring, the default). STN
        chips (OBDLink): STCMM 0, receive only. Both only govern monitoring:
        the adapter can still transmit when asked, so car-use's refusal of
        every other command is what keeps the session listen-only.
        """
        self.listen_only = True
        silent = None
        how = []
        if self.info.stn and self.at_ok("STCMM0"):
            how.append("STCMM0")
        if self.at_ok("ATCSM1"):
            how.append("ATCSM1")
        if how:
            silent = True
        return {
            "on": True,
            "adapter_silent": silent,
            "adapter_commands": how,
            "software_block": True,
            "note": (f"Adapter accepted {' and '.join(how)}: no acknowledgements while "
                     "monitoring. It can still transmit if commanded; car-use refuses every "
                     "command that would." if how else
                     "Adapter rejected AT CSM1 (common on clones, many of which are always "
                     "silent while monitoring, but car-use cannot confirm it). Only car-use's "
                     "own refusal to send requests is enforced."),
        }

    # -- listening ----------------------------------------------------------------
    def monitor(self, seconds: float) -> "MonitorBurst":
        """One ATMA burst: print every frame the adapter hears, for up to `seconds`.

        Sends nothing to the car. A busy bus outruns most adapters' links, so
        the adapter often stops by itself with BUFFER FULL; otherwise we stop
        it with a carriage return and wait for the prompt. Lines are stamped
        when they reach this computer, not when they were on the bus.
        """
        with self.lock:
            self.t.drain()
            start = time.monotonic()
            burst = MonitorBurst()
            pending = b""
            prompt = False

            def take(data: bytes) -> None:
                nonlocal pending, prompt
                if not data:
                    return
                pending += data
                mono, wall = time.monotonic(), time.time()
                parts = pending.replace(b"\n", b"\r").split(b"\r")
                pending = parts.pop()
                if b">" in pending:
                    prompt, pending = True, b""
                for raw in parts:
                    text = raw.decode("ascii", errors="replace").strip().rstrip(">").strip()
                    if b">" in raw:
                        prompt = True
                    up = text.upper()
                    if not text or up in ("ATMA", "STOPPED") or up.startswith("SEARCHING"):
                        continue
                    if up == "?":
                        burst.ended = "unsupported"
                    elif "BUFFER FULL" in up:
                        burst.ended = "buffer_full"
                    elif up in ERRORS or up.startswith("<"):
                        burst.errors.append(text)
                    else:
                        burst.lines.append((mono, wall, text))

            try:
                self.t.write(b"ATMA\r")
                deadline = start + max(seconds, 0.0)
                while not burst.ended and not prompt:
                    left = deadline - time.monotonic()
                    if left <= 0:
                        break
                    take(self.t._read_some(max(0.01, min(0.05, left))))
                if not prompt:
                    if not burst.ended:
                        self.t.write(b"\r")
                    stop_by = time.monotonic() + 2.0
                    while not prompt and time.monotonic() < stop_by:
                        take(self.t._read_some(0.05))
                    if not prompt:
                        raise TransportError("adapter did not stop listening (no prompt "
                                             f"after ATMA on {self.t.url})")
            except BaseException:
                # Never leave the adapter streaming: the next command would be
                # swallowed as the keypress that stops it.
                try:
                    self.t.write(b"\r")
                    self.t.read_until(b">", 1.0)
                except (TransportError, OSError):
                    pass
                raise
            finally:
                burst.ended = burst.ended or "stopped"
                burst.seconds = time.monotonic() - start
                self.log.append((burst.seconds, "ATMA",
                                 f"{len(burst.lines)} lines, {burst.ended}"))
            self.t.drain()
            return burst

    def close(self) -> None:
        self.t.close()


@dataclass
class MonitorBurst:
    """What one ATMA burst heard: (monotonic, wall clock, line) per frame line."""
    lines: list[tuple[float, float, str]] = field(default_factory=list)
    ended: str = ""          # "stopped" | "buffer_full" | "unsupported"
    errors: list[str] = field(default_factory=list)
    seconds: float = 0.0
