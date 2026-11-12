import struct

import pytest

from car_use.ecu import logs, tsini
from car_use.makers import available, find

INI = r'''
; hand-written fixture in the TunerStudio .ini format (not from any firmware)
[MegaTune]
   signature = "testecu 2026.11"   ; what the ECU answers to Q
   queryCommand = "Q"

[Constants]
   endianness = little
   nPages = 2
   pageSize = 128, 288
   page = 1
      reqFuel   = scalar, U08, 0, "ms", 0.1, 0.0, 0.0, 25.5, 1
      injLayout = bits,   U08, 1, [0:1], "Paired", "Semi-Sequential", "INVALID", "Sequential"
   page = 2
      veTable   = array,  U08, 0, [16x16], "%", 1.0, 0.0, 0.0, 255.0, 0
      rpmBins   = array,  U08, 256, [16], "RPM", 100.0, 0.0, 100.0, 25500.0, 0
#if CELSIUS
      cltBias   = scalar, S16, 272, "C", 0.1, 0.0, -40, 120, 1
#else
      cltBias   = scalar, S16, 272, "F", 0.1, 0.0, -40, 250, 1
#endif

[OutputChannels]
   ochGetCommand = "r\x00\x30%2o%2c"
   ochBlockSize  = 8
   secl     = scalar, U08, 0, "sec", 1.000, 0.000
   rpm      = scalar, U16, 1, "rpm", 1.000, 0.000
   coolantRaw = scalar, U08, 3, "C", 1.000, -40.0
   afr      = scalar, U08, 4, "AFR", 0.1, 0.0
   running  = bits,   U08, 5, [0:0], "no", "yes"
   coolant  = { coolantRaw }
'''


def test_ini_parse_and_decode():
    ini = tsini.parse(INI)
    assert ini.signature == "testecu 2026.11"
    assert ini.page_sizes == [128, 288]
    assert ini.tables()["veTable"].shape == (16, 16)
    assert ini.constants["cltBias"].units == "F"                     # #else branch
    assert tsini.parse(INI, {"CELSIUS"}).constants["cltBias"].units == "C"
    assert ini.constants["injLayout"].options[3] == "Sequential"
    assert ini.channels["coolant"].kind == "expr"
    block = struct.pack("<BHBBB", 12, 3150, 130, 147, 1) + b"\x00\x00"
    vals = ini.decode_channels(block)
    assert vals["rpm"] == 3150 and vals["coolantRaw"] == 90.0
    assert vals["afr"] == pytest.approx(14.7) and vals["running"] == "yes"
    s = ini.summary()
    assert s["tables"]["veTable"] == "16x16 %" and s["realtime_block_bytes"] == 8


MSL = '"TestECU log"\n"Capture Date: 2026-11-12"\nTime\tRPM\tAFR\tMAP\ns\trpm\tAFR\tkPa\n' + \
      "".join(f"{i * 0.1:.1f}\t{800 + i * 50}\t{14.7 - i * 0.1:.1f}\t{35 + i}\n" for i in range(20))


def test_msl_log():
    log = logs.parse(MSL)
    assert log.columns == ["Time", "RPM", "AFR", "MAP"] and log.units[1] == "rpm"
    assert len(log.rows) == 20 and log.duration() == pytest.approx(1.9)
    assert log.stats("rpm")["max"] == 1750
    assert log.header == ["TestECU log", "Capture Date: 2026-11-12"]


def test_csv_log_without_units():
    log = logs.parse("Time,RPM,Boost\n0,900,0\n1,3000,0.8\n2,6000,1.2\n")
    assert log.units == [] and log.stats("Boost")["max"] == 1.2


def test_mlg_rejected(tmp_path):
    p = tmp_path / "x.mlg"
    p.write_bytes(b"MLVLG\x00")
    with pytest.raises(ValueError, match="export"):
        logs.load_log(p)


def test_maker_packs():
    assert {"Toyota", "Maruti Suzuki", "Tesla"} <= set(available())
    assert find("4T1BF1FK0EU300042").make == "Toyota"          # by WMI
    assert find("MA3FJEB1S00100001").make == "Maruti Suzuki"
    assert find("audi").make == "Volkswagen"                     # alias
    assert find("Lada") is None
    for make in available():
        text = find(make).text
        tags = text.count("[common]") + text.count("[verified") + text.count("[unverified]")
        assert tags >= 1, make
