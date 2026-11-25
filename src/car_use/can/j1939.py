"""SAE J1939: the CAN dialect of trucks, buses, cranes, construction and farm
machines, and generator sets.

J1939 runs on 29-bit CAN ids (usually 250 kbit/s, 500 kbit/s on newer
machines). Each id carries a priority, a Parameter Group Number (PGN: which
message this is) and the sender's source address. Inside a message, each
Suspect Parameter Number (SPN) is one value at a fixed position with a fixed
scale and offset, the same on every machine that sends it. That is the big
difference from car CAN, where every maker lays its messages out differently.

This module:
  - splits a 29-bit id into priority, PGN, destination and source;
  - decodes a small table of standard SPNs (`SPNS`), with scaling from the
    public J1939-71 definitions; values the sender marks "not available" or
    "error" come back as None;
  - decodes DM1 (active diagnostic trouble codes, J1939-73), including
    multi-packet DM1 sent with the J1939-21 broadcast transport (BAM:
    TP.CM then TP.DT);
  - says whether a set of CAN ids looks like a J1939 bus.

It only reads. Nothing here builds a request or a command, except
`encode_*`, which the simulator uses to make its virtual machine's traffic.

Not covered yet: the connection-mode transport (RTS/CTS, used for
point-to-point transfers), proprietary PGNs, the older DM1 SPN conversion
methods (only the current one, CM = 0, is decoded), and any SPN not in
`SPNS`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# -- ids ---------------------------------------------------------------------------

GLOBAL = 0xFF        # destination "everyone"
NULL = 0xFE          # "no address yet" (address claim in progress)

# Preferred source addresses from the J1939 base table. Machines may use
# others (anything 0x80-0xF7 is self-configurable), so this is a hint only.
SOURCES = {
    0x00: "Engine #1",
    0x01: "Engine #2",
    0x03: "Transmission #1",
    0x0B: "Brakes - system controller",
    0x17: "Instrument cluster #1",
    0x21: "Body controller",
    0xF9: "Off-board diagnostic-service tool #1",
    0xFE: "Null address",
    0xFF: "Global",
}


@dataclass(frozen=True)
class J1939Id:
    priority: int        # 0 (highest) .. 7
    pgn: int             # 18-bit Parameter Group Number
    source: int          # source address (SA) of the sender
    destination: int     # PDU1: the addressed node; PDU2: always GLOBAL
    pf: int              # PDU format byte
    ps: int              # PDU specific byte (destination or group extension)

    @property
    def pdu1(self) -> bool:
        return self.pf < 240

    def to_dict(self) -> dict:
        return {"priority": self.priority, "pgn": self.pgn, "pgn_hex": f"{self.pgn:05X}",
                "source": self.source, "destination": self.destination,
                "name": PGNS.get(self.pgn, {}).get("acronym")}


def parse_id(ident: str | int) -> J1939Id:
    """Split a 29-bit CAN id (int, or 8 hex digits) into its J1939 parts.

    Bits 28-26 priority, 25 extended data page, 24 data page, 23-16 PDU
    format (PF), 15-8 PDU specific (PS), 7-0 source address. With PF < 240
    (PDU1) the PS byte is a destination address and is not part of the PGN;
    with PF >= 240 (PDU2) it is a group extension and is.
    """
    value = int(ident, 16) if isinstance(ident, str) else int(ident)
    if not 0 <= value <= 0x1FFFFFFF:
        raise ValueError(f"not a 29-bit CAN id: {ident!r}")
    priority = (value >> 26) & 0x7
    edp_dp = (value >> 24) & 0x3
    pf = (value >> 16) & 0xFF
    ps = (value >> 8) & 0xFF
    sa = value & 0xFF
    if pf < 240:
        pgn, dest = (edp_dp << 16) | (pf << 8), ps
    else:
        pgn, dest = (edp_dp << 16) | (pf << 8) | ps, GLOBAL
    return J1939Id(priority, pgn, sa, dest, pf, ps)


def build_id(pgn: int, source: int, priority: int = 6, destination: int = GLOBAL) -> str:
    """The 29-bit id (8 hex digits) for a PGN from `source`. Used by the simulator."""
    pf = (pgn >> 8) & 0xFF
    ps = destination if pf < 240 else pgn & 0xFF
    value = ((priority & 0x7) << 26) | (((pgn >> 16) & 0x3) << 24) | (pf << 16) | (ps << 8) \
        | (source & 0xFF)
    return f"{value:08X}"


# -- the standard parameters car-use decodes -----------------------------------------

# PGNs, from J1939-71 (and -21/-73 for transport and DM1). `rate` is the
# broadcast interval the standard recommends; machines vary.
PGNS: dict[int, dict] = {
    61444: {"acronym": "EEC1", "name": "Electronic Engine Controller 1", "rate": "engine-speed dependent, typically 10-20 ms"},
    65262: {"acronym": "ET1", "name": "Engine Temperature 1", "rate": "1 s"},
    65263: {"acronym": "EFL/P1", "name": "Engine Fluid Level/Pressure 1", "rate": "0.5 s"},
    65253: {"acronym": "HOURS", "name": "Engine Hours, Revolutions", "rate": "on request"},
    65266: {"acronym": "LFE", "name": "Fuel Economy (Liquid)", "rate": "100 ms"},
    65276: {"acronym": "DD", "name": "Dash Display", "rate": "1 s"},
    65265: {"acronym": "CCVS", "name": "Cruise Control/Vehicle Speed", "rate": "100 ms"},
    65271: {"acronym": "VEP1", "name": "Vehicle Electrical Power 1", "rate": "1 s"},
    65269: {"acronym": "AMB", "name": "Ambient Conditions", "rate": "1 s"},
    65226: {"acronym": "DM1", "name": "Active Diagnostic Trouble Codes", "rate": "1 s, and on change"},
    60416: {"acronym": "TP.CM", "name": "Transport Protocol - Connection Management", "rate": "as needed"},
    60160: {"acronym": "TP.DT", "name": "Transport Protocol - Data Transfer", "rate": "as needed"},
    59904: {"acronym": "RQST", "name": "Request", "rate": "as needed"},
    60928: {"acronym": "AC", "name": "Address Claimed", "rate": "as needed"},
}

PGN_TP_CM = 60416   # 0xEC00
PGN_TP_DT = 60160   # 0xEB00
PGN_DM1 = 65226     # 0xFECA
TP_BAM = 0x20       # TP.CM control byte: Broadcast Announce Message
TP_RTS, TP_CTS, TP_ACK, TP_ABORT = 0x10, 0x11, 0x13, 0xFF


@dataclass(frozen=True)
class Spn:
    spn: int
    key: str             # column name in recordings and helpers
    name: str            # J1939-71 name
    pgn: int
    byte: int            # first byte, 0-indexed (J1939 documents count from 1)
    length: int          # bytes, little-endian
    scale: float         # units per bit
    offset: float
    unit: str


# Positions are J1939-71 "start position" minus one. Every entry cites its
# PGN and SPN; each was checked against public J1939-71 summaries.
SPNS: list[Spn] = [
    # PGN 61444 EEC1, SPN 190 Engine Speed: bytes 4-5, 0.125 rpm/bit, offset 0.
    Spn(190, "engine_speed_rpm", "Engine Speed", 61444, 3, 2, 0.125, 0.0, "rpm"),
    # PGN 65262 ET1, SPN 110 Engine Coolant Temperature: byte 1, 1 degC/bit, offset -40.
    Spn(110, "coolant_temp_c", "Engine Coolant Temperature", 65262, 0, 1, 1.0, -40.0, "degC"),
    # PGN 65263 EFL/P1, SPN 100 Engine Oil Pressure: byte 4, 4 kPa/bit, offset 0.
    Spn(100, "oil_pressure_kpa", "Engine Oil Pressure", 65263, 3, 1, 4.0, 0.0, "kPa"),
    # PGN 65253 HOURS, SPN 247 Engine Total Hours of Operation: bytes 1-4, 0.05 h/bit, offset 0.
    Spn(247, "engine_hours_h", "Engine Total Hours of Operation", 65253, 0, 4, 0.05, 0.0, "h"),
    # PGN 65276 DD, SPN 96 Fuel Level 1: byte 2, 0.4 %/bit, offset 0.
    # (SPN 96 is in Dash Display, not in LFE.)
    Spn(96, "fuel_level_pct", "Fuel Level 1", 65276, 1, 1, 0.4, 0.0, "%"),
    # PGN 65266 LFE, SPN 183 Engine Fuel Rate: bytes 1-2, 0.05 L/h per bit, offset 0.
    Spn(183, "fuel_rate_lph", "Engine Fuel Rate", 65266, 0, 2, 0.05, 0.0, "L/h"),
    # PGN 65265 CCVS, SPN 84 Wheel-Based Vehicle Speed: bytes 2-3, 1/256 km/h per bit, offset 0.
    Spn(84, "vehicle_speed_kph", "Wheel-Based Vehicle Speed", 65265, 1, 2, 1 / 256, 0.0, "km/h"),
    # PGN 65271 VEP1, SPN 168 Battery Potential / Power Input 1: bytes 5-6, 0.05 V/bit, offset 0.
    Spn(168, "battery_v", "Battery Potential / Power Input 1", 65271, 4, 2, 0.05, 0.0, "V"),
    # PGN 65269 AMB, SPN 171 Ambient Air Temperature: bytes 4-5, 0.03125 degC/bit, offset -273.
    Spn(171, "ambient_temp_c", "Ambient Air Temperature", 65269, 3, 2, 0.03125, -273.0, "degC"),
]
BY_SPN = {s.spn: s for s in SPNS}
BY_KEY = {s.key: s for s in SPNS}
BY_PGN: dict[int, list[Spn]] = {}
for _s in SPNS:
    BY_PGN.setdefault(_s.pgn, []).append(_s)
COLUMNS = [s.key for s in SPNS]
UNITS = {s.key: s.unit for s in SPNS}


def raw_value(data: bytes, byte: int, length: int) -> int | None:
    """The raw little-endian value at `byte`, or None if missing or flagged.

    J1939-71 reserves the top of each range: for a 1-byte parameter 0xFB-0xFD
    are reserved, 0xFE is "error" and 0xFF "not available"; 2- and 4-byte
    parameters reserve the same way in their most significant byte (valid
    data ends at 0xFAFF / 0xFAFFFFFF).
    """
    if byte + length > len(data):
        return None
    raw = int.from_bytes(data[byte:byte + length], "little")
    top = raw >> (8 * (length - 1))
    if top > 0xFA:
        return None
    return raw


def decode_spn(spn: Spn, data: bytes) -> float | None:
    raw = raw_value(data, spn.byte, spn.length)
    if raw is None:
        return None
    return round(raw * spn.scale + spn.offset, 6)


def decode_pgn(pgn: int, data: bytes) -> dict[str, float | None]:
    """Every SPN car-use knows in this PGN, by key. Empty dict for unknown PGNs."""
    return {s.key: decode_spn(s, data) for s in BY_PGN.get(pgn, [])}


def encode_pgn(pgn: int, values: dict[int, float | None], size: int = 8) -> bytes:
    """A PGN's payload from SPN number -> value. Bytes no SPN covers are 0xFF,
    as J1939 requires for unused or unavailable data. For the simulator."""
    data = bytearray(b"\xFF" * size)
    for spn_no, value in values.items():
        spn = BY_SPN.get(int(spn_no))
        if spn is None or spn.pgn != pgn:
            raise KeyError(f"SPN {spn_no} is not in PGN {pgn} in car-use's table")
        if value is None:
            continue
        top = (0xFB << (8 * (spn.length - 1))) - 1      # largest valid raw value
        raw = max(0, min(int(round((value - spn.offset) / spn.scale)), top))
        data[spn.byte:spn.byte + spn.length] = raw.to_bytes(spn.length, "little")
    return bytes(data)


# -- DM1 -----------------------------------------------------------------------------

# J1939-73 Failure Mode Identifiers.
FMI = {
    0: "data valid but above normal operating range, most severe",
    1: "data valid but below normal operating range, most severe",
    2: "data erratic, intermittent or incorrect",
    3: "voltage above normal, or shorted to high source",
    4: "voltage below normal, or shorted to low source",
    5: "current below normal, or open circuit",
    6: "current above normal, or grounded circuit",
    7: "mechanical system not responding or out of adjustment",
    8: "abnormal frequency, pulse width or period",
    9: "abnormal update rate",
    10: "abnormal rate of change",
    11: "root cause not known",
    12: "bad intelligent device or component",
    13: "out of calibration",
    14: "special instructions",
    15: "data valid but above normal operating range, least severe",
    16: "data valid but above normal operating range, moderately severe",
    17: "data valid but below normal operating range, least severe",
    18: "data valid but below normal operating range, moderately severe",
    19: "received network data in error",
    20: "data drifted high",
    21: "data drifted low",
    31: "condition exists",
}
LAMPS = ("mil", "red_stop", "amber_warning", "protect")   # byte 1, bits 8-7, 6-5, 4-3, 2-1
_LAMP_STATE = {0: "off", 1: "on", 2: "reserved", 3: "not available"}
_FLASH_STATE = {0: "slow flash", 1: "fast flash", 2: "reserved", 3: "not flashing"}


@dataclass
class Fault:
    spn: int
    fmi: int
    occurrences: int | None      # None when the sender says "not available" (127)
    conversion_method: int

    def to_dict(self) -> dict:
        if self.conversion_method:
            # Conversion method 1 is an older SPN byte order that J1939-73 deprecated
            # and that is decoded here with the current layout, so the number may be
            # wrong. Say so rather than name the wrong part.
            return {"spn": self.spn, "fmi": self.fmi, "occurrences": self.occurrences,
                    "spn_name": None, "fmi_text": FMI.get(self.fmi, "reserved"),
                    "spn_uncertain": True,
                    "text": f"SPN {self.spn} (uncertain: old conversion method), FMI {self.fmi}: "
                            f"{FMI.get(self.fmi, 'reserved')}"}
        spn = BY_SPN.get(self.spn)
        return {"spn": self.spn, "fmi": self.fmi, "occurrences": self.occurrences,
                "spn_name": spn.name if spn else None,
                "fmi_text": FMI.get(self.fmi, "reserved"),
                "text": describe_fault(self.spn, self.fmi)}


def describe_fault(spn: int, fmi: int) -> str:
    s = BY_SPN.get(spn)
    what = f"SPN {spn}" + (f" ({s.name})" if s else "")
    return f"{what}, FMI {fmi}: {FMI.get(fmi, 'reserved')}"


def decode_dm1(payload: bytes) -> dict:
    """DM1 (PGN 65226, J1939-73): lamps and active faults.

    Byte 1: lamp status, two bits each, MIL (bits 8-7), red stop (6-5),
    amber warning (4-3), protect (2-1): 00 off, 01 on. Byte 2: the same
    lamps' flash status. Then 4 bytes per fault: SPN bits 1-8, SPN bits
    9-16, then SPN bits 17-19 in bits 8-6 with the FMI in bits 5-1, then the
    SPN conversion method (bit 8) and occurrence count (bits 7-1). One fault
    fits in a single 8-byte frame (padded with FF); more use BAM transport.
    SPN 0 / FMI 0 means "no active faults".
    """
    if len(payload) < 2:
        raise ValueError("DM1 payload shorter than 2 bytes")
    lamps = {name: _LAMP_STATE[(payload[0] >> (6 - 2 * i)) & 0x3] for i, name in enumerate(LAMPS)}
    flash = {name: _FLASH_STATE[(payload[1] >> (6 - 2 * i)) & 0x3] for i, name in enumerate(LAMPS)}
    faults: list[Fault] = []
    body = payload[2:]
    for i in range(0, len(body) - 3, 4):
        b = body[i:i + 4]
        if b == b"\xFF\xFF\xFF\xFF":
            continue                      # padding
        spn = b[0] | (b[1] << 8) | ((b[2] >> 5) << 16)
        fmi = b[2] & 0x1F
        if spn == 0 and fmi == 0:
            continue                      # the "no faults" placeholder
        oc = b[3] & 0x7F
        faults.append(Fault(spn, fmi, None if oc == 0x7F else oc, b[3] >> 7))
    return {"lamps": lamps, "flash": flash, "faults": [f.to_dict() for f in faults]}


def encode_dm1(lamps: dict | None = None, faults: list[dict] | None = None) -> bytes:
    """A DM1 payload. lamps: name -> "on"/"off"; faults: {spn, fmi, oc}. For the simulator."""
    lamps = lamps or {}
    b0 = 0
    for i, name in enumerate(LAMPS):
        b0 |= (1 if str(lamps.get(name, "off")) == "on" else 0) << (6 - 2 * i)
    out = bytearray([b0, 0xFF])           # flash: "not flashing" for every lamp
    faults = faults or []
    if not faults:
        out += bytes([0, 0, 0, 0])
    for f in faults:
        spn, fmi, oc = int(f["spn"]), int(f["fmi"]), int(f.get("oc", 1))
        if not 0 <= spn < (1 << 19) or not 0 <= fmi <= 31 or not 0 <= oc <= 126:
            raise ValueError(f"bad DM1 fault {f!r}")
        out += bytes([spn & 0xFF, (spn >> 8) & 0xFF, ((spn >> 16) << 5) | fmi, oc & 0x7F])
    while len(out) < 8:
        out.append(0xFF)
    return bytes(out)


def bam_frames(pgn: int, payload: bytes, source: int, priority: int = 7) -> list[tuple[str, bytes]]:
    """The TP.CM (BAM) frame and the TP.DT frames that broadcast `payload`.

    TP.CM BAM (PGN 60416 to global): control byte 32, total size (2 bytes,
    little-endian), number of packets, 0xFF, then the PGN being sent (3
    bytes, little-endian). Each TP.DT (PGN 60160 to global): sequence number
    from 1, then 7 data bytes, the last packet padded with 0xFF. For the
    simulator; J1939-21 asks for 50-200 ms between packets.
    """
    if not 9 <= len(payload) <= 1785:
        raise ValueError("BAM carries 9 to 1785 bytes")
    packets = (len(payload) + 6) // 7
    cm = bytes([TP_BAM, len(payload) & 0xFF, len(payload) >> 8, packets, 0xFF,
                pgn & 0xFF, (pgn >> 8) & 0xFF, (pgn >> 16) & 0xFF])
    out = [(build_id(PGN_TP_CM, source, priority), cm)]
    for n in range(packets):
        chunk = payload[n * 7:(n + 1) * 7]
        out.append((build_id(PGN_TP_DT, source, priority),
                    bytes([n + 1]) + chunk + b"\xFF" * (7 - len(chunk))))
    return out


# -- transport reassembly ------------------------------------------------------------

@dataclass
class _Session:
    pgn: int
    size: int
    packets: int
    started: float
    data: dict[int, bytes] = field(default_factory=dict)


class Transport:
    """Reassembles BAM (broadcast) multi-packet messages, per source address.

    A new TP.CM BAM from a source replaces any unfinished one from it.
    Packets out of order are kept; a session missing packets after
    `timeout` seconds (J1939-21 allows 750 ms between packets) is dropped
    and counted in `dropped`. RTS/CTS sessions are not reassembled (they
    are point-to-point, and car-use never takes part in them).
    """

    def __init__(self, timeout: float = 0.75):
        self.timeout = timeout
        self.sessions: dict[int, _Session] = {}
        self.completed = 0
        self.dropped = 0

    def feed(self, jid: J1939Id, data: bytes, t: float) -> tuple[int, int, bytes] | None:
        """Feed one TP frame. Returns (pgn, source, payload) when a message completes."""
        sa = jid.source
        old = self.sessions.get(sa)
        if old is not None and t - old.started > self.timeout * max(1, old.packets):
            del self.sessions[sa]
            self.dropped += 1
        if jid.pgn == PGN_TP_CM and data:
            if data[0] == TP_BAM and len(data) >= 8 and jid.destination == GLOBAL:
                if sa in self.sessions:
                    self.dropped += 1
                size = data[1] | (data[2] << 8)
                pgn = data[5] | (data[6] << 8) | (data[7] << 16)
                self.sessions[sa] = _Session(pgn, size, data[3], t)
            return None
        if jid.pgn == PGN_TP_DT and len(data) >= 2:
            s = self.sessions.get(sa)
            if s is None or jid.destination != GLOBAL:
                return None
            seq = data[0]
            if 1 <= seq <= s.packets:
                s.data[seq] = bytes(data[1:8])
            if len(s.data) == s.packets:
                del self.sessions[sa]
                payload = b"".join(s.data[i] for i in range(1, s.packets + 1))[:s.size]
                self.completed += 1
                return s.pgn, sa, payload
        return None


# -- a running decoder -------------------------------------------------------------

class Decoder:
    """Feed CAN frames; keeps the latest value of each SPN and the active
    faults per source. Same shape as can.library.Decoder: feed(), row()."""

    name = "j1939"

    def __init__(self):
        self.latest: dict[str, float | None] = {k: None for k in COLUMNS}
        self.sources: dict[str, int] = {}
        self.dm1: dict[int, dict] = {}
        self.pgns: dict[int, int] = {}          # PGN -> frames heard
        self.transport = Transport()
        self.decoded = 0
        self.frames = 0
        self.dm1_changes = 0

    def ids(self) -> list[str]:
        return []                              # J1939 decoding wants the whole bus

    def feed(self, ident: str, data: bytes, t: float = 0.0) -> dict | None:
        """One frame. Returns what changed ({"signals": ..., "dm1": ...}) or None."""
        if len(ident) != 8:
            return None
        jid = parse_id(ident)
        self.frames += 1
        self.pgns[jid.pgn] = self.pgns.get(jid.pgn, 0) + 1
        pgn, source, payload = jid.pgn, jid.source, data
        if jid.pgn in (PGN_TP_CM, PGN_TP_DT):
            done = self.transport.feed(jid, data, t)
            if done is None:
                return None
            pgn, source, payload = done
        if pgn == PGN_DM1:
            try:
                dm1 = decode_dm1(payload)
            except ValueError:
                return None
            dm1["source"] = source
            dm1["source_name"] = SOURCES.get(source)
            dm1["multi_packet"] = len(payload) > 8
            prev = self.dm1.get(source)
            self.dm1[source] = dm1
            self.decoded += 1
            changed = prev is None or prev["faults"] != dm1["faults"] or prev["lamps"] != dm1["lamps"]
            if changed:
                self.dm1_changes += 1
            return {"dm1": dm1, "changed": changed}
        values = decode_pgn(pgn, payload)
        if not values:
            return None
        for k, v in values.items():
            self.latest[k] = v
            self.sources[k] = source
        self.decoded += 1
        return {"signals": values, "source": source, "pgn": pgn}

    def row(self) -> dict[str, float | None]:
        return dict(self.latest)

    def faults(self) -> list[dict]:
        """Active faults from every source, each tagged with its source."""
        out = []
        for sa, dm1 in sorted(self.dm1.items()):
            for f in dm1["faults"]:
                out.append({**f, "source": sa, "source_name": SOURCES.get(sa)})
        return out

    def snapshot(self) -> dict:
        signals = {}
        for s in SPNS:
            v = self.latest[s.key]
            if v is None and s.key not in self.sources:
                continue
            signals[s.key] = {"value": v, "unit": s.unit, "spn": s.spn, "pgn": s.pgn,
                              "name": s.name, "source": self.sources.get(s.key)}
        return {
            "signals": signals,
            "dm1": {f"{sa:02X}": dm1 for sa, dm1 in sorted(self.dm1.items())},
            "faults": self.faults(),
            "pgns": {f"{p} ({PGNS[p]['acronym']})" if p in PGNS else str(p): n
                     for p, n in sorted(self.pgns.items())},
            "frames": self.frames,
            "decoded": self.decoded,
            "transport": {"completed": self.transport.completed,
                          "dropped": self.transport.dropped},
        }


def decode_frames(frames) -> dict:
    """Decode frames (objects with .id, .data, .mono) into a Decoder snapshot."""
    dec = Decoder()
    for f in sorted(frames, key=lambda x: x.mono):
        dec.feed(f.id, f.data, f.mono)
    return dec.snapshot()


def dm1_row(dm1: dict) -> list[str]:
    """faults.csv cells after the timestamps: source, four lamps, faults."""
    faults = "; ".join(f"SPN {f['spn']} FMI {f['fmi']}"
                       + (f" x{f['occurrences']}" if f["occurrences"] is not None else "")
                       for f in dm1["faults"])
    return [f"{dm1['source']:02X}", *[dm1["lamps"][n] for n in LAMPS], faults]


FAULT_COLUMNS = ["source", *LAMPS, "faults"]


# -- is this a J1939 bus? ------------------------------------------------------------

def recognise(ids: dict[str, int]) -> dict:
    """Does a set of heard ids (id -> count) look like J1939?

    J1939 when most ids are 29-bit and at least two of them carry a PGN from
    car-use's table, or one known PGN plus several in the standard broadcast
    range (PF 240-255). ISO 15765 diagnostic ids (18DA..., 18DB...) are not
    counted: those are OBD over 29-bit CAN, not J1939 broadcast.
    """
    ext = {i: n for i, n in ids.items()
           if len(i) == 8 and not i.upper().startswith(("18DA", "18DB"))}
    total = len(ids)
    if not total or not ext:
        return {"j1939": False, "why": "no 29-bit ids heard", "extended_ids": 0, "ids": total,
                "known_pgns": [], "sources": []}
    parsed = {i: parse_id(i) for i in ext}
    known = sorted({j.pgn for j in parsed.values() if j.pgn in PGNS})
    broadcast = {j.pgn for j in parsed.values() if j.pf >= 240}
    share = len(ext) / total
    yes = share >= 0.6 and (len(known) >= 2 or (len(known) == 1 and len(broadcast) >= 3))
    sources = sorted({j.source for j in parsed.values()})
    if yes:
        why = (f"{len(ext)} of {total} ids are 29-bit and {len(known)} carry standard J1939 "
               f"PGNs ({', '.join(PGNS[p]['acronym'] for p in known)}) from "
               f"{len(sources)} source address{'es' if len(sources) != 1 else ''}.")
    else:
        why = (f"{len(ext)} of {total} ids are 29-bit, {len(known)} carry a PGN car-use knows: "
               "not enough to call it J1939.")
    return {"j1939": yes, "why": why, "extended_ids": len(ext), "ids": total,
            "known_pgns": [{"pgn": p, "acronym": PGNS[p]["acronym"]} for p in known],
            "sources": [{"address": sa, "name": SOURCES.get(sa)} for sa in sources]}
