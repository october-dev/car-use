"""The car-use CLI: run Python from stdin with helpers pre-imported."""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from . import __version__

USAGE = """Usage:
  car-use [--sim SCENARIO | --device URL] <<'PY'
  print(car().describe())
  print(dtcs())
  PY

Commands:
  car-use skill                    print the agent skill (SKILL.md)
  car-use doctor [--sim S]         check setup and the connection to the car
  car-use dongle-doctor [--report] characterise the adapter; --report is anonymised JSON
  car-use scenarios                list simulator scenarios
  car-use sim [SCENARIO] [--port 35000]   serve a virtual car on TCP (foreground)
  car-use config set device URL    tcp://192.168.0.10:35000 | serial:///dev/cu.X?baud=38400 | sim:p0420
  car-use policy show|enable TIER|disable TIER    per-vehicle tiers (enable needs a person)
  car-use audit [--verify]         show or verify the audit log
  car-use bench list|run|grade     CarsBench: score an agent on virtual cars (bench/README.md)
  car-use maker [MAKE|VIN]         what car-use knows about a car maker
  car-use ecu ini FILE             summarise a TunerStudio .ini (tables, live channels)
  car-use ecu log FILE             summarise an .msl / .csv engine log
  car-use --version
"""


def _skill_text() -> str:
    from importlib import resources
    try:
        f = resources.files("car_use") / "SKILL.md"
        if f.is_file():
            return f.read_text(encoding="utf-8")
    except (ModuleNotFoundError, TypeError):
        pass
    return (Path(__file__).resolve().parents[2] / "SKILL.md").read_text(encoding="utf-8")


def _device(args) -> str | None:
    if getattr(args, "sim", None):
        return f"sim:{args.sim}"
    return getattr(args, "device", None)


def _jsonable(obj):
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)


def run_script(code: str, device: str | None) -> int:
    from . import helpers
    helpers._configure(device)
    ns = {"__name__": "__car_use__", "json": json}
    import math, time   # noqa: E401  (convenience for scripts)
    ns.update(math=math, time=time)
    ns.update({n: getattr(helpers, n) for n in helpers.__all__})
    try:
        exec(compile(code, "<car-use script>", "exec"), ns)
        return 0
    except SystemExit as e:
        return int(e.code or 0)
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        script_frames = [f for f in tb if f.filename == "<car-use script>"]
        where = f" (script line {script_frames[-1].lineno})" if script_frames else ""
        print(f"error{where}: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        helpers._shutdown()


def cmd_doctor(args) -> int:
    from .connect import open_vehicle, NoDevice
    from .transport.base import TransportError
    from .obd.elm import ElmError
    print(f"car-use {__version__}  python {sys.version.split()[0]}")
    try:
        v = open_vehicle(_device(args))
    except NoDevice as e:
        print(f"no device: {e}")
        return 1
    except (TransportError, ElmError, OSError) as e:
        print(f"cannot connect: {e}")
        return 1
    try:
        d = v.describe()
        for k, val in d.items():
            print(f"{k:>10}: {val}")
        if not v.elm.info.protocol_number or v.elm.info.protocol_number in ("0", "A0"):
            print("    status: adapter answers but the car does not. Turn the ignition on "
                  "(engine running is best) and run doctor again.")
            return 1
        print(f"   signals: {len(v.signals())} live signals available")
        print("    status: ready")
        return 0
    except (TransportError, ElmError) as e:
        print(f"    status: {e}")
        return 1
    finally:
        v.elm.close()
        if getattr(v, "_emulator", None):
            v._emulator.stop()


def cmd_dongle_doctor(args) -> int:
    if getattr(args, "report", False):
        from .connect import open_vehicle, NoDevice
        from .doctor.report import field_soak_seconds, share_report
        from .transport.base import TransportError
        from .obd.elm import ElmError
        try:
            v = open_vehicle(_device(args))
        except NoDevice as e:
            print(f"no device: {e}")
            return 1
        except (TransportError, ElmError, OSError) as e:
            print(f"status: {e}")
            return 1
        try:
            try:
                rep = share_report(
                    v.elm, v,
                    soak_requests=args.soak_requests,
                    soak_seconds=field_soak_seconds(args.soak_seconds),
                    current_ma=args.current_ma,
                )
            except ValueError as e:
                print(f"report refused: {e}")
                return 1
        finally:
            v.elm.close()
            if getattr(v, "_emulator", None):
                v._emulator.stop()
        text = json.dumps(rep, indent=2)
        if args.out:
            Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0
    code = "rep = dongle_doctor()\nprint(json.dumps(rep, indent=2))\n"
    return run_script(code, _device(args))


def cmd_sim(args) -> int:
    from .sim.emulator import Emulator
    from .sim.scenario import load
    s = load(args.scenario)
    emu = Emulator(s, host=args.host, port=args.port)
    print(f"virtual car '{s.title}' ({s.name}, adapter profile "
          f"{s.adapter.get('profile', 'genuine')}) on {emu.url}  ctrl-c to stop", flush=True)
    try:
        emu.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def cmd_policy(args) -> int:
    from .kernel import policy
    if args.action == "show":
        pol = policy.load_policy()
        print(json.dumps(pol or {"vehicles": {}}, indent=2))
        return 0
    vin = args.vin
    if not vin:
        from .connect import open_vehicle
        v = open_vehicle(_device(args))
        vin = v.vin
        v.elm.close()
    if not vin:
        print("Could not read the VIN; pass --vin.")
        return 1
    print(policy.set_tier(vin, args.tier, args.action == "enable"))
    return 0


def cmd_audit(args) -> int:
    from .kernel.policy import Audit
    a = Audit()
    if args.verify:
        ok, msg = a.verify()
        print(("ok: " if ok else "TAMPERED: ") + msg)
        return 0 if ok else 2
    if a.path.exists():
        lines = a.path.read_text(encoding="utf-8").splitlines()[-args.n:]
        print("\n".join(lines))
    return 0


def cmd_bench(args) -> int:
    from .bench import load_tasks
    from .bench.runner import run_task, summarize, table
    if args.action == "list":
        for t in load_tasks(args.tasks):
            print(f"{t.id:<20} {t.family:<16} {t.prompt[:70]}")
        return 0
    if args.action == "grade":
        from .bench.grade import grade, parse_answer
        run = Path(args.run)
        tasks = {t.id: t for t in load_tasks(args.tasks)}
        results = []
        for d in sorted(p for p in run.iterdir() if p.is_dir()):
            base = d.name.split("~")[0]
            if base not in tasks:
                continue
            log = [json.loads(x) for x in (d / "requests.jsonl").read_text().splitlines() if x]
            r = grade(tasks[base], parse_answer((d / "stdout.txt").read_text()), log)
            old = json.loads((d / "result.json").read_text()) if (d / "result.json").exists() else {}
            r.update({k: old[k] for k in ("seconds", "status", "harness") if k in old})
            results.append(r)
        print(table(results))
        old = json.loads((run / "summary.json").read_text()) if (run / "summary.json").exists() else {}
        summary = {**old.get("summary", {}), **summarize(results)}
        (run / "summary.json").write_text(json.dumps({"summary": summary, "results": results}, indent=2))
        print(f"\nregraded; wrote {run / 'summary.json'}")
        return 0
    if not args.agent:
        print("Pass --agent 'COMMAND' (prompt on stdin, or {prompt} in the command), or --agent null.")
        return 1
    import time as _t
    out = Path(args.out or f"bench-runs/{_t.strftime('%Y%m%d-%H%M%S')}-{args.harness}")
    tasks = load_tasks(args.tasks, args.only.split(",") if args.only else None)
    results, by_task = [], {}
    for t in tasks:
        for i in range(args.k):
            sub = out if args.k == 1 else out / f"try{i + 1}"
            r = run_task(t, args.agent, harness=args.harness, timeout=args.timeout, out_dir=sub)
            results.append(r)
            by_task.setdefault(t.id, []).append(r["passed"])
            print(f"  {t.id}: {'pass' if r['passed'] else 'fail'} (score {r['score']}, {r['status']})",
                  flush=True)
    print()
    print(table(results))
    summary = summarize(results)
    summary.update(agent=args.agent, harness=args.harness, k=args.k,
                   pass_hat_k=sum(all(v) for v in by_task.values()))
    if args.k > 1:
        print(f"pass^{args.k}: {summary['pass_hat_k']}/{len(by_task)} tasks passed every try")
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps({"summary": summary, "results": results}, indent=2))
    print(f"\nsaved to {out}/")
    return 0


def cmd_maker(args) -> int:
    from .makers import find, available
    if not args.query:
        print("Maker packs: " + ", ".join(available()))
        return 0
    pack = find(args.query)
    if pack is None:
        print(f"No maker pack for {args.query!r}. Packs: {', '.join(available())}")
        return 1
    print(pack.text)
    return 0


def cmd_ecu(args) -> int:
    if args.action == "ini":
        from .ecu.tsini import load
        print(json.dumps(load(args.file).summary(), indent=2))
        return 0
    from .ecu.logs import load_log
    print(json.dumps(load_log(args.file).summary(), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    p = argparse.ArgumentParser(prog="car-use", add_help=False)
    p.add_argument("--sim")
    p.add_argument("--device")
    p.add_argument("--version", "-V", action="store_true")
    p.add_argument("--help", "-h", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("skill")
    sp = sub.add_parser("doctor")
    sp.add_argument("--sim")
    sp.add_argument("--device")
    sp = sub.add_parser("dongle-doctor")
    sp.add_argument("--sim")
    sp.add_argument("--device")
    sp.add_argument("--report", action="store_true",
                    help="print an anonymised JSON report (WMI and model year only)")
    sp.add_argument("--out", help="also write the report JSON to this path")
    sp.add_argument("--soak-requests", type=int, default=30)
    sp.add_argument("--soak-seconds", type=float, default=None,
                    help="soak length in seconds; --report defaults to 600")
    sp.add_argument("--current-ma", type=float, default=None,
                    help="ignition-off current from a meter; car-use does not measure it")
    sub.add_parser("scenarios")
    sp = sub.add_parser("sim")
    sp.add_argument("scenario", nargs="?", default="healthy")
    sp.add_argument("--port", type=int, default=35000)
    sp.add_argument("--host", default="127.0.0.1")
    sp = sub.add_parser("config")
    sp.add_argument("action", choices=["set", "get"])
    sp.add_argument("key")
    sp.add_argument("value", nargs="?")
    sp = sub.add_parser("policy")
    sp.add_argument("action", choices=["show", "enable", "disable"])
    sp.add_argument("tier", nargs="?", default="")
    sp.add_argument("--vin")
    sp.add_argument("--sim")
    sp.add_argument("--device")
    sp = sub.add_parser("audit")
    sp.add_argument("--verify", action="store_true")
    sp.add_argument("-n", type=int, default=20)
    sp = sub.add_parser("bench")
    sp.add_argument("action", choices=["list", "run", "grade"])
    sp.add_argument("run", nargs="?", help="run directory (for grade)")
    sp.add_argument("--agent")
    sp.add_argument("--harness", choices=["car-use", "bare"], default="car-use")
    sp.add_argument("--tasks")
    sp.add_argument("--only")
    sp.add_argument("-k", type=int, default=1)
    sp.add_argument("--timeout", type=float, default=600)
    sp.add_argument("--out")
    sp = sub.add_parser("maker")
    sp.add_argument("query", nargs="?")
    sp = sub.add_parser("ecu")
    sp.add_argument("action", choices=["ini", "log"])
    sp.add_argument("file")

    args = p.parse_args(argv)
    if args.version:
        print(f"car-use {__version__}")
        return 0
    if args.help:
        print(USAGE)
        return 0
    if args.cmd == "skill":
        sys.stdout.write(_skill_text())
        return 0
    if args.cmd == "doctor":
        return cmd_doctor(args)
    if args.cmd == "dongle-doctor":
        return cmd_dongle_doctor(args)
    if args.cmd == "scenarios":
        from .sim.scenario import available, load
        for n in sorted(available()):
            print(f"{n:<16} {load(n).title}")
        return 0
    if args.cmd == "sim":
        return cmd_sim(args)
    if args.cmd == "config":
        from . import config
        if args.action == "set":
            config.set_(args.key, args.value or "")
            print(f"{args.key} = {args.value}")
        else:
            print(config.get(args.key, ""))
        return 0
    if args.cmd == "policy":
        if args.action != "show" and not args.tier:
            print("Name a tier, e.g. car-use policy enable T1D")
            return 1
        return cmd_policy(args)
    if args.cmd == "audit":
        return cmd_audit(args)
    if args.cmd == "bench":
        return cmd_bench(args)
    if args.cmd == "maker":
        return cmd_maker(args)
    if args.cmd == "ecu":
        return cmd_ecu(args)
    if sys.stdin.isatty():
        print(USAGE)
        return 0
    return run_script(sys.stdin.read(), _device(args))


if __name__ == "__main__":
    sys.exit(main())
