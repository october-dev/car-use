# Vehicle packs

A pack teaches car-use a manufacturer Mode 22 value that standard OBD does not have: state of charge, TPMS, a per-ECU odometer. Packs are TOML, like car-use's virtual cars. They are not Python, and reading them needs no extra package.

car-use loads `packs/*.toml` from this directory and `~/.car-use/packs/*.toml`. When the connected VIN matches, those names show up in `signals()` and `read("pack:<name>")`.

```toml
name = "example-counter"
description = "Synthetic example only. F190 is the standard VIN identifier; do not copy this DID onto a real car as a counter."

[match]
wmi = ["ZZZ"]          # first three characters of the VIN
year_from = 2010       # inclusive, optional
year_to = 2019

[[dids]]
ecu = "7E0"            # physical request header (ATSH). Restored to 7DF afterwards.
id = "F190"            # quoted four hex digits
name = "pack_counter"
formula = "A * 256 + B"   # A is the first data byte after 62 DID
unit = "count"
vss = "Vehicle.Demo.Counter"
description = "Two-byte counter."
```

The formula may use `A` through `Z` (response bytes), numbers, `+ - * /`, and parentheses. Nothing else. A pack cannot import code.

## What this loader supports

- Mode 22 only, one request header per reading. The `ecu` value is the request header (e.g. `7E0`), three hex digits up to `7FF`; the replying ECU's response ID (e.g. `7E8`) is a different number.
- 11-bit CAN protocols 6 and 8 only. Other protocols refuse a pack read before anything is sent.
- Formulas cover whole bytes A-Z with arithmetic. There is no bit extraction, no two's-complement decoding, and no bytes past Z. A signal that needs those needs a loader extension first.
- A pack signal must not reuse a built-in name, VSS path, or PID spelling. An invalid file is skipped with a diagnostic; it never breaks ordinary reads.

## Recording a response

On a car you are allowed to talk to, with the ignition on:

```bash
car-use <<'PY'
print(vin_info())
print([p.hex(" ").upper() for p in car().elm.query_targeted("7E0", "22F190")])
PY
```

`query_targeted` sends the request to that physical header and restores functional addressing afterwards. Save the VIN's WMI and model year, the ECU header you used, the request, and the raw response. That recording is the test. Do not guess a DID from a forum post and present it as measured.

## Contributing

1. Put the pack in `packs/<platform>.toml`.
2. Put the recorded response in `tests/fixtures/mode22/<platform>.json` and a test that `decode_payload` returns the value you measured.
3. Open a pull request. An agent may draft the pack in the workspace from a recording the person made. It may not invent the byte formula.

Hyundai/Kia, Toyota hybrid, and a US-domestic pack are not in the tree yet. They need a recording from one of those cars. A synthetic fixture used by the loader tests is not one of those packs.

## Vehicle packs and maker packs

Vehicle packs (this folder) are data car-use reads from the car. Maker packs (`src/car_use/makers/packs/`, `maker_info()`) are notes for the agent about a maker: tools, protocols, known problems. When a maker pack says "Mode 22 identifiers: none yet", a vehicle pack is where they go.
