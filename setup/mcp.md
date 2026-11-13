# car-use as an MCP server

For an agent that cannot run a shell. `car-use mcp` speaks MCP on stdin and stdout. It exposes three tools:

- `discover` — the capability manifest
- `observe` — `read`, `read_many`, `watch`, `dtcs`, `readiness`, `freeze_frame`, `vin_info`
- `act` — only what the manifest lists above "observe". Today that is clearing codes, and it still goes through the safety kernel. The agent cannot confirm.

`--sim` is enough to try it with no adapter:

```bash
car-use mcp --sim p0420
```

## Claude Desktop

In `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "car-use": {
      "command": "car-use",
      "args": ["mcp", "--sim", "p0420"]
    }
  }
}
```

Replace the args with no `--sim` once `car-use config set device ...` points at a real adapter.

## Claude Code

`.mcp.json` in the project:

```json
{
  "mcpServers": {
    "car-use": {
      "command": "car-use",
      "args": ["mcp", "--sim", "p0420"]
    }
  }
}
```

## Codex

`~/.codex/config.toml`:

```toml
[mcp_servers.car-use]
command = "car-use"
args = ["mcp", "--sim", "p0420"]
```
