"""Setup pages stay aligned with the sentences doctor actually prints."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "setup"
SRC = ROOT / "src" / "car_use"

# Phrases copied into setup/troubleshooting.md. Each one is a real string in src.
PHRASES = (
    "No car configured",
    "Cannot reach adapter at",
    "Wi-Fi dongles need this computer joined to the dongle's own",
    "Timed out after",
    "waiting for adapter",
    "Adapter connection lost",
    "Adapter closed the connection",
    "Serial adapters need pyserial",
    "Cannot open",
    "BLE adapters are not supported yet",
    "Unknown device URL",
    "adapter answers but the car does not. Turn the ignition on",
    "is the ignition on?",
    "status: ready",
)


def test_setup_pages_exist():
    for name in ("README.md", "wifi.md", "usb.md", "bluetooth.md", "adapters.md",
                 "troubleshooting.md"):
        text = (SETUP / name).read_text()
        assert len(text.splitlines()) > 5


def test_troubleshooting_quotes_real_doctor_messages():
    docs = (SETUP / "troubleshooting.md").read_text()
    source = "\n".join(p.read_text() for p in SRC.rglob("*.py"))
    for phrase in PHRASES:
        assert phrase in docs, phrase
        assert phrase in source, phrase


def test_wifi_and_usb_pages_use_the_documented_addresses():
    wifi = (SETUP / "wifi.md").read_text()
    usb = (SETUP / "usb.md").read_text()
    ble = (SETUP / "bluetooth.md").read_text()
    assert "tcp://192.168.0.10:35000" in wifi
    assert "192.168.1.10" in wifi
    assert "WiFi_OBDII" in wifi
    assert "/dev/cu." in usb and "ttyUSB" in usb and "COM" in usb
    assert "car-use[serial] @ git+https://github.com/october-dev/car-use" in usb
    assert "38400" in usb
    assert "BLE adapters are not supported yet" in ble


def test_usb_page_urls_reach_the_port_they_name(monkeypatch):
    from car_use.transport import base
    opened = []
    monkeypatch.setattr(base, "SerialTransport",
                        lambda path, baud=38400: opened.append((path, baud)))
    usb = (SETUP / "usb.md").read_text(encoding="utf-8")
    for baud in (38400, 115200):
        opened.clear()
        for url in re.findall(r'config set device "(serial:[^"]+)"', usb):
            base.open_transport(url.replace("baud=38400", f"baud={baud}"))
        assert opened == [(port, baud) for port in
                          ("/dev/cu.usbserial-A12345", "/dev/ttyUSB0", "COM3")]
    opened.clear()
    base.open_transport("COM3")
    assert opened == [("COM3", 38400)]
