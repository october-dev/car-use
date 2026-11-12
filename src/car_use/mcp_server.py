"""stdio MCP server: discover, observe, act.

Three tools, not one per signal. `act`'s name enum is built from the live
capability manifest, so a new capability shows up without a new tool.
`act` only calls the kernel. It cannot confirm on the agent's behalf.
"""
from __future__ import annotations

import json
import sys
from enum import Enum

from . import __version__
from . import helpers

OBSERVE_OPS = ("read", "read_many", "watch", "dtcs", "readiness", "freeze_frame", "vin_info")
PROTOCOL = "2024-11-05"


def serve(device: str | None) -> int:
    helpers._configure(device)
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as e:
                _send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}})
                continue
            if msg.get("method") == "notifications/initialized":
                continue
            resp = handle(msg)
            if resp is not None:
                _send(resp)
    finally:
        helpers._shutdown()
    return 0


def handle(msg: dict) -> dict | None:
    method = msg.get("method")
    req_id = msg.get("id")
    if req_id is None and method and method.startswith("notifications/"):
        return None
    try:
        if method == "initialize":
            result = {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "car-use", "version": __version__},
            }
        elif method == "tools/list":
            result = {"tools": tool_schemas(_manifest_dict())}
        elif method == "tools/call":
            result = call_tool((msg.get("params") or {}).get("name"),
                               (msg.get("params") or {}).get("arguments") or {})
        elif method == "ping":
            result = {}
        else:
            return _error(req_id, -32601, f"unknown method {method}")
    except Exception as e:
        return _error(req_id, -32000, f"{type(e).__name__}: {e}")
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def tool_schemas(manifest: dict) -> list[dict]:
    """Exactly three tools. Act names come from the manifest, not a hand list."""
    caps = manifest.get("capabilities") or []
    act_names = [c["name"] for c in caps if c.get("altitude") not in (None, "A0")]
    return [
        {
            "name": "discover",
            "description": "Manifest for this car: signals and capabilities, with altitude and tier.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "observe",
            "description": "Read-only: read, read_many, watch, dtcs, readiness, freeze_frame, vin_info.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": list(OBSERVE_OPS)},
                    "name": {"type": "string", "description": "One signal, for op=read."},
                    "names": {"type": "array", "items": {"type": "string"}},
                    "seconds": {"type": "number"},
                    "hz": {"type": "number"},
                },
                "required": ["op"],
                "additionalProperties": False,
            },
        },
        {
            "name": "act",
            "description": ("Do something the manifest allows. Routed through the safety kernel. "
                            "The agent cannot confirm; the owner does that at a terminal."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": act_names},
                    "params": {"type": "object"},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    ]


def call_tool(name: str | None, arguments: dict) -> dict:
    if name == "discover":
        return _ok(_manifest_dict())
    if name == "observe":
        return _ok(_observe(arguments))
    if name == "act":
        return _act(arguments)
    return _tool_error(f"unknown tool {name}")


def _observe(arguments: dict):
    op = arguments.get("op")
    if op == "read":
        return helpers.read(arguments["name"])
    if op == "read_many":
        return helpers.read_many(arguments.get("names") or [])
    if op == "watch":
        series = helpers.watch(arguments.get("names") or [],
                               seconds=float(arguments.get("seconds") or 2),
                               hz=float(arguments.get("hz") or 5))
        return {"summary": series.summary(), "rows": series.rows}
    if op == "dtcs":
        return helpers.dtcs()
    if op == "readiness":
        return helpers.readiness()
    if op == "freeze_frame":
        return helpers.freeze_frame()
    if op == "vin_info":
        return helpers.vin_info()
    raise ValueError(f"unknown observe op {op!r}")


def _act(arguments: dict) -> dict:
    name = arguments.get("name")
    allowed = {c["name"] for c in _manifest_dict()["capabilities"] if c.get("altitude") != "A0"}
    if name not in allowed:
        return _tool_error(f"{name} is not an action on this car. Use observe for reads.")
    if name == "obd.clear_dtcs":
        decision = helpers.clear_dtcs()
        body = _plain(decision)
        if not getattr(decision, "allowed", False):
            return _tool_error(json.dumps(body))
        return _ok(body)
    return _tool_error(f"no kernel path for {name}")


def _manifest_dict() -> dict:
    return _plain(helpers.manifest().to_dict())


def _plain(obj):
    if isinstance(obj, Enum):
        return obj.value
    if hasattr(obj, "to_dict"):
        return _plain(obj.to_dict())
    if hasattr(obj, "__dict__") and not isinstance(obj, dict):
        return {k: _plain(v) for k, v in vars(obj).items() if not k.startswith("_")}
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    return obj


def _ok(payload) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(_plain(payload))}], "isError": False}


def _tool_error(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


def _error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _send(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()
