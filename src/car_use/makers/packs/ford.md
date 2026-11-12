+++
make = "Ford"
aliases = ["lincoln"]
wmi = ["1FA", "1FB", "1FC", "1FD", "1FM", "1FT", "1LN", "2FA", "2FM", "3FA", "3FM", "MAJ"]
updated = "2026-11-12"
+++
# Ford / Lincoln

## Talking to the car
- Generic OBD-II on US models from 1996; CAN on all US models from 2008. [common]
- Dealer tools: IDS, replaced by FDRS. Enthusiasts use FORScan (https://forscan.org, Windows), which reads Ford-specific modules. [common]
- Many Fords have two CAN buses on the OBD port: high-speed (HS-CAN, engine) and medium-speed (MS-CAN, body). A plain ELM327 only sees HS-CAN. Reaching MS-CAN needs an adapter with an HS/MS switch, or an OBDLink. [common]

## Known patterns
- Clone ELM327 adapters are a frequent cause of "can't connect" on Fords when an app needs MS-CAN. Run `car-use dongle-doctor` first. [common]

## Mode 22 / UDS identifiers
None yet. Add one only with a capture from a real car.
