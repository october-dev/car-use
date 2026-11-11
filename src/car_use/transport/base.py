"""Byte transports to an adapter: TCP (Wi-Fi dongles, emulator), serial (USB/BT SPP).

BLE (GATT UART on FFF0/FFE0/18F0-style services) lands next; it needs `bleak`
and dynamic characteristic discovery.
"""
from __future__ import annotations

import socket
import time
from urllib.parse import urlparse, parse_qs


class TransportError(RuntimeError):
    pass


class Transport:
    url: str = ""

    def write(self, data: bytes) -> None: ...
    def _read_some(self, timeout: float) -> bytes: ...
    def close(self) -> None: ...

    def read_until(self, marker: bytes = b">", timeout: float = 5.0) -> bytes:
        buf = b""
        deadline = time.monotonic() + timeout
        while marker not in buf:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TransportError(f"Timed out after {timeout:.1f}s waiting for adapter "
                                     f"prompt on {self.url} (got {buf[-80:]!r})")
            buf += self._read_some(min(left, 0.25))
        return buf

    def drain(self) -> None:
        try:
            while self._read_some(0.05):
                pass
        except TransportError:
            pass


class TcpTransport(Transport):
    def __init__(self, host: str, port: int, connect_timeout: float = 5.0):
        self.url = f"tcp://{host}:{port}"
        try:
            self.sock = socket.create_connection((host, port), timeout=connect_timeout)
        except OSError as e:
            hint = ""
            if host.startswith("192.168."):
                hint = (" Wi-Fi dongles need this computer joined to the dongle's own "
                        "network (SSID like WiFi_OBDII / V-LINK) with the ignition on.")
            raise TransportError(f"Cannot reach adapter at {self.url}: {e}.{hint}") from e
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def write(self, data: bytes) -> None:
        self.sock.sendall(data)

    def _read_some(self, timeout: float) -> bytes:
        self.sock.settimeout(timeout)
        try:
            chunk = self.sock.recv(4096)
        except socket.timeout:
            return b""
        except OSError as e:
            raise TransportError(f"Adapter connection lost on {self.url}: {e}") from e
        if chunk == b"":
            raise TransportError(f"Adapter closed the connection on {self.url}")
        return chunk

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class SerialTransport(Transport):
    def __init__(self, path: str, baud: int = 38400):
        try:
            import serial  # type: ignore
        except ImportError as e:
            raise TransportError("Serial adapters need pyserial: "
                                 "uv tool install 'car-use[serial]'") from e
        self.url = f"serial://{path}?baud={baud}"
        try:
            self.ser = serial.Serial(path, baudrate=baud, timeout=0.1)
        except Exception as e:  # serial.SerialException
            raise TransportError(f"Cannot open {path}: {e}") from e

    def write(self, data: bytes) -> None:
        self.ser.write(data)
        self.ser.flush()

    def _read_some(self, timeout: float) -> bytes:
        self.ser.timeout = timeout
        return self.ser.read(self.ser.in_waiting or 1)

    def close(self) -> None:
        self.ser.close()


def open_transport(url: str) -> Transport:
    """tcp://host:port | serial:///dev/cu.usbserial-X?baud=115200 | /dev/... path."""
    if url.startswith("/dev/") or url.upper().startswith("COM"):
        return SerialTransport(url)
    u = urlparse(url)
    if u.scheme == "tcp":
        return TcpTransport(u.hostname or "192.168.0.10", u.port or 35000)
    if u.scheme == "serial":
        baud = int(parse_qs(u.query).get("baud", ["38400"])[0])
        return SerialTransport(u.path, baud)
    if u.scheme == "ble":
        raise TransportError("BLE adapters are not supported yet. Use a USB or Wi-Fi "
                             "adapter, or the simulator: --sim p0420")
    raise TransportError(f"Unknown device URL {url!r}. Use tcp://host:port, "
                         "serial:///dev/..., or sim:<scenario>.")
