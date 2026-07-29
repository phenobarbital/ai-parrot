---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: EventBus Consolidation — schema_version, default-capable hooks routing, ai-parrot follow-up

**Date**: 2026-07-20
**Author**: Jesus (phenobarbital) + Claude
**Status**: exploration
**Recommended Option**: Option B

---

## Problem Statement

The extraction of the bus core into `navigator-eventbus` succeeded — FEAT-316
(broker port), FEAT-317 (ai-parrot migration), and FEAT-318 (navigator cleanup)
are all complete on `dev`. The internal `parrot/core/events/bus/` copy is deleted,
all imports rewired, hooks shimmed, migration guard tests in place.

However, two consolidation items remain open in navigator-eventbus itself, plus
one follow-up in ai-parrot:

1. **Envelope versioning (M1)**: The wire format (`EventEnvelope.to_dict()` /
   `from_dict()`) lacks a `schema_version` field. Redis Streams traffic will
   accumulate versioned and version-less messages. Adding versioning NOW (before
   production traffic) avoids painful retroactive migration later.

2. **Default-capable hooks routing (M2)**: `HookManager(route_to_bus=False)` is
   the current default — hooks bypass the bus unless explicitly opted in. The
   original brainstorm's "bus as app-wide fabric" goal calls for auto-routing
   when a bus is attached. However, **audit reveals zero `set_event_bus` or
   `route_to_bus` references in ai-parrot** — the actual pattern uses
   `forward_to_global` / `forward_to_bus` per-subscriber. M2's impact on
   ai-parrot is minimal.

3. **ai-parrot follow-up**: The `navigator-eventbus` dependency is pinned to a
   git commit hash (`17b99c2...`), not a PyPI release. After navigator-eventbus
   `0.1.0` is published, ai-parrot needs to swap the pin and add the
   `test_no_internal_bus_copy` guard test.

## Constraints & Requirements

- `EventEnvelope` MUST stay `@dataclass(frozen=True, slots=True)` — no Pydantic in the hot path.
- New `schema_version` field MUST be last (positional-arg backwards compatibility).
- Readers must be lenient backwards (missing → 1) and strict forwards (unknown → raise).
- `HookManager` tri-state must not break existing consumers using `route_to_bus=True` or `route_to_bus=False`.
- navigator-eventbus `0.1.0` (final, not rc) must be tagged and published to PyPI before ai-parrot switches.
- Current package version is `0.1.0rc2`; M1+M2 land in the `0.1.0` final release.
- No new external dependencies in navigator-eventbus.

---

## Options Explored

### Option A: Strict Minimum — schema_version + tri-state only

Add `schema_version: int = 1` to `EventEnvelope` and change `HookManager`
to `route_to_bus: Optional[bool] = None` (tri-state). Touch only `from_dict()`
for the legacy tolerance rule. Release 0.1.0, swap ai-parrot's git pin to
`>=0.1.0,<0.2`. No other changes.

✅ **Pros:**
- Smallest possible diff — lowest risk of regressions
- Fast to implement and review
- Clear scope boundary

❌ **Cons:**
- Leaves `_row_to_envelope()` in `dlq.py` without the legacy→1 rule — DLQ replay of pre-M1 rows would produce envelopes missing `schema_version`, which downstream consumers might not expect
- `IngressEnvelope` (Pydantic boundary) doesn't carry `schema_version`, creating a gap between wire format and ingress validation
- No guard test in ai-parrot — regression risk if someone re-introduces internal bus code
- Converters (`from_legacy_event`, `from_lifecycle_dict`, `from_hook_event`) silently drop version info

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-eventbus` | Target package for M1+M2 | Release 0.1.0 from current rc2 |

🔗 **Existing Code to Reuse:**
- `navigator_eventbus/envelope.py` — extend `EventEnvelope` dataclass
- `navigator_eventbus/hooks/manager.py` — modify `HookManager.__init__`

---

### Option B: Thorough — M1 + M2 + all deserialization paths + guard test

Same as A, but the `schema_version` field propagates through ALL six
deserialization/construction paths identified in the audit:

1. `EventEnvelope.from_dict()` — legacy→1 rule (missing key → 1, unknown → raise)
2. `_row_to_envelope()` in `dlq.py` — same legacy→1 rule for Postgres DLQ rows
3. `IngressEnvelope` — add `schema_version: int = 1` field to Pydantic model, `to_envelope()` passes it through
4. `from_legacy_event()` — always emits version 1
5. `from_lifecycle_dict()` — always emits version 1
6. `from_hook_event()` — always emits version 1

Plus: ai-parrot gets `test_no_internal_bus_copy` guard test and the git→PyPI
pin swap.

✅ **Pros:**
- Every path that produces an `EventEnvelope` emits `schema_version` — no silent gaps
- DLQ replay works correctly with pre-M1 and post-M1 rows
- Ingress boundary validates version before it reaches the bus
- Guard test prevents regression in ai-parrot
- Complete audit trail — all 10 deserialization paths accounted for

❌ **Cons:**
- Slightly larger diff (~6 files in navigator-eventbus vs. ~2 in Option A)
- Converters change is mechanical but touches more test surface

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-eventbus` | Target package for M1+M2 | Release 0.1.0 from current rc2 |

🔗 **Existing Code to Reuse:**
- `navigator_eventbus/envelope.py` — `EventEnvelope` dataclass, `to_dict()`, `from_dict()`
- `navigator_eventbus/dlq.py` — `_row_to_envelope()` (line 310-334)
- `navigator_eventbus/ingress_models.py` — `IngressEnvelope` Pydantic model
- `navigator_eventbus/converters.py` — `from_legacy_event()`, `from_lifecycle_dict()`, `from_hook_event()`
- `navigator_eventbus/hooks/manager.py` — `HookManager.__init__` (line 45-50)
- `packages/ai-parrot/tests/core/events/test_migration_guard.py` — existing guard tests to extend

---

### Option C: Full Consolidation — B + deprecation layer + documentation

Everything in B, plus:

- Deprecation warning when `HookManager` is instantiated with explicit
  `route_to_bus=False` (the old default) — guides consumers toward the
  auto-routing path.
- Version compatibility matrix documented in navigator-eventbus README/TOPICS.md.
- Changelog entry in ai-parrot noting that auto-routing is a behavior change
  for any deployment calling `set_event_bus`.
- A `MIGRATION.md` in navigator-eventbus documenting the envelope versioning
  contract for future version bumps (how to add version 2, etc.).

✅ **Pros:**
- Most forward-looking — sets up the project for future envelope evolution
- Deprecation warning actively guides consumers
- Documentation prevents future maintainers from misunderstanding the versioning contract

❌ **Cons:**
- Deprecation warning on `route_to_bus=False` is premature — the auto-routing behavior hasn't been validated in production yet. Warning before proving the feature works is backwards.
- Documentation effort for a contract that may change when version 2 is actually designed
- `MIGRATION.md` is speculative — we don't know what version 2 will look like
- Heavier review burden for marginal value at this stage

📊 **Effort:** Medium-High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-eventbus` | Target package for M1+M2 | Release 0.1.0 from current rc2 |
| `warnings` (stdlib) | Deprecation warnings | For `route_to_bus=False` deprecation |

🔗 **Existing Code to Reuse:**
- Same as Option B, plus:
- `navigator_eventbus/TOPICS.md` — existing topic documentation to extend

---

## Recommendation

**Option B** is recommended because:

- It closes all deserialization paths identified in the audit — no silent gaps
  where an envelope could appear without `schema_version`. Option A leaves the
  DLQ replay and ingress paths uncovered, which are exactly the paths that will
  matter when version 2 eventually arrives.
- The extra effort over A is small (mechanical changes to converters and
  `_row_to_envelope`) but prevents real bugs: a DLQ row replayed after M1
  would produce an envelope that `to_dict()` emits with `schema_version=1`
  even though the original wire data predated versioning — this is correct
  behavior, not a bug, but only if the legacy→1 rule is applied consistently.
- Option C's deprecation warning is premature. The auto-routing hasn't been
  validated in production, and **the audit shows zero `route_to_bus` references
  in ai-parrot** — there's no consumer to warn yet. Documentation is good but
  can come later when version 2 is actually designed.
- The guard test (`test_no_internal_bus_copy`) is cheap insurance against
  regression — it should have been part of FEAT-317 but wasn't.

---

## Feature Description

### User-Facing Behavior

No user-visible behavior change. The `schema_version` field is internal to the
wire format. The `route_to_bus` auto-default only activates when a bus is
attached AND no explicit opt-out is set — and currently zero ai-parrot call
sites use `route_to_bus` or `set_event_bus`, so the behavioral change is latent
(future consumers will benefit).

The ai-parrot dependency moves from a git commit pin to a proper PyPI version,
improving reproducibility of installs.

### Internal Behavior

**M1 — Envelope schema_version:**
- `EventEnvelope` gains a trailing `schema_version: int = 1` field.
- `to_dict()` includes it in the serialized output.
- `from_dict()` applies the legacy→1 rule: missing key → version 1 (backwards
  compat with pre-M1 Streams entries); known version → parse; unknown (> 1) →
  raise `UnsupportedSchemaVersion` with topic and event_id context.
- `_row_to_envelope()` applies the same rule for DLQ Postgres rows.
- `IngressEnvelope` (Pydantic) gains the field and passes it through to
  `to_envelope()`.
- All three converters emit version 1 unconditionally.

**M2 — HookManager auto-routing:**
- `HookManager.__init__` changes from `route_to_bus: bool = False` to
  `route_to_bus: Optional[bool] = None`.
- `None` → auto: route to bus iff `self._event_bus is not None`.
- `True` → explicit opt-in (current behavior when set).
- `False` → explicit opt-out (current default behavior preserved).
- One-time INFO log on first auto-activation.
- `_build_dispatch()` and `_publish_hook_event()` use
  `_effective_route_to_bus()` instead of reading `self._route_to_bus` directly.

**ai-parrot follow-up:**
- `pyproject.toml` swaps git pin to `navigator-eventbus>=0.1.0,<0.2`.
- New `test_no_internal_bus_copy` guard test asserts `parrot/core/events/bus/`
  does not exist and no `parrot.*` module defines `BusCore` or `EventEnvelope`.

### Edge Cases & Error Handling

- **Pre-M1 Streams entries**: Lack `schema_version` key. `from_dict()` treats
  them as version 1. Mixed legacy + v1 messages in one stream are both
  consumable. No data migration needed.
- **Pre-M1 DLQ rows**: `_row_to_envelope()` applies the same legacy→1 rule.
  Replayed envelopes carry version 1 regardless of when they were originally
  stored.
- **Future version 2**: `from_dict()` raises `UnsupportedSchemaVersion` with
  the topic and event_id in the error message, enabling operators to identify
  exactly which message caused the failure.
- **`IngressEnvelope` with unknown version**: Pydantic validation accepts any
  int (the Pydantic model doesn't enforce range); the `EventEnvelope.from_dict`
  or direct construction handles the unknown-version raise. This is intentional
  — ingress validates shape, bus validates semantics.
- **`route_to_bus=None` with no bus**: `_effective_route_to_bus()` returns
  `False` — hooks fire via callback only, no error.
- **Bus attached then detached**: If `set_event_bus(None)` is called,
  auto-routing deactivates. The one-time log fires again on next re-attachment
  (flag resets on detach).

---

## Capabilities

### New Capabilities
- `envelope-schema-version`: Wire-format versioning for `EventEnvelope` with forwards-incompatible guard
- `hooks-auto-routing`: `HookManager` auto-routes to bus when attached (tri-state `route_to_bus`)

### Modified Capabilities
- `navigator-eventbus` package release: 0.1.0rc2 → 0.1.0 final
- `ai-parrot` dependency: git pin → PyPI version pin

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `navigator_eventbus/envelope.py` | extends | New `schema_version` field + `ENVELOPE_SCHEMA_VERSION` constant + `UnsupportedSchemaVersion` exception |
| `navigator_eventbus/envelope.py` `to_dict()` | modifies | Emits `schema_version` |
| `navigator_eventbus/envelope.py` `from_dict()` | modifies | Version-aware deserialization with legacy tolerance |
| `navigator_eventbus/dlq.py` `_row_to_envelope()` | modifies | Legacy→1 rule for DLQ rows |
| `navigator_eventbus/ingress_models.py` | extends | `schema_version` field on `IngressEnvelope` |
| `navigator_eventbus/converters.py` | modifies | All three converters emit `schema_version=1` |
| `navigator_eventbus/hooks/manager.py` | modifies | Tri-state `route_to_bus`, `_effective_route_to_bus()`, one-time log |
| `navigator_eventbus/__init__.py` | extends | Export `ENVELOPE_SCHEMA_VERSION`, `UnsupportedSchemaVersion` |
| `packages/ai-parrot/pyproject.toml` | modifies | Git pin → `navigator-eventbus>=0.1.0,<0.2` |
| `packages/ai-parrot/tests/` | extends | `test_no_internal_bus_copy` guard test |
| `backends/redis_streams.py` | none (verify) | Serializes via `to_dict()` — no code change expected |
| `backends/redis_pubsub.py` | none (verify) | Same — verify `from_dict()` path works |

---

## Code Context

### Verified Codebase References

#### EventEnvelope (navigator-eventbus, installed at .venv)

```python
# From .venv/.../navigator_eventbus/envelope.py:40-41
@dataclass(frozen=True, slots=True)
class EventEnvelope:
    topic: str                                    # line 62
    payload: dict[str, Any]                       # line 63
    event_id: str                                 # line 64, default uuid4()
    timestamp: datetime                           # line 65, default utcnow
    source: Optional[str] = None                  # line 66
    severity: Severity = Severity.INFO            # line 67
    priority: EventPriority = EventPriority.NORMAL  # line 68
    correlation_id: Optional[str] = None          # line 69
    trace_context: Optional[dict] = None          # line 70
    metadata: dict[str, Any] = field(default_factory=dict)  # line 71-73

    def to_dict(self) -> dict[str, Any]: ...      # line 95
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EventEnvelope": ...  # line 117
```

#### HookManager (navigator-eventbus)

```python
# From .venv/.../navigator_eventbus/hooks/manager.py:45-50
class HookManager:
    def __init__(self, *, route_to_bus: bool = False) -> None:
        self._hooks: Dict[str, BaseHook] = {}
        self._callback: Optional[Callable] = None
        self._event_bus: Optional["EventBus"] = None
        self._route_to_bus = route_to_bus

    def set_event_bus(self, bus) -> None: ...      # line 75-90
    # property route_to_bus                        # line 52-54
    # route_to_bus.setter                          # line 57-63
    def _build_dispatch(self) -> Callable: ...     # line 92-130
    def _publish_hook_event(self, event) -> None: ...  # line 132-177
```

#### DLQ — _row_to_envelope (navigator-eventbus)

```python
# From .venv/.../navigator_eventbus/dlq.py:310-334
@staticmethod
def _row_to_envelope(row: dict) -> EventEnvelope:
    # Inner _json() helper: json.loads if str, else passthrough (line 313-314)
    # Parses failed_at via fromisoformat, coerces naive→UTC (line 317-320)
    # Constructs EventEnvelope(...) directly, NOT via from_dict
    # Uses failed_at as timestamp (replay semantics)
```

#### IngressEnvelope (navigator-eventbus)

```python
# From .venv/.../navigator_eventbus/ingress_models.py:21-89
class IngressEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    # Mirrors EventEnvelope fields with Pydantic validation
    # _coerce_naive_to_utc field_validator (line 57-70)
    def to_envelope(self) -> EventEnvelope: ...    # line 72-89
```

#### Converters (navigator-eventbus)

```python
# From .venv/.../navigator_eventbus/converters.py
def from_legacy_event(event: Event, *, severity) -> EventEnvelope: ...     # line 43
def from_lifecycle_dict(data: dict, *, severity) -> EventEnvelope: ...     # line 74
def from_hook_event(event: HookEvent, *, severity) -> EventEnvelope: ...   # line 125
# All three construct EventEnvelope directly (not via from_dict)
```

#### from_dict call sites (wire data — the only 2)

```python
# backends/redis_pubsub.py:188
EventEnvelope.from_dict(json.loads(message["data"]))

# backends/redis_streams.py:350
EventEnvelope.from_dict(json.loads(data))
```

#### ai-parrot — pyproject.toml dependency

```python
# packages/ai-parrot/pyproject.toml:103-104
# TODO: switch to navigator-eventbus>=0.1.0 after PyPI publish (FEAT-317 close)
"navigator-eventbus @ git+https://github.com/phenobarbital/navigator-eventbus.git@17b99c22faf44bcf92fdf299a6e9a021d678a970",
```

#### ai-parrot — existing migration guard test

```python
# packages/ai-parrot/tests/core/events/test_migration_guard.py
# 4 tests: test_deleted_modules_not_importable, test_navigator_eventbus_smoke,
#   test_typed_events_subclass, test_facade_reexports
# Does NOT include test_no_internal_bus_copy (to be added)
```

#### ai-parrot — dual-emit pattern (actual usage)

```python
# parrot/bots/abstract.py:452
self._init_events(event_bus=event_bus, forward_to_global=True)
# Uses forward_to_global / forward_to_bus, NOT set_event_bus / route_to_bus
```

### Does NOT Exist (Anti-Hallucination)

- ~~`schema_version` / `ENVELOPE_SCHEMA_VERSION` / `UnsupportedSchemaVersion`~~ — do not exist yet anywhere; M1 creates them.
- ~~`HookManager.route_to_bus = None` tri-state~~ — currently strict `bool = False`; M2 creates it.
- ~~`HookManager._effective_route_to_bus()`~~ — does not exist; M2 creates it.
- ~~`set_event_bus` call sites in ai-parrot~~ — zero. The function exists in navigator-eventbus's `HookManager` but nothing in ai-parrot calls it.
- ~~`route_to_bus` references in ai-parrot~~ — zero. ai-parrot uses `forward_to_global` / `forward_to_bus` pattern instead.
- ~~`parrot/core/events/bus/`~~ — deleted by FEAT-317. Only stale `__pycache__` remains.
- ~~`parrot/core/events/evb.py`~~ — deleted by FEAT-317.
- ~~`parrot.core.hooks.base` / `parrot.core.hooks.models`~~ — deleted; migration guard test confirms `ModuleNotFoundError`.
- ~~pickle in envelope paths~~ — not used. `cloudpickle`/`jsonpickle` exist only in `brokers/` subpackage (generic message broker layer), never in `backends/` (EventEnvelope transport).
- ~~`navigator.*` imports in navigator-eventbus src/~~ — zero (verified by FEAT-318; neutrality test tightened and landed).
- ~~`test_no_internal_bus_copy` in ai-parrot~~ — does not exist yet; follow-up creates it.

---

## Parallelism Assessment

- **Internal parallelism**: M1 (envelope versioning) and M2 (hooks auto-routing) are fully independent — they touch different files and have no shared state. They CAN be implemented in parallel within navigator-eventbus. The ai-parrot follow-up depends on the navigator-eventbus 0.1.0 release (hard gate).
- **Cross-feature independence**: No in-flight specs conflict. FEAT-316/317/318 are all complete. The only shared touchpoint is the navigator-eventbus package version.
- **Recommended isolation**: `per-spec` — M1 and M2 are small enough to land in one PR to navigator-eventbus. The ai-parrot follow-up is a separate single-commit PR.
- **Rationale**: Two PRs total (one in navigator-eventbus, one in ai-parrot) with a release gate between them. Worktree overhead is not justified for this scope — both changes are small, well-bounded, and sequential by necessity (release gate).

---

## Open Questions

- [x] Which parrot hooks are pure duplicates vs. divergent? — *Owner: Claude Code*: Resolved by FEAT-317. All generic hooks (base, models, manager, mixins, scheduler, file_watchdog, broker hooks) now import from `navigator_eventbus.hooks.*`. Domain hooks (jira, github, imap, sharepoint, messaging, whatsapp, matrix, postgres, file_upload) stay local in ai-parrot. No duplicates remain.
- [x] Does anything persist envelopes outside Streams (DLQ table rows)? — *Owner: Claude Code*: Yes. `dlq.py:_row_to_envelope()` (line 310-334) reconstructs envelopes from Postgres rows. It does NOT use `from_dict()` — manual construction. The legacy→1 rule must be applied here too (Option B covers this).
- [x] FEAT numbering reconciliation (316 vs 318)? — *Owner: Jesus*: Resolved — FEAT-318 is the canonical ID per completed task indexes.
- [x] `set_event_bus` call sites in ai-parrot for M2 audit? — *Owner: Claude Code*: Zero call sites. ai-parrot uses `forward_to_global` / `forward_to_bus` pattern, not `set_event_bus` / `route_to_bus`. M2's auto-routing change is latent in ai-parrot.
- [ ] M4 shim strategy: the spec asks whether to keep `evb.py` as re-export shim permanently — *Owner: Jesus*: Moot. FEAT-317 deleted `evb.py` entirely. Consumers import from `navigator_eventbus` directly. Close this question.
- [ ] Should `route_to_bus` auto-activation be announced in ai-parrot's changelog as behavior change? — *Owner: Jesus*: Given zero call sites, the change is latent. Still worth a changelog note for future consumers who DO call `set_event_bus`.
