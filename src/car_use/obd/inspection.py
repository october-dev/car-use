"""Would this car likely pass a US OBD emissions inspection?

The allowance is the federal one in 40 CFR 85.2222(c)(2): model years 1996
through 2000 may have two incomplete readiness monitors, and 2001 and newer may
have one. This check also wants the check-engine light off and no confirmed
(stored) codes. A state can be stricter. This is not a certificate.
"""
from __future__ import annotations

from . import vin as vinmod

DRIVE = "Drive about 50 km of mixed driving and check again."
RULE = ("US federal allowance, 40 CFR 85.2222: 1996-2000 may have 2 incomplete "
        "readiness monitors, 2001 and newer may have 1. A state can be stricter. "
        "Not a certificate.")


def incomplete_allowance(model_year: int | None) -> int | None:
    """How many incomplete monitors are still allowed, or None before OBD-II."""
    if model_year is None:
        return 1
    if model_year < 1996:
        return None
    if model_year <= 2000:
        return 2
    return 1


def judge(*, mil_on: bool, stored: list[str], monitors: dict, model_year: int | None) -> dict:
    incomplete = [name for name, state in monitors.items() if state != "complete"]
    allowed = incomplete_allowance(model_year)
    too_many = allowed is not None and len(incomplete) > allowed
    reasons: list[str] = []
    if model_year is not None and model_year < 1996:
        reasons.append(f"model year {model_year} is before the OBD-II inspection this check knows")
    if mil_on:
        reasons.append("the check-engine light is commanded on")
    if stored:
        reasons.append("confirmed codes: " + ", ".join(stored))
    if too_many:
        reasons.append(f"{len(incomplete)} incomplete monitors ({', '.join(incomplete)}); "
                       f"this model year is allowed {allowed}")
    ready = not reasons
    if ready:
        nxt = None
    elif mil_on or stored:
        nxt = ("The check-engine light has to be off, and the confirmed codes gone, "
               "before an inspection. Driving will not clear a real fault.")
    elif too_many:
        nxt = DRIVE
    else:
        nxt = "This check does not apply to that model year."
    return {
        "ready": ready,
        "result": "likely to pass" if ready else "not ready",
        "reasons": reasons,
        "mil_on": bool(mil_on),
        "confirmed_codes": list(stored),
        "incomplete": incomplete,
        "incomplete_allowed": allowed,
        "model_year": model_year,
        "year_note": (None if model_year is not None else
                      "Model year could not be verified, so the stricter 2001 allowance of one "
                      "incomplete monitor was used."),
        "rule": RULE,
        "next": nxt,
    }


def ready_for_inspection(vehicle) -> dict:
    codes = vehicle.dtcs()
    status = vehicle.readiness()
    info = vinmod.decode(vehicle.vin)
    year = info.get("model_year") if info.get("check_digit_ok") else None
    return judge(mil_on=bool(codes.get("mil_on") or status.get("mil_on")),
                 stored=list(codes.get("stored") or []),
                 monitors=dict(status.get("monitors") or {}),
                 model_year=year)
