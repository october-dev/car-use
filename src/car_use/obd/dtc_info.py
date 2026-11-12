"""Short SAE-generic descriptions for common powertrain codes.

Manufacturer-specific codes (P1xxx, P3xxx, U1xxx...) belong in vehicle packs.
"""

GENERIC = {
    "P0100": "Mass or volume air flow circuit malfunction",
    "P0101": "Mass air flow circuit range/performance",
    "P0113": "Intake air temperature sensor 1 circuit high",
    "P0117": "Engine coolant temperature circuit low",
    "P0118": "Engine coolant temperature circuit high",
    "P0128": "Coolant thermostat (coolant below thermostat regulating temperature)",
    "P0130": "O2 sensor circuit, bank 1 sensor 1",
    "P0133": "O2 sensor circuit slow response, bank 1 sensor 1",
    "P0135": "O2 sensor heater circuit, bank 1 sensor 1",
    "P0141": "O2 sensor heater circuit, bank 1 sensor 2",
    "P0171": "System too lean, bank 1",
    "P0172": "System too rich, bank 1",
    "P0174": "System too lean, bank 2",
    "P0175": "System too rich, bank 2",
    "P0300": "Random/multiple cylinder misfire detected",
    "P0301": "Cylinder 1 misfire detected",
    "P0302": "Cylinder 2 misfire detected",
    "P0303": "Cylinder 3 misfire detected",
    "P0304": "Cylinder 4 misfire detected",
    "P0325": "Knock sensor 1 circuit, bank 1",
    "P0335": "Crankshaft position sensor A circuit",
    "P0340": "Camshaft position sensor A circuit, bank 1",
    "P0401": "EGR flow insufficient",
    "P0420": "Catalyst system efficiency below threshold, bank 1",
    "P0430": "Catalyst system efficiency below threshold, bank 2",
    "P0440": "Evaporative emission system malfunction",
    "P0442": "Evaporative emission system leak detected (small leak)",
    "P0455": "Evaporative emission system leak detected (large leak)",
    "P0457": "Evaporative emission system leak detected (fuel cap loose or off)",
    "P0456": "Evaporative emission system leak detected (very small leak)",
    "P0500": "Vehicle speed sensor A",
    "P0505": "Idle air control system",
    "P0562": "System voltage low",
    "P0563": "System voltage high",
    "P0700": "Transmission control system (MIL request)",
    "P0715": "Input/turbine speed sensor A circuit",
    "U0100": "Lost communication with ECM/PCM A",
    "U0121": "Lost communication with ABS control module",
}


def describe(code: str) -> str:
    code = code.upper()
    if code in GENERIC:
        return GENERIC[code]
    if len(code) == 5 and code[1] in "13":
        return "Manufacturer-specific code (needs a vehicle pack)"
    return "No generic description (look up for this make)"
