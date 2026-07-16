---
type: Wiki Overview
title: 'TASK-1619: GigSmart Pydantic Models'
id: doc:sdd-tasks-completed-task-1619-gigsmart-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: All Pydantic v2 input/output models for the 6 GigSmart API surfaces plus
  generic
relates_to:
- concept: mod:parrot_tools.interfaces.gigsmart.models.common
  rel: mentions
- concept: mod:parrot_tools.interfaces.gigsmart.models.gig
  rel: mentions
---

# TASK-1619: GigSmart Pydantic Models

**Feature**: FEAT-253 — GigSmart Interface Toolkit
**Spec**: `sdd/specs/gigsmart-interface-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

All Pydantic v2 input/output models for the 6 GigSmart API surfaces plus generic
Relay pagination types. Pure data models with no framework dependencies. Implements
Spec §2 Data Models.

---

## Scope

- Implement Relay pagination generics: `RelayPageInfo`, `RelayEdge[T]`, `RelayConnection[T]`
- Implement `OAuthToken` model
- Implement models for all 6 surfaces: locations, positions, gigs, engagements, timesheets, disputes
- All mutation input models must be `frozen=True`
- Field aliases for camelCase serialization to GraphQL variables
- Write unit tests for validation, serialization, and immutability

**NOT in scope**: GraphQL query strings (TASK-1620), client logic (TASK-1621).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/models/__init__.py` | CREATE | Package exports |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/models/common.py` | CREATE | Relay pagination, OAuthToken |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/models/location.py` | CREATE | Location models |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/models/position.py` | CREATE | Position models |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/models/gig.py` | CREATE | Gig/Shift models |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/models/engagement.py` | CREATE | Engagement models |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/models/timesheet.py` | CREATE | Timesheet + dispute models |
| `tests/tools/gigsmart/test_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field, ConfigDict  # pydantic v2
from typing import Generic, TypeVar
from datetime import datetime
```

### Does NOT Exist
- ~~`Money` as `{ amount_cents: int, currency: str }`~~ — Money is a plain ISO-4217 string scalar (e.g., `"20.00"`)
- ~~`TimesheetState` enum~~ — does NOT exist; lifecycle tracked via EngagementStateName + isApproved boolean
- ~~`Page[T]` with `nodes: list[T]`~~ — does NOT exist; use Relay `edges[].node` pattern
- ~~`workers_needed` field~~ — actual field is `slots_available` / `slotsAvailable`
- ~~`HireWorkerInput` / `EndEngagementInput`~~ — ALL engagement transitions use `TransitionEngagementInput`
- ~~`EditTimesheetInput`~~ — no edit mutation exists; only approve and remove

---

## Implementation Notes

### Key Types from Schema Introspection

**IDs**: Prefixed opaque strings — e.g., `gig_9ucAiJ...`, `eng_0WjivX...`, `engts_9fes...`
**Money**: ISO-4217 string scalar — e.g., `"20.00"` (use `str` in Python)
**DateTime**: ISO-8601 datetime
**Duration**: ISO-8601 duration string

### camelCase Aliases
All models must serialize to camelCase for GraphQL variables:
```python
class PostShiftInput(BaseModel, frozen=True):
    model_config = ConfigDict(populate_by_name=True)
    organization_id: str = Field(alias="organizationId")
    starts_at: datetime = Field(alias="startsAt")
```

### Gig State Enum Values
`ACTIVE`, `CANCELED`, `COMPLETED`, `DRAFT`, `EXPIRED`, `IN_PROGRESS`,
`INACTIVE`, `INCOMPLETE`, `PENDING_REVIEW`, `RECONCILED`, `UPCOMING`

### Gig State Actions
`CANCEL`, `CLOSE`, `MARK_AS_COMPLETE`, `PUBLISH`

### Engagement State Actions (key subset of 48)
`HIRE`, `ACCEPT`, `START`, `END`, `CANCEL`, `OFFER`, `PAUSE`, `RESUME`,
`APPROVE_TIMESHEET`, `BID`, `DENY_APPLICATION`, `RESCIND`

---

## Acceptance Criteria

- [ ] `RelayConnection[T]` parses `{"edges": [{"node": {...}}], "pageInfo": {...}}`
- [ ] All input models are `frozen=True` (reject attribute assignment)
- [ ] Models serialize to camelCase via `model_dump(by_alias=True)`
- [ ] `PostShiftInput` validates `slots_available >= 1`
- [ ] `TransitionEngagementInput` accepts action string
- [ ] Tests pass: `pytest tests/tools/gigsmart/test_models.py -v`

---

## Test Specification

```python
import pytest
from datetime import datetime, timezone
from parrot_tools.interfaces.gigsmart.models.common import RelayConnection, RelayEdge, RelayPageInfo
from parrot_tools.interfaces.gigsmart.models.gig import PostShiftInput, Gig

class TestRelayConnection:
    def test_parse_connection(self):
        data = {
            "edges": [{"node": {"id": "gig_abc", "name": "Test"}, "cursor": "c1"}],
            "pageInfo": {"hasNextPage": True, "endCursor": "c1"}
        }
        # Should parse successfully

class TestPostShiftInput:
    def test_frozen_immutability(self):
        inp = PostShiftInput(
            organization_id="org_1", organization_position_id="pos_1",
            organization_location_id="loc_1",
            starts_at=datetime.now(timezone.utc), ends_at=datetime.now(timezone.utc),
        )
        with pytest.raises(Exception):
            inp.organization_id = "changed"

    def test_camelcase_serialization(self):
        inp = PostShiftInput(
            organization_id="org_1", organization_position_id="pos_1",
            organization_location_id="loc_1",
            starts_at=datetime.now(timezone.utc), ends_at=datetime.now(timezone.utc),
        )
        dumped = inp.model_dump(by_alias=True)
        assert "organizationId" in dumped
        assert "startsAt" in dumped
```

---

## Completion Note

*(Agent fills this in when done)*
