"""~/.car-use/config.toml: flat key = "value" settings."""
from __future__ import annotations

import os
import tomllib

from . import paths

KEYS = {"device": "Adapter URL: tcp://192.168.0.10:35000, serial:///dev/cu.X?baud=38400, sim:p0420"}


def load() -> dict:
    p = paths.home() / "config.toml"
    if not p.exists():
        return {}
    return tomllib.loads(p.read_text(encoding="utf-8"))


def get(key: str, default=None):
    env = os.environ.get(f"CAR_USE_{key.upper()}")
    if env:
        return env
    return load().get(key, default)


def set_(key: str, value: str) -> None:
    if key not in KEYS:
        raise KeyError(f"Unknown setting {key!r}. Known: {', '.join(KEYS)}")
    data = load()
    data[key] = value
    paths.ensure()
    body = "".join(f'{k} = "{v}"\n' for k, v in sorted(data.items()))
    (paths.home() / "config.toml").write_text(body, encoding="utf-8")
