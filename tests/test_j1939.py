"""J1939 decoding: ids, standard SPNs, DM1 and BAM transport (no hardware, no simulator)."""
import pytest

from car_use.can import j1939 as J


def test_parse_id_pdu2_broadcast():
    j = J.parse_id("0CF00400")             # EEC1 from the engine, priority 3
    assert (j.priority, j.pgn, j.source, j.destination) == (3, 61444, 0x00, J.GLOBAL)
    assert not j.pdu1
    j = J.parse_id(0x18FEEE00)            # ET1
    assert (j.priority, j.pgn, j.source) == (6, 65262, 0)


def test_parse_id_pdu1_keeps_destination_out_of_the_pgn():
    j = J.parse_id("18EA00F9")            # Request from a service tool to the engine
    assert j.pdu1 and j.pgn == 59904 and j.destination == 0x00 and j.source == 0xF9
    j = J.parse_id("1CECFF00")            # TP.CM to global
    assert j.pgn == J.PGN_TP_CM and j.destination == J.GLOBAL and j.priority == 7
    j = J.parse_id("1CEBFF03")
    assert j.pgn == J.PGN_TP_DT and j.source == 3


def test_parse_id_data_page_bits_are_part_of_the_pgn():
    j = J.parse_id(f"{(6 << 26) | (1 << 24) | (0xFE << 16) | (0x10 << 8) | 0x21:08X}")
    assert j.pgn == 0x1FE10 and j.source == 0x21


def test_build_id_round_trips():
    for pgn, sa, prio in ((61444, 0, 3), (65226, 0x17, 6), (J.PGN_TP_CM, 0x0B, 7)):
        j = J.parse_id(J.build_id(pgn, sa, prio))
        assert (j.pgn, j.source, j.priority) == (pgn, sa, prio)
    with pytest.raises(ValueError):
        J.parse_id(0x20000000)


def test_standard_spn_scaling():
    # SPN 190: 1450 rpm = 11600 * 0.125 -> bytes 4-5 little-endian 50 2D
    assert J.decode_pgn(61444, bytes.fromhex("FFFFFF502DFFFFFF")) == {"engine_speed_rpm": 1450.0}
    # SPN 110: byte 1, offset -40
    assert J.decode_pgn(65262, bytes.fromhex("80FFFFFFFFFFFFFF")) == {"coolant_temp_c": 88.0}
    # SPN 100: byte 4, 4 kPa/bit
    assert J.decode_pgn(65263, bytes.fromhex("FFFFFF6EFFFFFFFF")) == {"oil_pressure_kpa": 440.0}
    # SPN 247: 4 bytes, 0.05 h/bit. 12345.6 h = 246912 = 0x0003C480
    assert J.decode_pgn(65253, bytes.fromhex("80C40300FFFFFFFF")) == {"engine_hours_h": 12345.6}
    # SPN 96: byte 2, 0.4 %/bit
    assert J.decode_pgn(65276, bytes.fromhex("FF9CFFFFFFFFFFFF")) == {"fuel_level_pct": 62.4}
    # SPN 84: 1/256 km/h; 0x0A00 = 10 km/h
    assert J.decode_pgn(65265, bytes.fromhex("FF000AFFFFFFFFFF")) == {"vehicle_speed_kph": 10.0}
    # SPN 168: bytes 5-6, 0.05 V; 27.6 V = 552 = 0x0228
    assert J.decode_pgn(65271, bytes.fromhex("FFFFFFFF2802FFFF")) == {"battery_v": 27.6}
    # SPN 171: bytes 4-5, 0.03125 degC, offset -273; 25 degC = 9536 = 0x2540
    assert J.decode_pgn(65269, bytes.fromhex("FFFFFF4025FFFFFF")) == {"ambient_temp_c": 25.0}
    # SPN 183: bytes 1-2, 0.05 L/h; 12.5 L/h = 250
    assert J.decode_pgn(65266, bytes.fromhex("FA00FFFFFFFFFFFF")) == {"fuel_rate_lph": 12.5}
    assert J.decode_pgn(0xFF10, bytes(8)) == {}


def test_not_available_and_error_are_missing():
    assert J.decode_pgn(65262, bytes.fromhex("FFFFFFFFFFFFFFFF")) == {"coolant_temp_c": None}
    assert J.decode_pgn(65262, bytes.fromhex("FE")) == {"coolant_temp_c": None}
    assert J.decode_pgn(61444, bytes.fromhex("FFFFFF00FFFFFFFF")) == {"engine_speed_rpm": None}
    assert J.decode_pgn(61444, bytes.fromhex("FFFFFF00FEFFFFFF")) == {"engine_speed_rpm": None}
    assert J.decode_pgn(65253, bytes.fromhex("000000FB")) == {"engine_hours_h": None}
    assert J.decode_pgn(61444, bytes.fromhex("FFFFFF")) == {"engine_speed_rpm": None}  # too short
    # top of the valid range still decodes
    assert J.decode_pgn(65262, bytes([0xFA])) == {"coolant_temp_c": 210.0}


def test_encode_pgn_matches_decode():
    data = J.encode_pgn(61444, {190: 1500})
    assert len(data) == 8 and data[0] == 0xFF and J.decode_pgn(61444, data)["engine_speed_rpm"] == 1500
    assert J.decode_pgn(65269, J.encode_pgn(65269, {171: -12.5}))["ambient_temp_c"] == -12.5
    with pytest.raises(KeyError):
        J.encode_pgn(61444, {110: 90})


def test_dm1_single_frame():
    dm1 = J.decode_dm1(bytes.fromhex("0400" "6E000003" "FFFF"))
    assert dm1["lamps"] == {"mil": "off", "red_stop": "off", "amber_warning": "on", "protect": "off"}
    (f,) = dm1["faults"]
    assert (f["spn"], f["fmi"], f["occurrences"]) == (110, 0, 3)
    assert "Engine Coolant Temperature" in f["text"] and "above normal" in f["text"]


def test_dm1_no_faults_and_high_spn_bits():
    assert J.decode_dm1(bytes.fromhex("0000000000000000"))["faults"] == []
    # SPN 520192 = 0x7F000: low 00, mid F0, top 3 bits 111 -> E0 | FMI 31
    dm1 = J.decode_dm1(bytes.fromhex("4000" "00F0FF7F" "FFFF"))
    (f,) = dm1["faults"]
    assert f["spn"] == 520192 and f["fmi"] == 31 and f["occurrences"] is None
    assert dm1["lamps"]["mil"] == "on"


def test_encode_dm1_round_trip_and_size():
    one = J.encode_dm1({"amber_warning": "on"}, [{"spn": 110, "fmi": 0, "oc": 3}])
    assert len(one) == 8
    two = J.encode_dm1({"red_stop": "on"}, [{"spn": 110, "fmi": 0, "oc": 3}, {"spn": 100, "fmi": 1, "oc": 1}])
    assert len(two) == 10
    faults = J.decode_dm1(two)["faults"]
    assert [(f["spn"], f["fmi"]) for f in faults] == [(110, 0), (100, 1)]
    assert J.decode_dm1(J.encode_dm1())["faults"] == []
    with pytest.raises(ValueError):
        J.encode_dm1(faults=[{"spn": 1, "fmi": 40}])


def _bam(payload, sa=0):
    return J.bam_frames(J.PGN_DM1, payload, sa)


def test_bam_frames_layout():
    payload = bytes(range(1, 19))           # 18 bytes -> 3 packets
    frames = _bam(payload)
    assert frames[0][0] == "1CECFF00"
    assert frames[0][1] == bytes([0x20, 18, 0, 3, 0xFF, 0xCA, 0xFE, 0x00])
    assert [f[0] for f in frames[1:]] == ["1CEBFF00"] * 3
    assert frames[3][1] == bytes([3, 15, 16, 17, 18, 0xFF, 0xFF, 0xFF])


def test_transport_reassembles_bam_dm1():
    payload = J.encode_dm1({"amber_warning": "on"},
                           [{"spn": 110, "fmi": 0, "oc": 3}, {"spn": 100, "fmi": 1, "oc": 1},
                            {"spn": 168, "fmi": 4, "oc": 2}])
    dec = J.Decoder()
    out = None
    for i, (ident, data) in enumerate(_bam(payload, sa=0)):
        out = dec.feed(ident, data, t=i * 0.05)
    assert out and out["dm1"]["multi_packet"] and out["changed"]
    assert [f["spn"] for f in dec.faults()] == [110, 100, 168]
    assert dec.transport.completed == 1
    # the same DM1 again is not a change
    for i, (ident, data) in enumerate(_bam(payload)):
        out = dec.feed(ident, data, t=1 + i * 0.05)
    assert out["changed"] is False


def test_transport_out_of_order_interleaved_and_dropped():
    p1 = J.encode_dm1(faults=[{"spn": 110, "fmi": 0}, {"spn": 100, "fmi": 1}])
    p2 = J.encode_dm1(faults=[{"spn": 96, "fmi": 18}, {"spn": 171, "fmi": 2}])
    a, b = _bam(p1, sa=0), _bam(p2, sa=3)
    t = J.Transport()
    assert t.feed(J.parse_id(a[0][0]), a[0][1], 0) is None
    assert t.feed(J.parse_id(b[0][0]), b[0][1], 0) is None
    assert t.feed(J.parse_id(a[2][0]), a[2][1], 0.1) is None      # packet 2 before 1
    assert t.feed(J.parse_id(b[1][0]), b[1][1], 0.1) is None
    got = t.feed(J.parse_id(a[1][0]), a[1][1], 0.2)
    assert got == (J.PGN_DM1, 0, p1)
    assert t.feed(J.parse_id(b[2][0]), b[2][1], 0.2) == (J.PGN_DM1, 3, p2)
    # a session that never finishes is dropped when the next one starts late
    t.feed(J.parse_id(a[0][0]), a[0][1], 10)
    t.feed(J.parse_id(a[1][0]), a[1][1], 10.05)
    t.feed(J.parse_id(a[0][0]), a[0][1], 20)
    assert t.dropped == 1
    # TP.DT with no announced session is ignored
    assert J.Transport().feed(J.parse_id(a[1][0]), a[1][1], 0) is None


def test_decoder_tracks_signals_and_sources():
    dec = J.Decoder()
    assert dec.feed("0CF00400", J.encode_pgn(61444, {190: 900}), 0)["signals"] == {"engine_speed_rpm": 900}
    dec.feed("18FEF117", J.encode_pgn(65265, {84: 12}), 0)
    assert dec.feed("025", bytes(8)) is None                # 11-bit: not J1939
    assert dec.feed("18FF1080", bytes(8)) is None           # proprietary B: counted, not decoded
    snap = dec.snapshot()
    assert snap["signals"]["engine_speed_rpm"]["value"] == 900
    assert snap["signals"]["vehicle_speed_kph"]["source"] == 0x17
    assert "61444 (EEC1)" in snap["pgns"] and "65296" in snap["pgns"]
    assert dec.row()["coolant_temp_c"] is None


def test_recognise():
    j1939 = {"0CF00400": 100, "18FEEE00": 1, "18FEF100": 10, "18FECA00": 1, "18FF1080": 5}
    r = J.recognise(j1939)
    assert r["j1939"] and "EEC1" in r["why"] and r["extended_ids"] == 5
    assert not J.recognise({"025": 10, "1A0": 10, "2B0": 4})["j1939"]
    # 29-bit OBD diagnostics alone are not J1939
    assert not J.recognise({"18DAF110": 3, "18DB33F1": 1})["j1939"]
    # mostly 11-bit with one stray J1939 id
    assert not J.recognise({"025": 1, "1A0": 1, "2B0": 1, "3C0": 1, "0CF00400": 1})["j1939"]
    assert not J.recognise({})["j1939"]


# -- wired into can-check, record and the helpers (synthetic frames) ------------------

def _capture():
    from car_use.obd.monitor import Capture, Frame
    frames, t = [], 0.0
    dm1 = J.encode_dm1({"amber_warning": "on"}, [{"spn": 110, "fmi": 0, "oc": 3},
                                                 {"spn": 100, "fmi": 1, "oc": 1}])
    for i in range(20):
        t += 0.01
        frames.append(Frame(t, 1000 + t, "0CF00400", J.encode_pgn(61444, {190: 1200 + i})))
    for ident, data in [("18FEEE00", J.encode_pgn(65262, {110: 104})),
                        ("18FEF100", J.encode_pgn(65265, {84: 0})),
                        ("18FEF717", J.encode_pgn(65271, {168: 27.4})),
                        *J.bam_frames(J.PGN_DM1, dm1, 0)]:
        t += 0.05
        frames.append(Frame(t, 1000 + t, ident, data))
    return Capture(frames=frames, seconds=t, bursts=1)


def test_can_check_names_a_j1939_bus_and_decodes_it():
    from car_use.doctor import port
    cap = _capture()
    bus = port._j1939(cap)
    assert bus["j1939"] and bus["signals"]["coolant_temp_c"]["value"] == 104
    result = {"verdict": "open", "why": "x", "listen": cap.summary(), "j1939": bus,
              "layout": [], "next": port._next("open", True, False, True)}
    text = port.render(result)
    assert "bus: J1939" in text and "SPN 110" in text and "multi-packet, BAM" in text
    assert "record --decode j1939" in text
    from car_use.obd.monitor import Capture, Frame
    assert port._j1939(Capture(frames=[Frame(0, 0, "025", bytes(8))] * 3)) is None


def test_record_decode_folder_j1939(tmp_path):
    import csv
    from car_use.record import decode_folder
    cap = _capture()
    with (tmp_path / "can.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_unix", "t_since_start", "burst", "id", "data"])
        for fr in cap.frames:
            w.writerow([f"{fr.wall:.3f}", f"{fr.mono:.3f}", 1, fr.id, fr.data.hex().upper()])
    out = decode_folder(tmp_path, "j1939")
    assert out["rows"] > 0 and out["j1939"]["transport"]["completed"] == 1
    rows = list(csv.DictReader((tmp_path / "signals.csv").open()))
    assert rows[-1]["coolant_temp_c"] == "104" and rows[-1]["battery_v"] == "27.4"
    faults = list(csv.DictReader((tmp_path / "faults.csv").open()))
    assert len(faults) == 1 and faults[0]["amber_warning"] == "on"
    assert faults[0]["faults"] == "SPN 110 FMI 0 x3; SPN 100 FMI 1 x1"


def test_j1939_helper_decodes_a_capture():
    from car_use import helpers
    out = helpers.j1939(capture=_capture())
    assert out["j1939"] and out["signals"]["engine_speed_rpm"]["value"] == 1219
    assert [f["spn"] for f in out["faults"]] == [110, 100]
    assert "j1939" in helpers.__all__


def test_protocol_a_is_can_and_j1939():
    from car_use.obd.elm import AdapterInfo, protocol_digit
    assert AdapterInfo(protocol_number="A").is_j1939 and AdapterInfo(protocol_number="A").is_can
    assert AdapterInfo(protocol_number="A6").number == "6" and not AdapterInfo(protocol_number="A6").is_j1939
    assert not AdapterInfo(protocol_number="A3").is_can
    assert protocol_digit("") == ""


def test_dm1_old_conversion_method_is_flagged_not_named():
    from car_use.can.j1939 import decode_dm1
    # SPN 110 (coolant temp), FMI 0, conversion method 1, occurrence 3.
    payload = bytes([0x04, 0xFF, 110, 0x00, 0x00, 0x80 | 3, 0xFF, 0xFF])
    f = decode_dm1(payload)["faults"][0]
    assert f["spn_uncertain"] is True and f["spn_name"] is None and "uncertain" in f["text"]
