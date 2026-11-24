# Does your car's OBD port carry steering and brake?

Standard OBD answers questions: speed, rpm, throttle, coolant. It has no reading for steering angle, the brake pedal or the indicators. Those travel between the car's own computers on the CAN bus.

On many cars that traffic also reaches the OBD port, so an adapter can hear it just by listening. On others a **gateway** sits between the port and the rest of the car, and the port stays silent until a scan tool asks something. Nobody keeps a full list of which is which, so check your own car.

## Check a car in ten minutes

You need an adapter that can listen (monitor mode, `ATMA`). OBDLink adapters (STN chip) are best. Many cheap clones can't listen at all, and `can-check` will say so.

1. Park the car with the handbrake on and start the engine, outdoors or in a ventilated place.
2. Run:

```bash
car-use can-check
```

car-use sends nothing to the car while it listens. You get one of these:

| verdict | means |
| --- | --- |
| `open` | The car's own messages reach the port. Steering and brake are probably among them. |
| `partial` | Only a few message ids reach the port. Some gateways pass a handful through. |
| `hidden` | The port is silent until asked. A gateway is likely. Standard OBD still works. |
| `not_can` | An older protocol (ISO 9141, KWP2000, J1850). Nothing to hear. |
| `adapter_cannot_listen` | The adapter has no monitor mode. Try an OBDLink. |

If the port is `open` or `partial`, find where each signal lives:

```bash
car-use can-check --find steering,brake,indicator
```

It asks you to hold still for a few seconds, then to turn the wheel from lock to lock, press the brake three times, and switch the left indicator on. It compares each step against the still part and lists the message bytes that moved, best guess first:

```
steering: best guess first
  - id 025 bytes 0-1: 88 different values, steady while still
brake: best guess first
  - id 1A0 byte 2 bit 0x01: switched 3 times, steady while still
```

Run it twice. A lead that shows up both times is real. Rolling counters and checksums change all the time, so they never show up as leads.

Try it on a virtual car first: `car-use can-check --sim open-bus --find all`. `hyundai-bus` is the same idea with a real Hyundai / Kia layout. Every other virtual car keeps its port silent, like a car with a gateway.

### When a known map fits

car-use bundles 20 DBC maps from comma's [opendbc](https://github.com/commaai/opendbc) (`car-use dbc list`). If the ids it hears line up with one, `can-check` says so and names each lead:

```
layout: looks like Hyundai / Kia (CAN, most 2015+ models) (hyundai_can_generated): 8 of 8 ids heard are in that map.
steering: best guess first
  - id 2B0 bytes 0-2: 381 different values, steady while still = SAS11.SAS_Angle in the Hyundai / Kia map
```

Then `car-use record --decode hyundai_can_generated` writes steering angle, brake, speed and indicators in real units. `layout: a weak match` means only a few ids coincide: treat it as a coincidence until `--find` agrees. Most Indian-market models (Maruti Suzuki, Tata, Mahindra) have no published map, which is why Port reports matter.

### What "hidden" doesn't mean

A gateway still passes diagnostic questions. Steering angle can often be read from the ABS or ESP module with a maker-specific Mode 22 request, a few times a second instead of fifty. That needs the right identifier for each car, which is what [vehicle packs](../packs/README.md) hold. Tapping the network behind the gateway also works, but it means unplugging modules in the car. car-use doesn't do that.

### Notes

- A cheap ELM327 overflows on a busy bus (`BUFFER FULL`) and has to restart, so it hears a sample of the bus, not every frame. `can-check` says when that happened. Listening to a few chosen ids (`car-use record --can-ids 025,1A0`) lets even a slow adapter keep up.
- Cars without stability control (ESP) often have no steering angle sensor at all. Brake switch and wheel speeds are on almost every CAN car.
- Some makers put a second bus on other OBD pins (Ford's MS-CAN on pins 3 and 11). car-use listens on the standard CAN pins 6 and 14 only.
- Trucks and machines (J1939): `car-use can-check --j1939`. See [j1939.md](j1939.md).
- Only listen. Don't send random messages to a car's bus. A generic scan tool has been reported to upset a steering angle sensor.

## Listen-only mode

`can-check` and `record` without `--pids` are **listen-only by default**. In a listen-only session car-use puts nothing on the bus:

- No automatic protocol search and no VIN request, because both are OBD requests. The protocol is set by number instead: 6 (CAN 11-bit, 500 kbit/s, most cars since 2008) unless you pass `--protocol`, `--j1939`, or set `car-use config set protocol ...`. With the default, a car on another speed sounds `hidden`. The simulator knows each virtual car's bus and uses it.
- No rpm check, so `engine_running` is unknown. On a J1939 machine it comes from engine speed on the bus.
- Every command that could make the adapter transmit is refused before it reaches the adapter: OBD requests, `raw_obd`, `clear_dtcs`, `control()`, `ATSP0`, `AT CSM0`, `STCMM 1`. car-use only lets through a short list of adapter commands that can't transmit (reset, formatting, protocol by number, filters, silent monitoring on, voltage).
- The audit log records each session's mode (`car-use audit`): `listen-only` or `obd-requests`, and what the adapter confirmed.

`--no-listen-only` brings back the old behaviour (auto search, VIN, rpm check). These are read requests, so they are still tier T0. `record --pids` sends OBD requests by nature, so it isn't listen-only unless you ask, and `--listen-only --pids` is refused. Scripts can run with `car-use --listen-only <<'PY'`. To change the default, the owner sets `[can] listen_only = false` in `~/.car-use/policy.toml`.

### What enforces it, honestly

On every adapter car-use supports today, listen-only is enforced by car-use's software, and only partly by the adapter.

| adapter | what car-use asks for | what the hardware does |
| --- | --- | --- |
| OBDLink (STN11xx/STN21xx) | `STCMM 0` (receive only) and `AT CSM1` | Doesn't acknowledge frames while monitoring. It can still transmit when commanded; car-use refuses to command it. |
| Genuine ELM327 v1.4b or newer | `AT CSM1` (silent monitoring, the default) | Same: no acknowledgements while monitoring, normal node otherwise. |
| ELM327 clones | `AT CSM1`, often rejected | Many clones are always silent while monitoring, but car-use can't confirm it, so it reports "enforced by car-use only". |

On all three, the chip itself can transmit, and it acknowledges replies after any request. The only thing stopping it in a listen-only session is car-use refusing to send. That's software, so a modified copy of car-use, or another program using the adapter, could transmit.

Hardware that can't transmit at all:

- **comma panda** in its `SILENT` safety mode puts its CAN controller into bus-monitoring mode, so it sends no acknowledgements and no frames. car-use doesn't listen through a panda yet; it only uses one for motion control.
- **SocketCAN** interfaces (CANable, PCAN and similar on Linux) support `ip link set can0 type can bitrate 250000 listen-only on` where the driver does, which configures the controller itself. car-use doesn't support these adapters yet.
- **Listen-only transceivers and contactless (clamp) readers** make transmitting physically impossible. That is where a car-use device is headed; it isn't built.

Even with these, the host can usually switch the mode back. Only a transceiver with no transmit path is a real guarantee.

## What's known so far

From community reverse-engineering, not tested by car-use. Treat each row as a lead, not a fact.

| | makes | evidence |
| --- | --- | --- |
| likely open | older Suzuki (about 2000-2015) | A 2009 Swift Sport's port carried its own traffic. The owner thinks the ids apply to most Suzukis of that era. A European car; Indian Marutis are untested. |
| | older Honda | Steering angle ids for a 2011 Civic were shared from the OBD port. |
| | Nissan Leaf | Frame lists from the OBD port are shared. |
| | Toyota | Mixed. Steering angle heard on some; a 2006 Sienna showed none. |
| likely hidden | Volkswagen, Skoda, Audi | The port talks to the J533 gateway. A diagnostic firewall was added from model year 2020/21. |
| | Hyundai, Kia | On the models checked, the port carries diagnostics only. Newer ones also use CAN FD. |
| | BMW, Mercedes and other luxury cars | Several networks behind a gateway. |
| | many 2018+ platforms | A general pattern, not a list. |
| unknown | current Maruti, Tata, Mahindra, current Honda and Toyota in India | Nothing published. Toyota's Glanza and Rumion are rebadged Marutis and should behave like them. |

Sources: [Macchina forum](https://forum.macchina.cc/t/collecting-steering-wheel-angle-in-real-time/262), [2009 Swift Sport](https://dillonfletcher.co.uk/?p=205), [AutoPi community (Hyundai/Kia)](https://community.autopi.io/t/what-to-do-if-can-recorder-doesnt-return-anything/761), [openpilot VW J533 wiki](https://github.com/commaai/openpilot/wiki/VW-J533-%28Gateway%29-Cable), [Ross-Tech SFD](https://wiki.ross-tech.com/wiki/index.php/SFD), [comma CAN FD](https://comma.ai/shop/can-fd-panda-kit), [LotusTalk](https://www.lotustalk.com/threads/steering-angle-sensor-broken-by-generic-obdii-scan-tool-and-fixed.538557/).

## Share what you find

```bash
car-use can-check --find steering,brake,indicator --report --model "Swift VXi 2021 petrol"
```

prints JSON with the WMI (first three VIN characters), model year, the model in your words, the verdict, the message ids heard and the leads for each signal. It never includes the full VIN. Paste it into a [Port report](https://github.com/october-dev/car-use/issues/new?template=port-report.yml). Reports from the simulator (`"simulated": true`) are not listed.

| make | model (as reported) | year | verdict | steering | brake | indicator | adapter |
| --- | --- | --- | --- | --- | --- | --- | --- |
| _no reports yet_ | | | | | | | |
