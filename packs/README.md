# Vehicle packs

A pack teaches car-use a manufacturer Mode 22 value that standard OBD does not have: state of charge, TPMS, a per-ECU odometer. Packs are YAML. They are not Python.

car-use loads `packs/*.yaml` from this directory and `~/.car-use/packs/*.yaml`. When the connected VIN matches, those names show up in `signals()` and `read("pack:<name>")`.

```yaml
name: example-counter
description: Synthetic. Not a real manufacturer identifier. Do not copy the DID onto a real car.
match:
  wmi: ["ZZZ"]          # first three characters of the VIN
  year_from: 2010       # inclusive, optional
  year_to: 2019
dids:
  - ecu: "7E0"          # physical request header (ATSH). Restored to 7DF afterwards.
    id: "F190"
    name: pack_counter
    formula: "A * 256 + B"   # A is the first data byte after 62 DID
    unit: count
    vss: Vehicle.Demo.Counter
    description: Two-byte counter.
```

The formula may use `A` through `Z` (response bytes), numbers, `+ - * /`, and parentheses. Nothing else. A pack cannot import code.

## Recording a response

On a car you are allowed to talk to, with the ignition on:

```bash
car-use <<'PY'
print(vin_info())
print(raw_obd("22F190"))   # the DID you mean to document
PY
```

Save the VIN's WMI and model year, the ECU header you used, the request, and the raw response. That recording is the test. Do not guess a DID from a forum post and present it as measured.

## Contributing

1. Put the YAML in `packs/<platform>.yaml`.
2. Put the recorded response in `tests/fixtures/mode22/<platform>.json` and a test that `decode_payload` returns the value you measured.
3. Open a pull request. An agent may draft the YAML in the workspace from a recording the person made. It may not invent the byte formula.

Hyundai/Kia, Toyota hybrid, and a US-domestic pack are not in the tree yet. They need a recording from one of those cars. A synthetic fixture used by the loader tests is not one of those packs.
