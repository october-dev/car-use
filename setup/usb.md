# USB adapters

USB adapters need the `serial` extra. Without it, doctor says `Serial adapters need pyserial`.

```bash
uv tool install "car-use[serial] @ git+https://github.com/october-dev/car-use"
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

`ttyUSB` is the usual ELM cable. `ttyACM` is some other USB serial chips. If opening the port is refused, check its owning group and your permissions; common groups are `dialout` (Debian/Ubuntu) and `uucp` (Arch). Log out and back in after changing group membership.

```bash
car-use config set device "serial:///dev/ttyUSB0?baud=38400"
car-use doctor
```

## Windows

car-use accepts a COM port name. In Device Manager, look under Ports (COM & LPT) for the USB serial device and note the COM number.

```bash
car-use config set device "serial:COM3?baud=38400"
car-use doctor
```

A bare `COM3` also works, at 38400 baud. Use `serial:COM3?baud=115200` for 115200 baud. The test suite checks port names and baud rates; it does not test Windows drivers or hardware. Windows and paired classic Bluetooth adapters have not been validated on real hardware.

If the port will not open, doctor says `Cannot open` and includes the path you set. Close other programs that already have the port, then try again.
