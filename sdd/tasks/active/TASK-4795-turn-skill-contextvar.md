# TASK-4795: Request-local turn skill (`current_turn_skill()`)

**Feature**: FEAT-752 — Follow-up Suggestion Chips
**Spec**: `sdd/specs/followup-suggestion-chips.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec rev 0.2, §7 "Skill rule". The skill lane needs to know which skill the `/trigger` activated for this turn, but
`create_system_prompt()` clears the active skill (`set_active_skill(None)`, `bots/abstract.py:3726`) **before** the LLM
call, so `current_active_skill()` is always `None` by the time suggestions attach (`bots/base.py:1735`, `:2303`).
This task adds a second request-local ContextVar that survives the prompt build and lives exactly as long as the
`ask()`/`ask_stream()` skill scope (exited at `base.py:1855` / `:2353`, after the attach points).

---

## Scope

- Add `_turn_skill` ContextVar and `current_turn_skill()` to `parrot/skills/tenancy.py`.
- `set_active_skill(skill)`: when `skill is not None`, also set `_turn_skill` (clearing with `None` must NOT clear it).
- `enter_active_skill_scope()` snapshots both vars; `exit_active_skill_scope()` resets both (composite token).
- Tests in a new `tests/unit/test_skill_turn_scope.py`.

**NOT in scope**: the provider that reads it (TASK-4798); any change to `current_active_skill()` semantics,
`abstract.py`, `base.py` or the trigger middleware.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/skills/tenancy.py` | MODIFY | `_turn_skill`, `current_turn_skill`, composite scope token |
| `packages/ai-parrot/tests/unit/test_skill_turn_scope.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.skills.tenancy import (                      # verified: packages/ai-parrot/src/parrot/skills/tenancy.py
    current_active_skill,      # :97
    set_active_skill,          # :102
    enter_active_skill_scope,  # :107
    exit_active_skill_scope,   # :117
)
from parrot.skills.models import SkillDefinition, SkillSource  # verified: skills/models.py:60, :53
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/skills/tenancy.py
from contextvars import ContextVar, Token                                         # line 10
from typing import Dict, Final, List, Optional                                    # line 13
_active_skill: ContextVar[Optional[SkillDefinition]] = ContextVar("parrot_active_skill", default=None)  # line 79
def current_active_skill() -> Optional[SkillDefinition]: return _active_skill.get()   # line 97-99
def set_active_skill(skill: Optional[SkillDefinition]) -> None: _active_skill.set(skill)  # line 102-104
def enter_active_skill_scope() -> Token: return _active_skill.set(_active_skill.get())    # line 107-114
def exit_active_skill_scope(token: Token) -> None: _active_skill.reset(token)             # line 117-119

# Callers (token is opaque to them — verified via grep over packages/):
#   packages/ai-parrot/src/parrot/bots/base.py:1133/1855 (ask), :1911/:2353 (ask_stream)
#   packages/ai-parrot/tests/unit/test_skill_tenant_hardening.py:69-71
# Writers of the active skill: skills/middleware.py:79 (set_active_skill(skill)), skills/mixin.py:108 (setter),
#   bots/abstract.py:3726 (set_active_skill(None) after the prompt build)
```

### Does NOT Exist
- ~~`current_turn_skill`~~ / ~~`_turn_skill`~~ — created by this task.
- ~~`SkillRegistryMixin.turn_skill`~~ — do not add a mixin attribute; the ContextVar is the single source.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/skills/tenancy.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_skill_turn_scope.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/skills/tenancy.py#set_active_skill",
    "sym:packages/ai-parrot/src/parrot/skills/tenancy.py#enter_active_skill_scope",
    "sym:packages/ai-parrot/src/parrot/skills/tenancy.py#exit_active_skill_scope"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the `_turn_skill` ContextVar below `_active_skill` — *why*: survives the prompt-build clear.
2. Add `current_turn_skill()` after `current_active_skill()` — *why*: the provider's read API.
3. Change `set_active_skill` to also record non-`None` skills — *why*: covers middleware and mixin setter in one place.
4. Replace the scope pair with a composite token — *why*: the turn skill must never leak into the next request.
5. Write tests; run the Validation Commands, including the existing tenancy hardening test.

### `packages/ai-parrot/src/parrot/skills/tenancy.py` (MODIFY — ContextVar)
```python
# occurrences: 1 (verified: grep -c '^_active_skill: ContextVar' packages/ai-parrot/src/parrot/skills/tenancy.py)
# AFTER — insert below `_active_skill: ContextVar[...] = ContextVar("parrot_active_skill", default=None)` (tenancy.py:79)
# FEAT-752: the skill activated during this turn. Unlike `_active_skill`, it is NOT cleared when the system
# prompt consumes the skill, so post-answer hooks (suggestion chips) can still read it.
_turn_skill: ContextVar[Optional[SkillDefinition]] = ContextVar("parrot_turn_skill", default=None)
```

### `packages/ai-parrot/src/parrot/skills/tenancy.py` (MODIFY — functions, replaces lines 102-119)
```python
# occurrences: 1 each (verified: grep -c 'def set_active_skill\|def enter_active_skill_scope\|def exit_active_skill_scope')
# REPLACE the bodies of set_active_skill / enter_active_skill_scope / exit_active_skill_scope (tenancy.py:102-119);
# INSERT current_turn_skill() right after current_active_skill() (:97-99).
def current_turn_skill() -> Optional[SkillDefinition]:
    """Return the skill a ``/trigger`` activated during this turn, even after the prompt consumed it (FEAT-752)."""
    return _turn_skill.get()


def set_active_skill(skill: Optional[SkillDefinition]) -> None:
    """Replace the request-local active skill; a non-``None`` skill is also recorded as the turn skill."""
    _active_skill.set(skill)
    if skill is not None:
        _turn_skill.set(skill)


class ActiveSkillScope(NamedTuple):
    """Opaque token pair returned by :func:`enter_active_skill_scope`."""

    active: Token
    turn: Token


def enter_active_skill_scope() -> ActiveSkillScope:
    """Snapshot the active and turn skills so :func:`exit_active_skill_scope` can restore both.

    ``ask()``/``ask_stream()`` open this scope so a skill a ``/trigger`` set during a call never outlives that
    call, even when the call fails before the system prompt consumes it.
    """
    return ActiveSkillScope(_active_skill.set(_active_skill.get()), _turn_skill.set(_turn_skill.get()))


def exit_active_skill_scope(token: ActiveSkillScope) -> None:
    """Restore the skills captured by :func:`enter_active_skill_scope`."""
    # FILL IN: reset token.turn then token.active (reverse order of creation) — bounded by
    #          test_scope_restores_both and the existing test_skill_tenant_hardening.py:69-71
    raise NotImplementedError
```
**Why this shape**: `NamedTuple` keeps the token opaque for `base.py` (it only passes it back). Add `NamedTuple` to the
`typing` import on line 13. Do not change `current_active_skill()`.

### FILL IN checklist
- [ ] `exit_active_skill_scope` — reset both tokens; bounded by the hardening test.
- [ ] Test bodies below.

---

## Acceptance Criteria

- [ ] `set_active_skill(skill); set_active_skill(None)` → `current_active_skill() is None`, `current_turn_skill() is skill`.
- [ ] After `exit_active_skill_scope(token)`, both skills are back to their values at `enter_…` time.
- [ ] The turn skill set inside one `asyncio` task does not appear in a sibling task.
- [ ] `test_skill_tenant_hardening.py` and `test_skill_tenancy.py` stay green; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_skill_turn_scope.py -q`
- `pytest packages/ai-parrot/tests/unit/test_skill_tenant_hardening.py -q`
- `pytest packages/ai-parrot/tests/unit/test_skill_tenancy.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_skill_turn_scope.py
import asyncio
from pathlib import Path
from parrot.skills.models import SkillDefinition, SkillSource
from parrot.skills.tenancy import (
    current_active_skill, current_turn_skill, enter_active_skill_scope, exit_active_skill_scope, set_active_skill,
)


def _skill(name: str = "s") -> SkillDefinition:
    return SkillDefinition(name=name, description="d", triggers=[f"/{name}"], source=SkillSource.AUTHORED,
                           template_body="b", token_count=1, file_path=Path(f"/tmp/{name}.md"))


def test_turn_skill_survives_prompt_clear():
    token = enter_active_skill_scope()
    try:
        s = _skill()
        set_active_skill(s)
        set_active_skill(None)  # what create_system_prompt does
        assert current_active_skill() is None
        assert current_turn_skill() is s
    finally:
        exit_active_skill_scope(token)


def test_scope_restores_both():
    # FILL IN: after exit, current_turn_skill() and current_active_skill() equal their pre-enter values
    ...


async def test_turn_skill_is_task_local():
    # FILL IN: set in one asyncio task; a sibling task created before/independently sees None
    ...
```

---

## Agent Instructions

Follow `sdd/templates/task.md` § Agent Instructions (worktree via `ensure_worktree --slug followup-suggestion-chips
--feature-id FEAT-752`, `PYTHONPATH=packages/ai-parrot/src`, commit only listed files,
`scripts/sdd/close_task.sh TASK-4795 followup-suggestion-chips verified`).

---

## Completion Note

*(Agent fills this in when done)*
