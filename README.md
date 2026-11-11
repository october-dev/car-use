<div align="center">
  <a href="https://github.com/october-dev/car-use">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
      <img src="assets/logo-light.svg" alt="car-use" width="560">
    </picture>
  </a>
  <br>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/tagline-dark.svg">
    <img src="assets/tagline-light.svg" alt="Let your agent use your car." width="520">
  </picture>
</div>

---

<p>
  <a href="#setup"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/button-setup-dark.svg"><img src="assets/button-setup-light.svg" height="40" align="top" alt="Setup"></picture></a>
  <a href="SKILL.md"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/button-skill-dark.svg"><img src="assets/button-skill-light.svg" height="40" align="top" alt="Skill"></picture></a>
  <a href="#try-it-without-a-car"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/button-sim-dark.svg"><img src="assets/button-sim-light.svg" height="40" align="top" alt="Virtual car"></picture></a>
  <a href="#try-it-without-a-car"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/callout-dark.svg"><img src="assets/callout-light.svg" height="40" align="top" alt="No car nearby? Diagnose a virtual one, no hardware needed."></picture></a>
</p>

---

Enable Claude Code, Codex, OpenClaw, Hermes, or any agent with a shell to read, diagnose and understand a real car through a $15 OBD-II adapter. No app on the car, no cloud account, no dependencies beyond Python.

> **Any car since 1996 (US) / 2001 (EU) / 2020 (India)** through a Wi-Fi or USB OBD-II adapter, clones included <br/>
> **A virtual car** with real faults to diagnose when there is no car nearby <br/>
> **Coming:** Bluetooth adapters, CAN sniffing, TunerStudio ECUs, carmaker APIs

```
  ● you: the check-engine light came on this morning
  │
  ● dtcs()          → P0420  Catalyst system efficiency below threshold, bank 1
  ● freeze_frame()  → set at 2210 rpm, 72 km/h, fuel trims normal
  ● watch(["o2_b1s1", "o2_b1s2"], seconds=10)
  │                 → downstream O2 switches 15×/10s, same as upstream
  │
  ● agent: the catalyst isn't storing oxygen. Fuel trims are normal, so
  │        this isn't a sensor or mixture problem upstream. Next check:
  │        an exhaust leak before the rear O2 sensor, then the converter.
  ✓ done
```

---

## Setup

Paste this into your agent:

```text
Install car-use with `uv tool install git+https://github.com/october-dev/car-use`, run `car-use skill` and follow it, then read https://github.com/october-dev/car-use/blob/main/onboarding.md and walk me through it.
```

The agent installs the CLI, learns the helpers from the skill, shows you a simulated diagnosis first, and then walks you through plugging in your adapter. Plugging in and turning the key are always your job.

### Try it without a car

```bash
uv tool install git+https://github.com/october-dev/car-use

car-use scenarios                 # virtual cars with real faults
car-use --sim p0420 <<'PY'
print(dtcs())
print(freeze_frame())
print(watch(["o2_b1s1", "o2_b1s2"], seconds=10))
PY
```

### Use your car

1. Plug an OBD-II adapter into the port under the dashboard and turn the ignition on.
2. Point car-use at it:

```bash
car-use config set device tcp://192.168.0.10:35000                       # Wi-Fi adapter (join its network first)
car-use config set device "serial:///dev/cu.usbserial-XXXX?baud=38400"   # USB adapter (needs car-use[serial])

car-use doctor          # is everything connected? names the one fix if not
car-use dongle-doctor   # what is this adapter really? graded A-D
```

## Usage

Agents (and you) pipe Python in. Helpers are pre-imported:

```bash
car-use <<'PY'
print(car().describe())          # VIN, adapter, protocol
print(vin_info())                # model year, manufacturer, check digit
print(dtcs())                    # stored / pending / permanent + descriptions
print(readiness())               # emissions monitors, distance since codes cleared
print(read_many(["rpm", "coolant", "ltft1", "battery"]))
PY
```

| Helper | What it returns |
| --- | --- |
| `car()` | The connected vehicle. `.describe()` gives a summary |
| `manifest()` | What this car + backend can observe and do, by altitude and tier |
| `signals(prefix)` | Live signals this car supports: alias, [VSS](https://covesa.github.io/vehicle_signal_specification/) path, unit |
| `read(name)` / `read_many(names)` | Readings by alias (`"rpm"`), VSS path (`"Vehicle.Speed"`) or PID (`"010C"`) |
| `watch(names, seconds, hz)` | A time series with min, max, mean, stdev and switch rate per signal |
| `dtcs()` | Trouble codes, generic descriptions, MIL state |
| `freeze_frame()` | The conditions the ECU saved when the code set |
| `readiness()` | Monitor status, and distance and warm-ups since codes were cleared |
| `vin_info()` | Offline VIN decode |
| `raw_obd("221E12")` | Read-only raw requests, for exploring manufacturer data |
| `clear_dtcs()` | Clears codes. Needs your permission (see [Safety](#safety)) |
| `dongle_doctor()` | Identifies the adapter, finds missing commands, measures throughput, grades it |

Signals use COVESA VSS names, so agents learn one vocabulary that will carry across adapters, CAN buses and carmaker APIs.

## Virtual cars

Each scenario behaves the way the real fault does on a real car, so an agent has to actually reason through it:

| Scenario | What's going on |
| --- | --- |
| `p0420` | Dead catalyst: the downstream O2 sensor mirrors the upstream one |
| `p0171` | Lean at idle, normal under load: a vacuum leak |
| `p0300` | Random misfire, unsteady idle, cylinder codes pending |
| `cleared-codes` | No codes, but monitors incomplete after 11 km. A seller cleared them |
| `dying-battery` | System voltage falling with the engine running: the charging system |
| `ignition-off` | The adapter has power but the car doesn't answer |
| `healthy` | A normal car, for comparison |

Scenarios also choose the adapter: a genuine ELM327, a typical clone (reports "v1.5", drops commands, slower), or an STN-based OBDLink. Run one as a network adapter with `car-use sim p0171 --port 35000` and point any OBD app at it.

Write your own as TOML in `~/.car-use/scenarios/`.

## Adapters

Most "ELM327" adapters sold online are clones of old firmware. They report versions that never existed and silently drop commands. car-use's driver is written for them, and `car-use dongle-doctor` tells you what you actually bought:

```
grade C · clone · basic reads work but slow or limited (15.7/s, 12 AT commands missing)
```

| Works today | Coming |
| --- | --- |
| Wi-Fi ELM327 / clones, USB ELM327, OBDLink (STN) over USB | Bluetooth LE adapters, CAN adapters (CANable, PCAN, panda), TunerStudio-protocol ECUs (Speeduino, rusEFI, MegaSquirt) |

Tip: don't leave a cheap adapter plugged into a parked car overnight. Many never sleep and drain the battery.

## Safety

A phone harness can send the wrong message. A car harness touches something with brakes. car-use is read-only by default, and anything else goes through a kernel that denies by default:

- **Raw requests are limited to read services.** Coding, actuation, security access and flashing are refused, whatever the agent sends.
- **Changing something needs you.** Clearing codes needs the owner to enable it per vehicle at a real terminal, and to confirm each time after being told what it costs. An agent can't enable it for you.
- **There's an audit trail.** Every decision is written to a hash-chained log. `car-use audit --verify` detects edits.
- **Hard lines:** no emissions defeats, odometer changes, immobiliser or key work, or control of a moving car.

## How it works

```
 agent ──► car-use <<'PY' … PY ──► helpers ──► kernel (policy, tiers, audit)
                                      │
                                      ▼
                   vehicle model (VSS signals, capabilities)
                                      │
               ┌──────────────┬───────┴───────┬────────────────┐
             OBD-II          sim          CAN (soon)     carmaker APIs (later)
          ELM327 / STN    virtual car
```

Each backend publishes a manifest of what it can observe and do. Actions are sorted by altitude:

| Altitude | Covers |
| --- | --- |
| A0 | Reading |
| A1 | Comfort and access |
| A2 | Setpoints |
| A3 | Missions, carried out by a carmaker's own certified driving system |
| A4 | Mobility services |

New interfaces (a carmaker API, a robotaxi platform) plug in as new backends, not a redesign.

## Roadmap

- [x] OBD-II reads, ELM327/STN driver, virtual cars, dongle doctor, kernel + audit
- [ ] Bluetooth LE adapters
- [ ] CAN sniffing with agent-assisted reverse engineering ("find the CAN ID for my door lock")
- [ ] Agent-built live dashboards
- [ ] TunerStudio-protocol ECUs, plus Haltech / Link / ECUMaster data streams
- [ ] Manufacturer data packs (Mode 22), always-on in-car logging, MCP server
- [ ] Carmaker APIs (Tesla, Smartcar, Home Assistant)

## Contributing

Issues and PRs welcome, especially:
- `dongle-doctor` reports from adapters you own;
- scenarios for faults you've diagnosed;
- manufacturer PIDs for your car.

```bash
git clone https://github.com/october-dev/car-use && cd car-use
uv sync && uv run pytest
```

## License

MIT © October
