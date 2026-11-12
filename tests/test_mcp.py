"""The local MCP server: three tools, sim-backed, act goes through the kernel."""
import json
import select
import subprocess
import sys
from pathlib import Path

from car_use.mcp_server import tool_schemas


def test_act_names_come_from_the_manifest_not_a_new_tool():
    tools = tool_schemas({"capabilities": [
        {"name": "obd.read", "altitude": "A0"},
        {"name": "obd.clear_dtcs", "altitude": "A1"},
        {"name": "climate.set", "altitude": "A1"},
    ]})
    assert [t["name"] for t in tools] == ["discover", "observe", "act"]
    assert tools[2]["inputSchema"]["properties"]["name"]["enum"] == [
        "obd.clear_dtcs", "climate.set"]
    assert "climate.set" not in [t["name"] for t in tools]


def test_mcp_over_stdio_with_the_simulator():
    proc = subprocess.Popen(
        [sys.executable, "-m", "car_use.run", "mcp", "--sim", "p0420"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )

    def rpc(msg: dict, *, expect: bool = True) -> dict | None:
        assert proc.stdin and proc.stdout
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()
        if not expect:
            return None
        ready, _, _ = select.select([proc.stdout], [], [], 20)
        assert ready, "MCP server did not reply"
        line = proc.stdout.readline()
        assert line, "server closed stdout"
        return json.loads(line)

    try:
        init = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert init["result"]["serverInfo"]["name"] == "car-use"
        rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect=False)
        listed = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = [t["name"] for t in listed["result"]["tools"]]
        assert names == ["discover", "observe", "act"]
        act_enum = listed["result"]["tools"][2]["inputSchema"]["properties"]["name"]["enum"]
        assert act_enum == ["obd.clear_dtcs"]

        found = rpc({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                     "params": {"name": "discover", "arguments": {}}})
        manifest = json.loads(found["result"]["content"][0]["text"])
        assert manifest["backend"] == "obd"
        assert any(c["name"] == "obd.clear_dtcs" for c in manifest["capabilities"])

        codes = rpc({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                     "params": {"name": "observe", "arguments": {"op": "dtcs"}}})
        assert json.loads(codes["result"]["content"][0]["text"])["stored"] == ["P0420"]

        reading = rpc({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                       "params": {"name": "observe", "arguments": {"op": "read", "name": "coolant"}}})
        assert 88 <= json.loads(reading["result"]["content"][0]["text"])["value"] <= 94

        denied = rpc({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                      "params": {"name": "act", "arguments": {"name": "obd.clear_dtcs"}}})
        assert denied["result"]["isError"] is True
        assert "T1D" in denied["result"]["content"][0]["text"]

        again = rpc({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                     "params": {"name": "observe", "arguments": {"op": "dtcs"}}})
        assert json.loads(again["result"]["content"][0]["text"])["stored"] == ["P0420"]
    finally:
        if proc.stdin:
            proc.stdin.close()
        proc.wait(timeout=10)


def test_setup_snippets_name_the_server():
    text = (Path(__file__).resolve().parents[1] / "setup" / "mcp.md").read_text()
    assert "car-use mcp --sim p0420" in text
    assert "claude_desktop_config.json" in text
    assert ".mcp.json" in text
    assert "mcp_servers.car-use" in text
    assert "discover" in text and "observe" in text and "act" in text
