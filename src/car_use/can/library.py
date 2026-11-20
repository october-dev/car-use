"""The bundled DBC maps (from opendbc), which car a capture looks like, and
the handful of signals that matter for driving data.

`SIGNALS` names, per DBC, where the car keeps its steering angle, driver
steering torque, brake switch, gas pedal, speed and indicators. The entries
follow opendbc's own carstate.py code for each brand, so a decoded column
means what openpilot means by it.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

from .dbc import Dbc

# Semantic columns, in the order recordings write them.
COLUMNS = ["speed_kph", "steering_angle_deg", "steering_torque", "brake_pressed",
           "gas_pedal", "left_blinker", "right_blinker"]

# Where each brand family lays out its core signals. "MSG.SIG" reads the value
# as is; a dict adds a test (eq / any_of), a sign bit (sign), a second part to
# add (plus), a flip (neg), on-if-nonzero (nz) or a unit change (mph).
_HYUNDAI = {
    "speed_kph": "WHL_SPD11.WHL_SPD_FL",
    "steering_angle_deg": "SAS11.SAS_Angle",
    "steering_torque": "MDPS12.CR_Mdps_StrColTq",
    "brake_pressed": "TCS13.DriverBraking",
    "gas_pedal": "EMS12.PV_AV_CAN",
    "left_blinker": {"sig": "CGW1.CF_Gway_TurnSigLh", "nz": True},
    "right_blinker": {"sig": "CGW1.CF_Gway_TurnSigRh", "nz": True},
}
_TOYOTA = {
    "speed_kph": "SPEED.SPEED",
    "steering_angle_deg": {"sig": "STEER_ANGLE_SENSOR.STEER_ANGLE", "plus": "STEER_ANGLE_SENSOR.STEER_FRACTION"},
    "steering_torque": "STEER_TORQUE_SENSOR.STEER_TORQUE_DRIVER",
    "brake_pressed": "BRAKE_MODULE.BRAKE_PRESSED",
    "gas_pedal": "GAS_PEDAL.GAS_PEDAL",
    "left_blinker": {"sig": "BLINKERS_STATE.TURN_SIGNALS", "eq": 1},
    "right_blinker": {"sig": "BLINKERS_STATE.TURN_SIGNALS", "eq": 2},
}
_HONDA = {
    "speed_kph": "ENGINE_DATA.XMISSION_SPEED",
    "steering_angle_deg": "STEERING_SENSORS.STEER_ANGLE",
    "steering_torque": "STEER_STATUS.STEER_TORQUE_SENSOR",
    "brake_pressed": "POWERTRAIN_DATA.BRAKE_PRESSED",
    "gas_pedal": "POWERTRAIN_DATA.PEDAL_GAS",
    "left_blinker": "SCM_FEEDBACK.LEFT_BLINKER",
    "right_blinker": "SCM_FEEDBACK.RIGHT_BLINKER",
}
_VW_MQB = {
    "speed_kph": "ESP_21.ESP_v_Signal",
    "steering_angle_deg": {"sig": "LWI_01.LWI_Lenkradwinkel", "sign": "LWI_01.LWI_VZ_Lenkradwinkel"},
    "steering_torque": {"sig": "LH_EPS_03.EPS_Lenkmoment", "sign": "LH_EPS_03.EPS_VZ_Lenkmoment"},
    "brake_pressed": "Motor_14.MO_Fahrer_bremst",
    "gas_pedal": "Motor_20.MO_Fahrpedalrohwert_01",
    "left_blinker": "Blinkmodi_02.Comfort_Signal_Left",
    "right_blinker": "Blinkmodi_02.Comfort_Signal_Right",
}

SIGNALS: dict[str, dict] = {
    "hyundai_can_generated": _HYUNDAI,
    "hyundai_2015_ccan": _HYUNDAI,
    "hyundai_canfd_generated": {
        "steering_angle_deg": "STEERING_SENSORS.STEERING_ANGLE",
        "steering_torque": "MDPS.MDPS_StrTqSnsrVal",
        "brake_pressed": "TCS.DriverBraking",
        "left_blinker": "BLINKERS.LEFT_LAMP",
        "right_blinker": "BLINKERS.RIGHT_LAMP",
    },
    "toyota_nodsu_pt_generated": _TOYOTA,
    "toyota_new_mc_pt_generated": _TOYOTA,
    "toyota_tnga_k_pt_generated": _TOYOTA,
    "honda_civic_hatchback_ex_2017_can_generated": _HONDA,
    "honda_bosch_radarless_generated": _HONDA,
    "honda_crv_touring_2016_can_generated": _HONDA,
    "vw_pq": {
        "speed_kph": "Bremse_1.BR1_Rad_kmh",
        "steering_angle_deg": {"sig": "Lenkhilfe_3.LH3_BLW", "sign": "Lenkhilfe_3.LH3_BLWSign"},
        "steering_torque": {"sig": "Lenkhilfe_3.LH3_LM", "sign": "Lenkhilfe_3.LH3_LMSign"},
        "brake_pressed": "Motor_2.MO2_BLS",
        "gas_pedal": "Motor_3.MO3_Pedalwert",
        "left_blinker": "Gate_Komf_1.GK1_Blinker_li",
        "right_blinker": "Gate_Komf_1.GK1_Blinker_re",
    },
    "vw_mqb": _VW_MQB,
    "vw_mqbevo": {**_VW_MQB, "brake_pressed": "ESP_05.ESP_Fahrer_bremst"},
    "mg": {
        "speed_kph": "SCS_HSC2_FrP19.VehSpdAvgHSC2",
        "steering_angle_deg": "SAS_HSC2_FrP00.StrgWhlAngHSC2",
        "steering_torque": "EPS_HSC2_FrP03.DrvrStrgDlvrdToqHSC2",
        "brake_pressed": "EHBS_HSC2_FrP00.BrkPdlAppdHSC2",
        "gas_pedal": "GW_HSC2_HCU_FrP00.EPTAccelActuPosHSC2",
        "left_blinker": {"sig": "GW_HSC2_BCM_FrP04.DircnIndLampSwStsHSC2", "eq": 1},
        "right_blinker": {"sig": "GW_HSC2_BCM_FrP04.DircnIndLampSwStsHSC2", "eq": 2},
    },
    "byd_atto3": {
        "speed_kph": "WHEEL_SPEED.WHEELSPEED_FL",
        "steering_angle_deg": "STEER_MODULE_2.STEER_ANGLE_2",
        "steering_torque": "STEERING_TORQUE.MAIN_TORQUE",
        "brake_pressed": "DRIVE_STATE.BRAKE_PRESSED",
        "gas_pedal": "DRIVE_STATE.RAW_THROTTLE",
        "left_blinker": "STALKS.LEFT_BLINKER",
        "right_blinker": "STALKS.RIGHT_BLINKER",
    },
    "nissan_x_trail_2017_generated": {
        "speed_kph": "WHEEL_SPEEDS_FRONT.WHEEL_SPEED_FL",
        "steering_angle_deg": "STEER_ANGLE_SENSOR.STEER_ANGLE",
        "steering_torque": "STEER_TORQUE_SENSOR.STEER_TORQUE_DRIVER",
        "brake_pressed": "DOORS_LIGHTS.USER_BRAKE_PRESSED",
        "gas_pedal": "GAS_PEDAL.GAS_PEDAL",
        "left_blinker": "LIGHTS.LEFT_BLINKER",
        "right_blinker": "LIGHTS.RIGHT_BLINKER",
    },
    "mazda_2017": {
        "speed_kph": "ENGINE_DATA.SPEED",
        "steering_angle_deg": "STEER.STEER_ANGLE",
        "steering_torque": "STEER_TORQUE.STEER_TORQUE_SENSOR",
        "brake_pressed": "PEDALS.BRAKE_ON",
        "gas_pedal": "ENGINE_DATA.PEDAL_GAS",
        "left_blinker": "BLINK_INFO.LEFT_BLINK",
        "right_blinker": "BLINK_INFO.RIGHT_BLINK",
    },
    "tesla_model3_party": {
        "speed_kph": "DI_speed.DI_vehicleSpeed",
        "steering_angle_deg": {"sig": "EPAS3S_sysStatus.EPAS3S_internalSAS", "neg": True},
        "steering_torque": {"sig": "EPAS3S_sysStatus.EPAS3S_torsionBarTorque", "neg": True},
        "brake_pressed": {"sig": "ESP_status.ESP_driverBrakeApply", "eq": 2},
        "gas_pedal": "DI_systemStatus.DI_accelPedalPos",
        "left_blinker": {"sig": "UI_warning.leftBlinkerBlinking", "any_of": [1, 2]},
        "right_blinker": {"sig": "UI_warning.rightBlinkerBlinking", "any_of": [1, 2]},
    },
    "gm_global_a_powertrain_generated": {
        "speed_kph": {"sig": "ECMVehicleSpeed.VehicleSpeed", "mph": True},
        "steering_angle_deg": "PSCMSteeringAngle.SteeringWheelAngle",
        "steering_torque": "PSCMStatus.LKADriverAppldTrq",
        "brake_pressed": "ECMEngineStatus.BrakePressed",
        "gas_pedal": "AcceleratorPedal2.AcceleratorPedal2",
        "left_blinker": {"sig": "BCMTurnSignals.TurnSignals", "eq": 1},
        "right_blinker": {"sig": "BCMTurnSignals.TurnSignals", "eq": 2},
    },
    "subaru_global_2017_generated": {
        "speed_kph": "Wheel_Speeds.FL",
        "steering_angle_deg": "Steering_Torque.Steering_Angle",
        "steering_torque": "Steering_Torque.Steer_Torque_Sensor",
        "brake_pressed": "Brake_Status.Brake",
        "gas_pedal": "Throttle.Throttle_Pedal",
        "left_blinker": "Dashlights.LEFT_BLINKER",
        "right_blinker": "Dashlights.RIGHT_BLINKER",
    },
}

# What a person would call each file.
LABELS = {
    "hyundai_can_generated": "Hyundai / Kia (CAN, most 2015+ models)",
    "hyundai_2015_ccan": "Hyundai / Kia (older C-CAN layout)",
    "hyundai_canfd_generated": "Hyundai / Kia (CAN FD, newer models; needs a CAN FD adapter)",
    "toyota_nodsu_pt_generated": "Toyota / Lexus (TSS-P without DSU)",
    "toyota_new_mc_pt_generated": "Toyota / Lexus (newer models)",
    "toyota_tnga_k_pt_generated": "Toyota (TNGA-K platform)",
    "honda_civic_hatchback_ex_2017_can_generated": "Honda (Bosch, Civic hatchback era)",
    "honda_bosch_radarless_generated": "Honda (Bosch radarless, 2022+)",
    "honda_crv_touring_2016_can_generated": "Honda (Nidec, CR-V 2016 era)",
    "vw_pq": "Volkswagen group (PQ platform: older Polo, Vento, Jetta)",
    "vw_mqb": "Volkswagen group (MQB: Golf, Octavia, Kushaq, Taigun, Virtus, Slavia)",
    "vw_mqbevo": "Volkswagen group (MQB evo, 2020+)",
    "mg": "MG (SAIC)",
    "byd_atto3": "BYD Atto 3",
    "nissan_x_trail_2017_generated": "Nissan (X-Trail / Rogue era)",
    "mazda_2017": "Mazda (2017+)",
    "tesla_can": "Tesla Model S / X (older)",
    "tesla_model3_party": "Tesla Model 3 / Y",
    "gm_global_a_powertrain_generated": "GM (Global A)",
    "subaru_global_2017_generated": "Subaru (Global platform)",
}


def names() -> list[str]:
    root = resources.files("car_use.can") / "dbcs"
    return sorted(p.name[:-4] for p in root.iterdir() if p.name.endswith(".dbc"))


@lru_cache(maxsize=None)
def load(name: str) -> Dbc:
    if name.endswith(".dbc") or "/" in name:
        return Dbc.load(name)
    path = resources.files("car_use.can") / "dbcs" / f"{name}.dbc"
    if not path.is_file():
        raise KeyError(f"No bundled DBC named {name!r}. Known: {', '.join(names())}")
    return Dbc.parse(path.read_text(encoding="utf-8", errors="replace"), name)


@dataclass
class Match:
    dbc: str
    label: str
    known: int            # heard ids this DBC defines
    heard: int            # car ids heard in total
    size_ok: int          # of those, how many had the length the DBC expects
    signals: list[str]    # semantic columns this DBC can fill from what was heard

    @property
    def score(self) -> float:
        return (self.size_ok + 0.5 * (self.known - self.size_ok)) / max(self.heard, 1)

    @property
    def confidence(self) -> str:
        """"strong" when the map explains most of what was heard, else "weak"."""
        return "strong" if self.score >= 0.7 and self.known >= 3 else "weak"

    def to_dict(self) -> dict:
        return {"dbc": self.dbc, "label": self.label, "known_ids": self.known, "heard_ids": self.heard,
                "length_matches": self.size_ok, "score": round(self.score, 2),
                "confidence": self.confidence, "signals": self.signals}


def match(lengths: dict[str, int], top: int = 3) -> list[Match]:
    """Rank the bundled DBCs by how well they explain the ids heard.

    `lengths` maps each heard car id ("2B0") to its data length. A DBC that
    defines most of the heard ids, with the same lengths, is likely the
    car's layout. A real car has more ids than any one DBC lists, and
    unrelated DBCs share a few common ids, so read the score as a lead, not
    a verdict, until a guided check confirms it.
    """
    out = []
    for name in names():
        d = load(name)
        known = [i for i in lengths if i in d.by_id]
        if not known:
            continue
        size_ok = sum(1 for i in known if d.by_id[i].size == lengths[i])
        have = {d.by_id[i].name for i in known}
        sigs = [c for c, spec in SIGNALS.get(name, {}).items() if _msg(spec) in have]
        out.append(Match(name, LABELS.get(name, name), len(known), len(lengths), size_ok, sigs))
    order = list(LABELS)
    out.sort(key=lambda m: (-m.score, -len(m.signals), order.index(m.dbc) if m.dbc in order else 99))
    return [m for m in out if m.score >= 0.35][:top]


def _msg(spec) -> str:
    return (spec if isinstance(spec, str) else spec["sig"]).split(".")[0]


def _value(d: Dbc, spec, latest: dict[str, dict]):
    spec = {"sig": spec} if isinstance(spec, str) else spec
    msg, sig = spec["sig"].split(".")
    vals = latest.get(msg)
    if vals is None or sig not in vals:
        return None
    v = vals[sig]
    if "plus" in spec:
        m2, s2 = spec["plus"].split(".")
        v += latest.get(m2, {}).get(s2, 0)
    if "sign" in spec:
        m2, s2 = spec["sign"].split(".")
        if latest.get(m2, {}).get(s2):
            v = -v
    if spec.get("neg"):
        v = -v
    if spec.get("mph"):
        v = v * 1.609344
    if "eq" in spec:
        return int(v == spec["eq"])
    if spec.get("nz"):
        return int(v != 0)
    if "any_of" in spec:
        return int(v in spec["any_of"])
    return round(v, 3) if isinstance(v, float) else v


class Decoder:
    """Turns a stream of (id, data) frames into the semantic columns.

    It keeps the latest decoded values of every message it has seen, so
    `row()` can be called at any rate: each column holds the most recent
    value of its signal, or None if that message hasn't been heard yet.
    """

    def __init__(self, dbc: str):
        self.name = dbc
        self.dbc = load(dbc)
        self.spec = SIGNALS.get(dbc, {})
        self.latest: dict[str, dict] = {}
        self.decoded = 0

    def feed(self, ident: str, data: bytes) -> dict | None:
        m = self.dbc.by_id.get(ident.upper())
        if m is None:
            return None
        vals = m.decode(data)
        self.latest[m.name] = vals
        self.decoded += 1
        return vals

    def row(self) -> dict:
        return {c: _value(self.dbc, self.spec[c], self.latest) if c in self.spec else None for c in COLUMNS}

    def ids(self) -> list[str]:
        """The ids this DBC's semantic signals live on, for an adapter filter."""
        wanted = set()
        for spec in self.spec.values():
            spec = {"sig": spec} if isinstance(spec, str) else spec
            for key in ("sig", "plus", "sign"):
                if key in spec:
                    wanted.add(spec[key].split(".")[0])
        return sorted(self.dbc.messages[m].hex_id for m in wanted if m in self.dbc.messages)


def which_signal(dbc: str, ident: str, lo: int, hi: int, masks: list[int] | None = None) -> dict | None:
    """The DBC signal that lives in bytes lo..hi of message `ident` (and in
    `masks`, one bit mask per byte, when given), preferring the signals the
    semantic map uses. None if the DBC has no message with that id."""
    m = load(dbc).by_id.get(ident.upper())
    if m is None:
        return None
    used = {(spec if isinstance(spec, str) else spec["sig"]) for spec in SIGNALS.get(dbc, {}).values()}
    best, best_key = None, None
    for sig in m.signals.values():
        occ = sig.bits()
        overlap = 0
        for i in range(lo, hi + 1):
            want = masks[i - lo] if masks and i - lo < len(masks) else 0xFF
            overlap += bin(occ.get(i, 0) & want).count("1")
        if not overlap:
            continue
        key = (f"{m.name}.{sig.name}" in used, overlap, -sig.size)
        if best_key is None or key > best_key:
            best, best_key = sig, key
    if best is None:
        return None
    column = next((c for c, spec in SIGNALS.get(dbc, {}).items()
                   if (spec if isinstance(spec, str) else spec["sig"]) == f"{m.name}.{best.name}"), None)
    return {"message": m.name, "signal": best.name, "unit": best.unit, "column": column}
