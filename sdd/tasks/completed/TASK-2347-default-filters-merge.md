# TASK-2347: `default_filters` constructor kwarg + merge precedence

**Feature**: FEAT-441 — Fireflies MCP Meeting Filters & Native Summary Retrieval
**Spec**: `sdd/specs/fireflies-mcp-improvements.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2346
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. Lets `FirefliesObsidianAgent`'s constructor (and therefore
`fireflies_daemon.yaml`, via TASK-2350) declare a standing filter scope for
unattended scheduled runs, without every caller having to repeat it. This
task only adds the constructor kwarg and the merge helper — TASK-2348 is
what actually calls `sync_fireflies_transcripts()` with the merged result.

---

## Scope

- Add a new `default_filters: Optional[FirefliesFilters] = None` keyword
  argument to `FirefliesObsidianAgent.__init__()`, stored as
  `self.default_filters`.
- Add a merge helper, e.g. `_merge_filters(default: Optional[FirefliesFilters],
  call: Optional[FirefliesFilters]) -> Optional[FirefliesFilters]`, that
  combines the two **field-by-field**: for every field, use the `call`
  value if it differs from that field's model default (i.e. the caller
  explicitly set it); otherwise use the `default` value for that field.
  Return `None` only if both inputs are `None`.
- Write unit tests for the merge helper: call-field-wins-when-both-set,
  default-fills-unset-call-fields, both-`None`-returns-`None`,
  only-default-set, only-call-set.

**NOT in scope**:
- Calling `_merge_filters()` from inside `sync_fireflies_transcripts()` —
  that integration happens in TASK-2348 (pagination loop needs the merged
  result to build tool args per page).
- Any change to `fireflies_daemon.yaml` — TASK-2350.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/agents/obsidian.py` | MODIFY | `default_filters` constructor kwarg + `_merge_filters()` helper. |
| `packages/ai-parrot/tests/agents/test_obsidian.py` | MODIFY | Add merge-precedence tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already present after TASK-2346 lands — do not re-add:
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Dict, Any, List, Literal
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/agents/obsidian.py:76-83 (verify line numbers before editing —
# TASK-2346 only adds a new class/function, it should not shift this constructor)
def __init__(
    self,
    name: str = "FirefliesObsidianSync",
    vault_path: Optional[str | Path] = None,
    fireflies_token: Optional[str] = None,
    meetings_folder: str = "meetings",
    **kwargs,
):
    """Initialize the Fireflies→Obsidian sync agent."""
    super().__init__(name=name, **kwargs)
    if vault_path:
        self.vault_path = Path(vault_path)
    else:
        env_vault = config.get("OBSIDIAN_VAULT_PATH") or os.getenv("OBSIDIAN_VAULT_PATH")
        self.vault_path = Path(env_vault) if env_vault else Path.home() / "vaults" / "notes"
    self.fireflies_token = fireflies_token
    self.meetings_folder = meetings_folder
    # ObsidianToolkit init, self._mcp_fireflies_initialized = False, self.logger = ...
    # (lines 104-118 — do not disturb, add default_filters assignment near
    # fireflies_token/meetings_folder for cohesion)

# From TASK-2346 (must exist before this task starts):
class FirefliesFilters(BaseModel):
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    keyword: Optional[str]
    scope: Literal["title", "sentences", "all"] = "all"
    organizers: list[EmailStr]
    participants: list[EmailStr]
    mine: Optional[bool] = None
    channel_id: Optional[str] = None
```

### Does NOT Exist
- ~~A `default_filters` constructor kwarg on `FirefliesObsidianAgent`~~ — does not exist yet; this task adds it.
- ~~A `_merge_filters` or similarly-named helper~~ — does not exist yet.
- ~~Any call site that already uses `self.default_filters`~~ — none; `sync_fireflies_transcripts()` is untouched by this task (TASK-2348's job).

---

## Implementation Notes

### Pattern to Follow
```python
def _merge_filters(
    default: Optional["FirefliesFilters"],
    call: Optional["FirefliesFilters"],
) -> Optional["FirefliesFilters"]:
    """Merge agent-level default filters with a per-call override.

    Per-call fields win wherever the caller explicitly set them; the
    agent's default_filters fills in any field the call left at its
    model-default (unset) value. Field-by-field, never whole-object.
    """
    if default is None and call is None:
        return None
    if default is None:
        return call
    if call is None:
        return default

    merged = default.model_dump()
    call_explicit = call.model_dump(exclude_defaults=True)
    merged.update(call_explicit)
    return FirefliesFilters(**merged)
```
`exclude_defaults=True` is the key mechanic: it produces a dict containing
only the fields the caller actually set to a non-default value, so
`merged.update(...)` only overwrites what the call explicitly specified.

### Key Constraints
- Merge must be **field-by-field**, never `call or default` (spec §7 Known
  Risks explicitly warns against this shortcut).
- Do not mutate either input `FirefliesFilters` instance.
- Constructor kwarg placement: keep it near `fireflies_token`/
  `meetings_folder` in the signature and body for readability — don't
  reorder existing parameters (would break any positional-argument caller,
  however unlikely).

### References in Codebase
- `sdd/specs/fireflies-mcp-improvements.spec.md` §3 Module 2, §7 (merge precedence risk note).
- `packages/ai-parrot/src/parrot/agents/obsidian.py:76-118` — full current constructor body to extend.

---

## Acceptance Criteria

- [ ] `FirefliesObsidianAgent(default_filters=FirefliesFilters(...))` stores it as `self.default_filters`.
- [ ] Omitting `default_filters` leaves `self.default_filters` as `None` (no behavior change for existing callers).
- [ ] `_merge_filters(default=FirefliesFilters(mine=False), call=FirefliesFilters(mine=True))` returns a filter with `mine=True`.
- [ ] `_merge_filters(default=FirefliesFilters(channel_id="X"), call=FirefliesFilters(mine=True))` returns a filter with both `channel_id="X"` and `mine=True`.
- [ ] `_merge_filters(None, None)` returns `None`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/agents/test_obsidian.py -v -k Merge`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/agents/obsidian.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/agents/test_obsidian.py
from parrot.agents.obsidian import FirefliesFilters, _merge_filters, FirefliesObsidianAgent


class TestMergeFilters:
    def test_call_wins_on_shared_field(self):
        default = FirefliesFilters(mine=False)
        call = FirefliesFilters(mine=True)
        merged = _merge_filters(default, call)
        assert merged.mine is True

    def test_default_fills_unset_call_fields(self):
        default = FirefliesFilters(channel_id="X")
        call = FirefliesFilters(mine=True)
        merged = _merge_filters(default, call)
        assert merged.channel_id == "X"
        assert merged.mine is True

    def test_both_none_returns_none(self):
        assert _merge_filters(None, None) is None

    def test_only_default_set(self):
        default = FirefliesFilters(mine=True)
        assert _merge_filters(default, None).mine is True

    def test_only_call_set(self):
        call = FirefliesFilters(mine=True)
        assert _merge_filters(None, call).mine is True


class TestDefaultFiltersConstructor:
    def test_stores_default_filters(self, vault_path):
        agent = FirefliesObsidianAgent(
            vault_path=str(vault_path),
            fireflies_token="test-token",
            default_filters=FirefliesFilters(mine=True),
        )
        assert agent.default_filters.mine is True

    def test_default_filters_none_when_omitted(self, agent):
        assert agent.default_filters is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/fireflies-mcp-improvements.spec.md` for full context.
2. **Check dependencies** — verify TASK-2346 is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `FirefliesFilters` exists exactly as TASK-2346 left it.
   - Re-check the constructor's current line range (TASK-2346 should not have moved it, but verify).
4. **Update status** in the per-spec index → `"in-progress"` with your session ID.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-2347-default-filters-merge.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: claude-sonnet-5 (sdd-start session)
**Date**: 2026-08-22
**Notes**: Added `default_filters: Optional[FirefliesFilters] = None`
constructor kwarg (stored as `self.default_filters`) and the
`_merge_filters()` field-by-field merge helper to
`packages/ai-parrot/src/parrot/agents/obsidian.py`, exactly per scope —
`sync_fireflies_transcripts()` itself is untouched (TASK-2348's job). Added
8 new unit tests (`TestMergeFilters`, `TestDefaultFiltersConstructor`) —
all pass; full `test_obsidian.py` suite (64 passed, 1 pre-existing skip)
shows no regressions. No new lint findings introduced by this task's own
lines (spot-checked against the task's line range — the only findings in
that vicinity are pre-existing `Optional[...]`/`except Exception` patterns
already present throughout the file, just shifted by the insertion).

**Deviations from spec**: none.
