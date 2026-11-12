+++
make = "BMW"
aliases = ["mini"]
wmi = ["WBA", "WBS", "WBY", "WMW", "5UX", "5YM", "4US"]
updated = "2026-11-12"
+++
# BMW / MINI

## Talking to the car
- Generic OBD-II emissions data works through any adapter. [common]
- Dealer tool: ISTA. From the F-series on (around 2008 and later), deep diagnostics use Ethernet over the OBD port (DoIP, with an "ENET" cable), not CAN. car-use does not support Ethernet diagnostics yet. [common]
- Enthusiast coding tools (BimmerCode and others) change settings. car-use never codes cars. [common]

## Mode 22 / UDS identifiers
None yet. Add one only with a capture from a real car.
