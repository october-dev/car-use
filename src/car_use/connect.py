"""Turn a device URL into a connected Vehicle."""
from __future__ import annotations

from . import config
from .obd.elm import Elm327
from .obd.vehicle import ObdVehicle
from .transport.base import open_transport


class NoDevice(RuntimeError):
    pass


def resolve_device(device: str | None) -> str:
    dev = device or config.get("device")
    if not dev:
        raise NoDevice(
            "No car configured. Either try the simulator (car-use --sim p0420), or plug in an "
            "adapter and run: car-use config set device tcp://192.168.0.10:35000 "
            "(Wi-Fi) or serial:///dev/cu.<adapter>?baud=38400 (USB).")
    return dev


def open_vehicle(device: str | None = None, kernel=None, protocol: str | None = None,
                 listen_only: bool = False) -> ObdVehicle:
    """Connect. ``protocol`` (or the `protocol` setting) skips the auto search;
    "A" is SAE J1939 for trucks and machines, which auto search never finds.
    ``listen_only`` connects without transmitting anything on the bus and
    refuses every command that would (see ObdVehicle.connect)."""
    dev = resolve_device(device)
    emu = None
    scenario = None
    url = dev
    if dev.startswith("sim:") or dev == "sim":
        from .sim.emulator import Emulator
        from .sim.scenario import load
        scenario = load(dev.partition(":")[2] or "healthy")
        emu = Emulator(scenario).start()
        url = emu.url
    protocol = protocol or config.get("protocol") or None
    if protocol is None and scenario is not None and (listen_only or scenario.protocol.upper() == "A"):
        # The simulator plays the person who knows the bus: protocol A for a
        # J1939 machine, or, when car-use may not search, the car's own protocol.
        protocol = scenario.protocol
    elm = Elm327(open_transport(url))
    v = ObdVehicle(elm, dev, kernel=kernel, scenario=scenario)
    v._emulator = emu   # keep alive for the vehicle's lifetime
    try:
        return v.connect(protocol=protocol, listen_only=listen_only)
    except BaseException:
        elm.close()
        if emu is not None:
            emu.stop()
        raise
