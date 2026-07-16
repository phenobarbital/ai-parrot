---
type: Wiki Overview
title: 'TASK-1274: Severity + BusinessHours models + select_starting_tier'
id: doc:sdd-tasks-completed-task-1274-severity-businesshours-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 module **C1**. The shipped baseline (`afe70e82`) has no notion
relates_to:
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.human.models
  rel: mentions
---

# TASK-1274: Severity + BusinessHours models + select_starting_tier

**Feature**: FEAT-194 — HITL Multi-Tier Escalation Policy
**Spec**: `sdd/specs/hitl-escalation-tier.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements §3 module **C1**. The shipped baseline (`afe70e82`) has no notion
of severity or business-hours windows; this task adds the foundation so
later tasks (C4 manager, C9 HumanTool input, C8 HumanDecisionNode) can
consume them.

---

## Scope

- Add `Severity` `str`-Enum (`LOW`, `NORMAL`, `HIGH`, `CRITICAL`) to
  `parrot/human/models.py`.
- Add `BusinessHours` Pydantic model (`tz: str`, `days: str`, `hours: str`)
  with a `contains(now: datetime) -> bool` helper.
- Add optional fields `min_severity: Optional[Severity]` and
  `business_hours: Optional[BusinessHours]` to `EscalationTier`.
- Add `HumanInteraction.severity: Severity = Severity.NORMAL`.
- Add pure method `EscalationPolicy.select_starting_tier(severity, now) -> Optional[EscalationTier]`
  that returns the first tier whose `min_severity` ≤ requested (or None)
  AND whose `business_hours` includes `now` (or has no window).
- Update `__all__` to export `Severity` and `BusinessHours`.
- Add the new symbols to `parrot/human/__init__.py` and its `__all__`.

**NOT in scope**: Wiring `severity` from HumanTool input (TASK-1282) or
HumanDecisionNode (TASK-1281). Manager calling `select_starting_tier`
(TASK-1277). Any UI / channel changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/human/models.py` | MODIFY | Add `Severity`, `BusinessHours`; extend `EscalationTier`; add `HumanInteraction.severity`; add `EscalationPolicy.select_starting_tier`; extend `__all__` |
| `packages/ai-parrot/src/parrot/human/__init__.py` | MODIFY | Re-export `Severity`, `BusinessHours` and update `__all__` |
| `packages/ai-parrot/tests/human/test_models_severity.py` | CREATE | Unit tests for Severity enum, BusinessHours.contains, and select_starting_tier |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Existing (do not change shape):
from pydantic import BaseModel, ConfigDict, Field, model_validator   # parrot/human/models.py:9
from enum import Enum                                                 # parrot/human/models.py:5
from datetime import datetime, timezone                               # parrot/human/models.py:4
from uuid import uuid4                                                # parrot/human/models.py:7
```

### Existing Signatures to Use

```python
# parrot/human/models.py:77-82 — EXISTING, do NOT rename
class EscalationActionType(str, Enum):
    INTERACT = "interact"
    NOTIFY = "notify"
    TICKET = "ticket"

# parrot/human/models.py:85-112 — EXISTING; this task EXTENDS it
class EscalationTier(BaseModel):
    level: int = Field(ge=1)
    name: str
    channel_type: Optional[str] = None
    target_humans: List[str] = Field(default_factory=list)
    timeout: float = Field(default=3600.0, gt=0)
    action_type: EscalationActionType = EscalationActionType.INTERACT
    action_metadata: Dict[str, Any] = Field(default_factory=dict)
    # Validator at line 102: INTERACT requires non-empty target_humans

# parrot/human/models.py:115-132 — EXISTING; this task ADDS select_starting_tier
class EscalationPolicy(BaseModel):
    policy_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    tiers: List[EscalationTier] = Field(default_factory=list)
    # Validator at line 122: contiguous levels starting at 1

# parrot/human/models.py:135-185 — EXISTING; this task ADDS severity
class HumanInteraction(BaseModel):
    # ... existing fields ...
    policy_id: Optional[str] = None                  # line 158
    policy: Optional[EscalationPolicy] = None        # line 159
    current_tier_level: int = Field(default=0, ge=0) # line 160
```

### Does NOT Exist

- ~~`parrot.human.Severity`~~ — to be added by this task.
- ~~`parrot.human.BusinessHours`~~ — to be added by this task.
- ~~`EscalationTier.min_severity`~~ — to be added.
- ~~`EscalationTier.business_hours`~~ — to be added.
- ~~`HumanInteraction.severity`~~ — to be added.
- ~~`EscalationPolicy.resolve_chain`~~ — not on the spec; use
  `select_starting_tier` (single-tier picker) instead.
- ~~`zoneinfo` only~~ — prefer `pytz`/`python-dateutil` already in deps;
  avoid Windows-only quirks of `zoneinfo`.

---

## Implementation Notes

### Pattern to Follow

```python
# Existing enum + validator pattern in parrot/human/models.py:
class InteractionStatus(str, Enum):                    # line 38
    PENDING = "pending"
    # ...

class EscalationTier(BaseModel):                        # line 85
    @model_validator(mode="after")                      # line 102
    def _check_interact_has_targets(self) -> "EscalationTier":
        ...
```

### Key Constraints

- `Severity` ordering: define a class-level `_ORDER = {LOW:0, NORMAL:1, HIGH:2, CRITICAL:3}`
  helper so `select_starting_tier` can compare without exposing a public
  comparator. Or use `IntEnum` aliased to `str` values — pick one and
  document.
- `BusinessHours.contains(now)` must respect `tz` via `pytz`/`dateutil.tz`.
  Days parser accepts `"mon-fri"`, `"mon,wed,fri"`, `"mon-sun"`. Hours
  parser accepts `"HH:MM-HH:MM"` (24h). Reject malformed inputs at
  validation time with a clear message.
- `select_starting_tier` is **pure** — no logging, no I/O. Returns
  `Optional[EscalationTier]`; `None` means "no tier currently applicable"
  (caller decides what to do; TASK-1277 will treat this as immediate
  fall-through to terminal CANCEL/TIMEOUT).
- Default `HumanInteraction.severity = Severity.NORMAL` so existing
  serialised interactions in Redis still deserialise without breaking.

### References in Codebase

- `parrot/human/models.py:38-47` — `InteractionStatus` enum pattern.
- `parrot/human/models.py:115-132` — `EscalationPolicy` validator pattern.

---

## Acceptance Criteria

- [ ] `from parrot.human import Severity, BusinessHours` works.
- [ ] `Severity` exposes a deterministic ordering usable in
  `tier.min_severity <= interaction.severity`.
- [ ] `BusinessHours(tz="Europe/Madrid", days="mon-fri", hours="09:00-18:00").contains(...)`
  returns expected booleans at boundary inputs (08:59, 09:00, 17:59,
  18:00, 18:01, weekend dates).
- [ ] Malformed `BusinessHours` strings raise `pydantic.ValidationError`
  with an actionable message.
- [ ] `HumanInteraction(severity=Severity.HIGH)` serialises and
  round-trips through `model_dump_json` / `model_validate_json`.
- [ ] `EscalationTier(min_severity=Severity.HIGH, ...)` accepted.
- [ ] `EscalationTier(business_hours=BusinessHours(...), ...)` accepted.
- [ ] `EscalationPolicy.select_starting_tier(Severity.CRITICAL, now)`
  returns the first tier with `min_severity` ≤ `CRITICAL` whose
  `business_hours` includes `now` (or has no window).
- [ ] `select_starting_tier` returns `None` when no tier is currently
  applicable.
- [ ] Existing serialised `HumanInteraction` blobs without `severity`
  deserialise correctly (default = `NORMAL`).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/human/test_models_severity.py -v`.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/human/models.py`.

---

## Test Specification

```python
# packages/ai-parrot/tests/human/test_models_severity.py
from datetime import datetime
import pytest
import pytz

from parrot.human import Severity, BusinessHours, HumanInteraction
from parrot.human.models import EscalationTier, EscalationPolicy, EscalationActionType


class TestSeverity:
    def test_enum_values(self):
        assert Severity.LOW.value == "low"
        assert Severity.CRITICAL.value == "critical"

    def test_ordering_low_lt_high(self):
        # implementation-defined comparator
        assert Severity.LOW <= Severity.HIGH  # or via helper


class TestBusinessHours:
    @pytest.fixture
    def bh(self):
        return BusinessHours(tz="Europe/Madrid", days="mon-fri", hours="09:00-18:00")

    def test_inside_window_weekday(self, bh):
        now = pytz.timezone("Europe/Madrid").localize(datetime(2026, 5, 22, 12, 0))
        assert bh.contains(now) is True

    def test_before_window(self, bh):
        now = pytz.timezone("Europe/Madrid").localize(datetime(2026, 5, 22, 8, 59))
        assert bh.contains(now) is False

    def test_weekend(self, bh):
        now = pytz.timezone("Europe/Madrid").localize(datetime(2026, 5, 23, 12, 0))
        assert bh.contains(now) is False

    def test_malformed_hours_rejected(self):
        with pytest.raises(Exception):
            BusinessHours(tz="UTC", days="mon-fri", hours="oops")


class TestSelectStartingTier:
    def test_severity_floor(self):
        policy = EscalationPolicy(
            name="p", tiers=[
                EscalationTier(level=1, name="L1", target_humans=["a"], min_severity=Severity.NORMAL),
                EscalationTier(level=2, name="L2", target_humans=["b"], min_severity=Severity.HIGH),
                EscalationTier(level=3, name="L3", target_humans=["c"], min_severity=Severity.CRITICAL),
            ],
        )
        chosen = policy.select_starting_tier(Severity.HIGH, datetime.now(pytz.UTC))
        assert chosen.level == 2

    def test_skips_off_hours(self): ...

    def test_returns_none_when_no_applicable_tier(self): ...

    def test_back_compat_existing_interaction_blob_without_severity(self):
        # Simulate a payload from before this task — model_validate_json
        # should set severity to NORMAL.
        ...
```

---

## Agent Instructions

1. Read the spec at `sdd/specs/hitl-escalation-tier.spec.md` §3 C1 and §6.
2. Verify dependencies are completed (none for this task).
3. Verify the Codebase Contract — confirm existing line numbers still
   match before editing.
4. Update task status in `sdd/tasks/index/hitl-escalation-tier.json`.
5. Implement per scope; do NOT touch wiring sites (those are other tasks).
6. Run the test suite for this task; lint with ruff.
7. Move this file to `sdd/tasks/completed/` and update the index.
8. Fill in the Completion Note below.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-22
**Notes**: All 24 tests pass. Severity ordering implemented via __le__/__lt__/__ge__/__gt__
on the Severity str-Enum. BusinessHours uses pytz for timezone handling.
select_starting_tier is a pure method returning Optional[EscalationTier].
Severity and BusinessHours exported from parrot.human.__init__.
**Deviations from spec**: none
