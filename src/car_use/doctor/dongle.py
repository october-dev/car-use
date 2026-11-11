"""Dongle doctor: characterise any ELM327-style adapter and grade it A-D.

Most "ELM327" adapters are clones of v1.4 firmware that report "v1.5" or
"v2.1". The doctor does not trust the version string; it measures.

The AT fingerprint below lists commands that clone firmware commonly drops.
Which command arrived in which genuine firmware version still needs field
validation, so the result reports what is missing rather than guessing a
version.
"""
from __future__ import annotations

import json
import statistics
import time

from .. import paths
from ..obd.elm import Elm327, ElmError
from ..obd import vin as vinmod
from ..transport.base import TransportError

FINGERPRINT = ["ATPPS", "ATMA", "ATCRA7E8", "ATCF7E8", "ATCM7FF", "ATIB10",
               "ATCSM1", "ATAMC", "ATIGN", "ATBRD23", "ATFE", "ATCV1250"]
# Never probed: ATLP (puts a real adapter to sleep), ATPP xx SV/ON (persistent writes).
# Commands that change persistent adapter state are reset right after the probe.
_RESET_AFTER = {"ATCRA7E8": "ATAR", "ATCF7E8": "ATCF000", "ATCM7FF": "ATCM000",
                "ATCV1250": "ATCV0000", "ATCSM1": "ATCSM0"}


def run(elm: Elm327, vehicle=None, soak_requests: int = 30) -> dict:
    rep: dict = {"ts": time.time(), "steps": {}}
    s = rep["steps"]

    t0 = time.monotonic()
    info = elm.initialize()
    s["identity"] = {"reported": info.identity, "device": info.device, "stn": info.stn,
                     "reset_seconds": round(time.monotonic() - t0, 2)}
    claimed = info.identity.upper()
    rep["claims_version"] = claimed.split("V")[-1] if "V" in claimed else "?"
    rep["kind"] = "stn" if info.stn else "unknown-elm"

    missing = []
    for cmd in FINGERPRINT:
        if cmd == "ATMA":
            ok = _probe_monitor(elm)
        else:
            ok = elm.at_ok(cmd)
        if not ok:
            missing.append(cmd)
        if cmd in _RESET_AFTER:
            elm.at_ok(_RESET_AFTER[cmd])
    s["fingerprint"] = {"tested": len(FINGERPRINT), "missing": missing}
    if not info.stn:
        if "1.5" in claimed or ("2." in claimed and len(missing) >= 4):
            rep["kind"] = "clone"
        elif not missing:
            rep["kind"] = "genuine-or-good-clone"
        else:
            rep["kind"] = "clone"

    try:
        rv = elm.at("ATRV")
        s["voltage"] = {"reported": rv,
                        "note": "Compare with a multimeter at the battery; clones often read 0.3-1 V off."}
    except TransportError:
        s["voltage"] = {"reported": None}
    s["low_power"] = {"tested": False,
                      "note": "Sleep behaviour is not probed (ATLP would put the adapter to "
                              "sleep). Many clones never sleep and drain a parked car's battery: "
                              "measure current at the port with the ignition off, or unplug it "
                              "when you leave the car."}

    proto = elm.detect_protocol()
    s["protocol"] = {"name": proto, "number": elm.info.protocol_number}
    link_ok = bool(elm.info.protocol_number)
    try:
        p = elm.query_one("0100")
        s["link"] = {"ok": True, "pid_bitmap_0100": p[2:6].hex().upper()}
    except (ElmError, TransportError) as e:
        s["link"] = {"ok": False, "error": str(e)}
        link_ok = False

    if link_ok:
        try:
            p = elm.query_one("0902")
            raw = (p[3:] if len(p) > 3 and p[2] == 0x01 else p[2:]).decode("ascii", "replace")
            dec = vinmod.decode(raw.strip("\x00 "))
            s["multiframe_vin"] = {"vin": dec["vin"], "valid_format": dec["valid_format"],
                                   "check_digit_ok": dec.get("check_digit_ok")}
        except (ElmError, TransportError) as e:
            s["multiframe_vin"] = {"error": str(e)}

        lat = []
        errors = 0
        for _ in range(soak_requests):
            t = time.monotonic()
            try:
                elm.query_one("010C")
                lat.append(time.monotonic() - t)
            except (ElmError, TransportError):
                errors += 1
        if lat:
            s["throughput"] = {"single_pid_per_s": round(1 / statistics.mean(lat), 1),
                               "p95_ms": round(sorted(lat)[int(len(lat) * 0.95) - 1] * 1000, 1),
                               "errors": errors, "requests": soak_requests}
        try:
            t = time.monotonic()
            r = elm.query_one("010C0D05")
            ok = len(r) >= 9
            s["multi_pid"] = {"ok": ok, "ms": round((time.monotonic() - t) * 1000, 1)}
        except (ElmError, TransportError) as e:
            s["multi_pid"] = {"ok": False, "error": str(e)}

    rep["grade"], rep["why"] = _grade(rep)
    rep["safety"] = ("read-only" if rep["kind"] == "clone" else "read-only (default)")
    return rep


def _probe_monitor(elm: Elm327) -> bool:
    """ATMA streams bus frames until any character arrives; stop it ourselves."""
    with elm.lock:
        elm.t.drain()
        elm.t.write(b"ATMA\r")
        time.sleep(0.4)
        elm.t.write(b"\r")
        try:
            out = elm.t.read_until(b">", 2.0).decode("ascii", "replace")
        except TransportError:
            return False
        elm.t.drain()
    return "?" not in out


def _grade(rep: dict) -> tuple[str, str]:
    s = rep["steps"]
    if not s.get("link", {}).get("ok"):
        return "D", "could not talk to the car (check ignition, seating, protocol)"
    pps = s.get("throughput", {}).get("single_pid_per_s", 0)
    vin_ok = s.get("multiframe_vin", {}).get("valid_format", False)
    missing = len(s["fingerprint"]["missing"])
    if rep["kind"] == "stn" and pps >= 20 and vin_ok:
        return "A", "STN-class adapter: fast, full command set"
    if missing == 0 and pps >= 15 and vin_ok:
        return "A", "full command set and fast"
    if pps >= 8 and vin_ok and missing <= 6:
        return "B", f"usable clone: {missing} AT commands missing, {pps}/s"
    if vin_ok:
        return "C", f"basic reads work but slow or limited ({pps}/s, {missing} AT commands missing)"
    return "D", "multi-frame replies garbled (VIN unreadable); expect broken Mode 09/22 reads"


def save(rep: dict) -> str:
    ident = rep["steps"]["identity"]
    key = "-".join(x for x in (ident.get("stn") or ident.get("reported") or "unknown",
                               rep["kind"]) if x).replace(" ", "_").replace("/", "_")
    path = paths.ensure("adapters") / f"{key}.json"
    path.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    return str(path)
