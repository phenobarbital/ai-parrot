# TASK-4546: Add tenant / user / session / cost_usd fields to the four usage events

**Feature**: FEAT-710 — Parrot telemetry event fan-out
**Spec**: `sdd/specs/parrot-telemetry-event-fanout.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Data Models, §3 Module 2. The four forwarded events must be self-describing because ContextVars do not cross the bus. `AfterInvokeEvent`/`InvokeFailedEvent` lack `user_id`/`session_id` today (design research S7).

---

## Scope

- `AfterInvokeEvent`, `InvokeFailedEvent`: add `tenant`, `user_id`, `session_id` (all `Optional[str] = None`), appended last.
- `AfterClientCallEvent`: add `tenant: Optional[str] = None`, `cost_usd: Optional[float] = None`, appended last.
- `ClientCallFailedEvent`: add `tenant: Optional[str] = None`, appended last.
- Update each class docstring `Attributes:` section.
- Write tests (defaults, `to_dict()` round trip).

**NOT in scope**: filling the fields at construction sites (TASK-4548, TASK-4549).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/invoke.py` | MODIFY | Fields on AfterInvokeEvent/InvokeFailedEvent |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py` | MODIFY | Fields on AfterClientCallEvent/ClientCallFailedEvent |
| `packages/ai-parrot/tests/unit/events/lifecycle/test_usage_event_fields.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

Verified against `origin/dev` @ `cf1888270` (2026-10-21). Re-run every `grep -c` before editing.

### Verified Imports
```python
from parrot.core.events.lifecycle.events import (AfterInvokeEvent, InvokeFailedEvent,
    AfterClientCallEvent, ClientCallFailedEvent)  # verified: core/events/lifecycle/yaml_loader.py:33-47
```

### Existing Signatures to Use
```python
# invoke.py — @dataclass(frozen=True)
class AfterInvokeEvent(LifecycleEvent): agent_name: str = ""; method: str = ""; duration_ms: float = 0.0;
    input_tokens: Optional[int] = None; output_tokens: Optional[int] = None          # :34-51
class InvokeFailedEvent(LifecycleEvent): agent_name, method, duration_ms, error_type: str = "", error_message: str = ""  # :55-72
# client.py — @dataclass(frozen=True)
class AfterClientCallEvent(LifecycleEvent): ... agent_name, user_id, session_id   # :45-76 (session_id last at :76)
class ClientCallFailedEvent(LifecycleEvent): ... agent_name, user_id, session_id  # :80-99 (session_id last at :99)
# navigator_eventbus/lifecycle/base.py:52  LifecycleEvent.to_dict() -> dict
```

### Does NOT Exist
- ~~`AfterInvokeEvent.user_id`~~ / ~~`.session_id`~~ / ~~`.tenant`~~ — created by this task
- ~~`AfterInvokeEvent.cost_usd`~~ — NOT added (cost is summed only from client calls)
- ~~`program_slug`~~ — never

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/core/events/lifecycle/events/invoke.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/events/lifecycle/test_usage_event_fields.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/invoke.py#AfterInvokeEvent",
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/invoke.py#InvokeFailedEvent",
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py#AfterClientCallEvent",
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py#ClientCallFailedEvent"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async-first; never block the event loop; `self.logger`, never `print`.
- Telemetry must never raise into the request path.
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Append the fields last in each frozen dataclass — *why*: defaulted fields after defaulted fields keep keyword construction valid everywhere.
2. Update docstrings, then write tests.

### `packages/ai-parrot/src/parrot/core/events/lifecycle/events/invoke.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'output_tokens: Optional\[int\] = None' packages/ai-parrot/src/parrot/core/events/lifecycle/events/invoke.py)
# AFTER — insert below `    output_tokens: Optional[int] = None` (AfterInvokeEvent, verified: :51)
    tenant: Optional[str] = None        # FEAT-710: server-resolved tenant
    user_id: Optional[str] = None       # FEAT-710: per-user attribution
    session_id: Optional[str] = None    # FEAT-710: per-session correlation
```
```python
# occurrences: 1 (verified: grep -c 'error_message: str = ""' packages/ai-parrot/src/parrot/core/events/lifecycle/events/invoke.py)
# AFTER — insert below `    error_message: str = ""` (InvokeFailedEvent, verified: :72)
    tenant: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
```

### `packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py` (MODIFY)
```python
# occurrences: 3 (verified: grep -c 'session_id: Optional\[str\] = None   # per-session correlation (spans only)' client.py)
# FILL IN: disambiguate — the AfterClientCallEvent occurrence is at :76 (after `user_id ... :75`, before
#          `@dataclass` of ClientCallFailedEvent :79); the ClientCallFailedEvent one is at :99. Do NOT touch BeforeClientCallEvent (:41).
# AfterClientCallEvent:
    tenant: Optional[str] = None        # FEAT-710
    cost_usd: Optional[float] = None    # FEAT-710: computed once at the origin; None = no calculator / unknown pricing
# ClientCallFailedEvent:
    tenant: Optional[str] = None        # FEAT-710
```
**Why**: `cost_usd` only on the success event — failed calls have no billable tokens.

### `packages/ai-parrot/tests/unit/events/lifecycle/test_usage_event_fields.py` (CREATE)
```python
"""FEAT-710 TASK-4546 — new usage-event fields."""
from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent, AfterInvokeEvent, ClientCallFailedEvent, InvokeFailedEvent,
)


def test_defaults_are_none() -> None:
    assert AfterInvokeEvent().tenant is None and AfterInvokeEvent().user_id is None
    assert AfterClientCallEvent().cost_usd is None
    assert ClientCallFailedEvent().tenant is None
    assert InvokeFailedEvent().session_id is None


def test_to_dict_carries_new_fields() -> None:
    # FILL IN: build each event with tenant/user/session(/cost_usd) set and assert they appear in to_dict() — AC-2
    raise NotImplementedError
```

### FILL IN checklist
- [ ] client.py disambiguation — AC-1
- [ ] `test_to_dict_carries_new_fields` — AC-2

---

## Acceptance Criteria

- [ ] The four events carry the fields listed in spec §2 Data Models, all defaulting to `None`.
- [ ] `to_dict()` includes them.
- [ ] Existing construction sites still work (`flows/dev_loop/dispatchers/claude.py:980/1039`, `clients/base.py:751/801`).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/events/lifecycle/test_usage_event_fields.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_client_global_bridge.py -q`

---

## Test Specification

See the test-file block in the Implementation Blueprint; every `FILL IN` test must pass.

---

## Agent Instructions

1. Work in the feature worktree, never on `dev`:
   `python -m scripts.sdd.ensure_worktree --slug parrot-telemetry-event-fanout --feature-id FEAT-710`
2. Read the spec `sdd/specs/parrot-telemetry-event-fanout.spec.md` (rev 0.4) for context.
3. Check that every `Depends-on` task is `done` in `sdd/tasks/index/parrot-telemetry-event-fanout.json`.
4. Verify the Codebase Contract before writing code (re-run `grep -c` on every anchor); fix the contract first if it drifted.
5. Set this task `in-progress` in the index and commit only that file.
6. Implement from the Blueprint, completing every `# FILL IN:`; never change a fixed signature or path.
7. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.
8. Commit only the files listed in this task.
9. Close with `scripts/sdd/close_task.sh TASK-4546 parrot-telemetry-event-fanout verified`.
10. Fill in the Completion Note and commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
