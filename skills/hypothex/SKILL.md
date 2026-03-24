---
name: hypothex
description: Use when you need to add runtime logging or observability to code, inspect runtime values, or trace execution flow. Provides instrumentation templates for Python, JavaScript, Go, Rust, Ruby, and shell.
---

# Hypothex: Runtime Debugging Skill

You have access to the Hypothex MCP server — a runtime debugging system that lets you observe what code actually does at runtime.

## When to Use

Use Hypothex when debugging issues where static analysis isn't enough — you need to see runtime values, execution flow, or timing. Follow the scientific method:

1. **Observe** — Read the code, understand the reported behavior
2. **Hypothesize** — Form a theory about what's wrong
3. **Instrument** — Insert log points to test your hypothesis
4. **Run** — Execute the instrumented code
5. **Analyze** — Query the logs via MCP tools to verify or refute
6. **Fix** — Apply the fix once you understand the root cause
7. **Clean up** — Remove instrumentation, clear the session

## Inserting Instrumentation

Insert raw HTTP POST calls in whatever language the codebase uses. The instrumentation must be **fire-and-forget** — wrap in try/except or equivalent so it never crashes the host process.

**Session ID:** Choose a descriptive session ID (e.g., `"auth-bug-login-flow"`, `"pdf-timing"`) and set it directly as a string literal in the payload. Do NOT use environment variables for the session ID.

**Comment markers:** Always wrap instrumentation in comment markers so it can be found and removed later:
- Start: `{comment} hypothex:start {session-id}`
- End: `{comment} hypothex:end {session-id}`

Use the language's comment syntax (`#`, `//`, `--`, etc.).

### Python

```python
# hypothex:start my-session-id
try:
    import httpx
    httpx.post("http://localhost:3282/log", json={
        "session_id": "my-session-id",
        "level": "debug",
        "message": "description of what you're observing",
        "data": {"variable_name": variable_value},
        "file": __file__,
        "function": "function_name",
        "line": 42
    })
except Exception:
    pass
# hypothex:end my-session-id
```

If the project uses `requests` instead of `httpx`:

```python
# hypothex:start my-session-id
try:
    import requests
    requests.post("http://localhost:3282/log", json={
        "session_id": "my-session-id",
        "level": "debug",
        "message": "description of what you're observing",
        "data": {"variable_name": variable_value},
        "file": __file__,
        "function": "function_name",
        "line": 42
    })
except Exception:
    pass
# hypothex:end my-session-id
```

If the project has no HTTP library, use stdlib:

```python
# hypothex:start my-session-id
try:
    import json, urllib.request
    _hypothex_data = json.dumps({
        "session_id": "my-session-id",
        "level": "debug",
        "message": "description of what you're observing",
        "data": {"variable_name": variable_value},
        "file": __file__,
        "function": "function_name",
        "line": 42
    }).encode()
    _hypothex_req = urllib.request.Request(
        "http://localhost:3282/log",
        data=_hypothex_data,
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(_hypothex_req, timeout=1)
except Exception:
    pass
# hypothex:end my-session-id
```

### JavaScript / TypeScript (Node.js)

```javascript
// hypothex:start my-session-id
try {
    fetch('http://localhost:3282/log', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            session_id: 'my-session-id',
            level: 'debug',
            message: 'description of what you are observing',
            data: { variableName: variableValue },
            file: __filename,
            function: 'functionName',
            line: 42
        })
    }).catch(() => {});
} catch {}
// hypothex:end my-session-id
```

### Go

```go
// hypothex:start my-session-id
func hypothexLog(message string, data map[string]interface{}) {
    go func() {
        defer func() { recover() }()
        payload, _ := json.Marshal(map[string]interface{}{
            "session_id": "my-session-id",
            "level":      "debug",
            "message":    message,
            "data":       data,
        })
        http.Post("http://localhost:3282/log", "application/json", bytes.NewReader(payload))
    }()
}
// hypothex:end my-session-id
```

### Rust

```rust
// hypothex:start my-session-id
if let Ok(client) = reqwest::blocking::Client::builder().timeout(std::time::Duration::from_secs(1)).build() {
    let _ = client.post("http://localhost:3282/log")
        .json(&serde_json::json!({
            "session_id": "my-session-id",
            "level": "debug",
            "message": "description",
            "data": {"key": "value"}
        }))
        .send();
}
// hypothex:end my-session-id
```

### Ruby

```ruby
# hypothex:start my-session-id
begin
  require 'net/http'
  require 'json'
  uri = URI("http://localhost:3282/log")
  Net::HTTP.post(uri, {
    session_id: 'my-session-id',
    level: 'debug',
    message: 'description',
    data: { variable_name: variable_value }
  }.to_json, 'Content-Type' => 'application/json')
rescue
end
# hypothex:end my-session-id
```

### Shell (curl)

```bash
# hypothex:start my-session-id
curl -s -X POST "http://localhost:3282/log" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"my-session-id","level":"debug","message":"description","data":{}}' \
  > /dev/null 2>&1 || true
# hypothex:end my-session-id
```

## Querying Logs (MCP Tools)

After running instrumented code, use these MCP tools:

- **`get_logs(session_id, limit?, level?, since?)`** — Fetch logs, optionally filtered
- **`list_sessions(limit?)`** — See all active sessions
- **`tail_logs(session_id, n?)`** — Get the N most recent logs
- **`search_logs(session_id, query)`** — Search message and data fields
- **`clear_session(session_id)`** — Delete all logs for a session

## Log Levels

- **`debug`** — Variable values, execution flow tracing
- **`info`** — Key state transitions, function entry/exit
- **`warn`** — Unexpected but non-fatal conditions
- **`error`** — Caught exceptions, failed operations

## Best Practices

1. **Be surgical** — Don't scatter logs everywhere. Place them at decision points and data boundaries.
2. **Log data, not just messages** — Put variable values in the `data` field so you can search them.
3. **Use meaningful messages** — "user object after auth middleware" not "checkpoint 1".
4. **Always clean up** — Search for `hypothex:start` / `hypothex:end` markers and delete those blocks. Use `clear_session` to clean the DB.
5. **One hypothesis at a time** — Instrument to test one specific theory, analyze, then adjust.
6. **Check health first** — If logs aren't appearing, hit `http://localhost:3282/health` to verify the server is running.

## Debug Mode

For structured hypothesis-driven debugging, use the `hypothex-debug` skill. Debug Mode adds:

- **Hypothesis tracking** — create and manage hypotheses about bug root causes
- **Log-hypothesis linking** — correlate runtime logs with the hypothesis they test
- **Structured workflow** — observe → hypothesize → instrument → reproduce → analyze → fix → cleanup
