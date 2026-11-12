"""Engine logs: MegaLogViewer .msl (tab-separated) and CSV exports.

Both look like: optional header lines, a row of column names, often a row of
units, then numbers. We find the name row by looking for the first row that is
followed by numeric data.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Log:
    columns: list[str]
    units: list[str]
    rows: list[list[float | None]]
    header: list[str] = field(default_factory=list)
    path: str = ""

    def column(self, name: str) -> list[float]:
        i = self._index(name)
        return [r[i] for r in self.rows if i < len(r) and r[i] is not None]

    def _index(self, name: str) -> int:
        low = [c.lower() for c in self.columns]
        if name.lower() not in low:
            raise KeyError(f"No column {name!r}. Columns: {', '.join(self.columns[:30])}")
        return low.index(name.lower())

    def duration(self) -> float | None:
        for t in ("Time", "time", "Time (s)", "Seconds"):
            if t.lower() in [c.lower() for c in self.columns]:
                v = self.column(t)
                return round(v[-1] - v[0], 3) if len(v) > 1 else None
        return None

    def stats(self, name: str) -> dict:
        v = self.column(name)
        if not v:
            return {"n": 0}
        return {"n": len(v), "min": min(v), "max": max(v), "mean": round(statistics.fmean(v), 3)}

    def summary(self) -> dict:
        cols = {}
        for i, c in enumerate(self.columns[:40]):
            unit = self.units[i] if i < len(self.units) else ""
            s = self.stats(c)
            cols[c] = {"unit": unit, **s}
        return {"rows": len(self.rows), "duration_s": self.duration(), "header": self.header[:5],
                "columns": cols}


def _num(s: str) -> float | None:
    s = s.strip().strip('"')
    try:
        return float(s)
    except ValueError:
        return None


def _numeric_row(cells: list[str]) -> bool:
    vals = [c for c in cells if c.strip()]
    return bool(vals) and sum(_num(c) is not None for c in vals) >= 0.8 * len(vals)


def parse(text: str, path: str = "") -> Log:
    lines = [ln.rstrip("\r\n") for ln in text.splitlines()]
    sample = "\n".join(lines[:50])
    sep = "\t" if "\t" in sample else ("," if sample.count(",") >= sample.count(";") else ";")
    cells = [[c.strip().strip('"') for c in ln.split(sep)] for ln in lines]
    for i, row in enumerate(cells):
        if len(row) < 2 or _numeric_row(row):
            continue
        nxt = cells[i + 1] if i + 1 < len(cells) else []
        nxt2 = cells[i + 2] if i + 2 < len(cells) else []
        if _numeric_row(nxt) and len(nxt) >= len(row) - 1:
            units, start = [], i + 1
        elif _numeric_row(nxt2) and len(nxt) == len(row):
            units, start = nxt, i + 2
        else:
            continue
        rows = [[_num(c) for c in r] for r in cells[start:] if _numeric_row(r)]
        return Log(columns=row, units=units, rows=rows,
                   header=[ln.strip().strip('"') for ln in lines[:i] if ln.strip()], path=path)
    raise ValueError("Could not find a header row followed by numeric data")


def load_log(path: str | Path) -> Log:
    p = Path(path)
    if p.suffix.lower() == ".mlg":
        raise ValueError("Binary .mlg logs aren't supported yet. In MegaLogViewer or TunerStudio, "
                         "export the log as .msl or CSV and pass that.")
    return parse(p.read_text(encoding="utf-8", errors="replace"), str(p))
