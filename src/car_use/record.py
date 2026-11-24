"""`car-use record`: log a drive's OBD readings and CAN frames to CSV, with timestamps.

Meant for lining car data up with a dashcam. Every row carries the wall-clock
time (UTC seconds) when the reply reached this computer, so sync this
computer's clock to GPS or NTP before a drive, and start each drive with one
firm brake from walking pace: it shows in the video, in `speed`, and in the
brake message if `can-check` found it.

Files in the recording folder:
  meta.json  what was recorded, with which adapter, how fast, how it ended.
             The car is identified by WMI and model year only, never the VIN.
  obd.csv    t_unix, t_since_start, then one column per OBD signal.
  can.csv    t_unix, t_since_start, burst, id, data (hex). Frames within one
             burst are contiguous; between bursts the adapter was restarting.
  signals.csv  with --decode DBC: t_unix, t_since_start, then speed_kph,
             steering_angle_deg, steering_torque, brake_pressed, gas_pedal,
             left_blinker, right_blinker in real units, up to 50 rows a second.
             Each cell is the latest value heard; empty until first heard.
             With --decode j1939 the columns are the standard J1939 SPNs
             (engine_speed_rpm, coolant_temp_c, ... see can/j1939.py).
  faults.csv   with --decode j1939: t_unix, t_since_start, source, the four
             DM1 lamps, and the active faults, one row each time a source's
             DM1 changes.

One ELM327-class adapter can either ask OBD questions or listen, not both at
once. With both --pids and --can, car-use alternates, which slows both.
"""
from __future__ import annotations

import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, paths
from .obd import pids as P
from .obd import vin as vinmod
from .obd.elm import ElmError
from .obd.monitor import Listener, validate_id
from .transport.base import TransportError

DEFAULT_PIDS = ["speed", "rpm", "throttle", "load", "maf", "map", "coolant"]
CLOCK_NOTE = ("t_unix is this computer's clock (UTC seconds) when the reply arrived. Sync the "
              "clock to GPS or NTP before a drive; Wi-Fi and USB adapters add tens of "
              "milliseconds of delay. t_since_start is monotonic seconds since recording began.")


class RecordError(ValueError):
    pass


def default_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return paths.ensure("recordings") / stamp


class Recorder:
    def __init__(self, vehicle, out_dir: Path | str | None = None, pids: list[str] | None = None,
                 can: bool = False, can_ids: list[str] | None = None, label: str = "",
                 can_slice: float | None = None, say=None, decode: str | None = None):
        self.v = vehicle
        self.elm = vehicle.elm
        self.out = Path(out_dir) if out_dir else default_dir()
        self.decoder = None
        self.j1939 = decode == "j1939"
        if self.j1939:
            from .can.j1939 import Decoder as J1939Decoder
            self.decoder = J1939Decoder()     # the whole bus: J1939 data is spread over many PGNs
        elif decode:
            from .can.library import Decoder
            try:
                self.decoder = Decoder(decode)
            except KeyError as e:
                raise RecordError(str(e.args[0])) from None
            if not self.decoder.spec:
                raise RecordError(f"{decode} has no steering/brake/speed map yet; record raw "
                                  "frames with --can and decode them later.")
            if not can and not can_ids:
                # Listen only to the messages the signals live on, so even a slow
                # adapter keeps up with them.
                can_ids = self.decoder.ids()
        self.can = bool(can or can_ids)
        self.can_ids = [validate_id(i) for i in can_ids] if can_ids else []
        self.label = label
        self._can_slice = can_slice
        self.say = say or (lambda text: None)
        self._unsupported: list[str] = []
        if self.can and not self.elm.info.is_can:
            raise RecordError("This car does not use CAN on the OBD port (protocol "
                              f"{self.elm.info.protocol or 'unknown'}), so there is nothing to "
                              "listen to. Record OBD readings without --can.")
        self.pids = self._choose_pids(pids, explicit=pids is not None)
        if not self.pids and not self.can:
            raise RecordError("None of the chosen OBD signals answer on this car.")
        # Alone, listen in one-second bursts; mixed with OBD, in short slices so
        # neither stream starves the other.
        self.can_slice = self._can_slice or (0.25 if self.pids else 1.0)

    def _choose_pids(self, wanted: list[str] | None, explicit: bool) -> list[str]:
        if wanted is None:
            if self.can:
                return []
            wanted = DEFAULT_PIDS
        names = []
        for n in wanted:
            try:
                P.resolve(n)
            except KeyError:
                raise RecordError(f"Unknown OBD signal {n!r}. See signals() for this car's "
                                  "names.") from None
            names.append(n)
        supported = self.v.supported_pids()
        keep = [n for n in names if P.resolve(n)[0].pid in supported]
        self._unsupported = [n for n in names if n not in keep]
        if explicit and self._unsupported:
            self.say("not on this car, skipped: " + ", ".join(self._unsupported))
        return keep

    # ---------------------------------------------------------------------------
    def meta(self) -> dict:
        decoded = vinmod.decode(self.v.vin) if self.v.vin else {}
        info = self.elm.info
        units = {n: P.resolve(n)[2].unit for n in self.pids}
        return {
            "schema": 1,
            "source": "car-use record",
            "car_use_version": __version__,
            "label": self.label or None,
            "simulated": getattr(self.v, "scenario", None) is not None,
            "vehicle": {"wmi": decoded.get("wmi"), "model_year": decoded.get("model_year"),
                        "manufacturer": decoded.get("manufacturer"),
                        "protocol": info.protocol},
            "adapter": {"identity": info.identity, "stn": info.stn},
            "clock": CLOCK_NOTE,
            "obd": ({"file": "obd.csv", "signals": self.pids, "units": units}
                    if self.pids else None),
            "can": ({"file": "can.csv", "ids_filter": self.can_ids or None} if self.can else None),
            "decoded": (_decoded_meta(self.decoder.name) if self.decoder else None),
            "skipped_signals": self._unsupported or None,
        }

    def run(self, seconds: float | None = None, progress_every: float = 10.0) -> dict:
        """Record until `seconds` pass, Ctrl-C, or the adapter goes away."""
        self.out.mkdir(parents=True, exist_ok=True)
        meta = self.meta()
        started = time.time()
        meta["started_utc"] = datetime.fromtimestamp(started, timezone.utc).isoformat()
        meta["ended"] = "recording"
        self._write_meta(meta)
        obd_f = (self.out / "obd.csv").open("w", newline="", encoding="utf-8") if self.pids else None
        can_f = (self.out / "can.csv").open("w", newline="", encoding="utf-8") if self.can else None
        sig_f = (self.out / "signals.csv").open("w", newline="", encoding="utf-8") if self.decoder else None
        sig_w = csv.writer(sig_f) if sig_f else None
        flt_f = (self.out / "faults.csv").open("w", newline="", encoding="utf-8") if self.j1939 else None
        flt_w = csv.writer(flt_f) if flt_f else None
        if sig_w:
            sig_w.writerow(["t_unix", "t_since_start", *columns_for(self.decoder.name)])
        if flt_w:
            from .can.j1939 import FAULT_COLUMNS
            flt_w.writerow(["t_unix", "t_since_start", *FAULT_COLUMNS])
        last_row = -1.0
        obd_w = csv.writer(obd_f) if obd_f else None
        can_w = csv.writer(can_f) if can_f else None
        if obd_w:
            obd_w.writerow(["t_unix", "t_since_start", *self.pids])
        if can_w:
            can_w.writerow(["t_unix", "t_since_start", "burst", "id", "data"])
        t0 = time.monotonic()
        rows = frames = bursts = buffer_full = 0
        ids: set[str] = set()
        ended = "time limit"
        error = None
        next_progress = t0 + progress_every
        listener = None
        try:
            if self.can and not self.pids:
                listener = Listener(self.elm, self.can_ids).__enter__()
            while True:
                now = time.monotonic()
                if seconds is not None and now - t0 >= seconds:
                    break
                if obd_w:
                    vals = self.v.read_many(self.pids)
                    first = next(iter(vals.values()))
                    mono = time.monotonic()
                    obd_w.writerow([f"{first.ts:.3f}", f"{mono - t0:.3f}",
                                    *[_cell(vals[n].value) for n in self.pids]])
                    obd_f.flush()
                    rows += 1
                if can_w:
                    left = None if seconds is None else seconds - (time.monotonic() - t0)
                    if left is not None and left <= 0:
                        break
                    slice_s = self.can_slice if left is None else min(self.can_slice, left)
                    if listener is not None:
                        lst, before = listener, listener.capture.buffer_full
                        got = lst.burst(slice_s)
                    else:
                        with Listener(self.elm, self.can_ids) as lst:
                            before, got = 0, lst.burst(slice_s)
                    if lst.capture.unsupported:
                        raise RecordError("This adapter cannot listen (no ATMA). Use an OBDLink "
                                          "or a genuine ELM327, or record without --can.")
                    bursts += 1
                    buffer_full += lst.capture.buffer_full - before
                    for f in got:
                        can_w.writerow([f"{f.wall:.3f}", f"{f.mono - t0:.3f}", bursts, f.id,
                                        f.data.hex().upper()])
                        ids.add(f.id)
                        if self.decoder:
                            last_row = _write_decoded(self.decoder, f.id, f.data, f.mono,
                                                      f"{f.wall:.3f}", f"{f.mono - t0:.3f}",
                                                      last_row, sig_w, flt_w)
                    frames += len(got)
                    can_f.flush()
                    for fh in (sig_f, flt_f):
                        if fh:
                            fh.flush()
                if time.monotonic() >= next_progress:
                    next_progress += progress_every
                    self.say(_progress(time.monotonic() - t0, rows, frames, len(ids)))
        except KeyboardInterrupt:
            ended = "stopped by you"
        except (TransportError, ElmError) as e:
            ended = f"adapter lost: {e}"
        except RecordError as e:
            ended, error = "error", str(e)
        finally:
            if listener is not None:
                try:
                    listener.__exit__(None, None, None)
                except (TransportError, ElmError):
                    pass
            for fh in (obd_f, can_f, sig_f, flt_f):
                if fh:
                    fh.close()
        elapsed = time.monotonic() - t0
        meta["ended"] = ended
        meta["error"] = error
        meta["summary"] = {
            "seconds": round(elapsed, 1),
            "obd_rows": rows if self.pids else None,
            "obd_rows_per_s": round(rows / elapsed, 2) if self.pids and elapsed else None,
            "can_frames": frames if self.can else None,
            "can_frames_per_s": round(frames / elapsed, 1) if self.can and elapsed else None,
            "can_ids": sorted(ids) if self.can else None,
            "can_bursts": bursts if self.can else None,
            "can_buffer_full": buffer_full if self.can else None,
            "decoded_frames": self.decoder.decoded if self.decoder else None,
        }
        if self.j1939:
            meta["summary"]["j1939"] = _j1939_summary(self.decoder)
        self._write_meta(meta)
        meta["folder"] = str(self.out)
        return meta

    def _write_meta(self, meta: dict) -> None:
        (self.out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


SIGNAL_UNITS = {"speed_kph": "km/h", "steering_angle_deg": "degrees, left positive on most cars",
                "steering_torque": "the car's own units (see the DBC)", "brake_pressed": "0/1",
                "gas_pedal": "the car's own units (see the DBC)", "left_blinker": "0/1",
                "right_blinker": "0/1"}


def decode_folder(folder: Path | str, dbc: str) -> dict:
    """Decode an earlier recording's can.csv into signals.csv with a DBC map, or
    with `dbc="j1939"` into J1939 signals.csv and faults.csv."""
    folder = Path(folder)
    src = folder / "can.csv"
    if not src.exists():
        raise RecordError(f"{src} not found: record with --can first.")
    if dbc == "j1939":
        from .can.j1939 import Decoder as J1939Decoder, FAULT_COLUMNS
        dec = J1939Decoder()
    else:
        from .can.library import Decoder
        try:
            dec = Decoder(dbc)
        except KeyError as e:
            raise RecordError(str(e.args[0])) from None
    rows = 0
    last = -1.0
    flt_f = (folder / "faults.csv").open("w", newline="", encoding="utf-8") if dbc == "j1939" else None
    flt_w = csv.writer(flt_f) if flt_f else None
    if flt_w:
        flt_w.writerow(["t_unix", "t_since_start", *FAULT_COLUMNS])
    try:
        with src.open(newline="", encoding="utf-8") as fin, \
                (folder / "signals.csv").open("w", newline="", encoding="utf-8") as fout:
            w = csv.writer(fout)
            w.writerow(["t_unix", "t_since_start", *columns_for(dbc)])
            for r in csv.DictReader(fin):
                t = float(r["t_since_start"])
                before = last
                last = _write_decoded(dec, r["id"], bytes.fromhex(r["data"]), t, r["t_unix"],
                                      r["t_since_start"], last, w, flt_w)
                rows += last != before
    finally:
        if flt_f:
            flt_f.close()
    meta_p = folder / "meta.json"
    if meta_p.exists():
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        meta["decoded"] = {**_decoded_meta(dbc), "decoded_frames": dec.decoded}
        meta_p.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    out = {"folder": str(folder), "dbc": dbc, "rows": rows, "decoded_frames": dec.decoded}
    if dbc == "j1939":
        out["j1939"] = _j1939_summary(dec)
    return out


def columns_for(dbc: str) -> dict:
    if dbc == "j1939":
        from .can.j1939 import UNITS
        return UNITS
    return SIGNAL_UNITS


def _decoded_meta(dbc: str) -> dict:
    if dbc == "j1939":
        from .can.j1939 import FAULT_COLUMNS
        return {"file": "signals.csv", "dbc": "j1939",
                "source": "SAE J1939-71 standard parameters, decoded by car-use",
                "columns": columns_for(dbc), "faults_file": "faults.csv",
                "faults_columns": FAULT_COLUMNS}
    return {"file": "signals.csv", "dbc": dbc, "source": "opendbc (MIT), bundled with car-use",
            "columns": SIGNAL_UNITS}


def _write_decoded(dec, ident: str, data: bytes, t: float, t_unix: str, t_rel: str,
                   last_row: float, sig_w, flt_w) -> float:
    """Feed one frame; write a signals row (at most 50 a second) and, for J1939,
    a faults row when a DM1 changes. Returns the time of the last signals row."""
    if flt_w is None:
        if dec.feed(ident, data) is not None and t - last_row >= 0.02:
            sig_w.writerow([t_unix, t_rel, *[_cell(v) for v in dec.row().values()]])
            return t
        return last_row
    got = dec.feed(ident, data, t)
    if got is None:
        return last_row
    if "dm1" in got:
        if got["changed"]:
            from .can.j1939 import dm1_row
            flt_w.writerow([t_unix, t_rel, *dm1_row(got["dm1"])])
        return last_row
    if t - last_row >= 0.02:
        sig_w.writerow([t_unix, t_rel, *[_cell(v) for v in dec.row().values()]])
        return t
    return last_row


def _j1939_summary(dec) -> dict:
    snap = dec.snapshot()
    return {"signals": {k: v["value"] for k, v in snap["signals"].items()},
            "faults": [f["text"] + f" (source {f['source']:02X})" for f in snap["faults"]],
            "dm1_changes": dec.dm1_changes, "transport": snap["transport"],
            "pgns": snap["pgns"]}


def _cell(value) -> str:
    return "" if value is None else f"{value:g}"


def _progress(seconds: float, rows: int, frames: int, ids: int) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    parts = [f"recording {h:02d}:{m:02d}:{s:02d}"]
    if rows:
        parts.append(f"{rows} OBD rows ({rows / seconds:.1f}/s)")
    if frames:
        parts.append(f"{frames} CAN frames from {ids} ids")
    return " · ".join(parts)
