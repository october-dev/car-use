"""Copy a chosen set of opendbc DBC files into car-use (src/car_use/can/dbcs).

opendbc (github.com/commaai/opendbc, MIT) builds some of its DBC files from
pieces, so this runs with a Python that can import opendbc:

    uv venv -p 3.12 /tmp/od && VIRTUAL_ENV=/tmp/od uv pip install opendbc
    /tmp/od/bin/python scripts/vendor_opendbc.py [path/to/opendbc/checkout]

The checkout (optional) is only used to record which commit the files came from.
"""
import os
import subprocess
import sys
from pathlib import Path

import opendbc
from opendbc.dbc.generator.generator import generate_all

# Brands sold in India and Southeast Asia first, then the common US/EU ones.
FILES = [
    "hyundai_can_generated", "hyundai_canfd_generated", "hyundai_2015_ccan",
    "toyota_nodsu_pt_generated", "toyota_new_mc_pt_generated", "toyota_tnga_k_pt_generated",
    "honda_civic_hatchback_ex_2017_can_generated", "honda_bosch_radarless_generated",
    "honda_crv_touring_2016_can_generated",
    "vw_pq", "vw_mqb", "vw_mqbevo",
    "mg", "byd_atto3", "nissan_x_trail_2017_generated", "mazda_2017",
    "tesla_can", "tesla_model3_party", "gm_global_a_powertrain_generated", "subaru_global_2017_generated",
]

src = Path(list(opendbc.__path__)[0]) / "dbc"
out = Path(__file__).resolve().parent.parent / "src" / "car_use" / "can" / "dbcs"
out.mkdir(parents=True, exist_ok=True)
generated = generate_all()
for name in FILES:
    text = generated.get(name)
    if text is None:
        text = (src / f"{name}.dbc").read_text(encoding="utf-8", errors="replace")
    (out / f"{name}.dbc").write_text(text, encoding="utf-8")

commit = "unknown"
if len(sys.argv) > 1:
    commit = subprocess.check_output(["git", "-C", sys.argv[1], "rev-parse", "HEAD"], text=True).strip()
lic = Path(sys.argv[1], "LICENSE") if len(sys.argv) > 1 else None
(out / "LICENSE.opendbc").write_text(lic.read_text() if lic and lic.exists() else
                                     "MIT License. Copyright (c) 2020, Comma.ai, Inc.\n", encoding="utf-8")
(out / "SOURCE.md").write_text(
    "These DBC files come from opendbc (https://github.com/commaai/opendbc), MIT licensed;\n"
    "see LICENSE.opendbc. They are copied unchanged by scripts/vendor_opendbc.py.\n\n"
    f"opendbc version {getattr(opendbc, '__version__', '?')}, commit {commit}.\n\n"
    + "".join(f"- {n}\n" for n in FILES), encoding="utf-8")
print(f"wrote {len(FILES)} DBC files to {out}")
