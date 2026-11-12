# Adapter compatibility

No field reports are in this repository yet. A row is added only from an anonymised `car-use dongle-doctor --report` pasted into an [Adapter report](https://github.com/october-dev/car-use/issues/new?template=adapter-report.yml) issue. Simulator output is not a field report and is not listed here.

| adapter | kind | grade | wmi | year | protocol | pids | vin multiframe | soak error rate | ignition-off mA |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| _no reports_ | | | | | | | | | |

## What a report contains

`car-use dongle-doctor --report` prints JSON and never includes the full VIN. It keeps:

- adapter identity, grade, and which AT commands in the fingerprint did not answer
- vehicle WMI (the first three VIN characters) and model year
- protocol, supported Mode 01 PID count, whether the multi-frame VIN read was well formed, and whether DTC modes 03, 07 and 0A answered (not the codes)
- soak error rate. The default soak is 600 seconds. Pass `--soak-seconds 0 --soak-requests N` for a short check.

## Ignition-off current

car-use does not measure current. `ATLP` is never sent, because it would put the adapter to sleep on a car someone still needs.

To fill `ignition_off_current_ma`, with the ignition off, read a meter in series with the adapter (a USB meter is enough on a USB adapter; on a Wi-Fi adapter, measure the OBD port supply). Pass that number as `--current-ma`. If you did not measure it, leave the flag off and the field stays null. Do not leave the adapter plugged in overnight to watch the battery.

## AT command fingerprint

`FINGERPRINT` in `car_use.doctor.dongle` is the set of AT commands clone firmware often drops. It has not been checked against a physical genuine ELM327 v2.x or an STN device. The report says `fingerprint_status: unvalidated`. A grade is a measurement of this session, not a claim about which firmware version that is. Field reports carry the missing-command list so the list can be corrected once those devices have been probed.
