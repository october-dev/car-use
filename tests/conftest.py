import pytest

from car_use.connect import open_vehicle
from car_use.kernel.policy import Kernel


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CAR_USE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CAR_USE_DEVICE", raising=False)
    yield tmp_path / "home"


@pytest.fixture
def sim():
    opened = []

    def _open(name, confirm=None):
        v = open_vehicle(f"sim:{name}", kernel=Kernel(confirm=confirm or (lambda q, e: False)))
        opened.append(v)
        return v
    yield _open
    for v in opened:
        v.elm.close()
        v._emulator.stop()
