"""A control session: a 100 Hz loop between the agent's commands and the car.

The agent never writes CAN frames itself. It sets a target (`steer`,
`accel`) and the loop sends it to the car through opendbc every 10 ms, for
as long as the target stays fresh. The loop owns every safety decision that
car-use makes on top of the panda's own:

  - commands only flow while the session is armed AND the panda reports
    that controls are allowed (the driver engaged the car's cruise control);
  - the driver pressing the brake or gas, or turning the wheel, disarms the
    session at once, and it stays disarmed until the agent arms it again;
  - a target older than STALE_AFTER seconds is dropped (hands off);
  - positive acceleration is refused above the owner's speed cap;
  - every arm, disarm, override and the session's end go into the audit log.
"""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field

from .. import config
from ..kernel.policy import Kernel
from ..model.capability import Tier

ACKNOWLEDGEMENT = ("I am the driver, I keep my hands on the wheel and my foot ready, "
                   "and I take full responsibility for what this car does")
STALE_AFTER = 0.3           # seconds without a fresh target before hands off
RATE_HZ = 100
DEFAULT_MAX_KPH = 40.0      # gas only below this; owners can change control_max_kph
ACCEL_LIMITS = (-3.5, 2.0)  # m/s^2, the same envelope opendbc's car ports use


class ControlError(RuntimeError):
    pass


@dataclass
class Command:
    """What the loop sends each tick. torque is -1..1 of the car's allowed
    steering torque (positive turns left), angle is degrees for cars that
    steer by angle, accel is m/s^2 (negative brakes)."""
    enabled: bool = False
    torque: float = 0.0
    angle: float | None = None
    accel: float = 0.0
    cancel: bool = False


@dataclass
class State:
    speed_kph: float = 0.0
    steering_angle_deg: float = 0.0
    steering_pressed: bool = False
    brake_pressed: bool = False
    gas_pressed: bool = False
    cruise_engaged: bool = False
    controls_allowed: bool = False
    ok: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _Target:
    torque: float = 0.0
    angle: float | None = None
    accel: float | None = None
    at: float = 0.0


@dataclass
class Status:
    armed: bool
    engaged: bool
    reason: str
    state: State
    car: str
    simulated: bool
    steer_mode: str
    can_accel: bool
    max_kph: float
    ticks: int
    log: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"] = self.state.to_dict()
        return d


class ControlSession:
    """Use as a context manager; leaving it always ends with hands off."""

    def __init__(self, runner, kernel: Kernel | None = None, vin: str = "", max_kph: float | None = None):
        self.runner = runner
        self.kernel = kernel or Kernel()
        self.vin = vin
        self.max_kph = float(max_kph if max_kph is not None else
                             config.get("control_max_kph", DEFAULT_MAX_KPH))
        self._target = _Target()
        self._armed = False
        self._reason = "not armed"
        self._state = State()
        self._ticks = 0
        self._log: list[str] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._loop, name="car-use-control", daemon=True)
        self._thread.start()
        self.kernel.record("control", vin=vin, event="session.start", car=runner.car,
                           simulated=runner.simulated, max_kph=self.max_kph)

    # ----------------------------------------------------------------- agent API
    def arm(self) -> Status:
        """Ask for control. Commands flow once the driver has engaged cruise."""
        self._check()
        with self._lock:
            self._armed = True
            self._reason = "armed"
            self._target = _Target(at=time.monotonic())
        self._note("armed")
        return self.status()

    def disarm(self, why: str = "disarmed by the agent") -> Status:
        with self._lock:
            was = self._armed
            self._armed = False
            self._reason = why
            self._target = _Target()
        if was:
            self._note(why)
        return self.status()

    def steer(self, torque: float | None = None, angle: float | None = None) -> None:
        """Set a steering target. Call again at least every 0.3 s to hold it."""
        self._check()
        if (torque is None) == (angle is None):
            raise ControlError("Give torque (-1..1) or angle (degrees), not both.")
        if angle is not None and self.runner.steer_mode != "angle":
            raise ControlError("This car steers by torque: use steer(torque=...).")
        if torque is not None and self.runner.steer_mode != "torque":
            raise ControlError("This car steers by angle: use steer(angle=...).")
        with self._lock:
            if torque is not None:
                self._target.torque = max(-1.0, min(1.0, float(torque)))
            else:
                self._target.angle = float(angle)
            self._target.at = time.monotonic()

    def accel(self, mps2: float) -> None:
        """Set a gas/brake target in m/s^2 (negative brakes). Refresh it like steer()."""
        self._check()
        if not self.runner.can_accel:
            raise ControlError("opendbc can't drive this car's gas and brake (no openpilot "
                               "longitudinal control for it). Steering may still work.")
        with self._lock:
            self._target.accel = max(ACCEL_LIMITS[0], min(ACCEL_LIMITS[1], float(mps2)))
            self._target.at = time.monotonic()

    def hold(self, seconds: float, torque: float | None = None, angle: float | None = None,
             accel: float | None = None) -> Status:
        """Keep a target fresh for `seconds`, then let go. Stops early if disarmed."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if torque is not None or angle is not None:
                self.steer(torque=torque, angle=angle)
            if accel is not None:
                self.accel(accel)
            if not self._armed:
                break
            time.sleep(0.05)
        return self.status()

    def state(self) -> State:
        with self._lock:
            return State(**asdict(self._state))

    def status(self) -> Status:
        with self._lock:
            s = State(**asdict(self._state))
            engaged = self._armed and s.controls_allowed
            return Status(self._armed, engaged, self._reason, s, self.runner.car, self.runner.simulated,
                          self.runner.steer_mode, self.runner.can_accel, self.max_kph, self._ticks,
                          list(self._log[-10:]))

    def close(self) -> None:
        if self._stop.is_set():
            return
        self.disarm("session closed")
        time.sleep(3 / RATE_HZ)
        self._stop.set()
        self._thread.join(timeout=2)
        try:
            self.runner.close()
        finally:
            self.kernel.record("control", vin=self.vin, event="session.end", ticks=self._ticks,
                               log=self._log[-20:])

    def __enter__(self) -> "ControlSession":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ----------------------------------------------------------------- the loop
    def _check(self) -> None:
        if self._error is not None:
            raise ControlError(f"control loop stopped: {self._error}")
        if self._stop.is_set():
            raise ControlError("this control session is closed")

    def _note(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self._log.append(f"{stamp} {text}")
        self.kernel.record("control", vin=self.vin, event=text)

    def _loop(self) -> None:
        period = 1 / RATE_HZ
        nxt = time.monotonic()
        try:
            while not self._stop.is_set():
                s = self.runner.read()
                cmd = self._decide(s)
                self.runner.write(cmd)
                self._ticks += 1
                nxt += period
                delay = nxt - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                else:
                    nxt = time.monotonic()
            # Stopping: the last frame this loop sends is always "not enabled", even if
            # a slow tick decided on an enabled command just before close() disarmed.
            self.runner.write(Command())
        except BaseException as e:   # the car or adapter went away: never leave it half-commanded
            self._error = e
            with self._lock:
                self._armed = False
                self._reason = f"stopped: {e}"
            try:
                self.runner.write(Command())
            except Exception:
                pass

    def _decide(self, s: State) -> Command:
        override = None
        with self._lock:
            self._state = s
            if self._armed:
                if s.brake_pressed:
                    override = "driver pressed the brake"
                elif s.gas_pressed:
                    override = "driver pressed the gas"
                elif s.steering_pressed:
                    override = "driver turned the wheel"
                elif not s.ok:
                    override = "car data went invalid"
            if override:
                self._armed = False
                self._reason = f"disarmed: {override}"
                self._target = _Target()
            armed = self._armed
            t = self._target
            fresh = armed and time.monotonic() - t.at <= STALE_AFTER
            if armed and not fresh:
                self._reason = "armed, waiting for a fresh command"
            elif armed and not s.controls_allowed:
                self._reason = "armed, waiting for the driver to engage cruise control"
            elif armed:
                self._reason = "engaged"
            torque, angle, accel = (t.torque, t.angle, t.accel) if fresh else (0.0, None, None)
        if override:
            self._note(f"disarmed: {override}")
        if not (armed and fresh and s.controls_allowed):
            return Command()
        if accel is not None and accel > 0 and s.speed_kph >= self.max_kph:
            accel = 0.0
        return Command(enabled=True, torque=torque, angle=angle, accel=accel or 0.0)


# --------------------------------------------------------------------- opening
def open_session(device: str | None = None, kernel: Kernel | None = None,
                 max_kph: float | None = None) -> ControlSession:
    """A control session on the simulator (device "sim" or "sim:NAME") or a real
    car through a comma panda (device None or "panda").

    A real car needs tier T4 enabled for its VIN and the owner's "yes" at the
    terminal for this session. The simulator needs neither: it moves nothing.
    """
    kernel = kernel or Kernel()
    if device and device.startswith("sim"):
        from .sim import SimRunner
        runner = SimRunner()
        return ControlSession(runner, kernel, vin=runner.vin, max_kph=max_kph)
    if device not in (None, "", "panda"):
        raise ControlError("Motion control needs a comma panda (device 'panda'); an ELM327 "
                           "can't send commands at 100 Hz or enforce the safety limits.")
    from .panda import PandaCar
    from ..kernel.policy import acknowledged, enabled_tiers
    runner = PandaCar()
    try:
        if "T4" in enabled_tiers(runner.vin) \
                and not acknowledged(runner.vin):
            kernel.record("deny", vin=runner.vin, intent="control.session", tier="T4",
                          reason="T4 is in policy.toml but the audit log has no typed acknowledgement")
            raise ControlError("T4 is set for this car but was never acknowledged at a terminal "
                               "(or the audit log was changed). Run: car-use control enable")
        decision = kernel.authorize(
            "control.session", Tier.T4, runner.vin,
            f"Start motion control on {runner.car} (VIN ending {runner.vin[-6:]}). The agent will "
            "send steering" + (" and gas/brake" if runner.can_accel else "") + " commands while you "
            "have cruise control engaged. Brake, gas or a firm hand on the wheel stops it at once. "
            "Only do this where it is legal and safe. Start?")
    except BaseException:
        runner.close()
        raise
    if not decision:
        runner.close()
        raise ControlError(decision.reason)
    return ControlSession(runner, kernel, vin=runner.vin, max_kph=max_kph)
