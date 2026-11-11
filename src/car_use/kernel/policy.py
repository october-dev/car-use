"""The kernel: every intent that could change the car goes through here.

v0 runs in-process. It already enforces the rules that matter (default deny,
per-vehicle tiers, raw-request allowlist, human confirmation on a real
terminal, hash-chained audit), but in-process code can be bypassed by a
determined agent editing files. Phase 1 moves it into its own process that
owns the adapter, and later onto the car-use dongle itself.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import tomllib
from dataclasses import dataclass, asdict

from .. import paths
from ..model.capability import Tier

# OBD/UDS services that only read. Everything else is refused on the raw path.
READ_SERVICES = {
    0x01: "current data", 0x02: "freeze frame", 0x03: "stored DTCs",
    0x06: "monitor test results", 0x07: "pending DTCs", 0x09: "vehicle info",
    0x0A: "permanent DTCs", 0x19: "UDS read DTC information", 0x22: "UDS read data by identifier",
}
NEVER_RAW = {
    0x04: "clears DTCs; use clear_dtcs(), which needs tier T1D and your confirmation",
    0x08: "on-board system control (actuation)",
    0x10: "UDS session control", 0x11: "ECU reset", 0x14: "clear diagnostic information",
    0x27: "security access", 0x28: "communication control", 0x29: "authentication",
    0x2E: "write data by identifier (coding)", 0x2F: "input/output control (actuation)",
    0x31: "routine control", 0x34: "request download (flashing)", 0x35: "request upload",
    0x36: "transfer data (flashing)", 0x37: "transfer exit", 0x3D: "write memory by address",
    0x85: "control DTC setting",
}


@dataclass
class Decision:
    allowed: bool
    status: str          # "allowed" | "denied" | "awaiting_owner"
    reason: str
    tier: str
    audit_id: str = ""

    def __bool__(self) -> bool:
        return self.allowed


class Audit:
    """Append-only JSONL where each entry hashes the previous one."""

    def __init__(self):
        self.path = paths.ensure("audit") / "audit.jsonl"

    def _last(self) -> tuple[int, str]:
        if not self.path.exists():
            return 0, "0" * 64
        last = None
        with self.path.open("rb") as f:
            for line in f:
                if line.strip():
                    last = line
        if not last:
            return 0, "0" * 64
        e = json.loads(last)
        return e["seq"], e["hash"]

    def append(self, kind: str, **fields) -> str:
        seq, prev = self._last()
        entry = {"seq": seq + 1, "ts": time.time(), "kind": kind, "prev": prev, **fields}
        body = json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str)
        entry["hash"] = hashlib.sha256(body.encode()).hexdigest()
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
        return f"{entry['seq']}:{entry['hash'][:12]}"

    def verify(self) -> tuple[bool, str]:
        if not self.path.exists():
            return True, "no audit entries yet"
        prev, n = "0" * 64, 0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            h = e.pop("hash")
            if e["prev"] != prev:
                return False, f"chain broken at seq {e['seq']}"
            body = json.dumps(e, sort_keys=True, separators=(",", ":"), default=str)
            if hashlib.sha256(body.encode()).hexdigest() != h:
                return False, f"entry {e['seq']} was modified"
            prev, n = h, n + 1
        return True, f"{n} entries, chain intact"


def _policy_path():
    return paths.home() / "policy.toml"


def load_policy() -> dict:
    p = _policy_path()
    if not p.exists():
        return {}
    return tomllib.loads(p.read_text(encoding="utf-8"))


def enabled_tiers(vin: str) -> set[str]:
    pol = load_policy()
    tiers = set(pol.get("vehicles", {}).get(vin or "unknown", {}).get("tiers", []))
    return {"T0"} | tiers


def _write_policy(pol: dict) -> None:
    lines = []
    for vin, conf in sorted(pol.get("vehicles", {}).items()):
        tiers = ", ".join(f'"{t}"' for t in sorted(conf.get("tiers", [])))
        lines += [f'[vehicles."{vin}"]', f"tiers = [{tiers}]", ""]
    paths.ensure()
    _policy_path().write_text("# Edited by `car-use policy`. Tiers: see SKILL.md.\n\n"
                              + "\n".join(lines), encoding="utf-8")


def ask_human(question: str, expect: str) -> bool:
    """Ask on the controlling terminal, never on stdin (stdin is the agent's script).

    No terminal (the agent is running us non-interactively) means no consent.
    """
    try:
        with open("/dev/tty", "r+") as tty:
            tty.write(f"\n[car-use] {question}\n[car-use] Type {expect!r} to confirm: ")
            tty.flush()
            answer = tty.readline().strip()
    except OSError:
        return False
    return answer == expect


def set_tier(vin: str, tier: str, enable: bool) -> str:
    tier = Tier(tier.upper()).value
    if tier in ("T3", "T4"):
        return f"{tier} cannot be enabled in this version of car-use."
    if enable:
        if not sys.stdin.isatty():
            return ("Refusing: enabling a tier must be done by a person at an interactive "
                    "terminal, not by an agent or a script.")
        if not ask_human(f"Enable {tier} for vehicle {vin}?", vin[-6:]):
            return "Not confirmed. Nothing changed."
    pol = load_policy()
    veh = pol.setdefault("vehicles", {}).setdefault(vin, {"tiers": []})
    tiers = set(veh.get("tiers", []))
    (tiers.add if enable else tiers.discard)(tier)
    veh["tiers"] = sorted(tiers)
    _write_policy(pol)
    Audit().append("policy", vin=vin, tier=tier, enabled=enable, by="human" if enable else "any")
    return f"{tier} {'enabled' if enable else 'disabled'} for {vin}."


class Kernel:
    def __init__(self, confirm=None):
        # confirm(question, expect) -> bool. Defaults to the controlling terminal.
        # Injectable for tests and, later, for the phone approvals app. There is
        # deliberately no environment variable or flag that auto-confirms.
        self.audit = Audit()
        self.confirm = confirm or ask_human

    def check_raw(self, request: str, vin: str) -> Decision:
        req = request.replace(" ", "").upper()
        try:
            service = int(req[:2], 16)
        except ValueError:
            return Decision(False, "denied", "not a hex OBD request", "T0")
        if service in READ_SERVICES:
            return Decision(True, "allowed", READ_SERVICES[service], "T0")
        why = NEVER_RAW.get(service, "only read services are allowed on the raw path")
        aid = self.audit.append("deny", vin=vin, intent="raw_obd", request=req, reason=why)
        return Decision(False, "denied", f"service 0x{service:02X} refused: {why}", "Ax", aid)

    def authorize(self, intent: str, tier: Tier, vin: str, consequence: str,
                  state_ok: tuple[bool, str] = (True, "")) -> Decision:
        if tier.value not in enabled_tiers(vin):
            aid = self.audit.append("deny", vin=vin, intent=intent, tier=tier.value,
                                    reason="tier not enabled")
            return Decision(False, "denied",
                            f"{intent} needs tier {tier.value}, which is not enabled for this "
                            f"vehicle. The owner can enable it at a terminal: "
                            f"car-use policy enable {tier.value}", tier.value, aid)
        ok, why = state_ok
        if not ok:
            aid = self.audit.append("deny", vin=vin, intent=intent, tier=tier.value, reason=why)
            return Decision(False, "denied", why, tier.value, aid)
        confirmed = self.confirm(consequence, "yes")
        if not confirmed:
            aid = self.audit.append("deny", vin=vin, intent=intent, tier=tier.value,
                                    reason="owner did not confirm")
            return Decision(False, "awaiting_owner",
                            "The owner has to confirm this at the car-use terminal prompt. "
                            "Ask them to run the same step themselves in an interactive shell.",
                            tier.value, aid)
        aid = self.audit.append("allow", vin=vin, intent=intent, tier=tier.value,
                                consequence=consequence)
        return Decision(True, "allowed", "confirmed by owner", tier.value, aid)

    def record(self, kind: str, **fields) -> str:
        return self.audit.append(kind, **fields)
