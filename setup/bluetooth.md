# Bluetooth

Bluetooth LE adapters (OBDLink CX, the BLE 4.0 Vgate iCar Pro, and most phone-only clones) are not supported yet.

If the device is set to a `ble://` URL, doctor says: `BLE adapters are not supported yet. Use a USB or Wi-Fi adapter, or the simulator: --sim p0420`.

Use a Wi-Fi or USB adapter instead. See [wifi.md](wifi.md) and [usb.md](usb.md). There is nothing to pair and no Bluetooth driver to install until that support exists.

Classic Bluetooth serial ports (a COM port or `/dev/cu.*` that appears only after pairing) are not a BLE URL. If the operating system already presents one as a serial port, the USB page is the one that matches. car-use still will not pair the radio for you.
