"""Maker packs: what an agent should know about a car maker before poking at the car.

Each pack is Markdown with a small TOML header between +++ lines:

    +++
    make = "Toyota"
    aliases = ["lexus"]
    wmi = ["4T1", "2T1", "JTD"]     # first 3 VIN characters that map here
    updated = "2026-11-12"
    +++

Every fact in a pack carries a confidence tag:
    [verified]  checked against the source given next to it
    [common]    widely known among technicians; no single source
    [unverified] a lead to check, not a fact; the agent must say so if it uses it

Packs never contain guessed Mode 22 / UDS identifiers. Add a DID only with the
capture or document it came from (VIN prefix, model year, request, response).
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path


@dataclass
class Pack:
    make: str
    aliases: list[str]
    wmi: list[str]
    updated: str
    text: str
    path: str


def _dir() -> Path:
    return Path(str(resources.files("car_use.makers") / "packs"))


def _parse(p: Path) -> Pack:
    raw = p.read_text(encoding="utf-8")
    _, head, body = raw.split("+++", 2)
    h = tomllib.loads(head)
    return Pack(make=h["make"], aliases=[a.lower() for a in h.get("aliases", [])],
                wmi=[w.upper() for w in h.get("wmi", [])], updated=h.get("updated", ""),
                text=body.strip(), path=str(p))


def packs() -> list[Pack]:
    return [_parse(p) for p in sorted(_dir().glob("*.md"))]


def available() -> list[str]:
    return [p.make for p in packs()]


def find(query: str) -> Pack | None:
    """By VIN (17 chars, matched on its WMI), make name or alias."""
    q = query.strip()
    all_packs = packs()
    if len(q) == 17:
        wmi = q[:3].upper()
        for p in all_packs:
            if wmi in p.wmi:
                return p
        from ..obd.vin import WMI
        maker = WMI.get(wmi, "")
        q = maker.split(" (")[0] if maker else q
    ql = q.lower()
    for p in all_packs:
        if ql == p.make.lower() or ql in p.aliases or p.make.lower() in ql:
            return p
    return None
