"""Offline VIN decoding: check digit, model year, manufacturer (WMI).

The check digit (position 9) is mandatory in North America and optional
elsewhere (many Indian and European VINs don't use it), so a mismatch is
reported, not raised. A garbled VIN from a clone adapter's multi-frame
handling usually fails here first.
"""
from __future__ import annotations

_TRANSLIT = {**{str(d): d for d in range(10)},
             **dict(zip("ABCDEFGH", range(1, 9))), **dict(zip("JKLMN", range(1, 6))),
             "P": 7, "R": 9, **dict(zip("STUVWXYZ", range(2, 10)))}
_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)
_YEARS = "ABCDEFGHJKLMNPRSTVWXY123456789"   # 1980.. / 2010.. cycle

WMI = {
    "1HG": "Honda (USA)", "2HG": "Honda (Canada)", "JHM": "Honda (Japan)",
    "1FA": "Ford (USA)", "1FT": "Ford trucks (USA)", "3FA": "Ford (Mexico)",
    "1G1": "Chevrolet (USA)", "1GC": "Chevrolet trucks (USA)", "2T1": "Toyota (Canada)",
    "4T1": "Toyota (USA)", "JTD": "Toyota (Japan)", "5YJ": "Tesla (USA)", "7SA": "Tesla (USA)",
    "LRW": "Tesla (China)", "WVW": "Volkswagen (Germany)", "WBA": "BMW (Germany)",
    "WDD": "Mercedes-Benz (Germany)", "KMH": "Hyundai (Korea)", "KNA": "Kia (Korea)",
    "5NP": "Hyundai (USA)", "MA3": "Maruti Suzuki (India)", "MAL": "Hyundai (India)",
    "MAT": "Tata Motors (India)", "MA1": "Mahindra (India)", "MZB": "Kia (India)",
    "MBH": "Suzuki/Maruti (India)", "MBJ": "Toyota Kirloskar (India)", "MEE": "Renault (India)",
    "ME4": "Honda Motorcycle & Scooter (India)", "MD2": "Bajaj Auto (India)",
    "MD6": "TVS Motor (India)", "MBL": "Hero MotoCorp (India)",
}


def check_digit(vin: str) -> str:
    total = sum(_TRANSLIT[c] * w for c, w in zip(vin, _WEIGHTS))
    r = total % 11
    return "X" if r == 10 else str(r)


def decode(vin: str) -> dict:
    vin = vin.strip().upper()
    out: dict = {"vin": vin, "valid_format": False}
    if len(vin) != 17 or any(c not in _TRANSLIT for c in vin):
        out["problem"] = ("VIN must be 17 characters without I, O or Q; got "
                          f"{len(vin)} characters. A garbled VIN often means the adapter "
                          "mishandled a multi-frame reply.")
        return out
    out["valid_format"] = True
    expected = check_digit(vin)
    out["check_digit_ok"] = vin[8] == expected
    if not out["check_digit_ok"]:
        out["check_digit_note"] = (f"position 9 is {vin[8]!r}, computed {expected!r}. Required in "
                                   "North America; optional in many other markets.")
    out["wmi"] = vin[:3]
    out["manufacturer"] = WMI.get(vin[:3]) or WMI.get(vin[:2] + "?") or "unknown (add to WMI table)"
    region = vin[0]
    out["region"] = ("North America" if region in "12345" else "Asia" if region in "JKLMNPR"
                     else "Europe" if region in "STUVWXYZ" else "other")
    y = vin[9]
    if y in _YEARS:
        idx = _YEARS.index(y)
        # Position 7 numeric -> 1980-2009 cycle, letter -> 2010-2039 (North American rule).
        base = 1980 if vin[6].isdigit() else 2010
        out["model_year"] = base + idx
    out["plant"] = vin[10]
    out["serial"] = vin[11:]
    return out
