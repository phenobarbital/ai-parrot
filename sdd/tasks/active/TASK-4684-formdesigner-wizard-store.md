# TASK-4684: Section wizard state store (M5)

**Feature**: FEAT-734 — Serve FormDesigner forms from a Teams agent
**Spec**: `sdd/specs/formdesigner-serve-forms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 5**: process-local, TTL-bounded state for multi-section forms
served as a card wizard. Shaped like `RecentActivityCache`
(`formdesigner_submit.py:201`) — bounded, best-effort, no new persistence
dependency. The spec's Delivery contracts add two requirements this store must
make possible: a **per-state async lock** (validate/advance/post under one lock)
and a **consumed** marker set before the single terminal POST.

Leaf task, wave 1.

---

## Scope

- Create `formdesigner_wizard.py` with the `WizardState` dataclass (spec §2 fields
  + `lock` + `consumed`) and `WizardStore` (`start`, `get`, `advance`, `finish`,
  `discard`).
- Key = `(conversation_id, form_uid)`. `start` replaces any existing state with a
  fresh `wizard_id`. `get` returns `None` when absent or past TTL. Bounded by
  `max_items` (evict least-recently-updated).
- Write `tests/msteams/test_formdesigner_wizard.py` (three M5 tests + start/discard).

**NOT in scope**: validating wizard control objects, rendering, posting — all in
the mixin (TASK-4692). Redis-backed state (spec §7: follow-up).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_wizard.py` | CREATE | WizardState + WizardStore |
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_wizard.py` | CREATE | M5 unit tests |


---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py
class RecentActivityCache:                                                # line 201 — shape to mirror
    def __init__(self, ttl_seconds: float = 300.0, max_items: int = 2048) -> None: ...  # line 204
    def seen(self, activity_id: str) -> bool: ...                         # line 209
```

### Does NOT Exist
- ~~`WizardStore` / `WizardState`~~ — this task creates them.
- ~~`WizardFormDialog` reuse~~ — the dialog lane (`dialogs/presets/wizard.py:36`) is deliberately NOT used (spec §2, §7). Do not import it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_wizard.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/msteams/test_formdesigner_wizard.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py#RecentActivityCache"
  ]
}
```

---

## Implementation Notes

- Use `time.monotonic()` for TTL — wall-clock jumps must not expire state.
- `lock` must be excluded from equality/repr (`field(default_factory=asyncio.Lock, repr=False, compare=False)`).
- `advance()` does NOT validate — the mixin validates under `state.lock` first.

---

## Implementation Blueprint

### Steps (in order)
1. Write `WizardState` — *why*: the mixin compares every field against the submitted control object.
2. Write `WizardStore` over an `OrderedDict` — *why*: O(1) LRU eviction for `max_items`.
3. Write the tests with a monkeypatched clock — *why*: TTL tests must not sleep.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_wizard.py` (CREATE)
```python
"""Per-conversation wizard state for sectioned FormDesigner cards (FEAT-734 M5). Process-local."""
from __future__ import annotations

import asyncio
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

_Key = tuple[str, uuid.UUID]


@dataclass
class WizardState:
    """One in-flight sectioned form for one conversation."""

    form_uid: uuid.UUID
    tenant: str
    section_index: int
    total_sections: int
    wizard_id: uuid.UUID
    owner_user_id: str
    form_version: str
    answers: dict[str, Any] = field(default_factory=dict)
    updated_at: float = 0.0
    consumed: bool = False  # set before the single terminal POST
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)


class WizardStore:
    """Process-local wizard state, keyed by (conversation_id, form_uid)."""

    def __init__(self, ttl_seconds: float = 3600.0, max_items: int = 512) -> None:
        self._ttl = ttl_seconds
        self._max = max_items
        self._items: OrderedDict[_Key, WizardState] = OrderedDict()

    def _now(self) -> float:
        return time.monotonic()

    def start(
        self, *, conversation_id: str, form_uid: uuid.UUID, tenant: str,
        total_sections: int, owner_user_id: str, form_version: str,
    ) -> WizardState:
        """Begin (or restart) a wizard; always a fresh wizard_id at section 0."""
        state = WizardState(
            form_uid=form_uid, tenant=tenant, section_index=0, total_sections=total_sections,
            wizard_id=uuid.uuid4(), owner_user_id=owner_user_id, form_version=form_version,
            updated_at=self._now(),
        )
        # FILL IN: store under (conversation_id, form_uid), move_to_end, then evict oldest while len > max_items
        return state

    def get(self, *, conversation_id: str, form_uid: uuid.UUID) -> WizardState | None:
        """None when absent or expired — the caller then restarts the form."""
        # FILL IN: drop and return None when now - updated_at > ttl
        raise NotImplementedError

    def advance(self, state: WizardState, answers: dict[str, Any]) -> WizardState:
        """Merge this step's answers and move to the next section (caller already validated)."""
        state.answers.update(answers)
        state.section_index += 1
        state.updated_at = self._now()
        return state

    def finish(self, *, conversation_id: str, form_uid: uuid.UUID) -> dict[str, Any]:
        """Pop the state and return the accumulated answers ({} when absent)."""
        # FILL IN
        raise NotImplementedError

    def discard(self, *, conversation_id: str, form_uid: uuid.UUID) -> None:
        """Remove state without posting (Cancel)."""
        self._items.pop((conversation_id, form_uid), None)
```
**Why this shape**: `WizardState` is spec §2 verbatim plus `consumed`/`lock`, which spec §3 Delivery contracts require ("per-state async lock", "mark the terminal state consumed before the one POST"). `discard` exists because Cancel "removes state without posting".

### `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_wizard.py` (CREATE)
```python
"""FEAT-734 M5 — WizardStore."""
import uuid

from parrot.integrations.msteams.formdesigner_wizard import WizardStore

UID = uuid.uuid4()


def _start(store, conv="c1", uid=UID):
    return store.start(conversation_id=conv, form_uid=uid, tenant="acme", total_sections=3,
                       owner_user_id="u1", form_version="1.0")


def test_wizard_advance_accumulates_answers(): ...   # FILL IN: two advances -> merged answers, index 2
def test_wizard_expiry_returns_none(monkeypatch): ...  # FILL IN: patch store._now past ttl
def test_wizard_eviction_bounded(): ...              # FILL IN: max_items=2, three starts -> oldest gone
def test_wizard_restart_gets_new_wizard_id(): ...    # FILL IN
def test_wizard_discard_and_finish(): ...            # FILL IN: finish returns answers then get() is None
```

### FILL IN checklist
- [ ] `start` store + LRU eviction; bounded by `max_items`
- [ ] `get` TTL eviction; bounded by `ttl_seconds`
- [ ] `finish` pop + return answers
- [ ] five test bodies

---

## Acceptance Criteria

- [ ] `get` returns `None` past TTL; `len` never exceeds `max_items`.
- [ ] Every `start` yields a new `wizard_id` at `section_index == 0`.
- [ ] `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_wizard.py -q`


---

## Test Specification

Five tests in the blueprint; the first three are spec §4 M5 rows.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug formdesigner-serve-forms --feature-id FEAT-734`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/formdesigner-serve-forms.json`
4. **Verify the Codebase Contract** — confirm every import/signature before writing code; never use anything under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker, never change a fixed signature or path
7. **Verify** — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot-integrations/src:packages/ai-parrot/src:packages/parrot-formdesigner/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4684 formdesigner-serve-forms verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
