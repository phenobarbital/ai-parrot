---
title: Memory Dynamics
summary: Accepted gates, evidence, backends, CLI/MCP/export and measured limits
---

# Memory Dynamics

## Purpose

The memory dynamics subsystem implements the core algorithms and protocols for memory review, state tracking, and evidence management. It provides the foundation for adaptive memory systems that learn from outcomes and improve over time.

Key components:
- FSRS-6 algorithm implementation with pinned parameters
- Review signal processing and grade selection
- Durable review application with revision checking
- Evidence validation and attribution
- Export/import for replay and analysis

## Public API

### Core Modules

- [`parrot.memory.dynamics.models`](ref:parrot.memory.dynamics.models) — Versioned state and evidence models
- [`parrot.memory.dynamics.fsrs`](ref:parrot.memory.dynamics.fsrs) — FSRS algorithm implementation
- [`parrot.memory.dynamics.grade`](ref:parrot.memory.dynamics.grade) — Grade selection logic
- [`parrot.memory.dynamics.ranking`](ref:parrot.memory.dynamics.ranking) — Candidate ranking
- [`parrot.memory.dynamics.review_log`](ref:parrot.memory.dynamics.review_log) — Review protocol
- [`parrot.memory.dynamics.export`](ref:parrot.memory.dynamics.export) — Export functionality
- [`parrot.memory.dynamics.cli`](ref:parrot.memory.dynamics.cli) — CLI commands

### Key Classes

- [`MemoryParameters`](ref:parrot.memory.dynamics.models.MemoryParameters) — Algorithm parameters
- [`MemoryState`](ref:parrot.memory.dynamics.models.MemoryState) — Persisted memory state
- [`Grade`](ref:parrot.memory.dynamics.models.Grade) — Review grades
- [`ReviewSignal`](ref:parrot.memory.dynamics.models.ReviewSignal) — Observed outcome signal
- [`ReviewCommand`](ref:parrot.memory.dynamics.models.ReviewCommand) — Review operation
- [`ReviewReceipt`](ref:parrot.memory.dynamics.models.ReviewReceipt) — Review result
- [`SQLiteEpisodeBackend`](ref:parrot.memory.episodic.backends.sqlite.SQLiteEpisodeBackend) — Durable review log (`apply_review`, `list_reviews`)
- [`EpisodicMemoryStore`](ref:parrot.memory.episodic.store.EpisodicMemoryStore) — `review`, `list_reviews`

### CLI Commands

- [`wikitoolkit memory`](ref:parrot.memory.dynamics.cli.register_memory_commands) — Memory operations group (`parrot wiki memory` is the same group); attached lazily, so other `wikitoolkit` commands never import `parrot.memory`

## Configuration & Parameters

### MemoryParameters

The `MemoryParameters` class defines the FSRS algorithm configuration:

| Field | Type | Default | Description |
|---|---|---|---|
| `algorithm` | `str` | Required | Algorithm identifier (must be "fsrs-6") |
| `time_policy` | `str` | Required | Time policy ("days-v1" or "hours-v1") |
| `parameter_id` | `str` | Required | Parameter set identifier |
| `weights` | `tuple[float, ...]` | DEFAULT_PARAMETERS | 21 FSRS parameters |
| `reference` | `str` | FSRS6_REFERENCE | Pinned reference version |
| `provenance` | `str` | Required | Parameter provenance |

### Default Parameters

```python
DEFAULT_PARAMETERS = (
    0.212, 1.2931, 2.3065, 8.2956, 6.4133, 0.8334, 3.0194, 0.001,
    1.8722, 0.1666, 0.796, 1.4835, 0.0614, 0.2629, 1.6483, 0.6014,
    1.8729, 0.5425, 0.0912, 0.0658, 0.1542
)
```

### Bounds

Parameters are validated against accepted bounds:
- Lower bounds: `LOWER_BOUNDS_PARAMETERS`
- Upper bounds: `UPPER_BOUNDS_PARAMETERS`
- Difficulty: `[1.0, 10.0]`
- Stability: `>= 0.001`

### MemoryState

The `MemoryState` model tracks persisted state:

| Field | Type | Description |
|---|---|---|
| `difficulty` | `float | None` | Difficulty rating (1.0-10.0) |
| `stability` | `float | None` | Stability rating (>= 0.001) |
| `reviewed_at` | `datetime | None` | Last review timestamp |
| `review_count` | `int` | Number of earned reviews |
| `apply_revision` | `int` | Current revision number |
| `status` | `str` | State status |
| `parameter_id` | `str | None` | Parameter set identifier |

### ReviewSignal

The `ReviewSignal` model captures observed outcomes:

| Field | Type | Description |
|---|---|---|
| `outcome_id` | `str` | Outcome identifier |
| `outcome_revision` | `int` | Outcome revision (>= 0) |
| `observed_at` | `datetime` | Observation timestamp |
| `scope` | `MemoryRequestScope` | Runtime scope |
| `evidence_ref` | `str` | Evidence reference |
| `source` | `Literal["tool_runtime", "coder_engine"]` | Source of signal |
| `outcome` | `Literal["success", "failure", "cancelled", "incomplete"]` | Outcome type |
| `first_attempt` | `bool` | First attempt flag |
| `correction_count` | `int` | Number of corrections (>= 0) |
| `error_signature` | `str | None` | Normalized error signature |
| `recovery_refs` | `tuple[str, ...]` | Recovery references |
| `passed_check_ids` | `tuple[str, ...]` | Passed check identifiers |

## Usage Examples

### Basic FSRS Operations

```python
from parrot.memory.dynamics.fsrs import retrievability, transition
from parrot.memory.dynamics.models import MemoryState, MemoryParameters, Grade
from datetime import datetime, timezone

# Calculate retrievability
state = MemoryState(
    difficulty=5.0,
    stability=10.0,
    reviewed_at=datetime.now(timezone.utc),
    review_count=3,
    apply_revision=1,
    status="reviewed",
    parameter_id="episodic-neutral-v1"
)

params = MemoryParameters(
    algorithm="fsrs-6",
    time_policy="days-v1",
    parameter_id="episodic-neutral-v1",
    weights=DEFAULT_PARAMETERS,
    reference=FSRS6_REFERENCE,
    provenance="default"
)

retrievability_score = retrievability(state, now=datetime.now(timezone.utc), parameters=params)

# Apply a review grade
new_state = transition(state, Grade.GOOD, reviewed_at=datetime.now(timezone.utc), parameters=params)
```

### Review Application

Reviews are normally applied through `EpisodicMemoryStore.review(...)` after `cite(...)`: the store selects the grade from the verified signal and
passes it, the memory's error signature and the review parameters to the backend. The backend call below is the low-level path (it is what the store uses):

```python
from datetime import datetime, timezone
from pathlib import Path

from parrot.memory.dynamics.models import Grade, MemoryParameters, ReviewCommand
from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend
from parrot.memory.episodic.models import MemoryNamespace

namespace = MemoryNamespace(tenant_id="default", agent_id="my-agent", user_id="user123", session_id="session456")

command = ReviewCommand.model_validate(
    {
        "ref": {
            "namespace": namespace.model_dump(mode="json"),
            "kind": "episode",
            "memory_id": "episode789",
            "content_version": "v1",
        },
        "signal": {
            "outcome_id": "outcome123",
            "outcome_revision": 0,
            "observed_at": datetime.now(timezone.utc),
            "scope": {**namespace.model_dump(mode="json"), "turn_id": "turn789", "identity_provenance": "runtime_derived"},
            "evidence_ref": "coder-review/v1/execution/task/outcome123",
            "source": "coder_engine",
            "outcome": "success",
            "first_attempt": True,
            "correction_count": 0,
            "passed_check_ids": ("unit-tests",),
        },
        "exposure_id": "exposure456",
        "expected_revision": 0,
    }
)
parameters = MemoryParameters(
    algorithm="fsrs-6", time_policy="days-v1", parameter_id="episodic-neutral-v1", provenance="docs-example"
)

backend = SQLiteEpisodeBackend(Path("memory.db"))
await backend.configure()
# The episode "episode789" must already be stored in this namespace.
receipt = await backend.apply_review(command, grade=Grade.GOOD, memory_error_signature=None, parameters=parameters)
```

`receipt.status` is `applied` only after the transaction commits. Calling `backend.apply_review(command)` without a grade still commits the review,
but stores no review record (see "Persisted review record" below).

### CLI Usage

```bash
# Check memory status
wikitoolkit memory --storage-path memory.db --agent-id my-agent status

# Recall memory
wikitoolkit memory --storage-path memory.db --agent-id my-agent --user-id user123 recall "recent interactions"

# Export committed reviews
wikitoolkit memory --storage-path memory.db --agent-id my-agent export-reviews --output reviews.json
```

The group options (`--storage-path`, `--tenant-id`, `--agent-id`, `--user-id`, `--session-id`, `--room-id`, `--crew-id`, `--model-id`, `--episodic/--no-episodic`,
`--user-memory/--no-user-memory`, `--dynamics/--no-dynamics`) select one explicitly configured store and scope. Sub-commands: `status`, `recall`, `cite`,
`review`, `forget`, `sync`, `import-feedback`, `export-reviews`. `parrot wiki memory ...` is the same group. The group is registered lazily: importing
`parrot.memory` happens only when a `memory` command runs.

### Export and Import

```python
from pathlib import Path

from parrot.memory.dynamics.export import export_reviews
from parrot.memory.dynamics.feedback import import_feedback
from parrot.memory.episodic.models import MemoryNamespace

namespace = MemoryNamespace(tenant_id="default", agent_id="my-agent", user_id="user123")

# `episodic_store` is the configured EpisodicMemoryStore; store=None raises ValueError (never an empty archive).
result = await export_reviews(namespace=namespace, destination=Path("reviews.json"), store=episodic_store)
# -> {"export_path": ..., "record_count": ..., "content_hash": ..., "format_version": "v1"}

# Import legacy coder feedback (idempotent, stable IDs)
stats = await import_feedback(Path("."), store=episodic_store, namespace=namespace)
```

### Reading committed reviews

```python
rows = await episodic_store.list_reviews(namespace)  # ordered by recorded_at, dedupe_key
```

Every namespace filter is applied before any `limit`. A backend without `list_reviews` raises `RuntimeError` (never an empty list). The archive is JSON with
`format`, `exported_at` (real UTC time; injectable `clock` in tests), `namespace`, `provenance` and `reviews`. Each review is a list entry (so two reviews of one
memory version both survive) with `dedupe_key`, `outcome_id`, `outcome_revision`, `ref_key`, `apply_revision`, `recorded_at`, the full validated `command`, and a
`record` object only when one was persisted.

## Gotchas

### Algorithm Constraints

- Only FSRS-6 algorithm is supported (pinned to v6.3.2)
- Parameters must stay within accepted bounds
- Time policy is either "days-v1" or "hours-v1"
- Legacy uninitialized state is neutral, not an earned review

### Review Protocol

- Reviews require delivered version, attribution, and verified outcome
- Reading/citing alone doesn't reinforce memory
- Synthetic evidence is rejected; only verified outcomes produce reviews
- Failure whose normalized error signature (first 200 characters) equals the memory's → AGAIN grade; any other failure selects no grade and no review
- Verified structural recovery (recovery references present) on a cited memory → EASY grade
- Success with corrections → HARD grade
- Verified first-attempt success → GOOD grade
- Anything else selects no grade

### Deduplication and Revision

- Dedupe key includes scope, outcome, and memory reference
- Expected revision must match apply revision
- Lower outcome revisions are rejected as stale
- Unknown in-scope references are ignored
- Cross-scope references reveal no content

### Storage and Durability

- SQLite backend uses WAL mode with busy timeout
- Writes use BEGIN IMMEDIATE transactions
- Schema is versioned with `PRAGMA user_version` (currently 3); migrations are additive and idempotent, with no backfill
- Export is atomic (unique temp file, fsync, replace), runs off the event loop and cleans up on failure
- There is no `retry_export`: re-running the export is idempotent

### Persisted review record (schema v3)

- A review committed through `EpisodicMemoryStore.review` stores, in the same `BEGIN IMMEDIATE` transaction as the review row and the `memory_state` upsert:
  the selected `grade`, the `before` and `after` `MemoryState`, the `parameter_id` (`episodic-neutral-v1`) and the `memory_error_signature` the grade was
  selected against (at most 2000 characters). `list_reviews` and the archive return them under `record`.
- Schema v3 only adds five nullable `reviews` columns (`grade`, `before_state`, `after_state`, `parameter_id`, `memory_error_signature`). Opening an older
  database migrates it in place, re-opening is a no-op, and a half-migrated database is completed. Nothing is backfilled.
- Reviews committed before the migration, or by a direct `apply_review(command)` without a grade, have no record and are exported without a `record` key —
  one is never fabricated. For a memory with no stored state, `before` is the neutral uninitialized state.
- Replay applies only the archived `command` and never depends on `record`: one application per review, then `duplicate`.
- The review parameters live in `episodic/store.py`; `episodic/recall.py` keeps its own inline literal with the same `parameter_id`, so there are two
  definitions that must stay in step.

### Performance Limits

- Exact vector search supported up to 5,000 rows
- p95 latency contract: ≤ 150 ms at ceiling
- Degradation reported when ceiling exceeded
- FTS success never masks vector failure
- No index dependency added in this feature

### Evidence and Attribution

- Model-provided flags don't grant authority
- Source is either "tool_runtime" or "coder_engine"
- Synthetic source not representable in production
- Evidence references validated before admission
- Attribution policy: cited mode by default
- Overlap attribution is opt-in

### Export and Replay

- Export carries inputs a fitter needs
- No fitting code exists in this feature
- Replay applies only archived commands
- One application per review
- Imported feedback remains replayable
- No generic 90-day TTL sweep for feedback

## Related

### Wiki Pages

- [Agent Memory](agent-memory.md) — Architecture, flags, lifecycle, scope and hard-cut migration
- [User Memory](user-memory.md) — Independent knowledge, provenance, correction and suppression
- [Conversation Memory](conversation-memory.md) — How conversation history is stored and managed

### External References

- [FEAT-892 Specification](../../sdd/specs/agent-memory-mixin.spec.md) — Full feature specification
- [FEAT-889 Agent Brain](../../sdd/specs/agent-brain.spec.md) — Brain service and versioned exposure
- [FEAT-571 Memory Dynamics](../../sdd/specs/memory-dynamics.spec.md) — Historical dynamics specification
- [FSRS Reference](https://github.com/open-spaced-repetition/fsrs4anki) — Original FSRS algorithm

### Ownership

- Dynamics models and algorithms are owned by FEAT-892
- Brain service boundary and versioned exposure are owned by FEAT-889
- Parameter fitting and optimizer are deferred to follow-up feature
- Export format and replay contracts are stable for fitting feature
