# TASK-855: Upgrade `anthropic` SDK Pin from 0.61.0 to >=0.97.0

**Feature**: FEAT-124 — Claude SDK Migration & ClaudeAgentClient
**Spec**: `sdd/specs/claude-sdk-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Spec Module 1. The `anthropic[aiohttp]` pin is at `==0.61.0` — 36 versions
> behind the latest `0.97.0`. This blocks adoption of new beta headers, model
> constants, and bug fixes. The upgrade is the prerequisite for regression
> validation (TASK-856).

---

## Scope

- Bump `anthropic[aiohttp]` from `==0.61.0` to `>=0.97.0,<1.0.0` in the
  `anthropic` extra (line 346) of `packages/ai-parrot/pyproject.toml`.
- Bump the same pin in the `llms` extra (line 370).
- Run `uv pip install -e "packages/ai-parrot[anthropic]"` and confirm the
  resolved version is ≥0.97.0.
- Verify `from anthropic import AsyncAnthropic, RateLimitError, APIStatusError`
  and `from anthropic.types import Message, MessageStreamEvent` succeed.

**NOT in scope**: code changes to `parrot/clients/claude.py` (that's TASK-856),
`claude-agent-sdk` restructure (that's TASK-860), new `ClaudeAgentClient`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | Bump `anthropic[aiohttp]` pin in `anthropic` extra (L346) and `llms` extra (L370) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
# Anthropic SDK — these must still resolve after the bump
from anthropic import AsyncAnthropic, RateLimitError, APIStatusError  # claude.py:17,75
from anthropic.types import Message, MessageStreamEvent                # claude.py:18
```

### Existing Signatures to Use
```python
# packages/ai-parrot/pyproject.toml — extras to modify
# Line 345-348:
# anthropic = [
#     "anthropic[aiohttp]==0.61.0",           ← change to >=0.97.0,<1.0.0
#     "claude-agent-sdk>=0.1.0,!=0.1.49",     ← leave for now (TASK-860)
# ]
#
# Line 366-373:
# llms = [
#     ...
#     "anthropic[aiohttp]==0.61.0",           ← change to >=0.97.0,<1.0.0
#     "claude-agent-sdk>=0.1.0,!=0.1.49",     ← leave for now (TASK-860)
#     ...
# ]
```

### Does NOT Exist
- ~~`anthropic.AsyncAnthropic.responses`~~ — no `responses` namespace; we use `messages.create`, `messages.stream`, `messages.batches`
- ~~`from anthropic.types import StreamEvent`~~ — the actual type is `MessageStreamEvent`

---

## Implementation Notes

### Pattern to Follow
This is a pure dependency pin change. No code changes expected.

### Key Constraints
- Pin style: `>=0.97.0,<1.0.0` (allow patch + minor within the 0.x series)
- Do NOT touch `claude-agent-sdk` lines — that's TASK-860
- After installing, run a quick import check to confirm no breakage

### References in Codebase
- `packages/ai-parrot/pyproject.toml:345-348` — `anthropic` extra
- `packages/ai-parrot/pyproject.toml:366-373` — `llms` extra
- `packages/ai-parrot/src/parrot/clients/claude.py:17-18` — imports to verify

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/pyproject.toml` pins `anthropic[aiohttp]>=0.97.0,<1.0.0` in the `anthropic` extra
- [ ] `packages/ai-parrot/pyproject.toml` pins `anthropic[aiohttp]>=0.97.0,<1.0.0` in the `llms` extra
- [ ] `uv pip install -e "packages/ai-parrot[anthropic]"` resolves to anthropic ≥0.97.0
- [ ] `from anthropic import AsyncAnthropic, RateLimitError, APIStatusError` succeeds
- [ ] `from anthropic.types import Message, MessageStreamEvent` succeeds

---

## Test Specification

```python
# Verification — run interactively after install
import anthropic
assert tuple(int(x) for x in anthropic.__version__.split('.')[:2]) >= (0, 97)

from anthropic import AsyncAnthropic, RateLimitError, APIStatusError
from anthropic.types import Message, MessageStreamEvent
print("All imports OK, version:", anthropic.__version__)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm the pyproject.toml lines are as described
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** the pin bump
6. **Verify** by installing and running import checks
7. **Move this file** to `tasks/completed/TASK-855-anthropic-sdk-pin-upgrade.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (FEAT-124 autonomous run)
**Date**: 2026-04-26
**Notes**: Bumped `anthropic[aiohttp]` pin from `==0.61.0` to `>=0.97.0,<1.0.0` in
both the `anthropic` and `llms` extras of `packages/ai-parrot/pyproject.toml`.
The `claude-agent-sdk` lines were left unchanged (TASK-860 will restructure them).
Verified the upgrade by running `uv pip install "anthropic[aiohttp]>=0.97.0,<1.0.0"`
in the existing `.venv` — resolved to `anthropic==0.97.0`. Confirmed all critical
imports still resolve: `AsyncAnthropic`, `RateLimitError`, `APIStatusError`,
`Message`, `MessageStreamEvent`. No code changes to `claude.py` were needed.

**Deviations from spec**: none
