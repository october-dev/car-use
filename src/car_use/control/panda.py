"""A real car through a comma panda, with opendbc doing the car-specific work.

Needs Python 3.12 and comma's packages, which aren't on PyPI in a usable
form, so they are an explicit install rather than a car-use dependency:

    pip install "pandacan @ git+https://github.com/commaai/panda"

(that pulls in opendbc at the commit the panda firmware was built against).

The flow follows opendbc's own PandaRunner: identify the car with the panda
in a no-output mode, let opendbc initialise it, then switch the panda to that
car's safety model. From then on the panda's firmware, not this file, decides
whether a command may reach the car. Closing switches the panda back to
no-output.
"""
from __future__ import annotations

import sys
import time

from .session import Command, ControlError, State

INSTALL = 'pip install "pandacan @ git+https://github.com/commaai/panda"'
VIN_UNKNOWN = "0" * 17


def _imports():
    if sys.version_info[:2] != (3, 12):
        raise ControlError(f"Motion control needs Python 3.12 (comma's packages don't support "
                           f"{sys.version_info.major}.{sys.version_info.minor} yet).")
    try:
        from panda import Panda
        from opendbc.car.can_definitions import CanData
        from opendbc.car.car_helpers import get_car
        from opendbc.car.structs import CarControl, CarParams
    except ImportError as e:
        raise ControlError(f"Motion control needs comma's panda and opendbc packages ({e.name} is "
                           f"missing). Install them with: {INSTALL}") from None
    return Panda, CanData, get_car, CarControl, CarParams


class PandaCar:
    simulated = False

    def __init__(self):
        Panda, CanData, get_car, CarControl, CarParams = _imports()
        self._CanData, self._CarControl, self._CarParams = CanData, CarControl, CarParams
        try:
            self.p = Panda()
        except Exception as e:
            raise ControlError(f"No comma panda found ({e}). Plug one into the car's harness "
                               "or OBD port and try again.") from None
        try:
            self.p.reset()
            self.p.set_safety_mode(CarParams.SafetyModel.elm327, 1)
            self.CI = get_car(self._recv, self.p.can_send_many, self.p.set_obd, True, False)
            cp = self.CI.CP
            if str(cp.carFingerprint).lower() == "mock":
                raise ControlError("opendbc doesn't recognise this car, so it has no safe way to "
                                   "control it. Supported cars: github.com/commaai/opendbc/blob/master/docs/CARS.md")
            self.vin = str(getattr(cp, "carVin", "") or "")
            if not self.vin or self.vin == VIN_UNKNOWN:
                raise ControlError("Couldn't read this car's VIN, and consent is per VIN, so control stays off.")
            self.car = f"{cp.brand} {cp.carFingerprint}".strip()
            self.steer_mode = "angle" if str(cp.steerControlType) == "angle" else "torque"
            self.can_accel = bool(getattr(cp, "openpilotLongitudinalControl", False))
            self.p.set_safety_mode(CarParams.SafetyModel.elm327, 1)
            self.CI.init(cp, self._recv, self.p.can_send_many)
            cfg = cp.safetyConfigs[0]
            self.p.set_safety_mode(cfg.safetyModel, cfg.safetyParam)
        except BaseException:
            self.close()
            raise

    def _recv(self, wait_for_one: bool = False):
        recv = self.p.can_recv()
        while not recv and wait_for_one:
            recv = self.p.can_recv()
        return [[self._CanData(addr, dat, bus) for addr, dat, bus in recv]]

    def read(self) -> State:
        cs = self.CI.update([int(time.monotonic() * 1e9), self._recv()[0]])
        allowed = bool(self.p.health().get("controls_allowed"))
        return State(speed_kph=float(cs.vEgo) * 3.6, steering_angle_deg=float(cs.steeringAngleDeg),
                     steering_pressed=bool(cs.steeringPressed), brake_pressed=bool(cs.brakePressed),
                     gas_pressed=bool(cs.gasPressed), cruise_engaged=bool(cs.cruiseState.enabled),
                     controls_allowed=allowed, ok=bool(cs.canValid))

    def write(self, cmd: Command) -> None:
        cc = self._CarControl.new_message()
        cc.enabled = cmd.enabled
        cc.latActive = cmd.enabled
        cc.longActive = cmd.enabled and self.can_accel
        if cmd.angle is not None:
            cc.actuators.steeringAngleDeg = cmd.angle
        cc.actuators.torque = cmd.torque
        cc.actuators.accel = cmd.accel
        cc.cruiseControl.cancel = cmd.cancel
        _, sends = self.CI.apply(cc.as_reader())
        self.p.can_send_many(sends, timeout=25)
        self.p.send_heartbeat()

    def close(self) -> None:
        p = getattr(self, "p", None)
        if p is None:
            return
        try:
            p.set_safety_mode(self._CarParams.SafetyModel.noOutput)
            p.reset()
        except Exception:
            pass
        self.p = None
