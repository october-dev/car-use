"""Would this car likely pass a US OBD emissions inspection?

The allowance is the federal one in 40 CFR 85.2222: model years 1996 through
2000 may have two incomplete non-continuous monitors, and 2001 and newer may
have one. Continuous monitors (misfire, fuel system, components) have to be
complete. The check-engine light must be off and there must be no confirmed
(stored) codes. A state can be stricter. This is not a certificate.
"""
from __future__ import annotations

CONTINUOUS = ("misfire", "fuel_system", "components")
DRIVE = "Drive about 50 km of mixed driving and check again."
RULE = ("US federal allowance, 40 CFR 85.2222: 1996-2000 may have 2 incomplete "
        "non-continuous monitors, 2001 and newer may have 1. Continuous monitors "
        "must be complete. A state can be stricter. Not a certificate.")


def incomplete_allowance(model_year: int | None) -> int | None:
    """How many incomplete non-continuous monitors are still allowed, or None before OBD-II."""
    if model_year is None:
        return 1
    if model_year < 1996:
        return None
    if model_year <= 2000:
        return 2
    return 1


def judge(*, mil_on: bool, stored: list[str], monitors: dict, model_year: int | None) -> dict:
    continuous_bad = [name for name in CONTINUOUS if monitors.get(name) == "incomplete"]
    others_bad = [name for name, state in monitors.items()
                  if name not in CONTINUOUS and state != "complete"]
    allowed = incomplete_allowance(model_year)
    reasons: list[str] = []
    if model_year is not None and model_year < 1996:
        reasons.append(f"model year {model_year} is before the OBD-II inspection this check knows")
    if mil_on:
        reasons.append("the check-engine light is commanded on")
    if stored:
        reasons.append("confirmed codes: " + ", ".join(stored))
    if continuous_bad:
        reasons.append("continuous monitors still incomplete: " + ", ".join(continuous_bad))
    if allowed is not None and len(others_bad) > allowed:
        listed = ", ".join(others_bad)
        reasons.append(f"{len(others_bad)} incomplete monitors ({listed}); "
                       f"this model year is allowed {allowed}")
    ready = not reasons
    if ready:
        nxt = None
    elif mil_on or stored:
        nxt = ("The check-engine light has to be off, and the confirmed codes gone, "
               "before an inspection. Driving will not clear a real fault.")
        if continuous_bad or others_bad:
            nxt = nxt + " " + DRIVE
    elif continuous_bad or others_bad:
        nxt = DRIVE
    else:
        nxt = "This check does not apply to that model year."
    return {
        "ready": ready,
        "result": "likely to pass" if ready else "not ready",
        "reasons": reasons,
        "mil_on": bool(mil_on),
        "confirmed_codes": list(stored),
        "incomplete": continuous_bad + others_bad,
        "incomplete_allowed": allowed,
        "model_year": model_year,
        "year_note": (None if model_year is not None else
                      "Model year was not decoded, so the stricter 2001 allowance of one "
                      "incomplete monitor was used."),
        "rule": RULE,
        "next": nxt,
    }


def ready_for_inspection(vehicle) -> dict:
    codes = vehicle.dtcs()
    status = vehicle.readiness()
    info = vehicle.vin_info()
    year = info.get("model_year") if info.get("valid_format") else None
    return judge(mil_on=bool(codes.get("mil_on") or status.get("mil_on")),
                 stored=list(codes.get("stored") or []),
                 monitors=dict(status.get("monitors") or {}),
                 model_year=year)
