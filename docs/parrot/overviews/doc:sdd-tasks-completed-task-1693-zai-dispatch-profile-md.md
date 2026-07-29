---
type: Wiki Overview
title: 'TASK-1693: ZaiCodeDispatchProfile — Pydantic profile with Z.ai-native thinking
  fields'
id: doc:sdd-tasks-completed-task-1693-zai-dispatch-profile-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 2 of FEAT-269 (spec §3, §2 Data Models). Unlike Grok's standalone
relates_to:
- concept: mod:parrot.flows.dev_loop.models
  rel: mentions
- concept: mod:parrot.models.zai
  rel: mentions
---

# TASK-1693: ZaiCodeDispatchProfile — Pydantic profile with Z.ai-native thinking fields

**Feature**: FEAT-269 — Z.ai Code Dispatcher for the Dev Loop (GLM-5.2)
**Spec**: `sdd/specs/zai-client-code.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1692
**Assigned-to**: unassigned

---

## Context

Module 2 of FEAT-269 (spec §3, §2 Data Models). Unlike Grok's standalone
profile, `ZaiCodeDispatchProfile` **subclasses `LLMCodeDispatchProfile`** so
it flows through the inherited `LLMCodeDispatcher.dispatch()` loop unchanged,
and the dispatcher's `_completion_args(profile, tools)` override (TASK-1694)
can read the Z.ai fields directly off the profile — no per-dispatch state on
the shared dispatcher instance (concurrency-safe under the semaphore).

---

## Scope

- Add `ZaiCodeDispatchProfile(LLMCodeDispatchProfile)` to
  `packages/ai-parrot/src/parrot/flows/dev_loop/models.py`, placed after
  `GrokCodeDispatchProfile` (line 490 block):
  - `model: str = "glm-5.2"` — convenience field mirroring
    `GrokCodeDispatchProfile.model` ergonomics.
  - `llm: str = "zai:glm-5.2"` — redeclared default.
  - A Pydantic v2 `model_validator(mode="after")` that keeps
    `llm == f"zai:{model}"` when the caller set only `model` (i.e., if `llm`
    was not explicitly provided, derive it from `model`).
  - `enable_thinking: bool = True` — redeclared default (Z.ai semantics; the
    Nvidia `extra_body` meaning does NOT apply — reinterpreted by TASK-1694).
  - `reasoning_effort: Literal["max", "xhigh", "high", "medium", "low",
    "minimal", "none"] = "max"`.
  - `max_tokens: int = Field(default=8192, ge=256, le=131072)` — redeclared
    bounds (GLM-5.2 supports 128K output; thinking tokens count toward it).
  - Google-style docstring describing the profile and each new field
    (`Field(..., description=...)` where it adds value).
- All other fields inherited unchanged (subagent, sandbox, approval_policy,
  timeout_seconds, max_turns, temperature, command_timeout_seconds,
  allowed_commands, clear_thinking).

**NOT in scope**: the dispatcher class (TASK-1694), exports from
`flows/dev_loop/__init__.py` (TASK-1695), tests (TASK-1696 — but run a smoke
instantiation before committing).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` | MODIFY | Add `ZaiCodeDispatchProfile` after the Grok profile block |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-03 against `dev`.

### Verified Imports
```python
# Already imported at the top of flows/dev_loop/models.py (BaseModel, Field,
# Literal are in use by the existing profiles — verify before adding imports;
# model_validator may need to be added to the pydantic import line).
from parrot.flows.dev_loop.models import LLMCodeDispatchProfile   # models.py:450
from parrot.models.zai import ZaiModel                            # models/zai.py:4 — GLM_5_2 exists after TASK-1692
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models.py
class LLMCodeDispatchProfile(BaseModel):                    # line 450
    subagent: Literal["sdd-worker"] = "sdd-worker"
    llm: str = "nvidia:moonshotai/kimi-k2-instruct-0905"
    sandbox: Literal["workspace-write"] = "workspace-write"
    approval_policy: Literal["never"] = "never"
    timeout_seconds: int   # Field(default=1800, ge=60, le=7200)
    max_turns: int         # Field(default=24, ge=1, le=100)
    max_tokens: int        # Field(default=4096, ge=256, le=32768) ← redeclare in subclass
    temperature: float     # Field(default=0.0, ge=0.0, le=2.0)
    command_timeout_seconds: int  # Field(default=300, ge=1, le=3600)
    allowed_commands: List[str]   # default_factory list: git, uv, pytest, python, python3, rg, ls, pwd, cat, sed, find
    enable_thinking: bool = False # ← redeclare True in subclass
    clear_thinking: bool = False

class GrokCodeDispatchProfile(BaseModel):                   # line 490 — style/docstring reference
    model: str = "grok-build-0.1"
```

### Does NOT Exist
- ~~`ZaiCodeDispatchProfile`~~ — created by this task
- ~~`reasoning_effort` on `LLMCodeDispatchProfile`~~ — new field, subclass only
- ~~Pydantic v1 `@validator`~~ — use Pydantic v2 `model_validator` (the repo
  is Pydantic v2; check models.py's existing imports)
- ~~`GrokCodeDispatchProfile` inheritance~~ — Grok's profile is a standalone
  BaseModel; do NOT copy its shape, this profile deliberately subclasses
  `LLMCodeDispatchProfile` instead (spec §2)

---

## Implementation Notes

### Pattern to Follow
```python
# Docstring style — mirror LLMCodeDispatchProfile (models.py:450-455):
class ZaiCodeDispatchProfile(LLMCodeDispatchProfile):
    """Declarative profile consumed by ``ZaiCodeDispatcher.dispatch()``.

    Subclasses ``LLMCodeDispatchProfile`` so it flows through the inherited
    dispatch loop unchanged; Z.ai-native fields (``enable_thinking``,
    ``reasoning_effort``) are consumed by ``ZaiCodeDispatcher._completion_args``.
    """
```

### Key Constraints
- The `model` ↔ `llm` sync must not fight an explicit `llm`: if the caller
  passes `llm="zai:glm-5.1"` explicitly, respect it. Simplest robust rule:
  in the after-validator, if `llm` still equals the class default AND
  `model` differs from the class default, set `llm = f"zai:{model}"`.
  (Also acceptable: always derive `llm` from `model` unless `llm` was
  explicitly set — use `model_fields_set` to detect.)
- `reasoning_effort` semantics (spec §6): GLM-5.2-only, effective only when
  thinking is enabled; `low`/`medium` map server-side to `high`, `xhigh` to
  `max`, `none`/`minimal` skip thinking. Do NOT add client-side mapping.
- Keep `clear_thinking` inherited but unused — do not remove or repurpose.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/models.py:450-536` — the two
  profile blocks this one sits beside
- `sdd/specs/zai-client-code.spec.md` §2 Data Models — the exact contract

---

## Acceptance Criteria

- [ ] `ZaiCodeDispatchProfile()` defaults: `model="glm-5.2"`,
      `llm="zai:glm-5.2"`, `enable_thinking is True`,
      `reasoning_effort="max"`, `max_tokens=8192`
- [ ] `ZaiCodeDispatchProfile(model="glm-5.1").llm == "zai:glm-5.1"`
- [ ] `max_tokens=131072` accepted; `131073` and `255` raise `ValidationError`
- [ ] `reasoning_effort="turbo"` raises `ValidationError` (Literal enforcement)
- [ ] `isinstance(ZaiCodeDispatchProfile(), LLMCodeDispatchProfile)` is True
- [ ] Existing dev_loop tests still pass:
      `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/models.py`

---

## Test Specification

> Committed tests land in TASK-1696 (`test_zai_profile_defaults`,
> `test_zai_profile_model_syncs_llm`, `test_zai_profile_max_tokens_bounds`).
> Smoke-verify the acceptance criteria inline before committing this task.

```python
from parrot.flows.dev_loop.models import ZaiCodeDispatchProfile, LLMCodeDispatchProfile
p = ZaiCodeDispatchProfile()
assert (p.model, p.llm, p.enable_thinking, p.reasoning_effort, p.max_tokens) == \
       ("glm-5.2", "zai:glm-5.2", True, "max", 8192)
assert ZaiCodeDispatchProfile(model="glm-5.1").llm == "zai:glm-5.1"
assert isinstance(p, LLMCodeDispatchProfile)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1692 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists
   - Confirm `LLMCodeDispatchProfile` field defaults/bounds at models.py:450
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `sdd/tasks/index/zai-client-code.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1693-zai-dispatch-profile.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-03
**Notes**: Added `ZaiCodeDispatchProfile(LLMCodeDispatchProfile)` in
`flows/dev_loop/models.py`, placed after `GrokCodeDispatchProfile`, with
`model="glm-5.2"`, `llm="zai:glm-5.2"`, `enable_thinking=True`,
`reasoning_effort` Literal (default `"max"`), and `max_tokens` redeclared
`Field(default=8192, ge=256, le=131072)`. Added a Pydantic v2
`model_validator(mode="after")` that derives `llm` from `model` only when
`llm` was not explicitly set (checked via `model_fields_set`), so an
explicit `llm=` override is respected. Added `model_validator` to the
pydantic import line. Verified via inline smoke script covering all
acceptance criteria (defaults, model→llm sync, explicit-llm override,
max_tokens bounds, reasoning_effort Literal enforcement, isinstance check),
`pytest packages/ai-parrot/tests/flows/dev_loop/ -v` (305 passed, 5 skipped,
4 pre-existing failures reproduced identically on unmodified `dev` — test
ordering flakiness in `test_webhook.py`/`test_server_repo_wiring.py`,
unrelated to this change), and `ruff check` (clean).

**Deviations from spec**: none
