# Changelog

The version is `car_use.__version__` in `src/car_use/__init__.py`. Pushing a tag `vX.Y.Z` that matches it publishes that version to PyPI.

## Unreleased

- CAN maps from opendbc: 20 DBC files bundled (MIT) with a zero-dependency reader that matches opendbc's own decoding. `can-check` names the car's layout and each signal it finds; `record --decode DBC` writes `signals.csv` (steering angle, brake, speed, indicators in real units); `car-use dbc list|show|decode`; `can_layout()` and `decode()` helpers; `[[bus.messages]]` in scenarios and the `hyundai-bus` virtual car.
- Motion control (tier T4, off by default): steering, gas and brake through opendbc and a comma panda. `car-use control enable` needs a person at a terminal, the car's VIN and a typed acknowledgement; each session asks again. A 100 Hz loop with a 0.3 s dead-man, disarm on any driver input, a gas speed cap (`control_max_kph`) and audit logging. `control()` helper, `car-use control check|enable|disable|demo`, and a practice car (`--sim`).
- `car-use can-check`: listens to the CAN bus on the OBD port without sending anything, and says whether the car's own traffic reaches it (open, partial, hidden). `--find steering,brake,indicator` guides the person through each and lists the message bytes that moved. `--report` prints anonymised JSON for a Port report.
- `car-use record`: logs OBD readings and CAN frames to CSV with UTC timestamps, for lining up with a dashcam.
- `listen()` helper, the `open-bus` virtual car, and monitor mode (ATMA) with id filters and BUFFER FULL in the simulator.

## 0.0.1

- OBD-II harness, virtual cars, adapter grading, and the safety kernel.
- Install with `uv tool install car-use` after this version is on PyPI.
