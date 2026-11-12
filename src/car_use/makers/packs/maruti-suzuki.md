+++
make = "Maruti Suzuki"
aliases = ["maruti", "suzuki"]
wmi = ["MA3", "MBH"]
updated = "2026-11-12"
+++
# Maruti Suzuki (India)

## Talking to the car
- India's largest car maker. BS-VI cars (sold from April 2020) support OBD-II over CAN for engine data. [common]
- Older BS-IV cars vary: some answer generic OBD-II, some only partly, some only through Suzuki's own tool. Try `car-use doctor`; if the adapter connects but the car doesn't answer, say so plainly rather than guessing. [unverified]
- Many Maruti petrol cars also come in factory CNG versions. Generic OBD does not show which fuel the engine is running on at the moment. [unverified]

## Mode 22 / UDS identifiers
None yet. Add one only with a capture from a real car.
