"""Capability model: what a vehicle + backend can observe, do, and drive.

Every backend publishes a Manifest. Agents discover capabilities from it
instead of the harness hard-coding verbs, so a backend for an API that does
not exist yet (an FSD mission API, a robotaxi operator) slots in without a
redesign.

Altitude says what kind of intent it is. DriverOfRecord says who carries the
safety responsibility for the driving task while it runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum


class Altitude(str, Enum):
    OBSERVE = "A0"   # read signals, DTCs, location, history
    ACT = "A1"       # comfort, access, maintenance (lock, climate, clear DTC)
    SETPOINT = "A2"  # parameters a vehicle system executes (nav dest, ACC speed)
    MISSION = "A3"   # goals an OEM/AV stack carries out (drive_to, summon, park)
    SERVICE = "A4"   # mobility bought from an operator (book a ride)


class DriverOfRecord(str, Enum):
    NONE = "none"                          # parked / not driving
    HUMAN = "human"                        # a person drives
    HUMAN_SUPERVISED = "human_supervised"  # L2/L2++: system steers, human is driver
    OEM_ADS = "oem_ads"                    # certified automated driving system
    OPERATOR = "operator"                  # a ride/AV operator owns the trip


class Tier(str, Enum):
    T0 = "T0"    # read
    T1 = "T1"    # comfort, parked
    T1D = "T1D"  # reversible diagnostics (clear DTCs)
    T2 = "T2"    # access/security (unlock, remote start)
    T2C = "T2C"  # vetted coding recipes
    T3 = "T3"    # assist setpoints, driver engaged
    T4 = "T4"    # motion control, closed course only


@dataclass(frozen=True)
class Capability:
    name: str                      # "obd.dtcs", "climate.set", "mission.drive_to"
    altitude: Altitude
    tier: Tier
    description: str = ""
    params: dict = field(default_factory=dict)       # JSON-schema-ish
    preconditions: tuple[str, ...] = ()              # e.g. ("parked",)
    driver_of_record: DriverOfRecord = DriverOfRecord.NONE
    reversible: bool = True


@dataclass
class Manifest:
    backend: str
    vehicle: dict
    signals: list[str] = field(default_factory=list)   # VSS paths available now
    capabilities: list[Capability] = field(default_factory=list)
    jurisdictions: tuple[str, ...] = ("*",)
    ownership_nexus: str | None = None

    def by_altitude(self, altitude: Altitude) -> list[Capability]:
        return [c for c in self.capabilities if c.altitude == altitude]

    def summary(self) -> str:
        lines = [f"backend: {self.backend}", f"vehicle: {self.vehicle}",
                 f"signals: {len(self.signals)}"]
        for alt in Altitude:
            caps = self.by_altitude(alt)
            if caps:
                lines.append(f"{alt.value} {alt.name.lower()}: "
                             + ", ".join(f"{c.name}[{c.tier.value}]" for c in caps))
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return asdict(self)
