"""A used-car scan you can hand to a seller.

Red, amber, and green come from what the car actually answered. Missing
odometer data is said out loud. Nothing here is a mechanical inspection.
"""
from __future__ import annotations

import html


def build(vehicle, expect_vin: str | None = None) -> dict:
    codes = vehicle.dtcs()
    ready = vehicle.readiness()
    info = vehicle.vin_info()
    items: list[dict] = []

    stored = list(codes.get("stored") or [])
    pending = list(codes.get("pending") or [])
    permanent = list(codes.get("permanent") or [])
    if codes.get("mil_on") or stored:
        items.append(_item("red", "Check-engine light or confirmed codes",
                           "Stored: " + (", ".join(stored) or "none") +
                           f". Light commanded on: {bool(codes.get('mil_on'))}."))
    else:
        items.append(_item("green", "No confirmed codes",
                           "The check-engine light is not commanded on, and there are no stored codes."))
    if pending:
        items.append(_item("amber", "Pending codes",
                           "Seen once, not confirmed: " + ", ".join(pending) + "."))
    if permanent and not stored:
        items.append(_item("amber", "Permanent codes are still stored",
                           ", ".join(permanent) + ". A scan tool cannot clear these. "
                           "They usually mean a fault was confirmed and the monitor has not run since."))
    elif permanent:
        items.append(_item("red", "Permanent codes", ", ".join(permanent) + "."))

    incomplete = list(ready.get("incomplete") or [])
    distance = ready.get("distance_since_clear")
    warmups = ready.get("warmups_since_clear")
    recent = (distance is not None and distance < 80) or (warmups is not None and warmups < 5)
    if incomplete and recent:
        items.append(_item(
            "red", "Monitors look recently cleared",
            f"Incomplete: {', '.join(incomplete)}. "
            f"Distance since codes were cleared: {distance} km. "
            f"Warm-ups since clear: {warmups}. "
            "A seller can turn the light off and still leave this pattern."))
    elif incomplete:
        items.append(_item("amber", "Some monitors are not complete",
                           ", ".join(incomplete) + ". Not enough on its own to call the codes cleared, "
                           "but an inspection may still refuse the car."))
    else:
        items.append(_item("green", "Readiness monitors are complete",
                           f"Distance since codes were cleared: {distance} km. "
                           f"Warm-ups since clear: {warmups}."))

    car_vin = (info.get("vin") or vehicle.vin or "").strip().upper()
    typed = (expect_vin or "").strip().upper()
    if not typed:
        items.append(_item("amber", "VIN was not compared",
                           f"The car reports {car_vin or 'no VIN'}. "
                           "Type the VIN from the windshield with --expect-vin and run this again."))
    elif typed != car_vin:
        items.append(_item("red", "VIN does not match",
                           f"You typed {typed}. The car reports {car_vin or 'nothing'}."))
    else:
        items.append(_item("green", "VIN matches what you typed", car_vin))

    items.append(_charging(vehicle))
    items.append(_item(
        "amber", "Odometer was not compared across ECUs",
        "Standard OBD on this connection does not report a per-ECU odometer, "
        "so a cluster-versus-module mismatch could not be checked."))

    rank = {"red": 2, "amber": 1, "green": 0}
    worst = max(items, key=lambda item: rank[item["level"]])["level"]
    headlines = {
        "red": "Do not treat this car as clean on this scan.",
        "amber": "No red flag in this scan, but something could not be checked.",
        "green": "Nothing in this scan is a red flag.",
    }
    return {
        "verdict": worst,
        "headline": headlines[worst],
        "vin": car_vin,
        "items": items,
        "note": "This is an OBD scan, not a mechanical inspection and not an emissions certificate.",
    }


def render_markdown(report: dict) -> str:
    lines = [f"# Used-car scan: {report['headline']}", "", report["note"], ""]
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
        "<meta charset=\"utf-8\">",
        f"<title>{html.escape(report['headline'])}</title>",
        "<body style=\"font-family: Georgia, serif; max-width: 40rem; margin: 2rem auto; color: #222\">",
        f"<h1>{html.escape(report['headline'])}</h1>",
        f"<p>{html.escape(report['note'])}</p>",
    ]
    for item in report["items"]:
        color = colors[item["level"]]
        parts.append(
            f"<h2 style=\"color: {color}\">{html.escape(item['level'])}: {html.escape(item['title'])}</h2>"
            f"<p>{html.escape(item['detail'])}</p>"
        )
    parts.append("</body>")
    return "\n".join(parts) + "\n"


def _charging(vehicle) -> dict:
    try:
        volts = vehicle.read("battery").value
        rpm = vehicle.read("rpm").value
    except Exception as e:
        return _item("amber", "Charging voltage was not read", str(e))
    if volts is None:
        return _item("amber", "Battery voltage was not reported",
                     "This car did not answer the 12 V PID, so charging was not checked.")
    running = rpm is not None and rpm > 400
    if running and volts < 13.2:
        return _item("red", "Battery is not being charged",
                     f"{volts} V with the engine running. A healthy alternator holds about 13.8 to 14.6 V.")
    if running and volts > 15.2:
        return _item("red", "Charging voltage is high",
                     f"{volts} V. That is above a normal alternator.")
    if running:
        return _item("green", "Charging voltage looks normal", f"{volts} V at {rpm} rpm.")
    return _item("amber", "Engine was not running, so charging was not checked",
                 f"Battery reads {volts} V. Start the engine and scan again to see the alternator.")


def _item(level: str, title: str, detail: str) -> dict:
    return {"level": level, "title": title, "detail": detail}
