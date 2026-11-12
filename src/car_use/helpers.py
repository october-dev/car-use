"""Helpers pre-imported into every `car-use <<'PY'` script.

The harness reports, the agent decides: helpers return observations (values,
units, sources, timestamps), never verdicts about what is wrong with a car.
"""
from __future__ import annotations

import statistics
import time

from . import connect as _connect
from .obd import pids as _pids

_state: dict = {"vehicle": None, "device": None}

__all__ = ["car", "manifest", "signals", "read", "read_many", "watch", "dtcs", "readiness",
           "freeze_frame", "vin_info", "raw_obd", "clear_dtcs", "dongle_doctor", "scenarios",
           "describe_dtc", "Series"]


def _configure(device: str | None) -> None:
    _state["device"] = device


def car():
    """The connected vehicle (connects on first use). car().describe() for a summary."""
    if _state["vehicle"] is None:
        _state["vehicle"] = _connect.open_vehicle(_state["device"])
    return _state["vehicle"]


def manifest():
    """What this car + backend can observe and do, by altitude and tier."""
    return car().manifest()


def signals(prefix: str = "") -> list[dict]:
    """Signals this car reports right now: alias, VSS path, unit, PID."""
    return car().signals(prefix)


def read(name: str):
    """One signal by alias ('rpm'), VSS path ('Vehicle.Speed') or PID ('010C')."""
    return car().read(name)


def read_many(names: list[str]) -> dict:
    """Several signals in as few round trips as the adapter allows."""
    return car().read_many(names)


class Series:
    """Samples from watch(): .rows, .column(name), .summary()."""

    def __init__(self, names: list[str], rows: list[dict], units: dict):
        self.names, self.rows, self.units = names, rows, units

    def column(self, name: str) -> list[float]:
        return [r[name] for r in self.rows if r.get(name) is not None]

    def summary(self) -> dict:
        out = {}
        for n in self.names:
            col = self.column(n)
            if not col:
                out[n] = {"samples": 0}
                continue
            mean = statistics.fmean(col)
            sd = statistics.pstdev(col) if len(col) > 1 else 0.0
            # Count crossings of the mean with hysteresis: how often a signal switches.
            band, side, switches = max(sd * 0.5, 1e-9), 0, 0
            for v in col:
                s = 1 if v > mean + band else -1 if v < mean - band else 0
                if s and side and s != side:
                    switches += 1
                if s:
                    side = s
            secs = (self.rows[-1]["t"] - self.rows[0]["t"]) if len(self.rows) > 1 else 0
            out[n] = {"unit": self.units.get(n, ""), "samples": len(col),
                      "min": round(min(col), 3), "max": round(max(col), 3),
                      "mean": round(mean, 3), "stdev": round(sd, 3), "switches": switches,
                      "switches_per_10s": round(switches * 10 / secs, 1) if secs else None}
        return out

    def __repr__(self) -> str:
        lines = [f"Series({len(self.rows)} samples)"]
        for n, s in self.summary().items():
            if s.get("samples"):
                lines.append(f"  {n:<14} min {s['min']:<8} max {s['max']:<8} mean {s['mean']:<8} "
                             f"sd {s['stdev']:<7} switches/10s {s['switches_per_10s']} {s['unit']}")
            else:
                lines.append(f"  {n:<14} no data")
        return "\n".join(lines)


def watch(names: list[str] | str, seconds: float = 10.0, hz: float = 5.0) -> Series:
    """Sample signals for `seconds` at up to `hz`. Real adapters may be slower than asked."""
    if isinstance(names, str):
        names = [names]
    v = car()
    units = {n: _pids.resolve(n)[2].unit for n in names}
    rows, t0 = [], time.monotonic()
    period = 1.0 / hz if hz > 0 else 0
    while (now := time.monotonic()) - t0 < seconds:
        vals = v.read_many(names)
        rows.append({"t": round(now - t0, 3), **{n: vals[n].value for n in names}})
        sleep = period - (time.monotonic() - now)
        if sleep > 0:
            time.sleep(sleep)
    return Series(names, rows, units)


def dtcs() -> dict:
    """Stored (confirmed), pending and permanent trouble codes, with generic descriptions."""
    return car().dtcs()


def readiness() -> dict:
    """MIL, DTC count, emissions monitors, distance and warm-ups since codes were cleared."""
    return car().readiness()


def ready_for_inspection() -> dict:
    """Whether this car would likely pass a US OBD emissions inspection.

    MIL off, no confirmed codes, and incomplete monitors within the federal
    allowance for the model year. Not a state certificate. If it is not ready,
    ``next`` says what to do.
    """
    from .obd.inspection import ready_for_inspection as _check
    return _check(car())


def freeze_frame() -> dict:
    """Conditions the ECU saved when the stored DTC set."""
    return car().freeze_frame()


def vin_info() -> dict:
    """Offline VIN decode: check digit, model year, manufacturer."""
    return car().vin_info()


def raw_obd(request: str):
    """Send a read-only OBD/UDS request in hex ('0105', '221E12'). Writes are refused."""
    return car().raw_obd(request)


def clear_dtcs():
    """Clear codes (tier T1D). Needs the owner to enable T1D and confirm at a terminal."""
    return car().clear_dtcs()


def describe_dtc(code: str) -> str:
    from .obd.dtc_info import describe
    return describe(code)


def dongle_doctor(save: bool = True) -> dict:
    """Characterise the connected adapter: identity, missing AT commands, speed, grade A-D."""
    from .doctor import dongle
    v = car()
    rep = dongle.run(v.elm, v)
    if save:
        rep["saved_to"] = dongle.save(rep)
    return rep


def scenarios() -> dict:
    """Simulator scenarios: name -> notes."""
    from .sim.scenario import available, load
    return {n: load(n).title for n in available()}


def _shutdown():
    v = _state.get("vehicle")
    if v is not None:
        try:
            v.elm.close()
        except Exception:
            pass
        emu = getattr(v, "_emulator", None)
        if emu is not None:
            emu.stop()
    _state["vehicle"] = None

