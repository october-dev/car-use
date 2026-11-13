# When doctor fails

Run `car-use doctor`. Quote the line it prints. The phrases below are copied from the program. Tests check that selected message fragments remain in this table and in the source.

| What doctor or a diagnostic script says | What is going on | What to do |
| --- | --- | --- |
| `No car configured` | No device URL is saved, and you did not pass `--sim` or `--device`. | `car-use config set device tcp://192.168.0.10:35000` for Wi-Fi, or a `serial:` URL (see [usb.md](usb.md)). Or practise on `car-use --sim p0420`. |
| `Cannot reach adapter at` and `Wi-Fi dongles need this computer joined to the dongle's own network` | The TCP address did not open. For a 192.168 address, car-use adds the Wi-Fi hint. | Join the adapter's Wi-Fi (`WiFi_OBDII` or `V-LINK` are the names the hint gives). Ignition on. Then try `192.168.0.10` and `192.168.1.10`, port 35000. |
| `Timed out after` / `waiting for adapter prompt` | The port opened, or the socket is up, but no ELM `>` prompt came back. | For serial adapters, try the other baud rate (38400, then 115200). Reseat the plug. Confirm the ignition is on. |
| `Adapter connection lost` or `Adapter closed the connection` | The connection to the adapter (Wi-Fi or USB) dropped mid-command. | Unplug it, plug it back, ignition on, run doctor once more. |
| `Serial adapters need pyserial` | The USB extra is not installed. | `uv tool install "car-use[serial] @ git+https://github.com/october-dev/car-use"` |
| `Cannot open` | The serial device path does not exist, is busy, or your user lacks permission. | Re-list `/dev/cu.*`, `/dev/ttyUSB*`, or the COM port. Close any other OBD app. For Linux permissions, see [usb.md](usb.md). |
| `BLE adapters are not supported yet` | The URL starts with `ble://`. | Use Wi-Fi or USB. See [bluetooth.md](bluetooth.md). |
| `Unknown device URL` | The URL is not `tcp://`, `serial:`, a `/dev/` path, a `COM` port, or `sim:`. | Fix the URL. The error names the forms car-use accepts. |
| `adapter answers but the car does not. Turn the ignition on` | The adapter has power and talks, but no ECU protocol was found. | Turn the ignition on. Engine running is best. Reseat the plug. Run doctor again. |
| `is the ignition on?` | A script or dongle-doctor received `UNABLE TO CONNECT`. The ordinary doctor uses the preceding ignition status when no protocol is found. | Same as above: ignition on, plug seated. |
| `status: ready` | Doctor completed its setup checks and printed the supported-signal count. | Go on to `dtcs()` and `readiness()`. |

One retry after the person has done the thing the line asks for. Do not loop.
