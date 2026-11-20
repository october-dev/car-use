"""Motion control: steering, gas and brake, through opendbc and a comma panda.

Off by default and off for every car until its owner turns it on. Turning it
on is tier T4: a person at an interactive terminal runs

    car-use control enable

confirms the car (last six VIN characters) and types the acknowledgement
sentence in ACKNOWLEDGEMENT word for word. Every session then asks again at
the terminal before the first command is sent. An agent cannot turn it on,
and there is no flag or environment variable that skips either prompt.

Who does what:
  - opendbc (github.com/commaai/opendbc, MIT) knows each supported car's
    steering and gas/brake messages and its tuning limits.
  - The panda's firmware (github.com/commaai/panda, MIT) runs opendbc's
    safety model: it only lets commands through while the driver has engaged
    the car's own cruise control, cuts them the moment the driver brakes,
    and caps steering torque and its rate of change. car-use never changes
    or bypasses that firmware.
  - car-use adds the owner's consent, a dead-man timer (no fresh command for
    0.3 s means hands off), a speed cap for gas, disengaging on any driver
    input, and the audit log.

Practice on the simulator first: `car-use control demo --sim`.
"""
from .session import (ACKNOWLEDGEMENT, Command, ControlError, ControlSession, State,
                      open_session)

__all__ = ["ACKNOWLEDGEMENT", "Command", "ControlError", "ControlSession", "State", "open_session"]
