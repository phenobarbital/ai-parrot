---
id: F017
query_id: Q016
type: grep
intent: Runtime facts — Python version, empty str(TimeoutError), asyncio alias
executed_at: 2026-09-02T13:41:00+02:00
duration_ms: 300
parent_id: null
depth: 0
---

# F017 — `str(TimeoutError()) == ''` on the supported Python range; that is the blank error text

## Summary

Local venv Python 3.12.3; `requires-python = ">=3.11"` in both `pyproject.toml` and `packages/ai-parrot/pyproject.toml`. On 3.11+ `asyncio.TimeoutError is TimeoutError` (verified `True`) and `str(TimeoutError())` is `''` (verified). `asyncio.wait_for` raises it with no args, so every log line that prints the exception (`pythonrepl.py:960`, `manager.py:1864`, `base.py:1504`, `client.py:1961`) prints nothing after the colon — the report's blank messages are the signature of an `asyncio.wait_for` timeout, not of a crash.

## Citations

- path: `pyproject.toml`
  lines: 11
  excerpt: |
    requires-python = ">=3.11"
- path: `packages/ai-parrot/pyproject.toml`
  lines: 18
  excerpt: |
    requires-python = ">=3.11"
