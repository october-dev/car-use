<div align="center">
  <a href="https://car-use.dev">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/october-dev/car-use/main/assets/logo-dark.svg">
      <img src="https://raw.githubusercontent.com/october-dev/car-use/main/assets/logo-light.svg" alt="car-use" width="560">
    </picture>
  </a>
  <br>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/october-dev/car-use/main/assets/tagline-dark.svg">
    <img src="https://raw.githubusercontent.com/october-dev/car-use/main/assets/tagline-light.svg" alt="Let your agent use your car." width="520">
  </picture>
</div>

---

<p>
  <a href="https://car-use.dev"><picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/october-dev/car-use/main/assets/button-site-dark.svg"><img src="https://raw.githubusercontent.com/october-dev/car-use/main/assets/button-site-light.svg" height="40" align="top" alt="Website"></picture></a>
  <a href="#setup"><picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/october-dev/car-use/main/assets/button-setup-dark.svg"><img src="https://raw.githubusercontent.com/october-dev/car-use/main/assets/button-setup-light.svg" height="40" align="top" alt="Setup"></picture></a>
  <a href="https://github.com/october-dev/car-use/blob/main/SKILL.md"><picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/october-dev/car-use/main/assets/button-skill-dark.svg"><img src="https://raw.githubusercontent.com/october-dev/car-use/main/assets/button-skill-light.svg" height="40" align="top" alt="Skill"></picture></a>
  <a href="#no-car-use-a-virtual-one"><picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/october-dev/car-use/main/assets/button-sim-dark.svg"><img src="https://raw.githubusercontent.com/october-dev/car-use/main/assets/button-sim-light.svg" height="40" align="top" alt="Virtual car"></picture></a>
  <a href="#no-car-use-a-virtual-one"><picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/october-dev/car-use/main/assets/callout-dark.svg"><img src="https://raw.githubusercontent.com/october-dev/car-use/main/assets/callout-light.svg" height="40" align="top" alt="No car nearby? Diagnose a virtual one, no hardware needed."></picture></a>
</p>

<p align="center">
  <a href="https://github.com/october-dev/car-use/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/october-dev/car-use/actions/workflows/ci.yml/badge.svg"></a>
</p>

---

Your AI agent can read your car's error codes, check its sensors and tell you what's wrong. All you need is a $15 plug-in adapter. No car nearby? Use a virtual one.

Works with Claude Code, Codex, OpenClaw, Hermes and any AI agent that can run a command.

> **Cars:** any car since 1996 (US), 2001 (EU) or 2020 (India), with almost any OBD-II adapter <br/>
> **Motorsport:** race cars, karts, project cars and Formula Student cars <br/>
> **More than cars:** cranes, diggers, generators and trucks, in one chat <br/>
> **Car to car:** your cars talk to each other and sort things out <br/>
> **car-use Cloud:** give every car its own always-on AI brain ([early access](https://car-use.dev/#cloud))

## Check engine light? Ask your agent.

**You:** My check engine light came on this morning. What's wrong?

| The agent… | What it found |
| --- | --- |
| reads the error code · `dtcs()` | **P0420**: the catalytic converter isn't working well |
| checks when it happened · `freeze_frame()` | At 2,210 rpm and 72 km/h. The fuel mix was normal. |
| watches both oxygen sensors · `watch(o2)` | The rear one copies the front one. On a healthy car it stays steady. |

**Agent:** Most likely a worn-out catalytic converter. Have a mechanic check for an exhaust leak before the rear sensor first. If there isn't one, the converter needs replacing.

## Setup

Paste this into your agent:

```text
Install car-use with `uv tool install car-use`, run `car-use skill` and follow it, then read https://github.com/october-dev/car-use/blob/main/onboarding.md and walk me through it.
```

Your agent installs car-use, learns how to use it, shows you a practice diagnosis on a virtual car, then helps you plug in your adapter. You do the plugging in and turning the key. The agent does the rest.

### Use your car

1. Plug an OBD-II adapter into the port under the dashboard and turn the ignition on.
2. Tell car-use where the adapter is:

```bash
car-use config set device tcp://192.168.0.10:35000                       # Wi-Fi adapter (join its Wi-Fi first)
car-use config set device "serial:///dev/cu.usbserial-XXXX?baud=38400"   # USB adapter (needs car-use[serial])

car-use doctor          # is everything connected? tells you the one fix if not
car-use dongle-doctor   # what adapter did you actually buy? graded A to D
```

Longer notes for Wi-Fi, USB, Windows and Bluetooth, plus which adapters are worth buying: [setup/](setup/).

## No car? Use a virtual one.

Pretend cars with real problems to solve. Pick one and let your agent work out what's wrong:

```bash
uv tool install car-use
car-use --sim p0420 <<'PY'
print(dtcs())
print(watch(["o2_b1s1", "o2_b1s2"], seconds=10))
PY
```

| Car | What's wrong | Difficulty |
| --- | --- | --- |
| `p0420` | Worn-out catalytic converter. The rear oxygen sensor copies the front one. | Medium |
| `p0171` | Air leak. Fuel correction is high at idle and normal when driving. | Medium |
| `p0300` | Engine misfire. Shaky idle, two cylinders acting up. | Hard |
| `cleared-codes` | The seller cleared the codes. Looks clean, but the self-checks haven't finished. | Tricky |
| `dying-battery` | Battery not charging. Voltage keeps dropping while the engine runs. | Easy |
| `healthy` | Nothing wrong. Use it to see what normal looks like. | Easy |
| `ignition-off` | The adapter has power but the car doesn't answer. | Easy |
| `kwp2000` | Older car on KWP2000, not CAN. Several codes, slow to wake. | Medium |
| `iso9141` | Older car on ISO 9141-2. One code. | Medium |

Each virtual car can also pretend to be a different adapter: a genuine ELM327, a cheap clone, or an OBDLink. Run one as a Wi-Fi adapter with `car-use sim p0171 --port 35000` and point any OBD app at it. You can write your own in `~/.car-use/scenarios/`.

## How agents use it

Your agent sends short Python scripts. The helpers are already loaded:

```bash
car-use <<'PY'
print(car().describe())          # which car and adapter
print(vin_info())                # model year, maker
print(dtcs())                    # error codes, explained
print(readiness())               # the car's self-checks, and how long since codes were cleared
print(read_many(["rpm", "coolant", "ltft1", "battery"]))
PY
```

| Helper | What it gives you |
| --- | --- |
| `car()` | The connected car. `.describe()` gives a summary |
| `manifest()` | Everything this car can report and do |
| `signals()` | The live readings this car supports, with names and units |
| `read(name)` / `read_many(names)` | One or more readings, e.g. `"rpm"`, `"Vehicle.Speed"` |
| `watch(names, seconds)` | Readings over time, with min, max, average and how often they swing |
| `dtcs()` | Error codes in plain English, and whether the check engine light is on |
| `freeze_frame()` | What the car was doing when the code appeared |
| `readiness()` | The car's emissions self-checks, and distance since codes were cleared |
| `ready_for_inspection()` | Whether it would likely pass a US OBD inspection, and what to do if not |
| `vin_info()` | Decodes the VIN |
| `raw_obd("221E12")` | Read-only requests for maker-specific data |
| `clear_dtcs()` | Clears codes, only with your OK (see [Safety](#safe-by-default)) |
| `dongle_doctor()` | Tests your adapter and grades it |
| `maker_info()` | What to know about this car's maker: tools, protocols, known problems |
| `tune_ini(path)` / `engine_log(path)` | Reads your ECU's TunerStudio .ini and your engine logs |

Readings use standard [COVESA VSS](https://covesa.github.io/vehicle_signal_specification/) names, so your agent learns one set of names that works across adapters, cars and makers.

## What it works with

| | Today | Coming |
| --- | --- | --- |
| **Adapters** | Wi-Fi and USB ELM327 (clones too), OBDLink | Bluetooth adapters, CAN adapters (CANable, PCAN, comma panda) |
| **Cars** | OBD-II cars, petrol and diesel, CAN and older protocols | Maker-specific data packs, EV battery data, Tesla, Smartcar |
| **Motorsport** | Any car with an OBD port. TunerStudio .ini files and engine logs (.msl, CSV) | Live data from Speeduino, rusEFI and MegaSquirt ECUs, a virtual copy of your ECU to test changes on, lap coaching |
| **More than cars** | | Cranes, diggers, generators and trucks (J1939), GPS trackers, makers' fleet systems |
| **Agents** | Claude Code, Codex, any agent with a shell | MCP server, OpenClaw and Hermes plugins, [car to car](https://agentintercom.org) |

Most "ELM327" adapters sold online are cheap clones that pretend to be a newer version. car-use is built for them, and `car-use dongle-doctor` tells you what you really bought:

```
grade C · clone · basic reads work but slow or limited (15.7/s, 12 AT commands missing)
```

Tip: don't leave a cheap adapter plugged in overnight. Many never sleep and drain the battery.

## What's next

| | | |
| --- | --- | --- |
| **Read** | Error codes, sensors, history | Today |
| **Do small things** | Turn on the AC, lock the doors, clear codes. Only with your OK. | Today |
| **Change settings** | Send a destination, set a charge limit | Today |
| **Drive somewhere** | "Go pick me up," when car makers allow it | Future |
| **Book a ride** | Book a robotaxi for you or your family | Future |

Every part of car-use says what it can see and do. When a car maker or robotaxi company opens up an API, it plugs straight in.

## How good is your agent at fixing cars?

[CarsBench](bench/README.md) gives an agent 12 virtual cars with real faults and scores it. It checks whether it finds the cause, whether it actually looked at the right readings, and whether it stays safe when the owner asks it to "just clear the light". Any agent can take it, with or without car-use, so you can see what the harness adds.

```bash
git clone https://github.com/october-dev/car-use && cd car-use
car-use bench run --agent 'claude -p --allowedTools "Bash(car-use:*)"'
```

First results: Claude Haiku 5.5 passed 12/12 with car-use and 11/12 without it, taking about 5x longer and clearing an owner's codes by accident on one car. See the [CarsBench leaderboard](https://car-use.dev/carsbench) and [bench/](bench/README.md).

## Safe by default

car-use can only read your car unless you allow more. It can never touch the brakes, steering or anything risky.

- **Read-only to start.** It can look at your car's data but can't change anything. Coding, flashing and controlling parts are always refused.
- **You stay in control.** Nothing changes unless you switch it on yourself, at your own computer, and say yes each time. Your agent can't do that for you.
- **Everything is logged.** Every action goes into a log that can't be secretly edited. Check it with `car-use audit --verify`.
- **Never allowed.** Turning off emissions systems, changing the odometer, messing with keys, or driving the car.

## Roadmap

Built in the open. See the [Roadmap](https://github.com/october-dev/car-use/issues/23) for what's being worked on and what's next.

## Contributing

The most useful things right now:
- `dongle-doctor` reports from adapters you own;
- virtual cars for problems you've fixed;
- maker-specific data for your car.

```bash
git clone https://github.com/october-dev/car-use && cd car-use
uv sync && uv run pytest
```

## License

MIT © [October](https://github.com/october-dev) · [car-use.dev](https://car-use.dev)
