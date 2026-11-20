# Motion control

car-use can steer, accelerate and brake a supported car through comma's
[opendbc](https://github.com/commaai/opendbc) and a
[comma panda](https://github.com/commaai/panda). It is **off for every car**
until the car's owner turns it on. This page is for that owner.

## Before you turn it on

- You are the driver the whole time. You sit in the driver's seat with your
  hands near the wheel and your foot ready.
- Only use it where that is legal. Start on closed, empty ground.
- It works on [cars opendbc supports](https://github.com/commaai/opendbc/blob/master/docs/CARS.md),
  usually ones with lane-keep assist. On many, opendbc controls only steering;
  `car-use control check` and the session's status say whether gas and brake work too.
- Changing how a car steers or brakes may affect its warranty or insurance.

## What you need

- A comma panda (red or black panda, or a comma device's panda), connected
  to the car the way comma describes for your model. An ELM327 can't do this:
  it can't send at 100 Hz and doesn't run the safety firmware.
- Python 3.12 and comma's packages, which aren't usable from PyPI:

```bash
pip install "pandacan @ git+https://github.com/commaai/panda"
car-use control check
```

## Turning it on

```bash
car-use control demo --sim      # practise on a virtual car first
car-use control enable          # reads the VIN through your OBD adapter, or add --vin
```

`enable` must be run by you at an interactive terminal. It asks for the last
six characters of the VIN, shows what the tier allows, and asks you to type
this sentence exactly:

> I am the driver, I keep my hands on the wheel and my foot ready, and I take full responsibility for what this car does

Both answers go into the audit log. Then, every time an agent opens a control
session, car-use asks you again at the terminal before anything is sent.
`car-use control disable` turns it off.

## What stops it

| Layer | What it does |
|---|---|
| panda firmware (opendbc safety) | Commands only pass while you have engaged the car's own cruise control. Braking cancels that at once. Steering torque and how fast it changes are capped per car. |
| opendbc | Sends each car's own steering and gas/brake messages, within that car's tuned limits. |
| car-use | Your consent per car and per session. A 100 Hz loop that drops any command older than 0.3 s. Any brake, gas or wheel input from you disarms the session until the agent arms it again. No gas at or above your speed cap (`car-use config set control_max_kph 40`). Everything in the audit log. |

## For agents

```python
with control() as c:            # control(device="sim") to practise
    c.arm()                     # waits for the driver to engage cruise
    c.hold(2.0, torque=0.2)     # steer gently left for 2 s (-1..1, positive is left)
    c.hold(1.0, accel=0.5)      # m/s^2, only if c.status().can_accel
    print(c.status())
```

Angle-steered cars (Tesla, some Fords) use `steer(angle=deg)` instead of
`torque`. SKILL.md has the rules agents follow.

## Status

Tested against the simulator and against opendbc's own car code (it produces
each car's steering messages from car-use's commands). It has not been run on
a real car with a panda yet. If you do, please open an issue with what happened.
