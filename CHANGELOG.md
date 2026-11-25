# Changelog

The version is `car_use.__version__` in `src/car_use/__init__.py`. Pushing a tag `vX.Y.Z` that matches it publishes that version to PyPI.

## Unreleased

- J1939 for trucks and machines: `can/j1939.py` parses 29-bit ids (priority, PGN, destination, source), decodes nine standard SPNs (190 engine speed, 110 coolant, 100 oil pressure, 247 engine hours, 96 fuel level, 183 fuel rate, 84 vehicle speed, 168 battery, 171 ambient) and treats "error"/"not available" as missing. It also decodes DM1 active faults with lamps, including multi-packet DM1 over BAM transport. `can-check` names a J1939 bus, `record --decode j1939` writes `signals.csv` and `faults.csv`, `dbc decode --dbc j1939` works on old recordings, and there is a `j1939()` helper. `--j1939`/`--protocol` and the `protocol` setting pick ELM327 protocol A. Tested against the simulator only, not on real heavy equipment.
- The `crane-j1939` virtual machine: a truck-mounted crane broadcasting those PGNs at J1939 rates, with a BAM DM1. Scenarios gain `[[bus.j1939]]` and `[[bus.dm1]]`.
- Listen-only mode, on by default for J1939 sessions and opt-in (`--listen-only`) for cars. There is no protocol search, no VIN request and no rpm check, and every command that could transmit is refused (`ListenOnlyError`). car-use asks the adapter for silent monitoring (ELM327 `AT CSM1`, STN `STCMM 0`) and reports whether it accepted. The audit log records each session's mode. `--listen-only`/`--no-listen-only`, `car-use --listen-only` for scripts, and `[can] listen_only` in `policy.toml`. Car `can-check` and `record` behave as before unless you pass `--listen-only`.
- Signed recordings: `record --sign [--asset ID]` hash-chains each chunk of each file and signs a manifest with a per-install Ed25519 key (`~/.car-use/keys`, 0600). `car-use verify FOLDER` reports intact or tampered and names the file and chunk. `car-use key` shows the public key. It is a software key, not a secure element. It needs the optional `car-use[sign]` extra (`cryptography`).

- CAN maps from opendbc: 20 DBC files bundled (MIT) with a zero-dependency reader that matches opendbc's own decoding. `can-check` names the car's layout and each signal it finds; `record --decode DBC` writes `signals.csv` (steering angle, brake, speed, indicators in real units); `car-use dbc list|show|decode`; `can_layout()` and `decode()` helpers; `[[bus.messages]]` in scenarios and the `hyundai-bus` virtual car.
- Motion control (tier T4, off by default): steering, gas and brake through opendbc and a comma panda. `car-use control enable` needs a person at a terminal, the car's VIN and a typed acknowledgement; each session asks again. A 100 Hz loop with a 0.3 s dead-man, disarm on any driver input, a gas speed cap (`control_max_kph`) and audit logging. `control()` helper, `car-use control check|enable|disable|demo`, and a practice car (`--sim`).
- `car-use can-check`: listens to the CAN bus on the OBD port without sending anything, and says whether the car's own traffic reaches it (open, partial, hidden). `--find steering,brake,indicator` guides the person through each and lists the message bytes that moved. `--report` prints anonymised JSON for a Port report.
- `car-use record`: logs OBD readings and CAN frames to CSV with UTC timestamps, for lining up with a dashcam.
- `listen()` helper, the `open-bus` virtual car, and monitor mode (ATMA) with id filters and BUFFER FULL in the simulator.

## 0.0.1

- OBD-II harness, virtual cars, adapter grading, and the safety kernel.
- Install with `uv tool install car-use` after this version is on PyPI.
