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

## Setting Up a Session

Before running instrumented code, set the session ID:

```bash
export HYPOTHEX_SESSION_ID="debug-$(date +%s)"
```

Use a descriptive session ID when possible (e.g., `"auth-bug-login-flow"`).

## Inserting Instrumentation

Insert raw HTTP POST calls in whatever language the codebase uses. The instrumentation must be **fire-and-forget** — wrap in try/except or equivalent so it never crashes the host process.

### Python

```python
try:
    import httpx, os
    httpx.post(f"http://localhost:{os.environ.get('HYPOTHEX_PORT', '3282')}/log", json={
        "session_id": os.environ.get("HYPOTHEX_SESSION_ID", "default"),
        "level": "debug",
        "message": "description of what you're observing",
        "data": {"variable_name": variable_value},
        "file": __file__,
        "function": "function_name",
        "line": 42
    })
except Exception:
    pass
```

If the project uses `requests` instead of `httpx`:

```python
try:
    import requests, os
    requests.post(f"http://localhost:{os.environ.get('HYPOTHEX_PORT', '3282')}/log", json={
        "session_id": os.environ.get("HYPOTHEX_SESSION_ID", "default"),
        "level": "debug",
        "message": "description of what you're observing",
        "data": {"variable_name": variable_value},
        "file": __file__,
        "function": "function_name",
        "line": 42
    })
except Exception:
    pass
```

If the project has no HTTP library, use stdlib:

```python
try:
    import json, os, urllib.request
    _hypothex_data = json.dumps({
        "session_id": os.environ.get("HYPOTHEX_SESSION_ID", "default"),
        "level": "debug",
        "message": "description of what you're observing",
        "data": {"variable_name": variable_value},
        "file": __file__,
        "function": "function_name",
        "line": 42
    }).encode()
    _hypothex_req = urllib.request.Request(
        f"http://localhost:{os.environ.get('HYPOTHEX_PORT', '3282')}/log",
        data=_hypothex_data,
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(_hypothex_req, timeout=1)
except Exception:
    pass
```

### JavaScript / TypeScript (Node.js)

```javascript
try {
    fetch(`http://localhost:${process.env.HYPOTHEX_PORT || '3282'}/log`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            session_id: process.env.HYPOTHEX_SESSION_ID || 'default',
            level: 'debug',
            message: 'description of what you are observing',
            data: { variableName: variableValue },
            file: __filename,
            function: 'functionName',
            line: 42
        })
    }).catch(() => {});
} catch {}
```

### Go

```go
func hypothexLog(message string, data map[string]interface{}) {
    go func() {
        defer func() { recover() }()
        port := os.Getenv("HYPOTHEX_PORT")
        if port == "" { port = "3282" }
        sessionID := os.Getenv("HYPOTHEX_SESSION_ID")
        if sessionID == "" { sessionID = "default" }
        payload, _ := json.Marshal(map[string]interface{}{
            "session_id": sessionID,
            "level":      "debug",
            "message":    message,
            "data":       data,
        })
        http.Post("http://localhost:"+port+"/log", "application/json", bytes.NewReader(payload))
    }()
}
```

### Rust

```rust
// Add to existing tokio runtime or use a blocking call
if let Ok(client) = reqwest::blocking::Client::builder().timeout(std::time::Duration::from_secs(1)).build() {
    let port = std::env::var("HYPOTHEX_PORT").unwrap_or_else(|_| "3282".into());
    let session = std::env::var("HYPOTHEX_SESSION_ID").unwrap_or_else(|_| "default".into());
    let _ = client.post(format!("http://localhost:{}/log", port))
        .json(&serde_json::json!({
            "session_id": session,
            "level": "debug",
            "message": "description",
            "data": {"key": "value"}
        }))
        .send();
}
```

### Ruby

```ruby
begin
  require 'net/http'
  require 'json'
  port = ENV['HYPOTHEX_PORT'] || '3282'
  uri = URI("http://localhost:#{port}/log")
  Net::HTTP.post(uri, {
    session_id: ENV['HYPOTHEX_SESSION_ID'] || 'default',
    level: 'debug',
    message: 'description',
    data: { variable_name: variable_value }
  }.to_json, 'Content-Type' => 'application/json')
rescue
end
```

### Shell (curl)

```bash
curl -s -X POST "http://localhost:${HYPOTHEX_PORT:-3282}/log" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"${HYPOTHEX_SESSION_ID:-default}\",\"level\":\"debug\",\"message\":\"description\",\"data\":{}}" \
  > /dev/null 2>&1 || true
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
4. **Always clean up** — Remove all instrumentation code after debugging. Use `clear_session` to clean the DB.
5. **One hypothesis at a time** — Instrument to test one specific theory, analyze, then adjust.
6. **Check health first** — If logs aren't appearing, hit `http://localhost:3282/health` to verify the server is running.
