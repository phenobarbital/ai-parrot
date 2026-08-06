# TASK-2155: Placeholder catalog module

**Feature**: FEAT-417 — CommCenter — Bulk Notification Sender over NotifyWorker
**Spec**: `sdd/specs/commcenter-notify.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Estimated effort note**: standalone module — the most parallelizable task in the feature
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. A template author has no way to learn which variables exist,
so they guess and blasts render with holes. This module is the static,
in-module catalog served by `GET /api/v1/comm_center/placeholders`.

It also carries two **safety disclosures** that are not cosmetic:
the bare-placeholder limitation, and the reserved names that render object
reprs instead of values.

---

## Scope

- Create the catalog module with the three groups defined below.
- Delegate every date function to `resolve_date` — **do not** reimplement date
  math.
- Provide a `build_catalog(now=None)` returning the serializable payload with
  live `sample` values for each function.
- Unit tests for group shape, resolver parity, and disclosure presence.

**NOT in scope**:
- The HTTP endpoint that serves it (TASK-2159 wires the route).
- Applying the functions during render (TASK-2157).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/comm_center_placeholders.py` | CREATE | Static catalog + `build_catalog()` |
| `packages/ai-parrot-server/tests/handlers/test_comm_center_placeholders.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified fresh 2026-08-06 by live import + signature introspection.

### Verified Imports

```python
from datetime import datetime
from typing import Any, Dict, List, Optional

from parrot.outputs.a2ui.recipes.params import resolve_date, DATE_RESOLVERS
# verified: packages/ai-parrot/src/parrot/outputs/a2ui/recipes/params.py:30,39
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/params.py:29-70
DATE_RESOLVERS = ("current_month", "previous_month", "today",
                  "yesterday", "first_of_month")            # line 30 — VERIFIED live

def resolve_date(resolver: str, *, tz: str = "UTC",
                 now: datetime | None = None) -> str: ...   # line 39 — VERIFIED live
# "YYYY-MM" for month resolvers, "YYYY-MM-DD" for day resolvers.
# Stdlib only; `now` is injectable → deterministic tests.
# Raises ValueError on an unrecognized resolver name.
```

```python
# packages/ai-parrot-server/src/parrot/handlers/scraping/info.py:22-62
# ← THE STATIC-CATALOG PATTERN TO FOLLOW (module constants + a build function
#   the handler calls once in __init__ and caches)
_DRIVER_TYPES: List[Dict[str, Any]] = [...]
_STRATEGIES: List[Dict[str, str]] = [...]
def _build_action_catalog() -> List[Dict[str, Any]]: ...
```

### Does NOT Exist

- ~~`{{today}}` as a built-in of `parrot.bots.dynamic_values`~~ — that registry's
  built-ins are `current_date`, `local_time`, `user_name`
  (`dynamic_values.py:62-70`). The `today`/`yesterday`/`current_month` naming
  lives in `DATE_RESOLVERS`. **Two different registries — do not conflate.**
- ~~`resolve_date("now")`~~ / ~~`resolve_date("current_year")`~~ — **not**
  resolver names; `DATE_RESOLVERS` has exactly the five listed above.
  `now` and `current_year` are **module-local extras this task implements**.
- ~~`Actor.email` / `Actor.phone`~~ — `Actor` has only `userid`, `name`,
  `account`, `accounts` (verified live). Relevant here because the catalog
  documents `{{email}}`/`{{phone}}` as *row* fields, not Actor attributes.
- ~~`parrot.handlers.comm_center_placeholders`~~ — does not exist yet.

---

## Implementation Notes

### The catalog — exactly three groups (spec §3 Module 3)

**Group 1 — `recipient_fields`** (resolved worker-side, pass 2):

| Placeholder | Required | Notes |
|---|---|---|
| `name` | yes | The only mandatory column |
| `username` | no | Always emitted; falls back to `name` — see the trap below |
| `email` | conditional | Required when the provider is email-like |
| `phone` | conditional | Required when the provider is SMS-like |
| `address` | no | Free-form |

**Group 2 — `computed_functions`** (resolved handler-side, pass 1) — the five
`DATE_RESOLVERS` **verbatim** plus two module-local extras:

| Name | Source | Output |
|---|---|---|
| `today` | `resolve_date("today")` | `YYYY-MM-DD` |
| `yesterday` | `resolve_date("yesterday")` | `YYYY-MM-DD` |
| `first_of_month` | `resolve_date("first_of_month")` | `YYYY-MM-DD` |
| `current_month` | `resolve_date("current_month")` | `YYYY-MM` |
| `previous_month` | `resolve_date("previous_month")` | `YYYY-MM` |
| `now` | **module-local** | ISO-8601 timestamp |
| `current_year` | **module-local** | `YYYY` |

**Group 3 — `reserved`** — must NOT be used in templates:
`recipient`, `message`, `subject`.

### Why `reserved` matters (verified, spec §2)

`notify` builds its pass-2 context as
`{"recipient": to, "username": to, "message": …, "subject": …, **kwargs}`
(`notify/providers/base.py:177-183`). `{{recipient}}` therefore renders an
`Actor` **repr**, verified as `<Ana Gomez: c1c4f2c8-…>`, not a name. The catalog
must say so explicitly.

### Required disclosures in the payload
1. **`limitation`** — record placeholders must be written as bare
   `{{ field }}`; filters and conditionals over them (`{{ name|upper }}`,
   `{% if email %}`) are not supported, because pass 1 uses `DebugUndefined`.
2. **`extra_columns`** — any column beyond the canonical five is forwarded
   verbatim as a pass-2 placeholder.

### Key Constraints
- `build_catalog(now: datetime | None = None)` — `now` threads into
  `resolve_date` so tests are deterministic.
- Pure/stdlib + `resolve_date`; no I/O, no DB, no aiohttp import.
- Google-style docstrings, full type hints, module-level constants for the
  static parts (catalog is cached by the handler).

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/scraping/info.py:22-62` — pattern
- `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/params.py` — resolvers
- `packages/ai-parrot/src/parrot/bots/dynamic_values.py:52` — `get_all_names()` registry pattern (reference only)

---

## Acceptance Criteria

- [ ] `from parrot.handlers.comm_center_placeholders import build_catalog` works
- [ ] Catalog has exactly the three groups: `recipient_fields`, `computed_functions`, `reserved`
- [ ] 5 recipient fields, 7 computed functions, 3 reserved names
- [ ] The five date functions delegate to `resolve_date` (no reimplemented date math)
- [ ] `now` and `current_year` implemented module-locally
- [ ] Every computed function carries a live `sample` value
- [ ] `build_catalog(now=...)` is deterministic
- [ ] Payload includes the `limitation` and `extra_columns` disclosures
- [ ] Module imports without aiohttp/DB side effects
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_comm_center_placeholders.py -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
from datetime import datetime
import pytest
from parrot.handlers.comm_center_placeholders import build_catalog
from parrot.outputs.a2ui.recipes.params import DATE_RESOLVERS

FROZEN = datetime(2026, 8, 6, 12, 0, 0)


class TestPlaceholderCatalog:
    def test_three_groups(self):
        c = build_catalog(now=FROZEN)
        assert set(c) >= {"recipient_fields", "computed_functions", "reserved"}

    def test_counts(self):
        c = build_catalog(now=FROZEN)
        assert len(c["recipient_fields"]) == 5
        assert len(c["computed_functions"]) == 7
        assert len(c["reserved"]) == 3

    def test_functions_are_resolvers_plus_two(self):
        names = {f["name"] for f in build_catalog(now=FROZEN)["computed_functions"]}
        assert names == set(DATE_RESOLVERS) | {"now", "current_year"}

    def test_deterministic_samples(self):
        a = build_catalog(now=FROZEN)
        b = build_catalog(now=FROZEN)
        assert a == b
        today = next(f for f in a["computed_functions"] if f["name"] == "today")
        assert today["sample"] == "2026-08-06"

    def test_reserved_names_flagged(self):
        reserved = {r["name"] for r in build_catalog(now=FROZEN)["reserved"]}
        assert reserved == {"recipient", "message", "subject"}

    def test_disclosures_present(self):
        c = build_catalog(now=FROZEN)
        assert c["limitation"]        # bare-placeholder restriction
        assert c["extra_columns"]     # pass-through note
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 3 has the authoritative catalog tables
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm `DATE_RESOLVERS` still has exactly
   five entries before assuming the 5+2 split
4. **Update status** in `sdd/tasks/index/commcenter-notify.json` → `"in-progress"`
5. **Implement** per scope
6. **Verify** acceptance criteria
7. **Move** to `sdd/tasks/completed/TASK-2155-placeholder-catalog.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
