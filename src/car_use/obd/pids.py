"""SAE J1979 Mode 01 PIDs: decode and encode, mapped to COVESA VSS paths.

Each PID yields one or more Signals. `decode(data) -> tuple` returns one value
per signal; `encode(values) -> bytes` is the inverse, used by the emulator.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Signal:
    path: str          # COVESA VSS path
    alias: str         # short name agents can type
    unit: str
    description: str


@dataclass(frozen=True)
class Pid:
    pid: int
    length: int
    signals: tuple[Signal, ...]
    decode: Callable[[bytes], tuple]
    encode: Callable[[tuple], bytes]


def _clamp(v: float, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(round(v))))


def _lin1(scale: float, offset: float):
    def dec(d: bytes) -> tuple:
        return (round(d[0] * scale + offset, 3),)

    def enc(v: tuple) -> bytes:
        return bytes([_clamp((v[0] - offset) / scale, 0, 255)])
    return dec, enc


def _lin2(scale: float, offset: float = 0.0):
    def dec(d: bytes) -> tuple:
        return (round((d[0] * 256 + d[1]) * scale + offset, 3),)

    def enc(v: tuple) -> bytes:
        raw = _clamp((v[0] - offset) / scale, 0, 65535)
        return bytes([raw >> 8, raw & 0xFF])
    return dec, enc


def _o2():
    # A: voltage = A/200 V; B: short-term trim = (B-128)*100/128 %
    def dec(d: bytes) -> tuple:
        return (round(d[0] / 200, 3), round((d[1] - 128) * 100 / 128, 2))

    def enc(v: tuple) -> bytes:
        trim = v[1] if len(v) > 1 and v[1] is not None else 0.0
        return bytes([_clamp(v[0] * 200, 0, 255), _clamp(trim * 128 / 100 + 128, 0, 255)])
    return dec, enc


def _sig(path, alias, unit, desc):
    return Signal(path, alias, unit, desc)


_P = "Vehicle.OBD."
_E = "Vehicle.Powertrain.CombustionEngine."

_TABLE: list[tuple[int, int, tuple[Signal, ...], tuple]] = [
    (0x04, 1, (_sig(_P + "EngineLoad", "load", "percent", "Calculated engine load"),), _lin1(100 / 255, 0)),
    (0x05, 1, (_sig(_E + "ECT", "coolant", "celsius", "Engine coolant temperature"),), _lin1(1, -40)),
    (0x06, 1, (_sig(_P + "ShortTermFuelTrim1", "stft1", "percent", "Short term fuel trim, bank 1"),), _lin1(100 / 128, -100)),
    (0x07, 1, (_sig(_P + "LongTermFuelTrim1", "ltft1", "percent", "Long term fuel trim, bank 1"),), _lin1(100 / 128, -100)),
    (0x0B, 1, (_sig(_P + "MAP", "map", "kPa", "Intake manifold absolute pressure"),), _lin1(1, 0)),
    (0x0C, 2, (_sig(_E + "Speed", "rpm", "rpm", "Engine speed"),), _lin2(0.25)),
    (0x0D, 1, (_sig("Vehicle.Speed", "speed", "km/h", "Vehicle speed"),), _lin1(1, 0)),
    (0x0E, 1, (_sig(_P + "TimingAdvance", "timing", "degrees", "Ignition timing advance, cyl 1"),), _lin1(0.5, -64)),
    (0x0F, 1, (_sig(_P + "IntakeTemp", "iat", "celsius", "Intake air temperature"),), _lin1(1, -40)),
    (0x10, 2, (_sig(_P + "MAF", "maf", "g/s", "Mass air flow"),), _lin2(0.01)),
    (0x11, 1, (_sig(_P + "ThrottlePosition", "throttle", "percent", "Throttle position"),), _lin1(100 / 255, 0)),
    (0x14, 2, (_sig(_P + "O2.Sensor1.Voltage", "o2_b1s1", "V", "O2 sensor bank 1 sensor 1 (upstream) voltage"),
               _sig(_P + "O2.Sensor1.ShortTermFuelTrim", "o2_b1s1_trim", "percent", "O2 B1S1 short term trim")), _o2()),
    (0x15, 2, (_sig(_P + "O2.Sensor2.Voltage", "o2_b1s2", "V", "O2 sensor bank 1 sensor 2 (downstream) voltage"),
               _sig(_P + "O2.Sensor2.ShortTermFuelTrim", "o2_b1s2_trim", "percent", "O2 B1S2 short term trim")), _o2()),
    (0x1F, 2, (_sig(_P + "RunTime", "runtime", "s", "Run time since engine start"),), _lin2(1)),
    (0x21, 2, (_sig(_P + "DistanceWithMIL", "distance_mil", "km", "Distance travelled with MIL on"),), _lin2(1)),
    (0x2F, 1, (_sig("Vehicle.Powertrain.FuelSystem.RelativeLevel", "fuel", "percent", "Fuel tank level"),), _lin1(100 / 255, 0)),
    (0x30, 1, (_sig(_P + "WarmupsSinceDTCClear", "warmups_since_clear", "count", "Warm-ups since codes cleared"),), _lin1(1, 0)),
    (0x31, 2, (_sig(_P + "DistanceSinceDTCClear", "distance_since_clear", "km", "Distance since codes cleared"),), _lin2(1)),
    (0x33, 1, (_sig(_P + "BarometricPressure", "baro", "kPa", "Barometric pressure"),), _lin1(1, 0)),
    (0x42, 2, (_sig("Vehicle.LowVoltageBattery.CurrentVoltage", "battery", "V", "Control module (12 V system) voltage"),), _lin2(0.001)),
    (0x46, 1, (_sig("Vehicle.Exterior.AirTemperature", "ambient", "celsius", "Ambient air temperature"),), _lin1(1, -40)),
    (0x5C, 1, (_sig(_E + "EOT", "oil_temp", "celsius", "Engine oil temperature"),), _lin1(1, -40)),
    (0x5E, 2, (_sig(_P + "FuelRate", "fuel_rate", "l/h", "Engine fuel rate"),), _lin2(0.05)),
]

PIDS: dict[int, Pid] = {pid: Pid(pid, n, sigs, dec, enc) for pid, n, sigs, (dec, enc) in _TABLE}

# alias or VSS path -> (pid, index of signal within that pid)
SIGNALS: dict[str, tuple[int, int]] = {}
for _p in PIDS.values():
    for _i, _s in enumerate(_p.signals):
        SIGNALS[_s.alias] = (_p.pid, _i)
        SIGNALS[_s.path] = (_p.pid, _i)


def resolve(name: str) -> tuple[Pid, int, Signal]:
    """Find a signal by alias, VSS path, or 'pid:0C' / '010C' form."""
    key = name.strip()
    if key in SIGNALS:
        pid, idx = SIGNALS[key]
        return PIDS[pid], idx, PIDS[pid].signals[idx]
    low = key.lower().removeprefix("pid:")
    if low.startswith("01") and len(low) == 4:
        low = low[2:]
    try:
        pid = int(low, 16)
    except ValueError:
        pid = -1
    if pid in PIDS:
        return PIDS[pid], 0, PIDS[pid].signals[0]
    close = sorted(a for a in SIGNALS if "." not in a and (key.lower() in a or a in key.lower()))
    hint = f" Did you mean: {', '.join(close)}?" if close else " See signals()."
    raise KeyError(f"Unknown signal {name!r}.{hint}")


# --- PID 01: monitor status since DTCs cleared --------------------------------

CONTINUOUS = ("misfire", "fuel_system", "components")
SPARK_MONITORS = ("catalyst", "heated_catalyst", "evap", "secondary_air",
                  "ac_refrigerant", "o2_sensor", "o2_heater", "egr")


def decode_monitor_status(d: bytes) -> dict:
    """Decode Mode 01 PID 01 (spark-ignition layout)."""
    a, b, c, dd = d[:4]
    out = {"mil_on": bool(a & 0x80), "dtc_count": a & 0x7F,
           "ignition": "compression" if b & 0x08 else "spark", "monitors": {}}
    for i, name in enumerate(CONTINUOUS):
        if b & (1 << i):
            out["monitors"][name] = "incomplete" if b & (1 << (i + 4)) else "complete"
    for i, name in enumerate(SPARK_MONITORS):
        if c & (1 << i):
            out["monitors"][name] = "incomplete" if dd & (1 << i) else "complete"
    return out


def encode_monitor_status(mil_on: bool, dtc_count: int, monitors: dict) -> bytes:
    a = (0x80 if mil_on else 0) | min(dtc_count, 0x7F)
    b = c = dd = 0
    for i, name in enumerate(CONTINUOUS):
        if name in monitors:
            b |= 1 << i
            if monitors[name] != "complete":
                b |= 1 << (i + 4)
    for i, name in enumerate(SPARK_MONITORS):
        if name in monitors:
            c |= 1 << i
            if monitors[name] != "complete":
                dd |= 1 << i
    return bytes([a, b, c, dd])


# --- DTCs ----------------------------------------------------------------------

_SYSTEMS = "PCBU"


def decode_dtc(hi: int, lo: int) -> str:
    return f"{_SYSTEMS[hi >> 6]}{(hi >> 4) & 0x3}{hi & 0xF:X}{lo >> 4:X}{lo & 0xF:X}"


def encode_dtc(code: str) -> bytes:
    code = code.strip().upper()
    if len(code) != 5 or code[0] not in _SYSTEMS:
        raise ValueError(f"Bad DTC {code!r}")
    hi = (_SYSTEMS.index(code[0]) << 6) | (int(code[1], 16) << 4) | int(code[2], 16)
    return bytes([hi, int(code[3:5], 16)])
