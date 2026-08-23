# TASK-2393: Google Calendar event tools + live calendar client

**Feature**: FEAT-453 — Business Browser Automation
**Spec**: `sdd/specs/web-automation-infra.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 7** (Goal G6).

`GoogleClient` already declares the calendar OAuth scopes (google.py:57-61) and
maps `'calendar': 'v3'` (line 720), but `get_calendar_client()` (line 760)
merely returns a **config dict** — `{'service': 'calendar', 'version': version}`
— and nothing consumes it. There are **zero** calendar event tools in the repo:
`parrot_tools/google/` contains only `base.py`, `places.py`, `tools.py`
(search / places / maps), and `grep -ci calendar` on `google/tools.py` is 0.

O365 has real event tooling (`parrot_tools/o365/events.py`) and is the pattern
to imitate, but the operator chose Google (spec §8, resolved U3).

Implements spec **Module 7**.

---

## Scope

- Promote `GoogleClient.get_calendar_client()` from returning a config dict to
  returning a usable Calendar v3 client, reusing the existing auth/scope plumbing.
- Create `GoogleCalendarToolkit(AbstractToolkit)` with `create_event`,
  `list_events` and `update_event`.
- Model inputs/outputs as Pydantic models; return structured results, not raw
  API dicts.
- Unit tests against a mocked Calendar v3 client — no network.

**NOT in scope**: the reminder scheduling that will call these (TASK-2394);
OAuth onboarding flows; deleting events.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/google.py` | MODIFY | Promote get_calendar_client to a live client |
| `packages/ai-parrot-tools/src/parrot_tools/google/calendar.py` | CREATE | GoogleCalendarToolkit |
| `packages/ai-parrot-tools/tests/google/test_calendar.py` | CREATE | Mocked v3 client tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the actual codebase, re-checked on `dev`
> after the FEAT-449/450/452 merges. Use these exact imports and signatures.
> **DO NOT** invent, guess, or assume anything not listed here. If you need
> something absent, VERIFY it exists with `grep`/`read` and update this section
> FIRST.

### Verified Imports

```python
from parrot.tools.toolkit import AbstractToolkit          # verified: tools/toolkit.py:216
from parrot.interfaces.google import GoogleClient         # verified: interfaces/google.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/interfaces/google.py
DEFAULT_SCOPES['calendar'] = [                      # lines 57-61
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events',
]
#   'calendar': 'v3'                                # line 720 (service->version map)
async def get_calendar_client(self, version: str = 'v3') -> Dict[str, Any]:  # line 760
    """Get Google Calendar client config."""
    return {'service': 'calendar', 'version': version}   # line 762  <- THE TARGET
async def ...(self, service_name: str, ...)         # line 688
    #   "service_name: Service name (drive, sheets, docs, calendar, storage, gmail)"

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                         # line 216
    auto_open: bool = False                         # line 310
    async def _open(self) -> None: ...              # line 388
    async def _close(self) -> None: ...             # line 404
    def get_tools(...): ...                         # line 484

# PATTERN TO IMITATE (already-working calendar tooling, different provider):
#   packages/ai-parrot-tools/src/parrot_tools/o365/events.py
#   packages/ai-parrot-tools/src/parrot_tools/o365/oauth_toolkit.py
```

### Does NOT Exist

- ~~`GoogleCalendarToolkit`~~, ~~`create_event`~~, ~~`list_events`~~ — **none exist**; verified absent across `packages/*/src`. This task creates them.
- ~~calendar helpers in `parrot_tools/google/tools.py`~~ — that file is search/places/maps only; `grep -ci calendar` returns **0**.
- ~~`GoogleClient.calendar`~~ as a property — not a thing. The accessor is `get_calendar_client()` (line 760).

---

## Implementation Notes

### Key Constraints
- Do not break the existing `get_calendar_client()` callers — verify with a grep
  first; if none exist (expected), the signature change is safe.
- All datetimes timezone-aware; Spanish filing deadlines are date-critical and a
  naive datetime will drift.
- No network in tests.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/scraping/advanced_actions.py` — the FEAT-222 extraction pattern
- `packages/ai-parrot/src/parrot/tools/obsidian.py` — FEAT-391 lazy-lifecycle toolkit
- `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` — FEAT-207 shared-state toolkit + run_id polling

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] `get_calendar_client()` returns a usable client, not a config dict
- [ ] `create_event` builds a valid Calendar v3 insert body
- [ ] `list_events` honours `time_min`/`time_max`
- [ ] `update_event` performs a partial update without clobbering unset fields
- [ ] All datetimes are timezone-aware
- [ ] Tests make no network calls
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/google/test_calendar.py -v`
- [ ] No linting errors: `ruff check` on every changed file

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
import pytest
from parrot_tools.google.calendar import GoogleCalendarToolkit


class TestCalendar:
    async def test_create_event_body(self, toolkit, mock_v3):
        await toolkit.create_event(summary="Modelo 303 Q1", start="2026-04-01T09:00:00+02:00",
                                   end="2026-04-01T09:30:00+02:00")
        body = mock_v3.events().insert.call_args.kwargs["body"]
        assert body["summary"] == "Modelo 303 Q1"

    async def test_list_events_range(self, toolkit, mock_v3):
        await toolkit.list_events(time_min="2026-01-01T00:00:00Z", time_max="2026-04-01T00:00:00Z")
        assert mock_v3.events().list.called

    async def test_naive_datetime_rejected(self, toolkit):
        with pytest.raises(ValueError, match="timezone"):
            await toolkit.create_event(summary="x", start="2026-04-01T09:00:00", end="2026-04-01T09:30:00")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/web-automation-infra.spec.md` — especially §6 Codebase Contract and §7 Decisions D1-D4.
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code:
   - Confirm every import still resolves (`grep`/`read` the source).
   - Confirm every listed signature still matches.
   - If anything changed, update this contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract
     without verifying it exists.
4. **Update status** in `sdd/tasks/index/web-automation-infra.json` → `"in-progress"`.
5. **Implement** per scope, contract, and notes — nothing more.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/TASK-2393-google-calendar-tools.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
