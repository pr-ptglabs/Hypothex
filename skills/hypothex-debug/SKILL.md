---
name: hypothex-debug
description: Use when debugging any bug, test failure, or unexpected behavior where static analysis isn't enough. Provides a structured hypothesis-driven debugging workflow using runtime evidence.
---

# Hypothex: Debug Mode Skill

You have access to the Hypothex debug mode — a structured debugging workflow that uses runtime evidence to find and fix bugs. Follow this workflow exactly.

## When to Use

Use Debug Mode when you need to find a bug's root cause. Do NOT guess at fixes — use runtime evidence.

## Workflow

### Step 1: Understand the Bug

- Read the user's bug description
- Examine relevant code, error messages, stack traces
- Summarize what you know and what's unclear

### Step 2: Generate Hypotheses

Create 2-4 hypotheses about the root cause. For each one, call:

```
create_hypothesis(session_id, description)
```

Example:
```
create_hypothesis("debug-auth-bug", "Session token not refreshed after password change")
create_hypothesis("debug-auth-bug", "Middleware caches old auth state across requests")
```

Rank them by likelihood and explain your reasoning.

### Step 3: Instrument

For each hypothesis (starting with most likely), inject logging at strategic points. Always use:

1. **Comment markers** for cleanup: `# hypothex:start <id>` / `# hypothex:end <id>`
2. **hypothesis_ids** in the log payload to link logs to hypotheses
3. **Fire-and-forget** pattern — never crash the host

#### Python template:

```python
# hypothex:start {session}:h{n}
try:
    import httpx
    httpx.post("http://localhost:3282/log", json={
        "session_id": "{session}",
        "hypothesis_ids": ["{session}:h{n}"],
        "level": "debug",
        "message": "describe what you're observing",
        "data": {"relevant_variable": value},
        "file": __file__,
        "function": "function_name",
        "line": 42
    })
except Exception:
    pass
# hypothex:end {session}:h{n}
```

#### JavaScript template:

```javascript
// hypothex:start {session}:h{n}
try {
    fetch('http://localhost:3282/log', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            session_id: '{session}',
            hypothesis_ids: ['{session}:h{n}'],
            level: 'debug',
            message: 'describe what you are observing',
            data: { relevantVariable: value },
            file: __filename,
            function: 'functionName',
            line: 42
        })
    }).catch(() => {});
} catch {}
// hypothex:end {session}:h{n}
```

**Placement guidelines:**
- Log at decision points (if/else branches, switch cases)
- Log variable values at data boundaries (before/after transforms)
- Log function entry/exit for suspected call path issues
- Use `data` field for structured values, not string interpolation

Tell the user what to do to reproduce the bug.

### Step 4: Reproduce & Analyze

After the user reproduces the bug, query the logs:

```
get_hypothesis_logs("{session}:h{n}")
```

Or use filtered queries:
```
get_logs(session_id, hypothesis_id="{session}:h{n}")
tail_logs(session_id, hypothesis_id="{session}:h{n}")
```

Based on the evidence:

- **If confirmed:** `update_hypothesis("{session}:h{n}", "confirmed")`
- **If rejected:** `update_hypothesis("{session}:h{n}", "rejected")` → instrument for next hypothesis

Review all hypotheses: `list_hypotheses(session_id)`

### Step 5: Fix

Once you have a confirmed hypothesis with supporting runtime evidence:

1. Explain the root cause with references to the log data
2. Propose and apply the fix
3. Ask the user to reproduce the bug again to verify

**CRITICAL: Do NOT propose a fix without runtime evidence from Step 4.** If you're tempted to skip ahead, stop and instrument first.

### Step 6: Cleanup

After the user confirms the fix works:

1. **Remove all instrumentation** — search for `hypothex:start` / `hypothex:end` markers and delete those blocks
2. **Clear the session** — `clear_session(session_id)`
3. **Verify clean diff** — the only remaining changes should be the actual fix

## Available MCP Tools

### Hypothesis Management
- `create_hypothesis(session_id, description)` — create a new hypothesis
- `list_hypotheses(session_id)` — list all hypotheses with status and log counts
- `update_hypothesis(hypothesis_id, status)` — set to "confirmed" or "rejected"

### Log Queries
- `get_logs(session_id, limit?, level?, since?, hypothesis_id?)` — fetch logs
- `tail_logs(session_id, n?, hypothesis_id?)` — most recent N logs
- `search_logs(session_id, query, hypothesis_id?)` — text search
- `get_hypothesis_logs(hypothesis_id)` — all logs for a hypothesis

### Session Management
- `list_sessions(limit?)` — see active sessions
- `clear_session(session_id)` — delete all session data

## Key Principles

1. **Evidence before fixes** — never skip instrumentation
2. **One hypothesis at a time** — don't instrument everything at once
3. **Always clean up** — no instrumentation in the final diff
4. **Fire-and-forget** — instrumentation must never crash the host
5. **Link logs to hypotheses** — always include hypothesis_ids for traceability
