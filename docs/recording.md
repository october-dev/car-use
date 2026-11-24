# Record a drive

`car-use record` logs what the car reports while you drive, with a timestamp on every row, so it can be lined up with a dashcam afterwards.

```bash
car-use record --label car-3                                  # standard OBD: speed, rpm, throttle, load...
car-use record --can-ids 025,1A0 --label car-3                # the CAN messages can-check found
car-use record --pids speed,rpm --can-ids 025,1A0 --minutes 45
car-use record --sim open-bus --can --seconds 30              # try it on a virtual car
```

It runs until the time is up, you press Ctrl-C, or the ignition goes off and the adapter stops answering. Every row is written to disk as it arrives, so a power cut loses at most the last second.

## What you get

A folder under `~/.car-use/recordings/` named after the UTC start time (or `--out DIR`):

| file | contents |
| --- | --- |
| `meta.json` | car-use version, adapter, protocol, WMI and model year (never the full VIN), your label, which signals and ids, rates achieved, and how it ended |
| `obd.csv` | `t_unix, t_since_start`, then one column per signal. Units are in `meta.json`. |
| `can.csv` | `t_unix, t_since_start, burst, id, data` (data as hex). Frames in one burst are back to back; between bursts the adapter was restarting. |

`t_unix` is this computer's clock in UTC seconds when the reply arrived. `t_since_start` is a monotonic clock, so it never jumps.

## How fast

It depends on the adapter. `meta.json` reports what you actually got.

- **Standard OBD.** Each question is a round trip. A cheap clone manages about 15 questions a second in total, shared across the signals you chose. car-use asks for up to six in one request when the car allows it. A good OBDLink is several times faster.
- **Listening to the whole bus.** A busy bus sends hundreds to a few thousand frames a second. An ELM327 overflows within a fraction of a second, so `can.csv` holds samples, and `can_buffer_full` in `meta.json` counts the overflows. An OBDLink keeps up far longer.
- **Listening to chosen ids** (`--can-ids`). The adapter filters in hardware, so even a slow one can keep up with two or three messages at their full rate. This is the setting to use for steering and brake once `can-check --find` has found them.
- **Both at once.** One adapter either asks or listens, not both. With `--pids` and `--can`, car-use alternates in short slices, which slows both.

## Lining it up with a dashcam

1. **One clock.** Set the dashcam to GPS time, and sync the computer running car-use to GPS or NTP before each drive. Wi-Fi and USB adapters add tens of milliseconds of delay on top.
2. **A sync mark.** Start each drive with one firm brake from walking pace. It shows in the video, as a drop in `speed`, and in the brake message if you recorded it. Line those up and the offset between the files is known.
3. **Check it.** Plot `speed` against the dashcam's GPS speed for the first minute. They should overlap.

## Listen-only, J1939 and signing

- Recording CAN without `--pids` is listen-only by default: car-use sends nothing to the car. What that means and which adapters enforce it: [port-check.md](port-check.md#listen-only-mode).
- `--decode j1939` decodes trucks and machines: see [j1939.md](j1939.md).
- `--sign` hash-chains the files as they're written and signs a manifest, so `car-use verify` can tell later whether anything changed: see [signed-recordings.md](signed-recordings.md).

## Privacy and consent

- `meta.json` keeps the WMI and model year, never the full VIN. `--label` is free text; don't put the VIN, a name or a number plate in it.
- car-use records the car, not people. A dashcam does record people. If you plan to share or sell footage, blur faces and number plates, keep cameras road-facing (no cabin camera or audio), and get written consent from every driver. The law on recording and selling footage differs by country.
- Nobody touches the laptop or phone while the car is moving. Set the recording up before you set off.

## A pilot rig

- A CAN logger with its own GPS and IMU (CSS Electronics CANedge, for example) records the whole bus at full rate onto an SD card, timestamped against GPS. That's the dependable option for a fleet. Use `can-check` first to learn which cars are worth fitting.
- With car-use, an OBDLink adapter and a small computer powered from the car (a Raspberry Pi, or an old laptop) running `car-use record --can-ids ...` is enough for a first look.
