# USB adapters

USB adapters need the `serial` extra. Without it, doctor says `Serial adapters need pyserial`.

```bash
uv tool install 'car-use[serial]'
```

Plug the adapter in, turn the ignition on, then find the port and set it. The usual baud rate for an ELM327 clone is 38400. An OBDLink is often 115200. If the first baud rate times out, try the other.

## macOS

List callout devices, not the `tty.*` twins:

```bash
ls /dev/cu.*
```

A USB-serial adapter shows up as something like `/dev/cu.usbserial-A12345` or `/dev/cu.wchusbserial10`. Ignore `Bluetooth` and `debug` entries.

```bash
car-use config set device "serial:///dev/cu.usbserial-A12345?baud=38400"
car-use doctor
```

## Linux

```bash
ls /dev/ttyUSB* /dev/ttyACM*
```

`ttyUSB` is the usual ELM cable. `ttyACM` is some other USB serial chips. If opening the port is refused, your user needs to be in the `dialout` group, then log out and back in.

```bash
car-use config set device "serial:///dev/ttyUSB0?baud=38400"
car-use doctor
```

## Windows

car-use accepts a COM port name. In Device Manager, look under Ports (COM & LPT) for the USB serial device and note the COM number.

```bash
car-use config set device "serial://COM3?baud=38400"
```

A path that is only `COM3` also works. car-use is developed and tested on macOS and Linux. The COM form is accepted by the serial URL parser. It is not covered by the test suite or by CI.

If the port will not open, doctor says `Cannot open` and includes the path you set. Unplug other programs that already have the port, then try again.
