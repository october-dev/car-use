"""A virtual car for practising motion control. It moves nothing real.

A simple bicycle model: torque turns the steering wheel, accel changes speed,
and the car's position, heading and speed follow. The simulated driver has
engaged cruise control at 30 km/h; tests and demos can make the driver brake,
press the gas, grab the wheel or cancel cruise with `driver(...)`.
"""
from __future__ import annotations

import math
import threading
import time

from .session import Command, State

WHEELBASE_M = 2.6
STEER_RATIO = 15.0
MAX_WHEEL_DEG = 480.0
WHEEL_DEG_PER_S = 360.0     # at full torque


class SimRunner:
    car = "Virtual car (sim)"
    vin = "1CARUSE0XS0CTL001"
    simulated = True
    steer_mode = "torque"
    can_accel = True

    def __init__(self, speed_kph: float = 30.0):
        self._lock = threading.Lock()
        self.speed = speed_kph / 3.6         # m/s
        self.wheel = 0.0                     # steering wheel degrees, left positive
        self.x = self.y = self.heading = 0.0
        self.cruise = True
        self.brake = self.gas = self.grab = False
        self.last = time.monotonic()
        self.commands = 0                    # ticks with enabled=True
        self.closed = False

    def driver(self, brake: bool | None = None, gas: bool | None = None, grab: bool | None = None,
               cruise: bool | None = None) -> None:
        """Play the person in the driver's seat."""
        with self._lock:
            if brake is not None:
                self.brake = brake
                if brake:
                    self.cruise = False   # braking cancels cruise, as on a real car
            if gas is not None:
                self.gas = gas
            if grab is not None:
                self.grab = grab
            if cruise is not None:
                self.cruise = cruise

    def read(self) -> State:
        with self._lock:
            return State(speed_kph=self.speed * 3.6, steering_angle_deg=self.wheel,
                         steering_pressed=self.grab, brake_pressed=self.brake, gas_pressed=self.gas,
                         cruise_engaged=self.cruise, controls_allowed=self.cruise, ok=True)

    def write(self, cmd: Command) -> None:
        with self._lock:
            now = time.monotonic()
            dt = min(now - self.last, 0.1)
            self.last = now
            if cmd.enabled and self.cruise:
                self.commands += 1
                self.wheel += cmd.torque * WHEEL_DEG_PER_S * dt
                self.speed = max(0.0, self.speed + cmd.accel * dt)
            else:
                self.wheel *= max(0.0, 1 - 2.0 * dt)       # self-centring
                if self.brake:
                    self.speed = max(0.0, self.speed - 4.0 * dt)
            self.wheel = max(-MAX_WHEEL_DEG, min(MAX_WHEEL_DEG, self.wheel))
            road = math.radians(self.wheel / STEER_RATIO)
            self.heading += self.speed / WHEELBASE_M * math.tan(road) * dt
            self.x += self.speed * math.cos(self.heading) * dt
            self.y += self.speed * math.sin(self.heading) * dt

    def pose(self) -> dict:
        with self._lock:
            return {"x_m": round(self.x, 2), "y_m": round(self.y, 2),
                    "heading_deg": round(math.degrees(self.heading), 1),
                    "speed_kph": round(self.speed * 3.6, 1), "wheel_deg": round(self.wheel, 1)}

    def close(self) -> None:
        self.closed = True
