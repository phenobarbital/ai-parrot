# TASK-3992: End-to-end scope regressions — test-chat join, concurrency, mismatch, no-request (Wave 4 tests)

**Feature**: FEAT-622 — Agent Studio — Host Toolkits
**Spec**: `sdd/specs/agentstudio-host-toolkits.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3991
**Assigned-to**: unassigned
**Wave**: 4 (spec §9) · **Module**: M3b + M5 regressions

---

## Context

Spec §4 integration rows and ARCHITECTURE R6.5 ("a green test proves nothing about a join it never crosses"): the
join must be asserted end to end — seam-shaped request → Studio test chat → `whoami` returns the **caller's** tenant
and id and the agent's owner/visibility; two concurrent `bot.session`s on one shared agent never cross; agent
tenant A vs caller tenant B → `tenant_mismatch`; calling outside any session (scheduler shape) → `no_context`.

---

## Scope

- `test_test_chat_join_scope_reaches_tool` (drive the tool with `tool_manager.execute_tool` inside the handler's
  `bot.session`, no LLM network).
- `test_concurrent_callers_never_cross` (mutation: store the scope on the instance ⇒ RED).
- `test_tenant_mismatch_refuses`, `test_no_request_refuses`.

**NOT in scope**: production code changes (none expected; a failure here reopens the owning task).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/studio/test_tool_scope_regressions.py` | CREATE | join / concurrency / mismatch / no-request regressions |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (ai-parrot `dev` @ `32b1a45d4`). The implementing agent MUST use these exact imports, class names,
> and method signatures. **DO NOT** invent, guess, or assume any import, attribute, or method not
> listed here. If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# FEAT-605 v0.2 real types (verify on origin/dev): RequestScope, StudioAgentRef, build_tool_scope
from parrot.tools.scope import ToolScopeUnavailable  # TASK-3976
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/manager.py — ToolManager.execute_tool (dispatch :2061, re-verify)
# packages/ai-parrot-server/src/parrot/handlers/studio/testing.py:270 — test chat session
```

### Does NOT Exist
- ~~a scripted LLM client in the repo for Studio test chat~~ — not verified; drive `tool_manager.execute_tool` inside the session instead (spec §4).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/tests/studio/test_tool_scope_regressions.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.execute_tool"
  ]
}
```

---

## Implementation Notes

### Cross-feature ordering
- **Wave 4 needs FEAT-605 W2.1 (`build_tool_scope`, `StudioAgentRef`, tenant partitions) and FEAT-621 W2 (runtime identity: `bot._studio_key`, `bot._tooling_ref`) merged** (X16 cross-spec waits); the asserted test-chat / meta-agent bindings need FEAT-605 W3.4 / W3.5.

### Key Constraints
- Async throughout; no blocking I/O in async paths; `self.logger` (or the module `logger`) — never `print`.
- Pydantic models for every new data structure; Google-style docstrings and strict type hints.
- Core (`packages/ai-parrot`) never imports `ai-parrot-server` (spec §7).
- ARCHITECTURE R4: no new/modified function above cyclomatic complexity 10 or 60 lines; run `flake8` on changed files.
- **Spec §4 test rule (applies to every test in this task):** build requests with `aiohttp.test_utils.make_mocked_request` and install the session the way `navigator_session` does (`request[SESSION_OBJECT] = ...`), or use `aiohttp_client` over a real app. Never a `Mock` / `SimpleNamespace` with hand-set `.session` / `.app`. Side-effect **counters** prove refusals, not mocks. Mutation-check every new assertion (revert the code, see RED) and record the evidence in the Completion Note.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Build the scope with FEAT-605's real types — *why*: spec §4 forbids stand-ins.
2. Write the four tests; record mutation evidence for each.

### `packages/ai-parrot-server/tests/studio/test_tool_scope_regressions.py` (CREATE)
```python
"""FEAT-622 Wave 4 end-to-end scope regressions (spec §4 integration rows)."""
# FILL IN: four tests per the Scope list; make_mocked_request + request[SESSION_OBJECT]; asyncio.gather for concurrency
```

### FILL IN checklist
- [ ] Each test body — bounded by the spec §4 row descriptions.

---

## Acceptance Criteria

- [ ] The four regressions pass; each mutation-checked (evidence in the Completion Note).
- [ ] `pytest packages/ai-parrot-server/tests/studio packages/ai-parrot/tests/tools -q` passes (spec AC "Existing Studio and tools tests pass").

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_tool_scope_regressions.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_tool_scope_regressions.py
async def test_test_chat_join_scope_reaches_tool(host_plugins): ...
async def test_concurrent_callers_never_cross(host_plugins): ...
async def test_tenant_mismatch_refuses(host_plugins): ...
async def test_no_request_refuses(host_plugins): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-host-toolkits --feature-id FEAT-622`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/agentstudio-host-toolkits.json`, and every "Cross-feature ordering"
   line in Implementation Notes must be satisfied on `origin/dev`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/agentstudio-host-toolkits.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-id> agentstudio-host-toolkits verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below (including mutation-check evidence), then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (sequential fallback loop, tramo B2)
**Date**: 2026-10-02
**Notes**: Four end-to-end regressions crossing the real join (resolver → Studio test chat → the agent's own `tool_manager` inside the
handler's `bot.session` → a tenant-bound host toolkit whose `whoami` reads the scope the SERVER bound): the caller's tenant/id and the
agent's owner/visibility reach the tool; six concurrent `bot.session`s on one shared agent never cross (gate event forces every
session to be open before any tool runs); agent tenant A vs caller tenant B ⇒ `tool_scope_unavailable` / `tenant_mismatch` with zero
executions; no session at all (scheduler shape) ⇒ `no_context`. The server host probe's tenant-bound toolkit now declares
`server_managed_params` tenant/caller/agent and its `whoami` returns them. No production code changed.
Mutations RED (restored): scope cached on the tool instance ⇒ concurrent test; `studio_scope` binding at test/ask removed ⇒ join
test; the agent-tenant mismatch rule removed ⇒ mismatch test. Gate-off mutation stays GREEN here on purpose: this toolkit declares
scope-sourced params, so the per-call injection refuses as a second line of defence; the gate itself is mutation-tested in core
`test_scope_enforcement.py` (standalone tenant-bound tool with NO scope params).
The runtime's `configure()` is replaced offline (as in the other Studio tests), so the toolkit is registered on the agent's
`tool_manager` inside the ask seam.

**Deviations from spec**: file as listed; none otherwise.
