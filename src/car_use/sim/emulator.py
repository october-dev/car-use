"""An ELM327 emulator backed by a Scenario, served over TCP.

Written from the ELM327 datasheet behaviour (not derived from other
emulators) so car-use and car-use Cloud can ship it under MIT.

Profiles mimic the adapters people own:
  genuine  ELM327 v2.3: full AT set, ~25 ms per request
  clone    reports "v1.5" (a version that never existed), rejects a set of
           AT commands, slower, bogus ATRV offset, never sleeps
  stn      OBDLink-style STN2120: answers ST commands, fast
"""
from __future__ import annotations

import socket
import socketserver
import threading
import time

from ..obd import pids as P
from .scenario import Scenario

CLONE_REJECTS = {"PP", "MA", "CRA", "CF", "CM", "KW", "IB", "CSM", "AMC", "AMT",
                 "IGN", "LP", "BRD", "FE", "CV", "@2", "@3"}
PROTOCOLS = {
    "1": "SAE J1850 PWM", "2": "SAE J1850 VPW", "3": "ISO 9141-2",
    "4": "ISO 14230-4 (KWP 5BAUD)", "5": "ISO 14230-4 (KWP FAST)",
    "6": "ISO 15765-4 (CAN 11/500)", "7": "ISO 15765-4 (CAN 29/500)",
    "8": "ISO 15765-4 (CAN 11/250)", "9": "ISO 15765-4 (CAN 29/250)",
}


class CarState:
    """Mutable car shared by every connection (so clearing codes sticks)."""

    def __init__(self, s: Scenario):
        self.s = s
        self.t0 = time.monotonic()
        self.lock = threading.Lock()
        self.stored = list(s.dtcs.get("stored", []))
        self.pending = list(s.dtcs.get("pending", []))
        self.permanent = list(s.dtcs.get("permanent", []))
        self.monitors = dict(s.monitors)
        self.overrides: dict[str, float] = {}
        self.cleared = False
        # Every OBD request any client sent, as (seconds since start, hex). This is
        # what car-use bench grades evidence and safety from: it sits below every
        # harness, so it can't be faked from the agent's side.
        self.requests: list[tuple[float, str]] = []

    def t(self) -> float:
        return time.monotonic() - self.t0

    def signal(self, alias: str):
        if alias in self.overrides:
            return self.overrides[alias]
        if self.cleared and alias in ("distance_since_clear", "warmups_since_clear", "distance_mil"):
            return 0.0
        return self.s.value(alias, self.t())

    def available_pids(self) -> set[int]:
        out = {0x01}
        for pid in P.PIDS.values():
            if self.s.signals.get(pid.signals[0].alias) is not None:
                out.add(pid.pid)
        return out

    def encode_pid(self, pid: int, frame: dict | None = None) -> bytes | None:
        if pid == 0x01:
            return P.encode_monitor_status(bool(self.stored), len(self.stored), self.monitors)
        if pid in (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0):
            avail = self.available_pids()
            bits = 0
            for i in range(1, 33):
                if pid + i in avail or (i == 32 and any(p > pid + 32 for p in avail)):
                    bits |= 1 << (32 - i)
            return bits.to_bytes(4, "big")
        spec = P.PIDS.get(pid)
        if spec is None:
            return None
        src = frame if frame is not None else None
        vals = []
        for sig in spec.signals:
            v = src.get(sig.alias) if src is not None else self.signal(sig.alias)
            vals.append(v)
        if vals[0] is None:
            return None
        return spec.encode(tuple(vals))

    def clear(self):
        with self.lock:
            self.stored, self.pending = [], []
            self.monitors = {k: "incomplete" for k in self.monitors}
            self.cleared = True


class _Session:
    def __init__(self, car: CarState):
        self.car = car
        prof = car.s.adapter.get("profile", "genuine")
        self.profile = prof
        self.latency = car.s.adapter.get("latency_ms", {"genuine": 25, "clone": 60, "stn": 8}.get(prof, 25)) / 1000
        self.reset()

    def reset(self):
        self.echo, self.linefeed, self.spaces, self.headers = True, True, True, False
        self.protocol = "0"
        self.kwp_inited = False

    @property
    def identity(self) -> str:
        return {"clone": "ELM327 v1.5", "stn": "ELM327 v1.4b"}.get(self.profile, "ELM327 v2.3")

    # -- formatting ----------------------------------------------------------
    def _hex(self, data: bytes) -> str:
        return (" " if self.spaces else "").join(f"{b:02X}" for b in data)

    def _protocol_number(self) -> str:
        return self.protocol.lstrip("A")

    def _non_can(self) -> bool:
        return self._protocol_number() in {"1", "2", "3", "4", "5"}

    def frames(self, payload: bytes) -> list[str]:
        if self._non_can():
            return self._legacy_frames(payload)
        if len(payload) <= 7:
            body = self._hex(payload)
            if self.headers:
                return [("7E8 " if self.spaces else "7E8") + self._hex(bytes([len(payload)])) +
                        (" " if self.spaces else "") + body]
            return [body]
        lines = [f"{len(payload):03X}"]
        lines.append("0:" + (" " if self.spaces else "") + self._hex(payload[:6]))
        rest, idx = payload[6:], 1
        while rest:
            lines.append(f"{idx % 16:X}:" + (" " if self.spaces else "") + self._hex(rest[:7]))
            rest, idx = rest[7:], idx + 1
        return lines

    def _legacy_frames(self, payload: bytes) -> list[str]:
        """ISO 9141-2, KWP2000 and J1850: no ISO-TP length line, no CAN header.

        Mode 09 PID 02 is five frames of four data bytes, with three leading
        zero pads so a 17-character VIN fits. Mode 03/07/0A has no DTC count
        byte and repeats the service byte every six DTC bytes (the 7-byte
        message limit).
        """
        if len(payload) >= 3 and payload[0] == 0x49 and payload[1] == 0x02:
            data = payload[3:] if payload[2] == 0x01 else payload[2:]
            if len(data) == 17:
                data = b"\x00\x00\x00" + data
            lines = []
            for n, i in enumerate(range(0, len(data), 4), start=1):
                lines.append(self._hex(bytes([0x49, 0x02, n]) + data[i:i + 4]))
            return lines
        if payload and payload[0] in (0x43, 0x47, 0x4A):
            body = payload[1:] or b"\x00\x00"
            return [self._hex(bytes([payload[0]]) + body[i:i + 6]) for i in range(0, len(body), 6)]
        if len(payload) <= 7:
            return [self._hex(payload)]
        return [self._hex(payload[i:i + 7]) for i in range(0, len(payload), 7)]

    # -- dispatch ------------------------------------------------------------
    def handle(self, raw: str) -> list[str]:
        cmd = raw.strip().upper().replace(" ", "")
        if not cmd:
            return []
        if cmd.startswith("AT"):
            return self.at(cmd[2:])
        if cmd.startswith("ST"):
            if self.profile != "stn":
                return ["?"]
            return {"STI": ["STN2120 r5.10.3"], "STDI": ["OBDLink MX+ r2.3.0"]}.get(cmd, ["OK"])
        if len(cmd) % 2 == 1 and len(cmd) > 2:
            cmd = cmd[:-1]       # optional trailing response count ("010C1"), as ELM327 v1.3+ allow
        try:
            req = bytes.fromhex(cmd)
        except ValueError:
            return ["?"]
        if req:
            with self.car.lock:
                self.car.requests.append((round(self.car.t(), 3), cmd))
        time.sleep(self.latency)
        if self.car.s.ignition != "run" and self.car.s.ignition != "accessory":
            return ["SEARCHING...", "UNABLE TO CONNECT"]
        out = []
        if self.protocol == "0":
            out.append("SEARCHING...")
            self.protocol = "A" + self.car.s.protocol
        if self._protocol_number() in {"4", "5"} and not self.kwp_inited:
            self.kwp_inited = True
            time.sleep(0.15)
            out.append("BUS INIT: ...OK")
        payload = self.obd(req)
        if payload is None:
            return out + ["NO DATA"]
        return out + self.frames(payload)

    def at(self, c: str) -> list[str]:
        if self.profile == "clone" and any(c.startswith(r) for r in CLONE_REJECTS):
            return ["?"]
        if c in ("Z", "WS"):
            self.reset()
            return ["", self.identity]
        if c == "D":
            self.reset()
            return ["OK"]
        if c == "I":
            return [self.identity]
        if c == "@1":
            return ["OBDII to RS232 Interpreter" if self.profile == "clone" else "car-use emulator"]
        if c == "RV":
            v = self.car.signal("battery") or 12.6
            if self.profile == "clone":
                v += 0.4
            return [f"{v:.1f}V"]
        if c == "DP":
            p = self.protocol.lstrip("A")
            return [("AUTO, " if self.protocol.startswith("A") else "") + PROTOCOLS.get(p, "AUTO")]
        if c == "DPN":
            return [self.protocol]
        for flag, attr in (("E", "echo"), ("L", "linefeed"), ("S", "spaces"), ("H", "headers")):
            if c in (flag + "0", flag + "1"):
                setattr(self, attr, c.endswith("1"))
                return ["OK"]
        if c.startswith("SP") or c.startswith("TP"):
            p = c[2:].lstrip("A") or "0"
            self.protocol = "0" if p == "0" else p
            return ["OK"]
        if c == "MA":
            return ["STOPPED"]
        if c == "LP":
            return ["OK"]
        if c and (c[0].isalpha() or c[0] == "@"):
            return ["OK"]
        return ["?"]

    def obd(self, req: bytes) -> bytes | None:
        car = self.car
        mode = req[0]
        if mode == 0x01 and len(req) >= 2:
            out = bytearray([0x41])
            for pid in req[1:7]:
                data = car.encode_pid(pid)
                if data is not None:
                    out += bytes([pid]) + data
            return bytes(out) if len(out) > 1 else None
        if mode == 0x02 and len(req) >= 2:
            pid = req[1]
            ff = car.s.freeze_frame
            if not ff or not car.stored:
                return None
            if pid == 0x02:
                return bytes([0x42, 0x02, 0x00]) + P.encode_dtc(ff.get("dtc", car.stored[0]))
            if pid == 0x00:
                frame_pids = {P.SIGNALS[a][0] for a in ff if a in P.SIGNALS}
                return bytes([0x42, 0x00, 0x00]) + _bitmap({0x02} | frame_pids)
            data = car.encode_pid(pid, frame=ff)
            return bytes([0x42, pid, 0x00]) + data if data is not None else None
        if mode in (0x03, 0x07, 0x0A):
            codes = {0x03: car.stored, 0x07: car.pending, 0x0A: car.permanent}[mode]
            body = b"".join(P.encode_dtc(c) for c in codes)
            if self._non_can():
                return bytes([mode + 0x40]) + body
            return bytes([mode + 0x40, len(codes)]) + body
        if mode == 0x04:
            car.clear()
            return bytes([0x44])
        if mode == 0x09 and len(req) >= 2:
            if req[1] == 0x00:
                return bytes([0x49, 0x00, 0x55, 0x40, 0x00, 0x00])
            if req[1] == 0x02:
                return bytes([0x49, 0x02, 0x01]) + car.s.vin.encode("ascii")[:17]
            return None
        if mode == 0x22 and len(req) >= 3:
            did = f"{req[1]:02X}{req[2]:02X}"
            if did in car.s.dids:
                return bytes([0x62, req[1], req[2]]) + bytes.fromhex(car.s.dids[did].replace(" ", ""))
            return bytes([0x7F, 0x22, 0x31])
        return None


def _bitmap(pids: set[int]) -> bytes:
    bits = 0
    for p in pids:
        if 1 <= p <= 32:
            bits |= 1 << (32 - p)
    return bits.to_bytes(4, "big")


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        sess = _Session(self.server.car)  # type: ignore[attr-defined]
        sock: socket.socket = self.request
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        buf = b""
        while True:
            try:
                chunk = sock.recv(1024)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\r" in buf:
                line, buf = buf.split(b"\r", 1)
                text = line.decode("ascii", errors="replace")
                eol = "\r\n" if sess.linefeed else "\r"
                out = ""
                if sess.echo:
                    out += text + eol
                for ln in sess.handle(text):
                    out += ln + eol
                out += eol + ">"
                try:
                    sock.sendall(out.encode("ascii"))
                except OSError:
                    return


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class Emulator:
    def __init__(self, scenario: Scenario, host: str = "127.0.0.1", port: int = 0):
        self.scenario = scenario
        self.car = CarState(scenario)
        self.server = _Server((host, port), _Handler)
        self.server.car = self.car  # type: ignore[attr-defined]
        self.host, self.port = self.server.server_address[:2]
        self.thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"tcp://{self.host}:{self.port}"

    def start(self) -> "Emulator":
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True,
                                       name=f"car-use-sim-{self.scenario.name}")
        self.thread.start()
        return self

    def serve_forever(self):
        self.server.serve_forever()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
