# TASK-1839: Envelope schema_version — core field, from_dict rules, exports

**Feature**: FEAT-319 — EventBus Consolidation
**Spec**: `sdd/specs/eventbus-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

> **REPO**: `navigator-eventbus` — work in `/home/jesuslara/proyectos/navigator-eventbus`
> (branch from `main` there), NOT in the ai-parrot checkout. SDD state (this file,
> the index) stays in ai-parrot.

---

## Context

Spec §3 Module 1 (partial — core). The wire format lacks versioning; this task adds
`schema_version` to `EventEnvelope` BEFORE production Redis Streams traffic exists.
Readers must be lenient backwards (missing key → 1) and strict forwards (unknown →
raise). TASK-1840 propagates the rule to the remaining construction paths (DLQ,
ingress, converters).

---

## Scope

- Add `ENVELOPE_SCHEMA_VERSION: int = 1` module constant to `envelope.py`.
- Add `class UnsupportedSchemaVersion(ValueError)` to `envelope.py` (NOT
  `serialization.py` — import-cycle constraint, see spec §7).
- Add `schema_version: int = ENVELOPE_SCHEMA_VERSION` as the **LAST** field of
  `EventEnvelope` (frozen/slots preserved; positional compat with pre-spec
  10-arg construction must survive).
- `to_dict()` emits `"schema_version"`.
- `from_dict()`: missing key → 1; `<= ENVELOPE_SCHEMA_VERSION` → parse;
  `> ENVELOPE_SCHEMA_VERSION` → raise `UnsupportedSchemaVersion` with topic and
  event_id in the message.
- Export `ENVELOPE_SCHEMA_VERSION` and `UnsupportedSchemaVersion` from
  `navigator_eventbus/__init__.py` (add to `__all__`).
- Unit tests (see Test Specification).

**NOT in scope**: DLQ `_row_to_envelope`, `IngressEnvelope`, converters (TASK-1840);
HookManager (TASK-1841); release/version bump (TASK-1842).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/navigator_eventbus/envelope.py` | MODIFY | constant + exception + field + to_dict/from_dict |
| `src/navigator_eventbus/__init__.py` | MODIFY | export the two new names, update `__all__` |
| `tests/test_envelope_schema_version.py` | CREATE | unit tests below |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-20 against `navigator-eventbus@main` local checkout
> (`/home/jesuslara/proyectos/navigator-eventbus`).

### Verified Imports
```python
from navigator_eventbus.envelope import EventEnvelope, Severity
from navigator_eventbus import EventEnvelope   # __all__ in __init__.py lines 25–39
```

### Existing Signatures to Use
```python
# src/navigator_eventbus/envelope.py
@dataclass(frozen=True, slots=True)
class EventEnvelope:                                   # line 41
    topic: str; payload: dict[str, Any]
    event_id: str; timestamp: datetime                 # tz-aware enforced in __post_init__
    source: Optional[str]; severity: Severity; priority: EventPriority
    correlation_id: Optional[str]; trace_context: Optional[dict]; metadata: dict
    def to_dict(self) -> dict[str, Any]                # line 95 — enums as .value, ts ISO 8601
    @classmethod
    def from_dict(cls, data) -> "EventEnvelope"        # line 118 — requires topic+timestamp
# EventPriority is imported FROM navigator_eventbus.evb (top of envelope.py) —
# envelope.py ⇄ evb.py cycle works via ordering; do not add imports that break it.
```

### Does NOT Exist
- ~~`schema_version` / `ENVELOPE_SCHEMA_VERSION` / `UnsupportedSchemaVersion`~~ — this task creates them.
- ~~`serialization.py` involvement~~ — generic `dumps/loads` only; `from_dict` lives in `envelope.py`. Do not touch it.
- ~~pickle in the envelope path~~ — none; do not add pickle-based tests.

---

## Implementation Notes

### Key Constraints
- `EventEnvelope` stays `@dataclass(frozen=True, slots=True)` — no Pydantic (FEAT-176 rationale).
- New field MUST be last (positional-arg compatibility).
- Never silently downgrade an unknown version; never require the key.
- Exception message format suggestion:
  `f"Unsupported envelope schema_version {v} (supported <= {ENVELOPE_SCHEMA_VERSION}) for topic={topic!r} event_id={event_id!r}"`.

### References in Codebase
- `src/navigator_eventbus/envelope.py` — the only implementation file that matters here.
- `tests/` — follow the existing pytest style in the repo (pytest-asyncio where needed; these tests are sync).

---

## Acceptance Criteria

- [ ] `EventEnvelope(...).schema_version == 1` by default; present in `to_dict()`.
- [ ] `from_dict` legacy rule: dict without the key parses → version 1.
- [ ] `from_dict` with `schema_version: 99` raises `UnsupportedSchemaVersion`; message contains topic and event_id.
- [ ] Positional construction with pre-spec arity (10 args) still valid; dataclass still frozen + slots.
- [ ] `from navigator_eventbus import ENVELOPE_SCHEMA_VERSION, UnsupportedSchemaVersion` works.
- [ ] All tests pass: `pytest tests/ -v` (full suite, not just new file).
- [ ] `ruff check src/` clean.

---

## Test Specification

```python
# tests/test_envelope_schema_version.py
import pytest
from navigator_eventbus import ENVELOPE_SCHEMA_VERSION, UnsupportedSchemaVersion
from navigator_eventbus.envelope import EventEnvelope


@pytest.fixture
def legacy_envelope_dict():
    """Wire dict as produced BEFORE this spec (no schema_version key)."""
    return {
        "topic": "order.created", "payload": {"id": 1},
        "event_id": "e-1", "timestamp": "2026-07-01T10:00:00+00:00",
        "source": "test", "severity": 20, "priority": 5,
        "correlation_id": None, "trace_context": None, "metadata": {},
    }


def test_envelope_schema_version_default():
    env = EventEnvelope(topic="t", payload={})
    assert env.schema_version == ENVELOPE_SCHEMA_VERSION == 1
    assert env.to_dict()["schema_version"] == 1


def test_from_dict_missing_version_is_legacy_v1(legacy_envelope_dict):
    env = EventEnvelope.from_dict(legacy_envelope_dict)
    assert env.schema_version == 1


def test_from_dict_unknown_version_raises(legacy_envelope_dict):
    data = {**legacy_envelope_dict, "schema_version": 99}
    with pytest.raises(UnsupportedSchemaVersion, match="order.created"):
        EventEnvelope.from_dict(data)


def test_frozen_slots_preserved_after_field_add():
    env = EventEnvelope(topic="t", payload={})
    with pytest.raises(Exception):  # FrozenInstanceError
        env.schema_version = 2
    assert not hasattr(env, "__dict__")  # slots


def test_roundtrip_preserves_version():
    env = EventEnvelope(topic="t", payload={"a": 1})
    assert EventEnvelope.from_dict(env.to_dict()).schema_version == 1
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/eventbus-consolidation.spec.md` (in ai-parrot) for full context.
2. **cd to `/home/jesuslara/proyectos/navigator-eventbus`** — all code work happens there.
3. **Verify the Codebase Contract** before writing any code (grep the listed lines).
4. **Update status** in ai-parrot `sdd/tasks/index/eventbus-consolidation.json` → `"in-progress"`.
5. **Implement**, run the FULL navigator-eventbus test suite.
6. **Move this file** to `sdd/tasks/completed/` and set index status `"done"`.
7. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
