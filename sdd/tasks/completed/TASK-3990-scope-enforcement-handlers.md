# TASK-3990: Execute and options handlers check the scope before vault read and construction (M3b, part 2)

**Feature**: FEAT-622 — Agent Studio — Host Toolkits
**Spec**: `sdd/specs/agentstudio-host-toolkits.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3987, TASK-3989
**Assigned-to**: unassigned
**Wave**: 4 (spec §9) · **Module**: M3b scope-enforcement (handlers)

---

## Context

Spec §2 "Scope enforcement" → "Options" and "Direct execute": the options handler calls
`ensure_tool_scope(cls)` **before** `hydrate_params` (the vault read, `toolkit_config.py:154`) and before
construction (`:157`); `StudioToolExecuteHandler` calls `ensure_tool_scope(cls)` before `_instantiate_tool`
(`testing.py:372`), then `instance.execute(...)` gates again. Refusal: HTTP 403 `tool_scope_unavailable` with
`details.reason`.

---

## Scope

- `testing.py` execute: `ensure_tool_scope(cls, tool_name=slug)` before `_instantiate_tool`; `ToolScopeUnavailable`
  → 403 `tool_scope_unavailable`, `details={"reason": exc.reason}`. Map a structured scope `ToolResult` returned by
  `instance.execute` to the same 403.
- `toolkit_config.py` options: `ensure_tool_scope(cls, tool_name=slug)` before `hydrate_params`; refusal 403.
- Regression tests `test_execute_standalone_refuses_without_scope` (absent-scope leg; the mismatched leg is
  added by TASK-3991 once binding exists) and `test_options_refuse_before_vault_and_construction` (vault spy on
  `hydrate_params`, constructor and `options_calls` counters 0).

**NOT in scope**: binding a `RequestContext` in these handlers (TASK-3991).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` | MODIFY | execute: ensure_tool_scope before _instantiate_tool; 403 mapping |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py` | MODIFY | options: ensure_tool_scope before hydrate_params; 403 |
| `packages/ai-parrot-server/tests/studio/test_scope_enforcement_handlers.py` | CREATE | R6 handler regressions |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (ai-parrot `dev` @ `32b1a45d4`). The implementing agent MUST use these exact imports, class names,
> and method signatures. **DO NOT** invent, guess, or assume any import, attribute, or method not
> listed here. If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.tools.scope import ToolScopeUnavailable, ensure_tool_scope  # TASK-3976
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/testing.py
instance = _instantiate_tool(cls, self.request.app)  # :372 (occurrences: 1) — re-verify after TK-08/10/13
result = await instance.execute(**execute_request.args)  # :393 (occurrences: 1)
# packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py
hydrated = await hydrate_params(spec)  # :154 (occurrences: 1)
instance = cls(**params)  # :157 (occurrences: 1)
```

### Does NOT Exist
- ~~a request context in `/tools/{slug}/execute` or the options handler~~ — none today; TASK-3991 binds one. Until then the check refuses with `no_context`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/testing.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_scope_enforcement_handlers.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/testing.py#StudioToolExecuteHandler.post",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py#StudioToolkitOptionsHandler.get"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- One `_scope_error(exc)` helper per handler module returning the 403 `StudioError`.

### Cross-feature ordering
- **Wave 4 needs FEAT-605 W2.1 (`build_tool_scope`, `StudioAgentRef`, tenant partitions) and FEAT-621 W2 (runtime identity: `bot._studio_key`, `bot._tooling_ref`) merged** (X16 cross-spec waits); the asserted test-chat / meta-agent bindings need FEAT-605 W3.4 / W3.5.
- `testing.py` / `toolkit_config.py`: after the FEAT-621 W2/W3 task for each file (X16 per-file rule).

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
1. Insert `ensure_tool_scope` before `_instantiate_tool` and before `hydrate_params` — *why*: zero vault reads / constructions on refusal.
2. Map refusals to 403 — *why*: X14.
3. Tests with a vault spy and counters; mutation: move the check after `hydrate_params` ⇒ vault spy RED.

### `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'hydrated = await hydrate_params(spec)' toolkit_config.py)
# BEFORE — insert above the `try:` that contains `hydrated = await hydrate_params(spec)` (toolkit_config.py:153-154)
        try:
            ensure_tool_scope(cls, tool_name=slug)
        except ToolScopeUnavailable as exc:
            return self._error(str(exc), status=403, code=exc.code, details={"reason": exc.reason})
```

### `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` (MODIFY)
```python
# BEFORE the `try:` around `instance = _instantiate_tool(cls, self.request.app)`:
        try:
            ensure_tool_scope(cls, tool_name=slug)
        except ToolScopeUnavailable as exc:
            return self._error(str(exc), status=403, code=exc.code, details={"reason": exc.reason})
# FILL IN: after `result = await instance.execute(...)`: a result with metadata.error_code == "tool_scope_unavailable"
#   (or "confirmation_required") → 403 with that code
```

### FILL IN checklist
- [ ] result-to-403 mapping after execute — bounded by spec §2 "Error surface".

---

## Acceptance Criteria

- [ ] `/tools/tp_probe_tool/execute` with an absent scope → 403 `tool_scope_unavailable`; constructor, `_open`, `_execute` counters 0.
- [ ] Options for `tp_probe` with a missing scope → 403 `tool_scope_unavailable`; `hydrate_params` not called; constructor and `options_calls` 0.
- [ ] Non-tenant-bound tools/toolkits behave as before.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_scope_enforcement_handlers.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_testing_surface.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_toolkit_config.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_scope_enforcement_handlers.py
async def test_execute_standalone_refuses_without_scope(host_plugins): ...      # R6 regression (absent scope)
async def test_options_refuse_before_vault_and_construction(host_plugins): ...  # R6 regression
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
**Notes**: `StudioToolExecuteHandler` calls `ensure_tool_scope(cls, tool_name=slug)` (shared `_scope_refusal` in `_base/_storage.py`)
right after the tenant policy check and BEFORE `_instantiate_tool` (R-b: no constructor side effect without a valid scope); a
structured `tool_scope_unavailable` `ToolResult` coming out of `instance.execute` maps to the same 403
(`StudioToolExecuteHandler._execute_response`). `StudioToolkitOptionsHandler` checks the scope (and then the unknown-param 404) before
`hydrate_params` and construction (`_options_refusal`; `get` complexity unchanged at 10). Refusal = 403 `tool_scope_unavailable`
with `details.reason`. R-c: the server host probe gained tenant-bound entries (`tp_tenant` toolkit, `tp_tenant_tool`) and
`test_host_toolkit_paths.py` now runs every Studio path (catalogue, schema, generic assign, feat593 GET, options, /me, live assign, bot
build) for both the plain and the tenant-bound entries.
Mutations RED (restored): scope check before `_instantiate_tool` removed; options refusal removed; structured-result mapping removed;
`ensure_tool_scope` no-op.
Tests: `test_scope_enforcement_handlers.py` (3; counters for constructor/executed/options, hydrate spy), paths test (16).
Server suite vs baseline-package: 0 new (log artifacts/logs/b2-server-3990.log).

**Deviations from spec**: shared `_scope_refusal` lives in `_base/_storage.py` (not a per-module `_scope_error`); `_host_probe.py` and
`test_host_toolkit_paths.py` modified for R-c. The mismatched-scope leg of the execute test needs binding (TASK-3991).
