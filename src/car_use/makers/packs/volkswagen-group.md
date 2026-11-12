+++
make = "Volkswagen"
aliases = ["vw", "audi", "skoda", "seat", "cupra", "porsche"]
wmi = ["WVW", "WVG", "WV1", "WV2", "WAU", "WA1", "TMB", "VSS", "WP0", "WP1", "3VW", "1VW", "MEX"]
updated = "2026-11-12"
+++
# Volkswagen Group (VW, Audi, Skoda, SEAT, Cupra, Porsche)

## Talking to the car
- Generic OBD-II on US models from 1996; CAN on all US models from 2008. EU petrol cars from 2001, diesels from 2004. [common]
- Dealer tool: ODIS. Enthusiasts use VCDS (Ross-Tech, https://www.ross-tech.com) or OBDeleven for maker-specific modules and coding. car-use does not code, and refuses coding requests. [common]
- Newer cars (around 2020 and later, MQB-evo and up) put a security gateway in front of most modules. Generic emissions data still works; deeper access needs an online login with the maker. [common]

## Mode 22 / UDS identifiers
None yet. Add one only with a capture from a real car.
