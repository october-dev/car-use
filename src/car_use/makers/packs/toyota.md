+++
make = "Toyota"
aliases = ["lexus", "toyota kirloskar"]
wmi = ["4T1", "4T3", "4T4", "2T1", "2T3", "5TD", "5TF", "5YF", "JTD", "JTE", "JTH", "JTJ", "JTK", "JTM", "JTN", "MBJ"]
updated = "2026-11-12"
+++
# Toyota / Lexus

## Talking to the car
- Generic OBD-II on US models from 1996; CAN (ISO 15765, protocol 6) on all US models from 2008, when CAN became mandatory for OBD-II in the US. [common]
- Dealer tool: Techstream, used with a J2534 pass-through cable. Maker-specific data (hybrid battery, ABS, airbag) needs Toyota's own requests, which car-use does not ship yet. [common]
- India: Toyota Kirloskar Motor, VIN prefix MBJ. Indian models with BS-VI (from April 2020) support OBD-II. [common]

## Known patterns
- 2AZ-FE (2.4 L, around 2007-2009 Camry/RAV4/Corolla-family) can burn oil, which over time damages the catalytic converter. A P0420 on one of these: ask about oil top-ups before blaming the converter alone. [common]
- Hybrids (Prius and others): many systems only report through Toyota-specific data, so generic OBD shows less than you'd expect. Missing data is normal, not a fault. [common]

## Mode 22 / UDS identifiers
None yet. Add one only with a capture from a real car (VIN prefix, model year, request, response).
