"""Generate README assets (SVG) for light and dark themes.

    uv run python scripts/make_assets.py [--name car-use]

Re-run after changing the name, colours or copy; outputs go to assets/.
"""
from __future__ import annotations

import argparse
from pathlib import Path

AMBER = "#F5A524"      # check-engine-light amber
AMBER_HI = "#FFD27A"
RED = "#E5484D"
FONT = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
THEMES = {
    "dark": {"fg": "#EDEDED", "muted": "#A1A1A1", "border": "#3A3A3A", "btn_bg": "#0D1117"},
    "light": {"fg": "#111111", "muted": "#555555", "border": "#D0D7DE", "btn_bg": "#FFFFFF"},
}

# Side-view pixel car, 20 x 9 cells: '#' body, 'g' glass, 'w' tyre, 'h' headlight, 't' taillight.
CAR = [
    "......#########.....",
    ".....#ggg#gggggg#...",
    "....#gggg#ggggggg#..",
    ".##################.",
    "t##################h",
    "####################",
    "##.wwww.####.wwww.##",
    "...wwww......wwww...",
    "....ww........ww....",
]
GLASS = "#6B4206"
TYRE = "#B86E00"


def car_rects(x0: float, y0: float, px: float) -> str:
    out = []
    for y, row in enumerate(CAR):
        for x, c in enumerate(row):
            if c == ".":
                continue
            fill = {"#": AMBER, "h": AMBER_HI, "t": RED, "w": TYRE, "g": GLASS}[c]
            cls = ' class="wheel"' if c == "w" else ""
            out.append(f'<rect{cls} x="{x0 + x * px}" y="{y0 + y * px}" width="{px}" height="{px}" fill="{fill}"/>')
    return "\n    ".join(out)


def speed_lines(x_right: float, y0: float, px: float) -> str:
    lines = [(3, 3, 0.0), (4, 5, 0.25), (6, 4, 0.5)]   # (row, length in cells, delay)
    out = []
    for row, length, delay in lines:
        w = length * px
        out.append(f'<rect class="speed" style="animation-delay:{delay}s" x="{x_right - w}" '
                   f'y="{y0 + row * px + px * 0.25}" width="{w}" height="{px * 0.5}" rx="{px * 0.25}" fill="{AMBER}"/>')
    return "\n    ".join(out)


STYLE = """<style>
    .speed { opacity: .15; animation: zoom 1.2s ease-in-out infinite; }
    @keyframes zoom { 0%,100% { opacity: .12; transform: translateX(0); } 50% { opacity: .7; transform: translateX(-6px); } }
    .wheel { animation: bump .6s steps(2) infinite; }
    @keyframes bump { 50% { transform: translateY(-1px); } }
    @media (prefers-reduced-motion: reduce) { .speed, .wheel { animation: none; } }
  </style>"""


def logo(name: str, t: dict) -> str:
    px = 10
    car_x, car_y = 92, 32
    text_x = car_x + len(CAR[0]) * px + 34
    width = text_x + int(len(name) * 52) + 20
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="140" viewBox="0 0 {width} 140" role="img" aria-label="{name}">
  {STYLE}
  <g shape-rendering="crispEdges">
    {speed_lines(car_x - 10, car_y, px)}
    {car_rects(car_x, car_y, px)}
  </g>
  <text x="{text_x}" y="106" font-family="{FONT}" font-size="96" font-weight="800" letter-spacing="-3" fill="{t['fg']}">{name}</text>
</svg>
'''


def tagline(t: dict) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="640" height="52" viewBox="0 0 640 52" role="img" aria-label="Let your agent use your car.">
  <text x="320" y="36" text-anchor="middle" font-family="{FONT}" font-size="32" fill="{t['muted']}">Let your agent use <tspan fill="{AMBER}" font-weight="700">your car.</tspan></text>
</svg>
'''


def button(label: str, icon: str, t: dict, filled: bool, width: int) -> str:
    bg = AMBER if filled else t["btn_bg"]
    stroke = AMBER if filled else t["border"]
    fg = "#111111" if filled else t["fg"]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="40" viewBox="0 0 {width} 40" role="img" aria-label="{label}">
  <rect x="0.5" y="0.5" width="{width - 1}" height="39" rx="6" fill="{bg}" stroke="{stroke}"/>
  <g transform="translate(16 12)" fill="none" stroke="{fg}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{icon}</g>
  <text x="44" y="26" font-family="{FONT}" font-size="16" font-weight="600" fill="{fg}">{label}</text>
</svg>
'''


ICON_BOOK = '<path d="M1 2h6a3 3 0 0 1 3 3v11a2 2 0 0 0-2-2H1z"/><path d="M19 2h-6a3 3 0 0 0-3 3v11a2 2 0 0 1 2-2h7z"/>'
ICON_CAR = '<path d="M2 11l2-6h12l2 6"/><rect x="1" y="11" width="18" height="4" rx="1"/><circle cx="5" cy="16" r="1"/><circle cx="15" cy="16" r="1"/>'
ICON_GLOBE = '<circle cx="10" cy="9" r="8"/><path d="M2 9h16M10 1c2.5 2.5 3.5 5 3.5 8s-1 5.5-3.5 8M10 1C7.5 3.5 6.5 6 6.5 9s1 5.5 3.5 8"/>'
ICON_TERM = '<rect x="1" y="1" width="18" height="15" rx="2"/><path d="M5 6l3 3-3 3M10 12h5"/>'


def callout(t: dict) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="270" height="40" viewBox="0 0 270 40" role="img" aria-label="No car? Diagnose a virtual one, free.">
  <path d="M40 22 C 30 28, 18 26, 8 20" fill="none" stroke="{AMBER}" stroke-width="1.6" stroke-linecap="round"/>
  <path d="M8 20 l7 -1 M8 20 l3 6" fill="none" stroke="{AMBER}" stroke-width="1.6" stroke-linecap="round"/>
  <text x="50" y="17" font-family="{FONT}" font-size="14" fill="{t['muted']}">No car nearby? Diagnose a</text>
  <text x="50" y="34" font-family="{FONT}" font-size="14" fill="{t['muted']}">virtual one, <tspan fill="{AMBER}">no hardware needed.</tspan></text>
</svg>
'''


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="car-use")
    args = ap.parse_args()
    out = Path(__file__).resolve().parents[1] / "assets"
    out.mkdir(exist_ok=True)
    for theme, t in THEMES.items():
        files = {
            f"logo-{theme}.svg": logo(args.name, t),
            f"tagline-{theme}.svg": tagline(t),
            f"button-site-{theme}.svg": button("Website", ICON_GLOBE, t, True, 132),
            f"button-setup-{theme}.svg": button("Setup", ICON_TERM, t, False, 112),
            f"button-skill-{theme}.svg": button("Skill", ICON_BOOK, t, False, 104),
            f"button-sim-{theme}.svg": button("Virtual car", ICON_CAR, t, False, 148),
            f"callout-{theme}.svg": callout(t),
        }
        for fname, body in files.items():
            (out / fname).write_text(body, encoding="utf-8")
    print(f"wrote {len(THEMES) * 7} files to {out}")


if __name__ == "__main__":
    main()
