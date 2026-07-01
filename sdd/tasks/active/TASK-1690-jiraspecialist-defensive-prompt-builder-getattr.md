# TASK-1690: Defensive `getattr` guard for `_prompt_builder` in JiraSpecialist.__init__

**Feature**: FEAT-268 — jiraspecialist-prompt-builder-stub-leak
**Spec**: `sdd/specs/jiraspecialist-prompt-builder-stub-leak.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`JiraSpecialist.__init__` (`packages/ai-parrot/src/parrot/bots/jira_specialist.py:228`)
does an **unguarded** attribute read:

```python
if self._prompt_builder is None:
```

When `JiraSpecialist`'s MRO ends up resolving to a class that doesn't declare
`_prompt_builder` anywhere (e.g. the fake stub classes injected by
`packages/ai-parrot/tests/conftest.py::_install_parrot_stubs()` — see
TASK-1689 and the spec's §1 for the full diagnosis), this line raises
`AttributeError: 'JiraSpecialist' object has no attribute '_prompt_builder'`
instead of degrading gracefully.

The real `Agent.__init__` (`packages/ai-parrot/src/parrot/bots/agent.py:95`)
already uses a defensive pattern for exactly this risk:

```python
if system_prompt is None and getattr(self, "_prompt_builder", None) is None:
```

`JiraSpecialist.__init__` should follow the same established convention.

This is a small, independent, low-risk hardening — it does **not** by itself
fix the `AttributeError` seen under pytest today (TASK-1689 fixes the root
cause: the stub leak), but it stops this specific line from ever raising
`AttributeError` again if a similarly-shaped MRO surprise occurs in the
future, consistent with the codebase's existing defensive-getattr pattern for
optional prompt-builder attributes.

---

## Scope

- Change `packages/ai-parrot/src/parrot/bots/jira_specialist.py:228` from:
  ```python
  if self._prompt_builder is None:
  ```
  to:
  ```python
  if getattr(self, "_prompt_builder", None) is None:
  ```
- No other lines in `__init__` change.

**NOT in scope**:
- Any change to `packages/ai-parrot/tests/conftest.py` (that's TASK-1689).
- Any change to `_action_trigger_agent` or any other method in
  `jira_specialist.py` — this task touches exactly one line.
- Renaming or restructuring `_prompt_builder` / `prompt_builder` property
  handling.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/jira_specialist.py` | MODIFY | One-line defensive `getattr` guard at line 228 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot/src/parrot/bots/jira_specialist.py — no new imports needed
# getattr is a builtin, already implicitly available.
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/jira_specialist.py
class JiraSpecialist(Agent):                    # line 155
    def __init__(self, **kwargs):                # line 205
        ...
        _builder = kwargs.pop("prompt_builder", None) or self._build_jira_prompt_builder()  # line 217
        self._init_kwargs: Dict[str, Any] = dict(kwargs)  # line 223
        self._init_kwargs["prompt_builder"] = _builder     # line 224
        super().__init__(**kwargs)                # line 225
        if self._prompt_builder is None:           # line 228 — CHANGE THIS LINE ONLY
            self.prompt_builder = _builder          # line 229 — unchanged

# packages/ai-parrot/src/parrot/bots/agent.py — the established pattern to mirror EXACTLY
class Agent(AbstractBot):
    def __init__(self, ..., **kwargs):
        ...
        if system_prompt is None and getattr(self, "_prompt_builder", None) is None:  # line 95
            self._prompt_builder = PromptBuilder.agent()  # line 96

# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(...):                          # line 156
    _prompt_builder: Optional[PromptBuilder] = None  # line 187 — class-level default, real class
```

### Does NOT Exist

- ~~A `hasattr`-based pattern used elsewhere for this attribute~~ — the
  established convention in this codebase is `getattr(self, "_prompt_builder", None)`,
  not `hasattr` + separate access. Use `getattr`, not `hasattr`.
- ~~A `prompt_builder` property setter that needs updating~~ — line 229
  (`self.prompt_builder = _builder`) already uses the property setter
  (`AbstractBot.prompt_builder` setter at `abstract.py:1082`) and is
  unaffected by this change.

---

## Implementation Notes

### Pattern to Follow

```python
# Before (jira_specialist.py:228):
if self._prompt_builder is None:
    self.prompt_builder = _builder

# After:
if getattr(self, "_prompt_builder", None) is None:
    self.prompt_builder = _builder
```

### Key Constraints

- This is a one-line, mechanical change. Do not refactor surrounding code.
- Do not add a `try/except AttributeError` — use `getattr` with a default,
  matching `agent.py:95` exactly.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/agent.py:95` — the exact pattern to
  replicate.

---

## Acceptance Criteria

- [ ] `jira_specialist.py:228` uses `getattr(self, "_prompt_builder", None) is None`.
- [ ] No other line in the file changed.
- [ ] `pytest packages/ai-parrot/tests/test_jira_transition_dispatch.py -v` —
      still 46/46 passing (no regression to FEAT-265's own suite).
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/jira_specialist.py`
- [ ] Combined with TASK-1689, the four previously-failing test files
      (`test_jira_assignment.py`, `test_jiratoolkit_defaults.py`,
      `test_jira_ticket_created.py`, `test_jiraspecialist_prompt_builder.py`)
      pass under pytest.

---

## Test Specification

```python
# No new dedicated test file for this one-line change. Verification is via
# the existing test files listed in the Acceptance Criteria above, run both
# in isolation and combined with TASK-1689's fix.
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/jiraspecialist-prompt-builder-stub-leak.spec.md` for full context.
2. **Check dependencies** — none; can run independently of TASK-1689, in
   either order or in parallel.
3. **Verify the Codebase Contract** — confirm line 228 in
   `jira_specialist.py` still reads `if self._prompt_builder is None:`
   before editing (line numbers may have shifted since spec time).
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** the one-line change exactly as specified.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-1690-jiraspecialist-defensive-prompt-builder-getattr.md`.
8. **Update the per-spec index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
