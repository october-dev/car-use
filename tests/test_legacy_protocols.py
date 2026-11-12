"""ISO 9141-2, KWP2000 and J1850 reply shapes, including a slow init."""
from car_use.kernel.policy import Kernel
from car_use.obd.elm import Elm327, _reassemble_legacy
from car_use.obd.vehicle import ObdVehicle
from car_use.sim.emulator import Emulator
from car_use.sim.scenario import Scenario
from car_use.transport.base import TcpTransport

KWP_VIN = "MA3EED1163A100914"
ISO_VIN = "1FAHP3112WA109141"


class _Scripted:
    """One canned reply per write. Enough to walk the ELM init sequence."""

    def __init__(self, answers: dict[str, bytes]):
        self.answers = answers
        self.last = b"\r"
        self.url = "sim:script"

    def write(self, data: bytes) -> None:
        self.last = data

    def drain(self) -> None:
        pass

    def close(self) -> None:
        pass

    def read_until(self, marker: bytes, timeout: float) -> bytes:
        cmd = self.last.decode().strip().upper().replace(" ", "")
        return self.answers.get(cmd, b"OK\r>")


def test_reassemble_non_can_vin_and_dtcs():
    frames = [
        bytes.fromhex("49020100000031"),
        bytes.fromhex("490202" + "41424344"),
        bytes.fromhex("490203" + "45464748"),
    ]
    joined = _reassemble_legacy(frames)
    assert joined == [bytes.fromhex("490201") + b"1ABCDEFGH"]
    dtcs = _reassemble_legacy([
        bytes.fromhex("430133000701"),
        bytes.fromhex("430300010128"),
    ])
    assert dtcs == [bytes.fromhex("4301330007010300010128")]
    assert _reassemble_legacy([bytes.fromhex("4100BE1FA813")])[0].hex() == "4100be1fa813"


def test_auto_search_falls_back_to_kwp():
    state = {"protocol": "0"}

    class T(_Scripted):
        def read_until(self, marker, timeout):
            cmd = self.last.decode().strip().upper().replace(" ", "")
            if cmd == "0100" and state["protocol"] in ("0", "A0", ""):
                return b"SEARCHING...\rUNABLE TO CONNECT\r>"
            if cmd == "0100":
                return b"4100BE1FA813\r>"
            if cmd.startswith("ATSP"):
                state["protocol"] = cmd[4:]
                return b"OK\r>"
            if cmd == "ATDPN":
                return state["protocol"].encode() + b"\r>"
            if cmd == "ATDP":
                return b"ISO 14230-4 (KWP FAST)\r>"
            if cmd == "ATZ":
                return b"ELM327 v1.5\r>"
            return b"OK\r>"

    elm = Elm327(T({}))
    elm.initialize()
    assert "KWP" in elm.detect_protocol()
    assert elm.info.protocol_number.lstrip("A") == "5"
    assert not elm.info.is_can


def _open(scenario: Scenario) -> ObdVehicle:
    emu = Emulator(scenario).start()
    elm = Elm327(TcpTransport(emu.host, emu.port))
    vehicle = ObdVehicle(elm, emu.url, kernel=Kernel(confirm=lambda _q, _e: False),
                         scenario=scenario)
    vehicle._emulator = emu
    return vehicle.connect()


def test_j1850_protocols_use_the_legacy_shape():
    vin = "4T1BF1FK0EU300042"
    for number, label in (("1", "J1850 PWM"), ("2", "J1850 VPW")):
        v = _open(Scenario(
            name=f"j1850-{number}", title=label, vin=vin, protocol=number,
            dtcs={"stored": ["P0301"]},
            monitors={"misfire": "complete", "components": "complete"},
        ))
        try:
            assert v.elm.info.protocol_number.lstrip("A") == number
            assert not v.elm.info.is_can
            assert v.read_vin() == vin
            assert v.dtcs()["stored"] == ["P0301"]
            assert v.readiness()["monitors"]["misfire"] == "complete"
        finally:
            v.elm.close()
            v._emulator.stop()


def test_kwp2000_and_iso9141_virtual_cars(sim):
    kwp = sim("kwp2000")
    assert kwp.elm.info.protocol_number.lstrip("A") == "5"
    assert not kwp.elm.info.is_can
    assert kwp.vin == KWP_VIN
    assert kwp.dtcs()["stored"] == ["P0420", "P0171", "P0300", "P0128"]
    ready = kwp.readiness()
    assert ready["mil_on"] is True
    assert ready["monitors"]["misfire"] == "complete"
    assert "BUS INIT" not in " ".join(line for _t, _c, line in kwp.elm.log)

    iso = sim("iso9141")
    assert iso.elm.info.protocol_number.lstrip("A") == "3"
    assert iso.vin == ISO_VIN
    assert iso.dtcs()["stored"] == ["P0301"]
    assert iso.readiness()["monitors"]["catalyst"] == "complete"
    assert iso.readiness()["monitors"]["misfire"] == "incomplete"
