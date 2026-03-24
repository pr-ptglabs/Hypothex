# Hypothex

Runtime debugging plugin for Claude Code. Hypothex lets Claude observe what code actually does at runtime by collecting logs from instrumented code and querying them through MCP tools.

Instead of guessing at bugs, Claude instruments your code with logging, runs it, and uses the runtime evidence to find the root cause.

## How It Works

Hypothex runs two services concurrently:

1. **HTTP Collector** — A FastAPI server that receives log entries via `POST /log` from instrumented code
2. **MCP Server** — Exposes tools to Claude Code for querying logs, managing sessions, and tracking debugging hypotheses

Data is stored in SQLite at `~/.hypothex/hypothex.db`.

## Install

### Prerequisites

```bash
pip install hypothex
```

### As a Claude Code Plugin (recommended)

```bash
/plugin marketplace add https://github.com/pr-ptglabs/hypothex
/plugin install hypothex@hypothex
```

This permanently installs the plugin for all sessions, giving Claude both the MCP tools and the debugging skills automatically.

### MCP-only Setup

If you only need the MCP tools without the skills, add to your project's `.mcp.json`:

```json
{
  "hypothex": {
    "command": "python",
    "args": ["-m", "hypothex.main"],
    "env": {
      "PYTHONUNBUFFERED": "1"
    }
  }
}
```

## What You Get

### MCP Tools

| Tool | Description |
|------|-------------|
| `get_logs` | Fetch logs for a session, filtered by level, time, or hypothesis |
| `tail_logs` | Get the N most recent logs |
| `search_logs` | Search message and data fields |
| `list_sessions` | List all sessions with log counts |
| `clear_session` | Delete all logs for a session |
| `create_hypothesis` | Create a debugging hypothesis |
| `list_hypotheses` | List hypotheses with status and log counts |
| `update_hypothesis` | Confirm or reject a hypothesis |
| `get_hypothesis_logs` | Get all logs linked to a hypothesis |

### Skills

- **hypothex** — Instrumentation templates for Python, JavaScript, Go, Rust, Ruby, and shell. Claude uses this to add runtime logging to your code.
- **hypothex-debug** — Structured hypothesis-driven debugging workflow. Claude creates hypotheses about the bug, instruments code to test them, analyzes runtime evidence, then fixes.

## Debugging Workflow

1. **Observe** — Claude reads the code and bug report
2. **Hypothesize** — Creates hypotheses about the root cause
3. **Instrument** — Injects fire-and-forget log statements at strategic points
4. **Run** — You execute the instrumented code
5. **Analyze** — Claude queries the logs to confirm or reject each hypothesis
6. **Fix** — Applies the fix backed by runtime evidence
7. **Clean up** — Removes instrumentation, clears the session

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `HYPOTHEX_PORT` | `3282` | HTTP collector port |
| `HYPOTHEX_SESSION_ID` | `default` | Session ID for log grouping |

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run the server standalone
python -m hypothex.main
```

## Project Structure

```
hypothex/
├── .claude-plugin/plugin.json    # Plugin metadata
├── .mcp.json                     # MCP server config
├── skills/
│   ├── hypothex/SKILL.md         # Instrumentation skill
│   └── hypothex-debug/SKILL.md   # Debug mode skill
├── src/hypothex/
│   ├── main.py                   # Entry point, starts both services
│   ├── collector.py              # FastAPI HTTP log collector
│   ├── mcp_server.py             # MCP tool definitions
│   ├── db.py                     # Async SQLite layer
│   └── models.py                 # Pydantic log model
└── tests/
```

## License

MIT — Made by [PTG Labs GmbH](https://ptg-labs.ch)
