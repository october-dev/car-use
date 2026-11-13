"""A used-car scan you can hand to a seller.

Red, amber, and green come from what the car actually answered. Missing
odometer data is said out loud. Nothing here is a mechanical inspection.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone

from .obd.elm import ElmError
from .obd.vin import decode as vin_decode
from .transport.base import TransportError

# A recent clear looks like incomplete monitors plus little driving since.
# Monitors usually complete within a few hundred km / several warm-ups of
# normal driving, so below either bound the car likely has not had the
# chance — consistent with a recent clear, not proof of one. Missing values
# simply do not count towards "recent". Kept in sync with "Used-car checks"
# in SKILL.md.
RECENT_CLEAR_KM = 300
RECENT_CLEAR_WARMUPS = 10

_MONITOR_NAMES = {
    "misfire": "misfire", "fuel_system": "fuel system", "components": "components",
    "catalyst": "catalyst", "evap": "EVAP", "o2_sensor": "oxygen sensor",
    "o2_heater": "oxygen sensor heater", "egr": "EGR", "pm_filter": "particulate filter",
}


def _try(read):
    """One section's read. An unsupported mode (older cars answer some with '?')
    must not cost the whole scan."""
    try:
        return read(), None
    except ElmError as e:
        return {}, str(e) or type(e).__name__


def build(vehicle, expect_vin: str | None = None) -> dict:
    items: list[dict] = []
    codes, codes_err = _try(vehicle.dtcs)
    ready, ready_err = _try(vehicle.readiness)
    if codes_err and ready_err:
        raise ElmError("scan", codes_err)    # the car isn't answering at all: no report
    if codes_err:
        items.append(_item("amber", "Trouble codes were not reported",
                           f"The car did not answer the code request ({codes_err}). "
                           "Try again with the engine running, or use another scanner."))
    if ready_err:
        items.append(_item("amber", "Readiness monitors were not reported",
                           f"The car did not answer the monitor request ({ready_err}), "
                           "so a recent code clear can't be ruled out."))

    stored = list(codes.get("stored") or [])
    pending = list(codes.get("pending") or [])
    permanent = list(codes.get("permanent") or [])
    descriptions = codes.get("descriptions") or {}
    # The light is sampled twice (once inside dtcs(), once here); an observed
    # "on" from either sample is kept.
    mil_on = bool(codes.get("mil_on") or ready.get("mil_on"))
    if codes_err and not mil_on:
        pass
    elif mil_on or stored:
        detail = "Stored: " + (_describe_codes(stored, descriptions) or "none") + ". "
        detail += ("The check-engine light is commanded on." if mil_on
                   else "The check-engine light is not commanded on.")
        items.append(_item("red", "Check-engine light or confirmed codes", detail))
    else:
        items.append(_item("green", "No confirmed codes",
                           "The check-engine light is not commanded on, and there are no stored codes."))
    if pending:
        items.append(_item("amber", "Pending codes",
                           "Seen once, not confirmed: "
                           + _describe_codes(pending, descriptions) + "."))
    if permanent and not stored:
        items.append(_item(
            "amber", "Permanent codes are still stored",
            _describe_codes(permanent, descriptions) + ". A scan tool cannot clear "
            "these: a confirmed fault is still held in permanent memory and its "
            "repair has not been verified. Ask the seller for the repair history "
            "and re-check after a drive."))
    # Stored codes together with permanent ones are already red above.

    incomplete = list(ready.get("incomplete") or [])
    if ready_err:
        incomplete, recent = [], False
    distance = ready.get("distance_since_clear")
    warmups = ready.get("warmups_since_clear")
    recent = (not ready_err) and (
        (distance is not None and distance < RECENT_CLEAR_KM)
        or (warmups is not None and warmups < RECENT_CLEAR_WARMUPS))
    names = ", ".join(_MONITOR_NAMES.get(m, m.replace("_", " ")) for m in incomplete)
    if incomplete and recent:
        items.append(_item(
            "red", "Monitors look recently cleared",
            f"Incomplete: {names}. "
            f"Distance since codes were cleared: {_km(distance)}. "
            f"Warm-ups since clear: {_num(warmups)}. "
            "A seller can turn the light off and still leave this pattern."))
    elif incomplete:
        items.append(_item("amber", "Some monitors are not complete",
                           names + ". Not enough on its own to call the codes cleared, "
                           "but an inspection may still refuse the car."))
    elif not ready_err:
        items.append(_item("green", "Readiness monitors are complete",
                           f"Distance since codes were cleared: {_km(distance)}. "
                           f"Warm-ups since clear: {_num(warmups)}."))

    items.append(_vin_item(vehicle, expect_vin))
    items.append(_charging(vehicle))
    note = _item("amber", "Odometer was not compared across modules",
                 "car-use does not yet compare odometer readings across modules. "
                 "Check the service history yourself.")
    note["note"] = True     # shown, but a known gap in car-use is not a fault in the car
    items.append(note)

    rank = {"red": 2, "amber": 1, "green": 0}
    worst = max((i for i in items if not i.get("note")), key=lambda item: rank[item["level"]])["level"]
    headlines = {
        "red": "Do not treat this car as clean on this scan.",
        "amber": "No red flag in this scan, but something needs attention.",
    }
    scenario = getattr(vehicle, "scenario", None)
    return {
        "verdict": worst,
        "headline": headlines.get(worst, headlines["amber"]),
        "vin": (vehicle.vin or "").strip().upper(),
        "scanned_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "simulated": scenario.title if scenario is not None else None,
        "items": items,
        "note": "This is an OBD scan, not a mechanical inspection and not an emissions certificate.",
    }


def render_markdown(report: dict) -> str:
    lines = [f"# Used-car scan: {report['headline']}", "", _provenance(report), "",
             report["note"], ""]
    for level in ("red", "amber", "green"):
        group = [item for item in report["items"] if item["level"] == level]
        if not group:
            continue
        lines.append(f"## {level.capitalize()}")
        lines.append("")
        for item in group:
            lines.append(f"- **{item['title']}.** {item['detail']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_html(report: dict) -> str:
    colors = {"red": "#9b1c1c", "amber": "#8a5a00", "green": "#1b6b3a"}
    parts = [
        "<!DOCTYPE html>",
        "<html lang=\"en\">",
        "<head>",
        "<meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        f"<title>{html.escape(report['headline'])}</title>",
        "</head>",
        "<body style=\"font-family: Georgia, serif; max-width: 40rem; margin: 2rem auto; color: #222\">",
        f"<h1>{html.escape(report['headline'])}</h1>",
        f"<p>{html.escape(_provenance(report))}</p>",
        f"<p>{html.escape(report['note'])}</p>",
    ]
    for level in ("red", "amber", "green"):
        for item in [i for i in report["items"] if i["level"] == level]:
            color = colors[item["level"]]
            parts.append(
                f"<h2 style=\"color: {color}\">{html.escape(item['level'])}: "
                f"{html.escape(item['title'])}</h2>"
                f"<p>{html.escape(item['detail'])}</p>"
            )
    parts.append("</body>")
    parts.append("</html>")
    return "\n".join(parts) + "\n"


def _vin_item(vehicle, expect_vin: str | None) -> dict:
    # The VIN already cached at connect time; never re-read here, so an
    # unreadable VIN cannot abort the rest of the report.
    car_vin = (vehicle.vin or "").strip().upper()
    typed = (expect_vin or "").strip().upper()
    if not vin_decode(car_vin).get("valid_format"):
        return _item("amber", "VIN could not be read",
                     "The car did not report a usable VIN, so it was not compared. "
                     "Compare the VIN on the windshield with the paperwork yourself.")
    if not typed:
        return _item("amber", "VIN was not compared",
                     f"The car reports {car_vin}. "
                     "Type the VIN from the windshield with --expect-vin and run this again.")
    if not vin_decode(typed).get("valid_format"):
        return _item("amber", "The VIN you typed is not usable",
                     f"{typed} is not a valid 17-character VIN, so it was not compared. "
                     "Check it against the windshield and run this again.")
    if typed != car_vin:
        return _item("red", "VIN does not match",
                     f"You typed {typed}. The car reports {car_vin}.")
    detail = car_vin
    info = vin_decode(car_vin)
    maker, year = info.get("manufacturer") or "", info.get("model_year")
    if year and not maker.startswith("unknown"):
        detail += f" ({maker}, {year})"
    elif year:
        detail += f" ({year})"
    return _item("green", "VIN matches what you typed", detail)


def _charging(vehicle) -> dict:
    try:
        volts = vehicle.read("battery").value
        rpm = vehicle.read("rpm").value
    except (TransportError, ElmError, OSError) as e:
        return _item("amber", "Charging voltage was not read", str(e))
    if volts is None:
        return _item("amber", "Battery voltage was not reported",
                     "This car did not answer the 12 V PID, so charging was not checked.")
    if rpm is None:
        return _item("amber", "Engine state is unknown, so charging was not checked",
                     f"Battery reads {_volts(volts)} but the engine speed was not reported. "
                     "Start the engine and scan again to see the alternator.")
    if rpm > 400:
        at = f"with the engine running at {_rpm(rpm)}"
        if volts < 13.2:
            return _item("amber", "Charging voltage reads low",
                         f"{_volts(volts)} {at}. Some cars regulate charging down to "
                         "about 12.6 V in fuel-economy mode, so one reading cannot "
                         "diagnose the alternator. Have the charging system tested "
                         "if it stays low.")
        if volts > 15.2:
            return _item("amber", "Charging voltage reads high",
                         f"{_volts(volts)} {at}. Some regulated systems charge up to "
                         "about 15.5 V, so one reading cannot diagnose the alternator. "
                         "Have the charging system tested if it stays high.")
        return _item("green", "Charging voltage looks normal",
                     f"{_volts(volts)} at {_rpm(rpm)}.")
    return _item("amber", "Engine was not running, so charging was not checked",
                 f"Battery reads {_volts(volts)}. Start the engine and scan again to see the alternator.")


def _describe_codes(codes: list[str], descriptions: dict) -> str:
    parts = []
    for code in codes:
        desc = (descriptions or {}).get(code)
        parts.append(f"{code} ({desc})" if desc else code)
    return ", ".join(parts)


def _provenance(report: dict) -> str:
    when = report.get("scanned_at") or "an unknown time"
    sim = report.get("simulated")
    src = f"simulated car: {sim}" if sim else "live car"
    return f"Scanned {when} ({src})."


def _km(distance) -> str:
    if distance is None:
        return "not reported"
    return f"{distance:g} km" if isinstance(distance, float) else f"{distance} km"


def _num(value) -> str:
    if value is None:
        return "not reported"
    return f"{value:g}" if isinstance(value, float) else str(value)


def _volts(volts: float) -> str:
    return f"{volts:.1f} V"


def _rpm(rpm: float) -> str:
    return f"{rpm:.0f} rpm"


def _item(level: str, title: str, detail: str) -> dict:
    return {"level": level, "title": title, "detail": detail}
