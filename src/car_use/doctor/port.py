"""Does this car's OBD port carry its own CAN traffic? And where are steering and brake?

`car-use can-check` listens without sending anything to the car, then says
whether the port is open (the car's internal messages reach it), partial
(a few do), or hidden (a gateway keeps the port silent until a scan tool
asks). With `--find`, it guides the person through a few things to do with
the car parked, engine running: turn the wheel, press the brake, switch an
indicator on. Comparing each action against a still baseline shows which
message bytes moved, which is where that signal lives on this car.

The person does every step with the car parked. car-use never asks anyone to
do anything while driving.
"""
from __future__ import annotations

import time

from .. import __version__
from ..obd import vin as vinmod
from ..obd.elm import ElmError
from ..obd.monitor import Capture, Frame, is_diagnostic, listen
from ..transport.base import TransportError
from .report import assert_shareable

STILL = ("Keep still: car parked, engine running, hands off the wheel, foot off the brake, "
         "indicators off.")
ACTIONS = {
    "steering": ("Turn the steering wheel slowly all the way one way, then all the way the "
                 "other, and back to the middle.", "continuous"),
    "brake": ("Press the brake pedal firmly, hold for a second, release. Do it three times.",
              "toggle"),
    "indicator": ("Switch the left indicator on and leave it blinking.", "toggle"),
}


def _stats(frames: list[Frame]) -> dict[str, dict]:
    """Per id: samples, and per byte the values seen, bits that changed, transitions."""
    out: dict[str, dict] = {}
    for f in sorted(frames, key=lambda x: x.mono):
        if is_diagnostic(f.id):
            continue
        s = out.setdefault(f.id, {"samples": 0, "bytes": {}, "last": None, "frames": []})
        s["samples"] += 1
        s["frames"].append(f.data)
        for i, b in enumerate(f.data):
            bs = s["bytes"].setdefault(i, {"values": set(), "changed": 0, "transitions": 0})
            bs["values"].add(b)
            last = s["last"]
            if last is not None and i < len(last) and last[i] != b:
                bs["changed"] |= last[i] ^ b
                bs["transitions"] += 1
        s["last"] = f.data
    return out


STEADY_FRAMES = 8


def find_changes(still: Capture, action: Capture, kind: str = "continuous",
                 top: int = 3) -> list[dict]:
    """Bytes that moved during the action but held steady while still.

    Rolling counters, checksums and engine noise move in both windows, so
    they drop out. Adjacent bytes of one id that both moved are reported as
    one field (a 16-bit steering angle is two bytes). ``kind`` is
    "continuous" (many values: steering) or "toggle" (a bit or two
    switching: brake switch, indicator).
    """
    s_stats, a_stats = _stats(still.frames), _stats(action.frames)
    cands: list[dict] = []
    for ident, a in a_stats.items():
        if a["samples"] < 2:
            continue
        s = s_stats.get(ident)
        trusted = s is not None and s["samples"] >= 2
        moved: dict[int, dict] = {}
        for i, ab in a["bytes"].items():
            sb = (s or {}).get("bytes", {}).get(i)
            still_changed = sb["changed"] if sb else 0
            bits = ab["changed"]
            transitions = ab["transitions"]
            if sb and still_changed == 0 and len(sb["values"]) == 1:
                ref = next(iter(sb["values"]))
                diff = 0
                for v in ab["values"]:
                    diff |= v ^ ref
                bits |= diff
                first = a["frames"][0][i] if i < len(a["frames"][0]) else ref
                if first != ref:
                    transitions += 1
            bits &= ~still_changed & 0xFF
            if bits:
                moved[i] = {"bits": bits, "transitions": transitions}
        for group in _runs(sorted(moved)):
            lo, hi = group[0], group[-1]
            values = {fr[lo:hi + 1] for fr in a["frames"] if len(fr) > hi}
            bits = [moved[i]["bits"] for i in group]
            transitions = max(moved[i]["transitions"] for i in group)
            nbits = sum(bin(b).count("1") for b in bits)
            if kind == "continuous":
                score = len(values) * 2 + transitions
            else:
                score = min(transitions, 20) * 2 + (10 if nbits <= 2 else 0) + \
                    (5 if len(values) <= 3 else 0)
            if not trusted:
                score /= 4
            else:
                # "Steady while still" from a handful of frames is weak evidence: a
                # slow, noisy gauge can happen to hold for three frames. Full weight
                # from STEADY_FRAMES frames heard while still.
                score *= min(1.0, s["samples"] / STEADY_FRAMES)
            cands.append({
                "id": ident,
                "bytes": [lo, hi] if hi > lo else [lo],
                "bits": [f"0x{b:02X}" for b in bits],
                "values": len(values),
                "transitions": transitions,
                "samples": a["samples"],
                "still_samples": s["samples"] if s else 0,
                "score": round(score, 1),
                "note": _note(ident, lo, hi, bits, len(values), transitions, kind, trusted),
            })
    cands.sort(key=lambda c: -c["score"])
    if cands:
        # Slow noise (a gauge that ticks once in a while) can look steady in a short
        # still window. Keep only leads within reach of the best one.
        floor = cands[0]["score"] * 0.4
        cands = [c for c in cands if c["score"] >= floor]
    return cands[:top]


def _runs(idx: list[int]) -> list[list[int]]:
    out: list[list[int]] = []
    for i in idx:
        if out and i == out[-1][-1] + 1:
            out[-1].append(i)
        else:
            out.append([i])
    return out


def _note(ident, lo, hi, bits, values, transitions, kind, trusted) -> str:
    where = f"id {ident} byte{'s' if hi > lo else ''} {lo}{'-' + str(hi) if hi > lo else ''}"
    if kind == "toggle" and sum(bin(b).count("1") for b in bits) <= 2:
        what = f"{where} bit {bits[0]:#04x}: switched {transitions} times"
    else:
        what = f"{where}: {values} different values"
    if not trusted:
        return what + " (barely heard while still, so this is a weak lead)"
    return what + ", steady while still"


def run(elm, vehicle=None, seconds: float = 5.0, find: list[str] | None = None,
        still_seconds: float = 5.0, action_seconds: float = 10.0, ready_seconds: float = 3.0,
        say=None, act=None) -> dict:
    """Listen, give a verdict, then optionally guide the person through `find` actions.

    ``say(text)`` shows a line to the person (the CLI prints to stderr).
    ``act(name | None)`` is only for the simulator: it plays the person's
    part, so a virtual car's steering moves when the prompt says to turn it.
    """
    say = say or (lambda text: None)
    find = list(find or [])
    for name in find:
        if name not in ACTIONS:
            raise ValueError(f"unknown action {name!r}; choose from {', '.join(ACTIONS)}")
    info = elm.info
    out: dict = {"ts": time.time(), "adapter": {"identity": info.identity, "stn": info.stn},
                 "protocol": info.protocol, "protocol_number": info.protocol_number,
                 "simulated": vehicle is not None and getattr(vehicle, "scenario", None) is not None}
    listen_only = bool(getattr(vehicle, "listen_only", None) or getattr(elm, "listen_only", False))
    out["listen_only"] = (getattr(vehicle, "listen_only", None) or {"on": listen_only})
    # Asking the engine for rpm is an OBD request; in listen-only mode it is skipped.
    out["engine_running"] = None if listen_only or info.is_j1939 else _engine_running(vehicle)
    say(f"Listening for {seconds:g} s. car-use sends nothing to the car while it listens.")
    cap = listen(elm, seconds)
    out["listen"] = cap.summary()
    out["verdict"], out["why"] = cap.traffic()
    out["j1939"] = _j1939(cap)
    out["bus"] = "j1939" if out["j1939"] else ("can" if cap.ids() else None)
    if out["j1939"]:
        rpm = (out["j1939"]["signals"].get("engine_speed_rpm") or {}).get("value")
        if rpm is not None:
            out["engine_running"] = rpm > 300
    # Car maps (opendbc) do not apply to a J1939 machine.
    out["layout"] = [] if out["j1939"] else _layout(cap)
    out["next"] = _next(out["verdict"], out["engine_running"], bool(find), bool(out["j1939"]))
    out["found"] = {}
    if find and out["verdict"] in ("open", "partial"):
        for name in find:
            prompt, kind = ACTIONS[name]
            if ready_seconds > 0:
                say(f"Next: {name}. Get ready. {STILL}")
                time.sleep(ready_seconds)
            say(f"Hold still for {still_seconds:g} s...")
            still = listen(elm, still_seconds)
            say(f"Now, for {action_seconds:g} s: {prompt}")
            if act:
                act(name)
            try:
                moved = listen(elm, action_seconds)
            finally:
                if act:
                    act(None)
            say(f"Done with {name}. You can stop.")
            cands = find_changes(still, moved, kind)
            _name_candidates(cands, out["layout"])
            out["found"][name] = {
                "candidates": cands,
                "still_frames": len(still.car_frames()),
                "action_frames": len(moved.car_frames()),
                "sampled": bool(still.buffer_full or moved.buffer_full),
            }
        top = (out["layout"] or [{}])[0]
        if top.get("confidence") == "strong" and any(
                c.get("dbc_signal") for body in out["found"].values() for c in body["candidates"]):
            out["next"] = (f"The {top['label']} map explains what moved. Record it in real units: "
                           f"car-use record --decode {top['dbc']}")
    return out


def _j1939(cap: Capture) -> dict | None:
    """If the bus is J1939 (trucks, machines), what it is and what it says."""
    from ..can import j1939
    bus = j1939.recognise(cap.ids())
    if not bus["j1939"]:
        return None
    return {**bus, **j1939.decode_frames(cap.car_frames())}


def _layout(cap: Capture) -> list[dict]:
    """Which bundled DBC maps (from opendbc) best explain the ids heard."""
    from ..can.library import match
    lengths = {f.id: len(f.data) for f in cap.car_frames()}
    return [m.to_dict() for m in match(lengths)] if lengths else []


def _name_candidates(cands: list[dict], layout: list[dict]) -> None:
    """Add the matching DBC signal's name to each lead, when a map fits."""
    if not layout:
        return
    from ..can.library import which_signal
    top = layout[0]
    if top.get("confidence") != "strong":
        return
    for c in cands:
        lo, hi = c["bytes"][0], c["bytes"][-1]
        hit = which_signal(top["dbc"], c["id"], lo, hi, [int(b, 16) for b in c["bits"]])
        if hit:
            c["dbc_signal"] = {**hit, "dbc": top["dbc"]}
            c["note"] += f" = {hit['message']}.{hit['signal']} in the {top['label']} map"


def _engine_running(vehicle) -> bool | None:
    if vehicle is None:
        return None
    try:
        rpm = vehicle.read("rpm").value
    except (ElmError, TransportError, KeyError):
        return None
    return None if rpm is None else rpm > 300


def _next(verdict: str, engine_running: bool | None, found: bool, j1939: bool = False) -> str:
    if j1939:
        return ("This is a J1939 bus. Record its standard signals and active faults with: "
                "car-use record --decode j1939")
    if verdict in ("open", "partial") and not found:
        return ("With the car parked and the engine running, run car-use can-check --find "
                "steering,brake,indicator to see which messages carry them.")
    if verdict in ("open", "partial"):
        return ("Repeat once to confirm the top candidate for each signal, then record it with "
                "car-use record --can --can-ids <ids>.")
    if verdict == "hidden" and engine_running is False:
        return ("Some cars only put traffic on the port with the engine running. Start the engine "
                "(in a ventilated place) and run can-check again.")
    if verdict == "hidden" and engine_running is None:
        return ("Nothing reached the port. On a car, start the engine (in a ventilated place) and "
                "run can-check again; standard OBD still works. On a truck or machine "
                "(9-pin Deutsch port, J1939 at 250 kbit/s) run car-use can-check --j1939.")
    if verdict == "hidden":
        return ("Standard OBD still works (car-use record without --can). For steering or brake, "
                "look for maker-specific Mode 22 identifiers (a vehicle pack).")
    if verdict == "adapter_cannot_listen":
        return "Try again with an OBDLink (STN) adapter or a genuine ELM327."
    return "Standard OBD readings still work; car-use record without --can logs them."


def share_report(result: dict, vehicle=None, model: str | None = None) -> dict:
    """The part of a can-check that can go into a public issue: no VIN, no serial."""
    decoded = vinmod.decode(vehicle.vin) if vehicle is not None and vehicle.vin else {}
    listen_ = result.get("listen") or {}
    report = {
        "schema": 1,
        "source": "car-use can-check --report",
        "car_use_version": __version__,
        "simulated": bool(result.get("simulated")),
        "vehicle": {
            "wmi": decoded.get("wmi"),
            "model_year": decoded.get("model_year"),
            "manufacturer": decoded.get("manufacturer"),
            "model": (model or "").strip() or None,
            "protocol": result.get("protocol"),
            "protocol_number": result.get("protocol_number"),
            "engine_running": result.get("engine_running"),
        },
        "adapter": {"reported": (result.get("adapter") or {}).get("identity"),
                    "stn": (result.get("adapter") or {}).get("stn")},
        "verdict": result.get("verdict"),
        "bus": result.get("bus"),
        "listen_only": (result.get("listen_only") or {}).get("on"),
        "j1939": ({"known_pgns": result["j1939"]["known_pgns"],
                   "sources": result["j1939"]["sources"],
                   "faults": [{k: f[k] for k in ("spn", "fmi", "source")}
                              for f in result["j1939"]["faults"]]}
                  if result.get("j1939") else None),
        "listen": {k: listen_.get(k) for k in ("seconds", "frames", "frames_per_s", "bursts",
                                                "buffer_full", "sampled")},
        "ids": sorted((listen_.get("ids") or {}).keys()),
        "layout": [{k: lay[k] for k in ("dbc", "known_ids", "heard_ids", "score")}
                   for lay in result.get("layout") or []],
        "found": {
            name: [{k: c[k] for k in ("id", "bytes", "bits", "values", "transitions", "note", "dbc_signal")
                    if k in c}
                   for c in body.get("candidates", [])]
            for name, body in (result.get("found") or {}).items()
        },
    }
    assert_shareable(report)
    return report


def render(result: dict) -> str:
    """Plain text for the person."""
    lst = result.get("listen") or {}
    lines = [f"verdict: {result['verdict']}", f"  {result['why']}"]
    lo = result.get("listen_only") or {}
    if lo.get("on"):
        how = ("the adapter confirmed silent monitoring (" + ", ".join(lo["adapter_commands"]) + ")"
               if lo.get("adapter_silent") else "enforced by car-use only; the adapter did not confirm "
               "silent monitoring" if "adapter_silent" in lo else "enforced by car-use")
        lines.append(f"mode: listen-only, nothing was sent to the bus; {how}.")
    if lst.get("frames"):
        rate = f", about {lst['frames_per_s']} frames/s heard" if lst.get("frames_per_s") else ""
        lines.append(f"  heard {lst['frames']} frames from {len(lst.get('ids') or {})} ids"
                     f" in {lst['seconds']} s{rate}.")
        if lst.get("sampled"):
            lines.append(f"  The adapter overflowed {lst['buffer_full']} times (BUFFER FULL), so "
                         "this is a sample of the bus, not every frame.")
    lines += _render_j1939(result.get("j1939"))
    for i, lay in enumerate(result.get("layout") or []):
        if i == 0:
            how = "looks like" if lay.get("confidence") == "strong" else "a weak match, maybe"
            lines.append(f"layout: {how} {lay['label']} ({lay['dbc']}): "
                         f"{lay['known_ids']} of {lay['heard_ids']} ids heard are in that map.")
            if lay.get("confidence") != "strong":
                lines.append("  Too few ids line up to be sure. Run --find to check which bytes really move.")
            if lay["signals"]:
                lines.append(f"  It can decode: {', '.join(lay['signals'])}. "
                             f"Record them with: car-use record --decode {lay['dbc']}")
        else:
            lines.append(f"  also possible: {lay['label']} ({lay['known_ids']} of {lay['heard_ids']} ids)")
    if result.get("engine_running") is False:
        lines.append("  The engine was not running.")
    for name, body in (result.get("found") or {}).items():
        cands = body.get("candidates") or []
        if not cands:
            lines.append(f"{name}: nothing moved that was steady while still. Repeat it more "
                         "firmly, or the signal is not on this bus.")
            continue
        lines.append(f"{name}: best guess first")
        for c in cands:
            lines.append(f"  - {c['note']}")
    lines.append(f"next: {result['next']}")
    return "\n".join(lines) + "\n"


def _render_j1939(bus: dict | None) -> list[str]:
    if not bus:
        return []
    from ..can.j1939 import SOURCES
    lines = [f"bus: J1939 (the CAN dialect of trucks, buses and heavy machines)", f"  {bus['why']}"]
    for key, s in bus["signals"].items():
        value = "not available" if s["value"] is None else f"{s['value']:g} {s['unit']}"
        src = s["source"]
        lines.append(f"  {key:<18} {value:<16} SPN {s['spn']}, from {src:02X}"
                     + (f" {SOURCES[src]}" if src in SOURCES else ""))
    for sa, dm1 in bus["dm1"].items():
        lamps = [n for n, state in dm1["lamps"].items() if state == "on"]
        how = " (multi-packet, BAM)" if dm1.get("multi_packet") else ""
        name = f" {dm1['source_name']}" if dm1.get("source_name") else ""
        lines.append(f"  DM1 from {sa}{name}{how}: lamps on: {', '.join(lamps) or 'none'}")
        if not dm1["faults"]:
            lines.append("    no active faults")
        for f in dm1["faults"]:
            oc = f", seen {f['occurrences']}x" if f["occurrences"] is not None else ""
            lines.append(f"    - {f['text']}{oc}")
    tp = bus.get("transport") or {}
    if tp.get("dropped"):
        lines.append(f"  {tp['dropped']} multi-packet message(s) were incomplete (adapter overflowed?).")
    return lines
