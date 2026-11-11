"""Where car-use keeps state. CAR_USE_HOME overrides ~/.car-use."""
from __future__ import annotations

import os
from pathlib import Path


def home() -> Path:
    return Path(os.environ.get("CAR_USE_HOME", Path.home() / ".car-use")).expanduser()


def ensure(sub: str = "") -> Path:
    p = home() / sub if sub else home()
    p.mkdir(parents=True, exist_ok=True)
    return p
