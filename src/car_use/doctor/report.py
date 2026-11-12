"""Anonymised adapter reports for sharing.

A full ``dongle.run`` result stays on the machine that captured it and may
contain a VIN. ``share_report`` is the copy that can go into an issue: WMI
and model year only. car-use cannot measure current; that number is whatever
the person read on a meter.
"""
from __future__ import annotations

import re

from ..obd.elm import Elm327, ElmError
from ..obd import vin as vinmod
from ..transport.base import TransportError
from . import dongle

# Field reports soak for ten minutes so the error rate is not a lucky sample.
# Pass a shorter ``soak_seconds`` (or None) in tests and one-off checks.
FIELD_SOAK_SECONDS = 600.0

_VIN = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")
_SECRET_KEYS = {"vin", "serial"}


def share_report(elm: Elm327, vehicle=None, soak_requests: int = 30,
                 soak_seconds: float | None = None, current_ma: float | None = None) -> dict:
    full = dongle.run(elm, vehicle, soak_requests=soak_requests, soak_seconds=soak_seconds)
    vin_step = full["steps"].get("multiframe_vin") or {}
    decoded = vinmod.decode(vin_step["vin"]) if vin_step.get("vin") else {}
    pid_count = _pid_count(vehicle) if full["steps"].get("link", {}).get("ok") else None
    report = {
        "schema": 1,
        "source": "car-use dongle-doctor --report",
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
            "vin_multiframe_ok": bool(vin_step.get("valid_format") and vin_step.get("check_digit_ok")),
            "dtc_modes": _dtc_modes(elm),
        },
        "soak": full["steps"].get("soak"),
        "ignition_off_current_ma": current_ma,
        "current_draw": {
            "measured": current_ma is not None,
            "milliamps": current_ma,
            "note": ("car-use does not measure current. With the ignition off, read a meter "
                     "in series with the adapter and pass --current-ma. Unplug the adapter "
                     "when you leave the car; many clones never sleep."),
        },
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
                    raise ValueError(f"shareable report contains {path}.{key}")
                walk(value, f"{path}.{key}")
        elif isinstance(obj, list):
            for i, value in enumerate(obj):
                walk(value, f"{path}[{i}]")
        elif isinstance(obj, str) and _VIN.search(obj.upper()):
            raise ValueError(f"shareable report contains a VIN at {path}")
    walk(report, "report")


def render_table(reports: list[dict]) -> str:
    """Markdown table of shareable reports. Empty input is an empty table, not invented rows."""
    header = ("| adapter | kind | grade | wmi | year | protocol | pids | vin multiframe "
              "| soak error rate | ignition-off mA |")
    rule = "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    rows = [header, rule]
    for rep in reports:
        assert_shareable(rep)
        ident = rep.get("identity") or {}
        vehicle = rep.get("vehicle") or {}
        soak = rep.get("soak") or {}
        adapter = ident.get("stn") or ident.get("reported") or "?"
        year = vehicle.get("model_year")
        pids = vehicle.get("supported_pid_count")
        rate = soak.get("error_rate") if soak else None
        current = rep.get("ignition_off_current_ma")
        cells = [
            adapter,
            rep.get("kind") or "",
            rep.get("grade") or "",
            vehicle.get("wmi") or "",
            "" if year is None else str(year),
            vehicle.get("protocol") or "",
            "" if pids is None else str(pids),
            "yes" if vehicle.get("vin_multiframe_ok") else "no",
            "" if rate is None else str(rate),
            "" if current is None else str(current),
        ]
        rows.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    if len(rows) == 2:
        rows.append("| _no reports_ | | | | | | | | | |")
    return "\n".join(rows)


def _cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


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
    for mode in ("03", "07", "0A"):
        try:
            elm.query_one(mode)
            out[mode] = True
        except (ElmError, TransportError):
            out[mode] = False
    return out
