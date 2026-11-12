"""Headers keep each ECU's reply attached to the CAN id that sent it."""
from car_use.obd.elm import assemble_headers
from car_use.sim.emulator import frames_with_id


def test_headers_roundtrip_11bit_and_29bit():
    short = bytes.fromhex("43010300")
    assert assemble_headers(frames_with_id("7E8", short)) == {"7E8": short}
    long = bytes.fromhex("490201") + b"1HGCM82633A004352"
    parsed = assemble_headers(frames_with_id("18DAF110", long))
    assert parsed == {"18DAF110": long}
    both = frames_with_id("7E8", short) + frames_with_id("7E9", bytes.fromhex("43010700"))
    got = assemble_headers(both)
    assert got["7E8"] == short and got["7E9"] == bytes.fromhex("43010700")


def test_two_ecus_keep_their_own_codes_and_signals(sim):
    v = sim("two-ecu")
    codes = v.dtcs()
    assert codes["stored"] == ["P0300", "P0700"]
    assert codes["by_ecu"]["7E8"]["stored"] == ["P0300"]
    assert codes["by_ecu"]["7E9"]["stored"] == ["P0700"]
    assert "P0700" not in codes["by_ecu"]["7E8"]["stored"]

    assert v.read("coolant").value == 90
    assert v.read("rpm").value == 800
    assert v.read("coolant", ecu="7E9").value == 40
    assert v.read("rpm", ecu="7E9").value is None
    # functional addressing is restored, so the next plain read is the engine again
    assert v.read("coolant").value == 90

    engine = v.raw_obd("22F190")
    trans = v.raw_obd("22F190", ecu="7E9")
    assert engine[0].replace(" ", "").endswith("AAAA")
    assert trans[0].replace(" ", "").endswith("BBBB")
    assert v.raw_obd("22F190")[0].replace(" ", "").endswith("AAAA")
