# TASK-2606: Result size policy + per-call deadline

**Feature**: FEAT-477 — Expose an AI-Parrot Agent as an MCP Server
**Spec**: `sdd/specs/mcp-as-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2604
**Assigned-to**: unassigned

---

## Context

Implements the response-shaping half of spec §3 **Module 3** — goals **G8** and the
deadline part of **G7**.

Spec §1 Goals G8: tool responses must stay under the ~30 000-token custom-connector
ceiling, **enforced by the adapter layer, not left to method authors**.

---

## Scope

- Enforce a per-tool result cap: `MCPToolDeclaration.max_result_tokens` when set, else
  `AgentMCPMountConfig.max_result_tokens` (default 25 000).
- Truncate or paginate **deterministically**, and state it explicitly in the response, so
  the model does not silently reason over a clipped list (spec §2 Edge Cases).
- Apply `exclude_none` and mandatory pagination on list-shaped results (spec §8
  response-size policy).
- Enforce `call_deadline_seconds` (default 240 s, below the 300 s client ceiling): a
  blocking method yields a clean timeout error **naming the method**.
- Unit tests.

**NOT in scope**: job handles (TASK-2607) — the deadline turns a too-slow call into a clean
error; making it durable is 2607's job.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/mcp/result_policy.py` | CREATE | Size policy + deadline wrapper |
| `packages/ai-parrot-server/src/parrot/mcp/principal_guard.py` | MODIFY | Apply policy around adapter execution |
| `packages/ai-parrot-server/tests/mcp/test_result_policy.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> VERIFIED against `dev` on 2026-08-31.

### Verified Imports
```python
from parrot.mcp.adapter import MCPToolAdapter
from parrot.tools.abstract import ToolResult
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/adapter.py
class MCPToolAdapter:                                             # :8
    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]   # :59
    def _toolresult_to_mcp(self, result: ToolResult) -> dict[str, Any]     # :108

# packages/ai-parrot-server/src/parrot/mcp/transports/streamable_http.py
KEEP_ALIVE_INTERVAL: float = 15.0        # :56   SSE keep-alive; unrelated to the call deadline
```

### Does NOT Exist
- ~~`ResultPolicy`~~ as an existing class — you are creating the module.
- ~~`MCPToolAdapter.max_tokens`~~ — not a real attribute; the cap lives in your wrapper.
- ~~A token counter in `parrot.mcp`~~ — none exists. Use a documented approximation
  (e.g. serialized-character heuristic) and state the method in the docstring; do not
  invent an import for a tokenizer.

---

## Implementation Notes

### Key Constraints
- Truncation must be **visible**: include an explicit marker in the response (e.g. a
  `truncated: true` field plus a human-readable note) so the model knows the list is partial.
- Determinism: the same oversized result must truncate identically every time — no
  set/dict iteration-order dependence.
- The deadline is enforced with `asyncio.wait_for`; on timeout raise a clean MCP error that
  names the method, never a bare `TimeoutError` traceback.
- The cap resolution order is per-tool → mount default.

### References in Codebase
- `packages/ai-parrot/src/parrot/mcp/adapter.py:108` — where `ToolResult` becomes MCP content

---

## Acceptance Criteria

- [ ] Per-tool `max_result_tokens` overrides the mount default
- [ ] Oversized results are truncated/paginated and the response says so explicitly
- [ ] Truncation is deterministic across repeated runs
- [ ] `exclude_none` is applied; list results are paginated
- [ ] A method exceeding `call_deadline_seconds` yields a clean timeout naming the method
- [ ] The deadline is strictly below the 300 s client ceiling
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/mcp/test_result_policy.py -v`
- [ ] No linting errors

---

## Test Specification

```python
class TestResultPolicy:
    def test_per_tool_cap_overrides_mount_default(self):
        assert resolve_cap(decl_with_cap(100), cfg(25_000)) == 100

    def test_truncation_states_itself(self):
        out = apply_size_policy(huge_list_result, cap=100)
        assert out["truncated"] is True
        assert "truncated" in json.dumps(out).lower()

    def test_truncation_is_deterministic(self):
        a = apply_size_policy(huge_list_result, cap=100)
        b = apply_size_policy(huge_list_result, cap=100)
        assert a == b

    def test_exclude_none_applied(self):
        out = apply_size_policy(result_with_nones, cap=10_000)
        assert "null" not in json.dumps(out)

    async def test_call_deadline_names_the_method(self):
        with pytest.raises(MCPToolError, match="slow_forecast"):
            await run_with_deadline(slow_method, deadline=0.05, name="slow_forecast")

    def test_deadline_below_client_ceiling(self):
        assert AgentMCPMountConfig(...).call_deadline_seconds < 300
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 3, G7/G8, §2 Edge Cases.
2. **Check dependencies** — TASK-2604 completed.
3. **Verify the Codebase Contract**. 4. **Update status** → `"in-progress"`.
5. **Implement**. 6. **Verify** acceptance criteria.
7. **Move** to `sdd/tasks/completed/`. 8. **Update index** → `"done"`. 9. **Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-01
**Notes**: `result_policy.py` implements `resolve_cap(declaration, mount_config)`
(per-tool `max_result_tokens` -> mount default -> `DEFAULT_MAX_RESULT_TOKENS`),
`apply_size_policy(result, cap)` (allowlist-style `exclude_none` applied first;
oversized lists truncated to a deterministic **prefix** — no set/dict
iteration-order dependence — with `truncated`/`note`/`total_count`/
`returned_count`; oversized non-list results truncate their serialized string
form the same deterministic way), and `run_with_deadline(fn, deadline, name)`
(`asyncio.wait_for` wrapping a zero-arg async callable, raising `MCPToolError`
naming the tool on timeout — never a bare `TimeoutError` traceback). No token
counter exists anywhere in `parrot.mcp`, so the cap is enforced against a
documented `_CHARS_PER_TOKEN` character-count heuristic, not a real tokenizer
(per the Codebase Contract's explicit instruction not to invent one).
Wired into `principal_guard.py`'s `PBACGuard.tools_call()`: the adapter
execution (`self._server.handle_tools_call(params)`) is wrapped in
`run_with_deadline` using `AgentMCPMountConfig.call_deadline_seconds` (a new
`mount_config` constructor param on `PBACGuard`, `None`-safe, falling back to
240s); on success, `_apply_result_size_policy()` reads the tool's
`MCPToolDeclaration` off `AgentMethodTool._declaration` (when present — a
plain `tool_manager` tool has none, correctly falling through to the mount
default) to resolve the cap, then applies `apply_size_policy` to the JSON
payload already embedded in the MCP response's first content block's `text`
(re-serializing the truncated payload back in place when policing changes
anything). 11/11 new tests pass; full `packages/ai-parrot-server/tests/mcp/`
suite (136 tests, up from 125) stays green — including the unmodified
`test_pbac_guard.py` suite, confirming the new wiring is behavior-preserving
for calls that don't hit either policy. `ruff check` clean on all three files.

**Deviations from spec**: none of substance, one documented limitation.
`MCPToolAdapter.execute()`'s own "direct results" fallback
(`mcp/adapter.py:59`, `else: {"content": [{"text": str(result)}], ...}`) —
used whenever a tool method returns a plain dict/list rather than a
`ToolResult` (true of every example `AgentMethodTool` method in this
feature's own tests) — serializes via Python's `str()`, not `json.dumps()`,
so a dict/list result becomes a Python-repr string (single-quoted) rather
than valid JSON. `_apply_result_size_policy`'s `json.loads(text)` correctly
falls back to string-truncation for these (still deterministic, still states
`truncated`), but loses the smarter per-item list pagination `apply_size_policy`
provides for a *real* JSON list. Fixing that root cause means changing
`adapter.py`'s "direct results" branch to `json.dumps` — out of this task's
file list (`agent_tools.py`/`adapter.py` are TASK-2600/pre-existing scope,
not `result_policy.py`/`principal_guard.py`) and a behavior change other
callers of `MCPToolAdapter.execute()` (outside FEAT-477) also depend on;
flagging as a candidate follow-up rather than touching it here.
