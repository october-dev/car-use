"""Anonymised adapter reports for sharing.

A full ``dongle.run`` result stays on the machine that captured it and may
contain a VIN. ``share_report`` is the copy that can go into an issue: WMI
and model year only. car-use cannot measure current; that number is whatever
the person read on a meter.
"""
from __future__ import annotations

import re

from .. import __version__
from ..obd.elm import Elm327, ElmError
from ..obd import vin as vinmod
from ..transport.base import TransportError
from . import dongle

# Field reports soak for ten minutes so the error rate is not a lucky sample.
# Pass a shorter ``soak_seconds`` (or None) in tests and one-off checks.
FIELD_SOAK_SECONDS = 600.0

# A VIN can arrive glued to other text ("VIN1G1PE5SB7F7000999" in a raw ATZ
# banner), so look at every 17-character window of every letter/digit run.
# Over-matching is the safe side: a rejected report can be re-run, a leaked VIN can't.
_RUN = re.compile(r"[A-Z0-9]{17,}")
_VIN_CHARS = re.compile(r"[A-HJ-NPR-Z0-9]{17}")


def _has_vin(text: str) -> bool:
    for run in _RUN.findall(text.upper()):
        for i in range(len(run) - 16):
            w = run[i:i + 17]
            if _VIN_CHARS.fullmatch(w) and sum(c.isdigit() for c in w) >= 3 \
                    and any(c.isalpha() for c in w):
                return True
    return False


_SECRET_KEYS = {"vin", "serial"}


class PrivacyError(ValueError):
    """A shareable report still carries identity: it must not be published."""


def share_report(elm: Elm327, vehicle=None, soak_requests: int = 30,
                 soak_seconds: float | None = None, current_ma: float | None = None,
                 notice=None) -> dict:
    full = dongle.run(elm, vehicle, soak_requests=soak_requests, soak_seconds=soak_seconds,
                      notice=notice)
    vin_step = full["steps"].get("multiframe_vin") or {}
    decoded = vinmod.decode(vin_step["vin"]) if vin_step.get("vin") else {}
    # A failed soak can leave the link dead or replies out of step.
    # Do not publish subsequent probes as capability measurements.
    interrupted = bool((full["steps"].get("soak") or {}).get("interrupted"))
    link_ok = bool(full["steps"].get("link", {}).get("ok")) and not interrupted
    pid_count = _pid_count(vehicle) if link_ok else None
    report = {
        "schema": 1,
        "source": "car-use dongle-doctor --report",
        "car_use_version": __version__,
        # Best effort: true for in-process virtual cars (--sim). A virtual car served
        # over TCP (car-use sim) looks like a real adapter and reports false.
        "simulated": vehicle is not None and vehicle.scenario is not None,
        "kind": full["kind"],
        "grade": full["grade"],
        "why": full["why"],
        "claims_version": full["claims_version"],
        "identity": {
            "reported": full["steps"]["identity"].get("reported"),
            "stn": full["steps"]["identity"].get("stn"),
        },
        "fingerprint": full["steps"]["fingerprint"],
        "fingerprint_status": "unvalidated",
        "fingerprint_note": (
            "Missing AT commands are reported as measured. This list has not been "
            "checked against a physical genuine ELM327 v2.x or STN device, so a grade "
            "is not a firmware version."
        ),
        "vehicle": {
            "wmi": decoded.get("wmi"),
            "model_year": decoded.get("model_year"),
            "protocol": (full["steps"].get("protocol") or {}).get("name"),
            "protocol_number": (full["steps"].get("protocol") or {}).get("number"),
            "supported_pid_count": pid_count,
            "vin_multiframe_ok": bool(vin_step.get("valid_format")),
            "dtc_modes": None if interrupted else _dtc_modes(elm),
        },
        "soak": full["steps"].get("soak"),
        "ignition_off_current_ma": current_ma,
        "ignition_off_current_note": (
            "car-use does not measure current. With the ignition off, read a meter "
            "in series with the adapter and pass --current-ma. Unplug the adapter "
            "when you leave the car; many clones never sleep."),
    }
    assert_shareable(report)
    return report


def field_soak_seconds(given: float | None) -> float:
    """``--report`` soaks for ten minutes unless the caller overrides it."""
    return FIELD_SOAK_SECONDS if given is None else given


def assert_shareable(report: dict) -> None:
    """Reject a report that still carries a VIN or a serial number."""
    def walk(obj, path: str) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if str(key).lower() in _SECRET_KEYS:
                    raise PrivacyError(f"shareable report contains {path}.{key}")
                walk(value, f"{path}.{key}")
        elif isinstance(obj, list):
            for i, value in enumerate(obj):
                walk(value, f"{path}[{i}]")
        elif isinstance(obj, str) and _has_vin(obj):
            raise PrivacyError(f"shareable report contains a VIN at {path}")
    walk(report, "report")


def _pid_count(vehicle) -> int | None:
    if vehicle is None:
        return None
    try:
        return len(vehicle.supported_pids())
    except (ElmError, TransportError):
        return None


def _dtc_modes(elm: Elm327) -> dict:
    """Whether Mode 03 / 07 / 0A answered. The codes themselves are not shared."""
    out = {}
    for mode, want in (("03", 0x43), ("07", 0x47), ("0A", 0x4A)):
        try:
            payload = elm.query_one(mode)
        except (ElmError, TransportError):
            out[mode] = False
        else:
            out[mode] = bool(payload) and payload[0] == want
    return out
