"""Each virtual car has a signature an agent can actually observe."""
from car_use.obd import pids as P
from car_use.sim.scenario import available, load


def test_compression_ignition_bit_roundtrips():
    raw = P.encode_monitor_status(False, 0, {"misfire": "complete"}, compression=True)
    decoded = P.decode_monitor_status(raw)
    assert decoded["ignition"] == "compression"
    assert decoded["monitors"]["misfire"] == "complete"
    spark = P.decode_monitor_status(P.encode_monitor_status(False, 0, {"misfire": "complete"}))
    assert spark["ignition"] == "spark"


def test_new_scenarios_are_listed_and_explained():
    names = set(available())
    for name in ("p0128", "p0442", "dpf-regen", "hybrid-12v", "cng-bifuel", "obd-2b", "healthy-ev"):
        assert name in names
        assert load(name).notes.strip()


def test_p0128_coolant_stays_low_after_a_long_idle(sim):
    s = load("p0128")
    assert s.value("runtime", 0) >= 900
    assert s.value("coolant", 0) < 50
    assert s.value("coolant", 900) < 70
    assert s.value("coolant", 900) - s.value("coolant", 0) < 20
    v = sim("p0128")
    assert v.dtcs()["stored"] == ["P0128"]
    assert v.read("coolant").value < 50
    assert v.read("runtime").value >= 900
    assert "thermostat" in s.notes.lower()


def test_p0442_has_no_drivability_symptom(sim):
    v = sim("p0442")
    assert v.dtcs()["stored"] == ["P0442"]
    assert abs(v.read("ltft1").value) < 5
    assert abs(v.read("stft1").value) < 8
    assert v.readiness()["monitors"]["evap"] == "complete"
    ff = v.freeze_frame()
    assert ff["dtc"] == "P0442" and abs(ff["values"]["ltft1"]["value"]) < 5
    assert "drives" in load("p0442").notes or "drive" in load("p0442").notes


def test_dpf_regen_is_a_warm_diesel_burning_extra_fuel(sim):
    s = load("dpf-regen")
    assert s.compression
    v = sim("dpf-regen")
    assert v.dtcs()["stored"] == []
    assert v.readiness()["ignition"] == "compression"
    assert v.read("rpm").value > 900
    assert v.read("fuel_rate").value > 2.5
    assert v.read("coolant").value > 80
    frames = v.raw_obd("22F1D0")
    assert frames[0].replace(" ", "") == "62F1D02D"
    assert "simulator-only" in s.notes


def test_hybrid_12v_is_low_with_the_engine_stopped(sim):
    v = sim("hybrid-12v")
    assert v.dtcs()["stored"] == ["P0562"]
    assert v.read("rpm").value == 0
    assert v.read("battery").value < 12.2
    assert "12 V" in load("hybrid-12v").notes or "12V" in load("hybrid-12v").notes


def test_cng_bifuel_looks_like_petrol_on_mode_01(sim):
    v = sim("cng-bifuel")
    assert v.dtcs()["stored"] == []
    assert abs(v.read("ltft1").value) < 5
    assert v.read("o2_b1s2").value > 0.5
    frames = v.raw_obd("22F1E1")
    assert frames[0].replace(" ", "") == "62F1E102"
    assert "CNG" in load("cng-bifuel").notes


def test_obd_2b_answers_only_a_few_sensors(sim):
    v = sim("obd-2b")
    assert v.dtcs()["stored"] == []
    assert v.read("rpm").value > 500
    assert v.read("o2_b1s1").value is None
    assert v.read("ltft1").value is None
    assert v.read("maf").value is None
    monitors = v.readiness()["monitors"]
    assert monitors["misfire"] == "complete"
    assert "catalyst" not in monitors and "evap" not in monitors


def test_healthy_ev_has_almost_no_engine_data(sim):
    v = sim("healthy-ev")
    assert v.dtcs()["stored"] == []
    assert v.read("speed").value == 0
    assert v.read("battery").value > 13.5
    for name in ("rpm", "coolant", "o2_b1s1", "ltft1", "maf"):
        assert v.read(name).value is None
    assert "rpm" not in {s["alias"] for s in v.signals()}
    assert "no data" in load("healthy-ev").notes or "nothing else" in load("healthy-ev").notes
