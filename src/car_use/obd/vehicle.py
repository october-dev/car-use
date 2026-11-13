"""The OBD backend: a Vehicle reached through an ELM327/STN adapter."""
from __future__ import annotations

import time
from dataclasses import dataclass

from ..kernel.policy import Kernel, Decision
from ..model.capability import Altitude, Capability, DriverOfRecord, Manifest, Tier
from . import pids as P
from .dtc_info import describe
from .elm import Elm327, ElmError
from ..transport.base import TransportError
from . import vin as vinmod


@dataclass
class Reading:
    name: str
    path: str
    value: float | None
    unit: str
    ts: float
    source: str

    def __repr__(self) -> str:
        return f"{self.name}={self.value} {self.unit}"

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _codes_from(payload: bytes | None) -> list[str]:
    """CAN DTC payload: service, count, then pairs. Empty and 0000 pairs are skipped."""
    if not payload or payload[0] not in (0x43, 0x47, 0x4A):
        return []
    body = payload[2:]
    out = []
    for i in range(0, len(body) - 1, 2):
        if body[i] == 0 and body[i + 1] == 0:
            continue
        out.append(P.decode_dtc(body[i], body[i + 1]))
    return out


CAPABILITIES = [
    Capability("obd.read", Altitude.OBSERVE, Tier.T0, "Read live Mode 01 signals"),
    Capability("obd.dtcs", Altitude.OBSERVE, Tier.T0, "Stored, pending and permanent DTCs"),
    Capability("obd.readiness", Altitude.OBSERVE, Tier.T0, "Emissions monitor readiness"),
    Capability("obd.freeze_frame", Altitude.OBSERVE, Tier.T0, "Snapshot stored with the DTC"),
    Capability("obd.vin", Altitude.OBSERVE, Tier.T0, "VIN from Mode 09"),
    Capability("obd.raw_read", Altitude.OBSERVE, Tier.T0, "Read-only raw requests (01,02,03,06,07,09,0A,19,22)"),
    Capability("obd.clear_dtcs", Altitude.ACT, Tier.T1D,
               "Clear DTCs and MIL. Resets readiness monitors; permanent codes stay.",
               preconditions=("engine_off_or_idle", "speed==0"), reversible=False,
               driver_of_record=DriverOfRecord.NONE),
]


class ObdVehicle:
    backend = "obd"

    def __init__(self, elm: Elm327, device_url: str, kernel: Kernel | None = None,
                 scenario=None):
        self.elm = elm
        self.device_url = device_url
        self.kernel = kernel or Kernel()
        self.scenario = scenario
        self.vin = ""
        self._supported: set[int] | None = None
        self._multi_ok: bool | None = None
        self._pack_cache: list | None = None

    # -- connect ---------------------------------------------------------------
    def connect(self) -> "ObdVehicle":
        self.elm.initialize()
        self.elm.detect_protocol()
        try:
            self.vin = self.read_vin()
        except (ElmError, ValueError):
            self.vin = ""
        return self

    def describe(self) -> dict:
        info = self.elm.info
        d = {"vin": self.vin or "unknown", "adapter": info.identity, "protocol": info.protocol,
             "device": self.device_url}
        if info.stn:
            d["stn"] = info.stn
        if self.scenario is not None:
            d["simulated"] = self.scenario.title
        return d

    def manifest(self) -> Manifest:
        sigs = [P.PIDS[p].signals[i].path for p in sorted(self.supported_pids()) if p in P.PIDS
                for i in range(len(P.PIDS[p].signals))]
        sigs.extend(did.vss for did in self._pack_dids() if did.vss)
        return Manifest(backend="obd", vehicle=self.describe(), signals=sigs,
                        capabilities=list(CAPABILITIES))

    # -- signals -----------------------------------------------------------------
    def supported_pids(self) -> set[int]:
        if self._supported is not None:
            return self._supported
        out: set[int] = set()
        base = 0x00
        while base <= 0xC0:
            try:
                p = self.elm.query_one(f"01{base:02X}")
            except ElmError:
                break
            bits = int.from_bytes(p[2:6], "big")
            for i in range(1, 33):
                if bits & (1 << (32 - i)):
                    out.add(base + i)
            if not bits & 1:
                break
            base += 0x20
        self._supported = out
        return out

    def signals(self, prefix: str = "") -> list[dict]:
        out = []
        for pid in sorted(self.supported_pids()):
            spec = P.PIDS.get(pid)
            if not spec:
                continue
            for s in spec.signals:
                if s.path.startswith(prefix) or s.alias.startswith(prefix):
                    out.append({"alias": s.alias, "path": s.path, "unit": s.unit,
                                "pid": f"01{pid:02X}", "description": s.description})
        for did in self._pack_dids():
            if did.name.startswith(prefix) or did.vss.startswith(prefix) \
                    or prefix in ("", "pack", "pack:"):
                out.append({"alias": did.name, "path": did.vss, "unit": did.unit,
                            "pid": f"22{did.did}", "description": did.description,
                            "ecu": did.ecu, "pack": True})
        return out

    def _matched_packs(self) -> list:
        if self._pack_cache is None:
            from .packs import matching
            self._pack_cache = matching(self.vin)
        return self._pack_cache

    def _pack_dids(self) -> list:
        return [did for pack in self._matched_packs() for did in pack.dids]

    def _pack_did(self, name: str):
        from .packs import find_did
        return find_did(name, self._matched_packs())

    def _read_pack(self, name: str) -> Reading | None:
        did = self._pack_did(name)
        if did is None:
            return None
        from .packs import FormulaError, decode_payload
        now = time.time()
        source = f"obd:22{did.did}@{did.ecu}"
        try:
            payloads = self.elm.query_targeted(did.ecu, "22" + did.did)
        except ElmError as e:
            if e.code == "NO DATA":
                return Reading(did.name, did.vss, None, did.unit, now, f"{source} (no data)")
            raise
        try:
            value = decode_payload(did.formula, payloads[0], bytes.fromhex(did.did))
        except FormulaError as e:
            return Reading(did.name, did.vss, None, did.unit, now, f"{source} ({e})")
        return Reading(did.name, did.vss, round(value, 3), did.unit, now, source)

    def read(self, name: str, ecu: str | None = None) -> Reading:
        if ecu is None:
            packed = self._read_pack(name)
            if packed is not None:
                return packed
        spec, idx, sig = P.resolve(name)
        now = time.time()
        try:
            if ecu:
                replies = self.elm.query_ecu(ecu, f"01{spec.pid:02X}")
                if not replies:
                    raise ElmError(f"01{spec.pid:02X}", "NO DATA")
                p = replies[0]
            else:
                p = self.elm.query_one(f"01{spec.pid:02X}")
        except ElmError as e:
            if e.code == "NO DATA":
                return Reading(sig.alias, sig.path, None, sig.unit, now, f"obd:01{spec.pid:02X} (no data)")
            raise
        data = p[2:2 + spec.length]
        return Reading(sig.alias, sig.path, spec.decode(data)[idx], sig.unit, now,
                       f"obd:01{spec.pid:02X}" + (f"@{ecu}" if ecu else ""))

    def read_many(self, names: list[str]) -> dict[str, Reading]:
        pack_names = [n for n in names if self._pack_did(n) is not None]
        resolved = [(n, *P.resolve(n)) for n in names if n not in pack_names]
        pids_needed = list(dict.fromkeys(spec.pid for _, spec, _, _ in resolved))
        values: dict[int, bytes] = {}
        if self._multi_ok is not False and self.elm.info.is_can and len(pids_needed) > 1:
            try:
                for i in range(0, len(pids_needed), 6):
                    chunk = pids_needed[i:i + 6]
                    p = self.elm.query_one("01" + "".join(f"{x:02X}" for x in chunk))
                    values.update(_split_multi(p[1:]))
                self._multi_ok = all(x in values for x in pids_needed) or self._multi_ok
            except ElmError:
                self._multi_ok = False
        now = time.time()
        out: dict[str, Reading] = {}
        for n, spec, idx, sig in resolved:
            if spec.pid not in values:
                out[n] = self.read(n)
                continue
            out[n] = Reading(sig.alias, sig.path, spec.decode(values[spec.pid])[idx], sig.unit,
                             now, f"obd:01{spec.pid:02X}")
        for n in pack_names:
            out[n] = self._read_pack(n)
        return out

    # -- diagnostics ---------------------------------------------------------------
    def _dtcs_with_headers(self) -> dict | None:
        """Ask with ATH1 so each ECU's codes stay attached to its CAN id."""
        try:
            found = {mode: self.elm.query_by_ecu(mode) for mode in ("03", "07", "0A")}
        except (ElmError, TransportError):
            return None
        per: dict[str, dict] = {}
        for mode, key in (("03", "stored"), ("07", "pending"), ("0A", "permanent")):
            for ecu, payload in found[mode].items():
                per.setdefault(ecu, {"stored": [], "pending": [], "permanent": []})
                per[ecu][key] = _codes_from(payload)
        per = {ecu: codes for ecu, codes in per.items() if any(codes.values())}

        def union(key: str) -> list[str]:
            out: list[str] = []
            for codes in per.values():
                for code in codes[key]:
                    if code not in out:
                        out.append(code)
            return out

        if not per:
            return None
        return {"stored": union("stored"), "pending": union("pending"),
                "permanent": union("permanent"), "by_ecu": per}

    def _dtc_list(self, mode: str) -> list[str]:
        try:
            payloads = self.elm.query(mode)
        except ElmError as e:
            if e.code == "NO DATA":
                return []
            raise
        codes: list[str] = []
        want = int(mode, 16) + 0x40
        for p in payloads:
            if not p or p[0] != want:
                continue
            body = p[2:] if self.elm.info.is_can else p[1:]
            for i in range(0, len(body) - 1, 2):
                if body[i] == 0 and body[i + 1] == 0:
                    continue
                codes.append(P.decode_dtc(body[i], body[i + 1]))
        return list(dict.fromkeys(codes))

    def dtcs(self) -> dict:
        res = self._dtcs_with_headers()
        if res is None:
            res = {"stored": self._dtc_list("03"), "pending": self._dtc_list("07"),
                   "permanent": self._dtc_list("0A"), "by_ecu": {}}
        res["descriptions"] = {c: describe(c) for c in
                               dict.fromkeys(res["stored"] + res["pending"] + res["permanent"])}
        try:
            res["mil_on"] = self.readiness()["mil_on"]
        except ElmError:
            pass
        return res

    def readiness(self) -> dict:
        p = self.elm.query_one("0101")
        out = P.decode_monitor_status(p[2:6])
        incomplete = [k for k, v in out["monitors"].items() if v != "complete"]
        out["incomplete"] = incomplete
        for alias in ("distance_since_clear", "warmups_since_clear"):
            try:
                out[alias] = self.read(alias).value
            except (ElmError, KeyError):
                pass
        return out

    def freeze_frame(self) -> dict:
        try:
            p = self.elm.query_one("020200")
        except ElmError as e:
            if e.code == "NO DATA":
                return {}
            raise
        out: dict = {"dtc": P.decode_dtc(p[3], p[4]) if len(p) >= 5 else None, "values": {}}
        for alias in ("rpm", "speed", "coolant", "load", "stft1", "ltft1", "iat", "map", "throttle"):
            spec, idx, sig = P.resolve(alias)
            try:
                r = self.elm.query_one(f"02{spec.pid:02X}00")
            except ElmError:
                continue
            out["values"][alias] = {"value": spec.decode(r[3:3 + spec.length])[idx], "unit": sig.unit}
        return out

    def read_vin(self) -> str:
        p = self.elm.query_one("0902")
        raw = p[3:] if len(p) > 3 and p[2] == 0x01 else p[2:]
        return raw.decode("ascii", errors="replace").strip("\x00 ").strip()

    def vin_info(self) -> dict:
        return vinmod.decode(self.vin or self.read_vin())

    def raw_obd(self, request: str, ecu: str | None = None) -> list[str] | Decision:
        d = self.kernel.check_raw(request, self.vin)
        if not d:
            return d
        replies = self.elm.query_ecu(ecu, request) if ecu else self.elm.query(request)
        return [p.hex(" ").upper() for p in replies]

    def clear_dtcs(self) -> Decision:
        speed = rpm = None
        try:
            speed = self.read("speed").value
            rpm = self.read("rpm").value
        except ElmError:
            pass
        moving = speed not in (None, 0, 0.0)
        state = (not moving and (rpm is None or rpm < 1200),
                 "Car must be stationary with the engine off or idling to clear codes.")
        before = self.dtcs()
        d = self.kernel.authorize(
            "obd.clear_dtcs", Tier.T1D, self.vin,
            f"Clear all DTCs on {self.vin or 'this car'} (stored: {before['stored'] or 'none'})? "
            "This turns off the check-engine light and resets emissions readiness monitors; "
            "the car will fail an emissions inspection until they complete again.",
            state_ok=state)
        if not d:
            return d
        self.elm.query("04")
        self.kernel.record("effect", vin=self.vin, intent="obd.clear_dtcs", before=before)
        return d


def _split_multi(body: bytes) -> dict[int, bytes]:
    """Split a multi-PID Mode 01 reply body (after 0x41) into {pid: data}."""
    out: dict[int, bytes] = {}
    i = 0
    while i < len(body):
        pid = body[i]
        length = 4 if pid in (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0x01) else \
            (P.PIDS[pid].length if pid in P.PIDS else None)
        if length is None:
            break
        out[pid] = body[i + 1:i + 1 + length]
        i += 1 + length
    return out
