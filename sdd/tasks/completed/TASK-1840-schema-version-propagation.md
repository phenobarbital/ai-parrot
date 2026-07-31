# TASK-1840: schema_version propagation — DLQ rows, IngressEnvelope, converters

**Feature**: FEAT-319 — EventBus Consolidation
**Spec**: `sdd/specs/eventbus-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1839
**Assigned-to**: unassigned

> **REPO**: `navigator-eventbus` — work in `/home/jesuslara/proyectos/navigator-eventbus`
> (same branch as TASK-1839). SDD state stays in ai-parrot.

---

## Context

Spec §3 Module 1 (remainder). TASK-1839 added the field and the `from_dict` rules,
which covers the two wire-data paths (Redis Streams/Pub-Sub backends call
`from_dict`). This task closes the OTHER envelope-producing paths so no envelope
ever appears without a version: DLQ Postgres row reconstruction (manual
construction, NOT `from_dict`), the ingress Pydantic boundary
(`extra="forbid"` would REJECT clients sending the new key), and the three
in-process converters.

---

## Scope

- `dlq.py:_row_to_envelope()`: apply the legacy→1 rule — row dict without a
  version → envelope with `schema_version=1`; pass through a stored version if
  the row has one (post-M1 rows nest the original envelope dict in the payload;
  the reconstructed envelope's own field uses legacy→1).
- `ingress_models.py`: add `schema_version: int = 1` field to `IngressEnvelope`;
  `to_envelope()` passes it through. Shape validation only — do NOT reject
  unknown versions here (semantic rejection stays in `from_dict`, spec §3 M1).
- `converters.py`: `from_legacy_event`, `from_lifecycle_dict`, `from_hook_event`
  all construct envelopes with `schema_version=1` explicitly (they construct
  `EventEnvelope` directly; with the field defaulting to 1 this is automatic —
  add assertions/tests, and only add explicit kwargs if a converter builds the
  envelope in a way that would bypass the default).
- Verify (test, no code change expected): `backends/redis_streams.py` and
  `backends/redis_pubsub.py` round-trip the new field via `json.loads` + `from_dict`.
- Unit + integration tests (see Test Specification).

**NOT in scope**: `envelope.py` / exports (TASK-1839); HookManager (TASK-1841);
release (TASK-1842).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/navigator_eventbus/dlq.py` | MODIFY | legacy→1 rule in `_row_to_envelope` |
| `src/navigator_eventbus/ingress_models.py` | MODIFY | `schema_version` field + pass-through |
| `src/navigator_eventbus/converters.py` | MODIFY (maybe none) | ensure version 1 emitted; explicit only if needed |
| `tests/test_schema_version_propagation.py` | CREATE | DLQ/ingress/converter tests |
| `tests/` (backends) | MODIFY/CREATE | roundtrip-with-version assertions on existing backend tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-20 against `navigator-eventbus@main` local checkout.

### Verified Imports
```python
from navigator_eventbus.envelope import EventEnvelope
from navigator_eventbus.ingress_models import IngressEnvelope
from navigator_eventbus.converters import (
    from_legacy_event, from_lifecycle_dict, from_hook_event,
)
from navigator_eventbus.dlq import DLQHandler
# After TASK-1839 lands:
from navigator_eventbus import ENVELOPE_SCHEMA_VERSION, UnsupportedSchemaVersion
```

### Existing Signatures to Use
```python
# src/navigator_eventbus/dlq.py
class DLQHandler:
    async def replay(...)                                    # line 268
        # line 304: envelope = self._row_to_envelope(dict(row))
    @staticmethod
    def _row_to_envelope(row: dict[str, Any]) -> EventEnvelope   # line 311
        # manual construction (NOT from_dict); inner _json() helper json.loads's
        # str JSONB fields (payload/trace_context/metadata); failed_at → timestamp,
        # naive coerced to UTC via .replace(tzinfo=timezone.utc)

# src/navigator_eventbus/ingress_models.py
class IngressEnvelope(BaseModel):                            # line 21
    model_config = ConfigDict(extra="forbid", frozen=True)
    # _coerce_naive_to_utc field_validator; mirrors EventEnvelope fields
    def to_envelope(self) -> EventEnvelope                   # line 72 — direct construction

# src/navigator_eventbus/converters.py — all construct EventEnvelope directly
def from_legacy_event(event, *, severity) -> EventEnvelope   # line 43
def from_lifecycle_dict(data, *, severity) -> EventEnvelope  # line 74 — topic lifecycle.<class>
def from_hook_event(event, *, severity) -> EventEnvelope     # line 125 — topic hooks.<type>.<event>

# Wire-data from_dict call sites (verify roundtrip, no change expected):
#   src/navigator_eventbus/backends/redis_pubsub.py  — EventEnvelope.from_dict(json.loads(...))
#   src/navigator_eventbus/backends/redis_streams.py — EventEnvelope.from_dict(json.loads(...))
```

### Does NOT Exist
- ~~a `schema_version` column in the `evb_dlq` table~~ — rows carry the envelope
  fields; do NOT add a DB migration. The legacy→1 rule is applied in Python.
- ~~version validation in `IngressEnvelope`~~ — intentionally absent; any int passes
  Pydantic; `from_dict` is the semantic gate.
- ~~`to_envelope()` usage by ingress adapters~~ — adapters call `bus.emit()` with
  kwargs instead; `to_envelope()` exists but is not on their hot path. Still update it.

---

## Implementation Notes

### Key Constraints
- Identical tolerance rule everywhere: lenient backwards (missing → 1), never
  silently downgrade, never require the key.
- `IngressEnvelope(extra="forbid")` is the reason this task exists for ingress:
  without the new field, post-M1 clients sending `schema_version` get rejected.
- DLQ: `_row_to_envelope` uses `failed_at` as timestamp by design (replay
  semantics) — do not "fix" that.

### References in Codebase
- `src/navigator_eventbus/dlq.py:311–334` — the exact construction to extend.
- Existing backend tests — extend with mixed legacy + v1 message assertions.

---

## Acceptance Criteria

- [ ] Pre-M1 DLQ row (no version anywhere) → replayed envelope has `schema_version == 1`.
- [ ] `IngressEnvelope` accepts and defaults `schema_version`; `to_envelope()` passes it through; a payload WITH the key no longer trips `extra="forbid"`.
- [ ] All three converters produce envelopes with `schema_version == 1`.
- [ ] Streams + Pub/Sub roundtrip test: serialized envelope carries the field; mixed legacy (no key) + v1 messages both consumable.
- [ ] Full suite green: `pytest tests/ -v`; `ruff check src/` clean.

---

## Test Specification

```python
# tests/test_schema_version_propagation.py
import pytest
from navigator_eventbus.dlq import DLQHandler
from navigator_eventbus.ingress_models import IngressEnvelope
from navigator_eventbus.converters import from_lifecycle_dict


@pytest.fixture
def legacy_dlq_row():
    """Postgres evb_dlq row persisted BEFORE this spec (no schema_version)."""
    return {
        "topic": "order.created", "payload": '{"id": 1}',
        "event_id": "e-1", "failed_at": "2026-07-01T10:00:00",
        "source": "test", "severity": 20, "priority": 5,
        "correlation_id": None, "trace_context": None, "metadata": "{}",
        "attempts": 3, "error": "boom", "subscriber_id": "sub-1",
    }


def test_dlq_row_to_envelope_legacy_v1(legacy_dlq_row):
    env = DLQHandler._row_to_envelope(legacy_dlq_row)
    assert env.schema_version == 1


def test_ingress_envelope_schema_version_default_and_passthrough():
    ing = IngressEnvelope(topic="t", payload={}, timestamp="2026-07-01T10:00:00+00:00")
    assert ing.schema_version == 1
    assert ing.to_envelope().schema_version == 1
    # explicit key must not trip extra="forbid"
    IngressEnvelope(topic="t", payload={}, timestamp="2026-07-01T10:00:00+00:00",
                    schema_version=1)


def test_converters_emit_schema_version():
    env = from_lifecycle_dict({"event_class": "X", "data": {}})
    assert env.schema_version == 1
    # + equivalent asserts for from_legacy_event / from_hook_event
```

> Adjust fixture fields to the actual `_row_to_envelope` row shape and converter
> signatures after re-verifying them in the checkout (contract step 3).

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/eventbus-consolidation.spec.md` (ai-parrot).
2. **Check dependencies** — TASK-1839 must be in `sdd/tasks/completed/`.
3. **cd to `/home/jesuslara/proyectos/navigator-eventbus`** — all code work there.
4. **Verify the Codebase Contract** (grep the listed lines) before writing code.
5. **Update status** in `sdd/tasks/index/eventbus-consolidation.json` → `"in-progress"`.
6. **Implement**, run the FULL test suite.
7. **Move this file** to `sdd/tasks/completed/`, set index status `"done"`, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-21
**Notes**: Implemented in the same `navigator-eventbus` worktree/branch as
TASK-1839 (`feat-FEAT-319-eventbus-consolidation`). Applied legacy→1 rule
in `dlq.py:_row_to_envelope` (explicit `schema_version=row.get("schema_version", 1)`);
added `schema_version: int = 1` field + pass-through to `IngressEnvelope`/
`to_envelope()`; verified all three converters already emit `schema_version=1`
via the dataclass default (no code change needed — none bypass it). Added
`tests/test_schema_version_propagation.py` (5 tests) plus mixed
legacy+v1 roundtrip tests to `tests/test_backends_streams.py` and
`tests/test_backends.py`. Full suite green: 317 passed, 1 skipped.
Ruff clean on touched files. Commit: `07a02f9`.

**Deviations from spec**: none

---

## Addendum (2026-07-21) — code review critical fix (DLQ persistence gap)

Independent code review (via `code-reviewer` agent) found a critical gap:
the original implementation only handled the READ side (defaulting
`schema_version` to `1` in `_row_to_envelope` when absent) — the
`evb_dlq` table had no `schema_version` column and `_persist()` never
wrote `envelope.schema_version`, so DLQ replay would silently downgrade
EVERY row to version `1` forever, not just legacy (pre-M1) ones. This
was invisible today only because `ENVELOPE_SCHEMA_VERSION == 1`; it
would have silently violated the spec's "never downgrade" rule the
moment a future version bump landed.

Fixed (user-approved, "fix all items"):
- `DLQ_DDL` gains a `schema_version INTEGER NOT NULL DEFAULT 1` column,
  plus `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` so tables created
  before this fix are retrofitted automatically on the next
  `ensure_table()` call (`CREATE TABLE IF NOT EXISTS` alone would not
  touch an existing table).
- `_persist()` now writes `envelope.schema_version` (`_INSERT_SQL`
  gained a 13th placeholder).
- `_row_to_envelope` now raises `UnsupportedSchemaVersion` (via the
  shared `_validate_schema_version()` helper, TASK-1839 addendum) for a
  stored version greater than `ENVELOPE_SCHEMA_VERSION`, instead of
  silently downgrading.
- `replay()` now isolates per-row failures (try/except per row, logs +
  skips, leaves the row un-replayed) instead of letting one bad row
  abort the entire batch.

Added tests: `test_ddl_retrofits_schema_version_column`,
`test_dlq_replay_preserves_stored_schema_version`,
`test_row_to_envelope_raises_for_future_schema_version`,
`test_dlq_replay_skips_unsupported_schema_version_row`; updated
`test_retry_exhaustion_persists_to_dlq`'s arg-index assertions (the new
column shifted `failure_reason`/`attempts` positions in `_INSERT_SQL`).
Commit: `a50c1f8` (same worktree/branch). Full suite green: 334 passed,
1 skipped. Ruff clean.
