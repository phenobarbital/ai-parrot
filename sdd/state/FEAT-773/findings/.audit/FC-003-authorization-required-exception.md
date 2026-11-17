---
id: FC-003
query_id: Q022
type: read
intent: "R2: read AuthorizationRequired exception definition (core)."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-003 — AuthorizationRequired(tool_name, message, auth_url, provider, scopes) is defined in core parrot/auth/exceptions.py

## Summary

`parrot/auth/exceptions.py` (65 lines) defines `AuthorizationRequired(tool_name, message, auth_url=None, provider="unknown", scopes=None)`; docstring states `ToolManager.execute_tool` converts it to `ToolResult(status='authorization_required')` with metadata `auth_url`/`provider`. Typical producer is a toolkit `_pre_execute` hook. Also defines `SystemAccountNotProvisioned` (FEAT-326).

## Citations

- path: `packages/ai-parrot/src/parrot/auth/exceptions.py`
  lines: 12-47
  symbol: `AuthorizationRequired`
  excerpt: |
    class AuthorizationRequired(Exception):
        def __init__(self, tool_name: str, message: str, auth_url: Optional[str] = None, provider: str = "unknown", scopes: Optional[List[str]] = None)

## Notes

Brainstorm §10 'AuthorizationRequired defined in core rather than Jira package' → confirmed core.
