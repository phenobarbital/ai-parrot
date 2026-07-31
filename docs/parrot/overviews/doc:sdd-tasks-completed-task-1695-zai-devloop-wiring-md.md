---
type: Wiki Overview
title: 'TASK-1695: Dev-loop wiring — package exports + server `zai` agent branch'
id: doc:sdd-tasks-completed-task-1695-zai-devloop-wiring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Module 4 of FEAT-269 (spec §3). Makes the new dispatcher reachable: exported'
relates_to:
- concept: mod:parrot.flows.dev_loop
  rel: mentions
- concept: mod:parrot.flows.dev_loop.dispatcher
  rel: mentions
- concept: mod:parrot.flows.dev_loop.models
  rel: mentions
---

# TASK-1695: Dev-loop wiring — package exports + server `zai` agent branch

**Feature**: FEAT-269 — Z.ai Code Dispatcher for the Dev Loop (GLM-5.2)
**Spec**: `sdd/specs/zai-client-code.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1694
**Assigned-to**: unassigned

---

## Context

Module 4 of FEAT-269 (spec §3). Makes the new dispatcher reachable: exported
from `parrot.flows.dev_loop` like its five siblings, and selectable in the
dev-loop reference server via `DEV_LOOP_DEVELOPMENT_AGENT=zai` with the
config keys defined in spec §2.

---

## Scope

- `packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py`:
  - Add `ZaiCodeDispatcher` to the dispatcher import block (lines 13-19)
    and `ZaiCodeDispatchProfile` to the models import block (lines 35-42).
  - Add both names to `__all__` (dispatcher names around lines 58-66,
    profile names around lines 59-67 — keep the existing pairing order).
- `examples/dev_loop/server.py` (`_on_startup`, agent selection lines
  449-540):
  - Add an `elif development_agent == "zai":` branch after the `"grok"`
    branch, mirroring its shape:
    - `ZaiCodeDispatcher(max_concurrent=conf.config.getint(
      "ZAI_CODE_MAX_CONCURRENT_DISPATCHES",
      fallback=conf.CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES),
      redis_url=redis_url, stream_ttl_seconds=conf.FLOW_STREAM_TTL_SECONDS)`
    - `ZaiCodeDispatchProfile(
      model=conf.config.get("DEV_LOOP_ZAI_MODEL", fallback="glm-5.2"),
      enable_thinking=conf.config.getboolean("DEV_LOOP_ZAI_ENABLE_THINKING", fallback=True),
      reasoning_effort=conf.config.get("DEV_LOOP_ZAI_REASONING_EFFORT", fallback="max"))`
    - `logger.info("Development node using Z.ai code dispatcher (model=%s, thinking=%s)",
      development_profile.model, development_profile.enable_thinking)`
  - Add the import of `ZaiCodeDispatcher` / `ZaiCodeDispatchProfile` to the
    server's existing dispatcher import block (lines 91-98 area).
  - Extend the final `elif development_agent not in {"claude", "claude-code"}`
    `RuntimeError` message to include `'zai'` in the enumerated valid values.

**NOT in scope**: dispatcher/profile implementation (TASK-1693/1694),
committed tests — including `test_server_zai_agent_startup` (TASK-1696),
README/docs for the example server, any change to `factories.py` or
`config.py` (dispatcher selection does NOT live there).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py` | MODIFY | Import + `__all__` for the new pair |
| `examples/dev_loop/server.py` | MODIFY | `"zai"` selection branch, imports, error message |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-03 against `dev`.

### Verified Imports
```python
from parrot.flows.dev_loop.dispatcher import ZaiCodeDispatcher    # exists after TASK-1694
from parrot.flows.dev_loop.models import ZaiCodeDispatchProfile   # exists after TASK-1693
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py
from parrot.flows.dev_loop.dispatcher import (      # line 13
    ClaudeCodeDispatcher,                           # line 14
    CodexCodeDispatcher,                            # line 15
    GeminiCodeDispatcher,                           # line 16
    LLMCodeDispatcher,                              # line 17
    GrokCodeDispatcher,                             # line 18
    DevLoopCodeDispatcher,                          # line 19
)
from parrot.flows.dev_loop.models import (          # line 35
    ClaudeCodeDispatchProfile,                      # line 38
    CodexCodeDispatchProfile,                       # line 39
    GeminiCodeDispatchProfile,                      # line 40
    LLMCodeDispatchProfile,                         # line 41
    GrokCodeDispatchProfile,                        # line 42
)
# __all__ entries: "ClaudeCodeDispatcher"(58), "ClaudeCodeDispatchProfile"(59),
#   "CodexCodeDispatcher"(60), "CodexCodeDispatchProfile"(61), ... paired ordering

# examples/dev_loop/server.py — the branch to mirror (grok, lines 516-530)
elif development_agent == "grok":
    development_dispatcher = GrokCodeDispatcher(
        max_concurrent=conf.config.getint(
            "GROK_CODE_MAX_CONCURRENT_DISPATCHES",
            fallback=conf.CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES,
        ),
        redis_url=redis_url,
        stream_ttl_seconds=conf.FLOW_STREAM_TTL_SECONDS,
    )
    development_profile = GrokCodeDispatchProfile(
        model=conf.config.get("DEV_LOOP_GROK_MODEL", fallback="grok-build-0.1")
    )
    logger.info("Development node using Grok code dispatcher (model=%s)",
                development_profile.model)
elif development_agent not in {"claude", "claude-code"}:
    raise RuntimeError(
        "DEV_LOOP_DEVELOPMENT_AGENT must be 'claude-code', 'codex', "
        "'gemini', 'nvidia', or 'grok', "
        f"got {development_agent!r}"
    )
# selection var (line ~456):
development_agent = conf.config.get("DEV_LOOP_DEVELOPMENT_AGENT", fallback="claude-code").strip().lower()
# server import block: lines 91-98 import the five dispatchers + profiles
```

### Does NOT Exist
- ~~`DEV_LOOP_ZAI_MODEL` / `ZAI_CODE_MAX_CONCURRENT_DISPATCHES` /
  `DEV_LOOP_ZAI_ENABLE_THINKING` / `DEV_LOOP_ZAI_REASONING_EFFORT`~~ —
  introduced by this task (config keys read via `conf.config`, no defaults
  file changes needed; `getboolean`/`getint`/`get` with `fallback=` is the
  existing pattern)
- ~~a dispatcher registry in `flows/dev_loop/config.py` or `factories.py`~~ —
  agent selection lives ONLY in `examples/dev_loop/server.py:_on_startup`;
  `factories.py` merely receives a pre-built dispatcher
- ~~`ZaiCodeDispatchProfile.thinking` field~~ — the field is
  `enable_thinking` (bool) + `reasoning_effort` (str); `thinking={...}` is
  the *request* payload built by the dispatcher, not a profile field

---

## Implementation Notes

### Pattern to Follow
Mirror the Grok branch exactly (server.py:516-530) — same config-key naming
scheme (`<PROVIDER>_CODE_MAX_CONCURRENT_DISPATCHES`, `DEV_LOOP_<PROVIDER>_*`),
same logger.info style (extended with thinking state per spec §2).

### Key Constraints
- `conf.config.getboolean(..., fallback=True)` for the thinking flag —
  matches the nvidia branch's boolean handling (server.py:505-513).
- Keep `__all__` alphabetical-pairing convention (Dispatcher then Profile,
  grouped by provider) as the file currently does.
- The `RuntimeError` message must list all six agents:
  `'claude-code', 'codex', 'gemini', 'nvidia', 'grok', or 'zai'`.
- Do not restructure the if/elif chain or touch other branches.

### References in Codebase
- `examples/dev_loop/server.py:449-545` — the selection chain
- `packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py:13-67` — export blocks
- `sdd/specs/zai-client-code.spec.md` §2 (config-key table)

---

## Acceptance Criteria

- [ ] `from parrot.flows.dev_loop import ZaiCodeDispatcher, ZaiCodeDispatchProfile` works
- [ ] Both names present in `parrot.flows.dev_loop.__all__`
- [ ] `DEV_LOOP_DEVELOPMENT_AGENT=zai` startup path builds `ZaiCodeDispatcher`
      + `ZaiCodeDispatchProfile` with the §2 config keys and defaults
      (`glm-5.2`, thinking on, effort `max`)
- [ ] Invalid agent error message includes `'zai'`
- [ ] Existing dev_loop suite still green (incl. server wiring tests):
      `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py examples/dev_loop/server.py`

---

## Test Specification

> Committed integration tests (`test_server_zai_agent_startup`,
> `test_server_invalid_agent_lists_zai`) land in TASK-1696, mirroring
> `test_server_repo_wiring.py:158` (`test_server_grok_agent_startup`).
> Smoke-verify the import surface inline before committing:

```python
import parrot.flows.dev_loop as dl
assert "ZaiCodeDispatcher" in dl.__all__ and "ZaiCodeDispatchProfile" in dl.__all__
from parrot.flows.dev_loop import ZaiCodeDispatcher, ZaiCodeDispatchProfile  # noqa: F401
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1694 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm the `__init__.py` import/`__all__` line anchors (13-19, 35-42,
     58-67) — they may shift; anchor on names
   - Confirm the Grok branch shape at server.py:516-530
4. **Update status** in `sdd/tasks/index/zai-client-code.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1695-zai-devloop-wiring.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-03
**Notes**: Added `ZaiCodeDispatcher`/`ZaiCodeDispatchProfile` to the
dispatcher/models import blocks and `__all__` in
`flows/dev_loop/__init__.py`, keeping the Dispatcher-then-Profile pairing
order used by the other providers. Added the same import pair to
`examples/dev_loop/server.py`'s dispatcher import block, and a
`elif development_agent == "zai":` branch mirroring the Grok branch shape
(config keys `ZAI_CODE_MAX_CONCURRENT_DISPATCHES`, `DEV_LOOP_ZAI_MODEL`,
`DEV_LOOP_ZAI_ENABLE_THINKING`, `DEV_LOOP_ZAI_REASONING_EFFORT`, all with
the §2-specified defaults/fallbacks) plus the specified `logger.info` line.
Extended the invalid-agent `RuntimeError` message to enumerate `'zai'`.
Verified via inline smoke import
(`from parrot.flows.dev_loop import ZaiCodeDispatcher, ZaiCodeDispatchProfile`
+ `__all__` membership), `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
(305 passed, 5 skipped, same 4 pre-existing order-dependent failures
reproduced identically on unmodified `dev`), and `ruff check` (clean).

**Deviations from spec**: none
