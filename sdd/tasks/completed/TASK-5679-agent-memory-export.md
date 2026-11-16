# TASK-5679: Deterministic review export and replayable archives

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5678, TASK-5662
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes lazy command group and overlapping cli.py from TASK-5678; Consumes durable review/archive source from TASK-5662

## Context

Implement the bounded M6 slice of FEAT-892 revision 0.2. The owner's accepted
section 8 decisions govern defaults; earlier proposed wording is not permission to change them.
These are planning artifacts, not evidence that carried G1–G4 gates passed.

## Owner Decision (rework of the done-with-issues delivery, 2026-11-16)

The first delivery (`438c492521`) shipped a placeholder CLI export and an `export_reviews` that never read a store.
The owner decided to **extend this task's scope, not defer** (binding):

1. Add a read API for committed reviews: a method on the SQLite episodic backend (scoped by namespace, **every filter
   applied before any limit**, deterministic total order) and a matching store method. A backend without it **fails
   visibly**, like `apply_review` does (never an empty list).
2. Rebuild the export on real data with keyword-only `export_reviews(*, namespace, destination, ...)` that exports what
   the configured store holds. The CLI command exports what the store holds — no empty placeholder.
3. Fix the smaller issues: two reviews of the same memory version must both survive; `exported_at` is the real time
   (injectable clock for tests); retry either backs off or does not claim to; no blocking write inside an async function;
   no shared `.tmp` name.
4. Tests use a **real temporary SQLite store with reviews applied through `apply_review`** (not hand-built inputs) and
   cover **replay of the exported archive**.

Resolution notes (recorded, not silently decided): the blueprint signature has no store parameter, but a store cannot be
derived from `namespace` and `destination`. The required keyword-only parameters stay `namespace` and `destination`;
`store` and `clock` are added as optional keyword-only parameters. The CLI resolves the configured store from the opened
toolkit manager and passes it. `store=None` raises `ValueError` — it never exports an empty archive.
`apply_review` persists only the validated `ReviewCommand` plus `apply_revision`/`recorded_at`; grades, before/after
memory state and `parameter_id` are NOT persisted, so the archive must not contain or invent them (spec: no invented
historical per-memory grades). The Completion Note must state exactly what AC12/AC18 coverage this leaves.

## Owner Decision 2 (host-delegated, 2026-11-16) — persist the full review record (issue:cef9e1a8c0e6)

The reworked export is deterministic and replayable but not fit-ready: the SQLite review log persists only the command
plus `apply_revision`/`recorded_at`. Binding decision — **fix before TASK-5681**:

- **(A) Persist the full ReviewRecord at `apply_review` time** in the SQLite backend, **in the same transaction as the
  review row** (spec C6): the selected **grade**, the **before** and **after** `MemoryState`, the **parameter_id**, and the
  **memory error signature the grade was selected against**.
- **Additive, idempotent migration via `PRAGMA user_version`** (spec D8): new **nullable** columns, **no backfill**; existing
  rows keep NULL and are listed/exported as **legacy records with those fields absent — never fabricated**.
- `list_reviews` and the export archive carry the new fields. **Replay must still produce exactly one application and must
  not depend on them** (replay applies only the archived `command`).
- Test with a real temporary store **including a database created at the previous schema version**.
- Close this task as `done` only if AC18 is then met end to end.

Design (resolution notes, recorded so they are not silently decided):

- `EpisodicMemoryStore.review` already selects the grade (`select_grade`, attribution `"cited"`, signature `episode.error_message
  or episode.error_type`). It now passes `grade`, that signature and the review parameters to the backend; the backend, which
  alone can read the current memory state inside the transaction, computes `before`/`after` with `fsrs.transition`.
- Direct `backend.apply_review(command)` calls without a grade keep the legacy behavior (record columns stay NULL), so existing
  callers and replay are unaffected. Supplying exactly one of `grade`/`parameters` is a `ValueError` raised before any write.
- The review parameters equal the neutral parameters used at recall time (`parameter_id="episodic-neutral-v1"`, `fsrs-6`,
  `days-v1`). They are defined once in `store.py` (`recall.py` keeps its own inline literal; it is out of scope — flagged, not changed).
- A legacy memory (reviewed before this change) has no stored `MemoryState`; its `before` state is the neutral uninitialized
  `MemoryState()` — documented, not reconstructed.

## Release Preconditions

No additional owner decision is required beyond completed dependency contracts. Do not bypass a blocked dependency.

Before releasing any blocked task, record the accepted amendment in the spec, expand its
Validation Contract with the released module test paths, regenerate the index test contract
using `parrot sdd tests contract`, and change status through the normal SDD workflow.
Do not infer gate acceptance from a completed spike or from the spec's approved body label.
The current scheduler treats every non-done status as pending: `blocked` is documentary,
not an automatic dispatch fence. Do not launch this feature unattended while gates remain;
the task executor must stop before code if its release preconditions are unmet.

## Scope

- Stable evidence export without training dependencies (`packages/ai-parrot/src/parrot/memory/dynamics/export.py`).
- Wire export command to deterministic exporter (`packages/ai-parrot/src/parrot/memory/dynamics/cli.py`).
- Stable mappings, round trip and export failure recovery (`packages/ai-parrot/tests/memory/dynamics/test_export.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py` | MODIFY | `list_reviews`; schema v3 additive migration; `apply_review` persists the full record atomically |
| `packages/ai-parrot/src/parrot/memory/episodic/store.py` | MODIFY | `list_reviews`; `review` passes grade, error signature and parameters to the backend |
| `packages/ai-parrot/src/parrot/memory/dynamics/review_log.py` | MODIFY | `ReviewBackend.apply_review` protocol gains the optional record keywords |
| `packages/ai-parrot/src/parrot/memory/dynamics/export.py` | MODIFY | Archive carries the persisted record; legacy rows carry none |
| `packages/ai-parrot/src/parrot/memory/dynamics/cli.py` | MODIFY | Export command exports what the configured store holds |
| `packages/ai-parrot/tests/memory/dynamics/test_export.py` | MODIFY | Real store, record carried, legacy absent, replay independent of the record |
| `packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py` | MODIFY | `list_reviews` tests; previous-schema migration; atomic record persistence |
| `packages/ai-parrot/tests/memory/dynamics/test_store_reviews.py` | MODIFY | Store `list_reviews`; `review` persists the record |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.episodic.store import EpisodicMemoryStore
from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend
from parrot.memory.dynamics.models import Grade, MemoryParameters, MemoryState, ReviewCommand
from parrot.memory.dynamics.fsrs import transition
from pathlib import Path
from typing import Any
import pytest
```

### Existing Signatures and Anchors

- `packages/ai-parrot/src/parrot/memory/dynamics/cli.py` is created by TASK-5678; anchor `def register_memory_commands(group: click.Group) -> None:` is planned, not an existing verified symbol.
- `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py:137` — `class SQLiteEpisodeBackend(AbstractEpisodeBackend):`; `:274` — `async def apply_review(self, command: ReviewCommand) -> ReviewReceipt:` (the only review write path; `self._write_lock`, `self._require_database()`).
- `sqlite.py:54-65` — `reviews` table `(dedupe_key TEXT PRIMARY KEY, outcome_id, outcome_revision, ref_key, payload_digest, payload TEXT, apply_revision, recorded_at)`; `payload` is the JSON of the full validated `ReviewCommand` (`ref.namespace.*` is inside it). The table has NO namespace columns, no grade, no before/after state, no parameter_id.
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:353` — `async def review(self, memory_ids, signal, *, namespace, exposure_id) -> list[ReviewReceipt]`; `:391` — `apply_review = getattr(self._backend, "apply_review", None)` capability pattern (unavailable backend => visible unavailable receipt).
- `packages/ai-parrot/src/parrot/memory/episodic/models.py:285` — `MemoryNamespace.build_filter(self) -> dict[str, Any]` (always tenant_id and agent_id, plus each non-None of user_id/session_id/room_id/crew_id/model_id).
- `packages/ai-parrot/src/parrot/memory/dynamics/models.py:366` — `class ReviewCommand(BaseModel)` (`ref`, `signal`, `exposure_id`, `expected_revision`; `dedupe_key`, `payload_digest`).
- `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py:22` — `_SCHEMA_VERSION = 2`; `:33` — `_SCHEMA = """..."""` (`CREATE TABLE IF NOT EXISTS reviews (...)` has no grade/state columns); `configure()` runs `executescript(_SCHEMA)` then `PRAGMA user_version=_SCHEMA_VERSION` when lower, and raises `ValueError` when the database version is newer.
- `sqlite.py` `apply_review`: inside `BEGIN IMMEDIATE` it reads `SELECT apply_revision FROM memory_state WHERE ref_key = ?`, checks revisions, then `INSERT INTO reviews (dedupe_key, outcome_id, outcome_revision, ref_key, payload_digest, payload, apply_revision, recorded_at)` and upserts `memory_state (ref_key, apply_revision, state, updated_at)` with `state = {"apply_revision", "command"}`, then `COMMIT`.
- `packages/ai-parrot/src/parrot/memory/dynamics/fsrs.py:111` — `def transition(state: MemoryState, grade: Grade, *, reviewed_at: datetime, parameters: MemoryParameters) -> MemoryState` (pure; raises `ValueError` when `state.parameter_id` differs from `parameters.parameter_id`; `reviewed_at` must be aware UTC).
- `packages/ai-parrot/src/parrot/memory/dynamics/models.py:158` — `MemoryState` (frozen; `MemoryState()` is the neutral uninitialized state; `model_dump(mode="json")`); `:128` — `MemoryParameters(algorithm, time_policy, parameter_id, weights=DEFAULT_PARAMETERS, reference, provenance)`; `:119` — `Grade(IntEnum)` AGAIN=1..EASY=4.
- `packages/ai-parrot/src/parrot/memory/dynamics/grade.py:28` — `select_grade(signal, *, attribution, memory_error_signature, verified_recovery) -> Grade | None`.
- `packages/ai-parrot/src/parrot/memory/dynamics/review_log.py:12` — `async def apply_review(self, command: ReviewCommand) -> ReviewReceipt:` (Protocol `ReviewBackend`).
- `packages/ai-parrot/src/parrot/memory/episodic/store.py:470` — `_apply_review_with_current_revision(self, apply_review, command)` calls `apply_review(current_command)` (up to 3 compare-and-swap retries); `store.py` already imports `select_grade` and `.recall`.
- Test fixtures to reuse: `tests/memory/dynamics/test_store_reviews.py` (real `SQLiteEpisodeBackend` + `EpisodicMemoryStore` under `tmp_path`) and `test_sqlite_backend.py`.

### Does NOT Exist

- `SQLiteEpisodeBackend.list_reviews` and `EpisodicMemoryStore.list_reviews` do not exist yet — this task adds them.
- Before this task no grade/state/parameter_id is persisted; rows committed before the migration (or via a direct `apply_review(command)` without a grade) have NO record — never fabricate one, never backfill.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/episodic/store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/dynamics/review_log.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/dynamics/export.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/dynamics/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/dynamics/test_export.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/dynamics/test_store_reviews.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py#SQLiteEpisodeBackend",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py#SQLiteEpisodeBackend.apply_review",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py#SQLiteEpisodeBackend.list_reviews",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.review",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.list_reviews",
    "sym:packages/ai-parrot/src/parrot/memory/dynamics/fsrs.py#transition",
    "sym:packages/ai-parrot/src/parrot/memory/dynamics/grade.py#select_grade"
  ]
}
```

## Implementation Notes

Use async I/O, strict hints, Pydantic v2 and Google docstrings; log through self.logger or
the module logger. Format Python with black (120) and run scoped ruff. Keep test logs under
artifacts/logs. All DB/process fixtures are isolated; no shared DDL or dependency mutation is
authorized. User explicitly confirmed that the new AgentMemoryToolkit remains in core at
parrot.memory.agent_memory; do not move it into parrot_tools.

## Implementation Blueprint

### Steps (in order)

1. Verify release preconditions and dependency contracts — unresolved evidence must not become invented implementation policy.
2. Recheck the exact anchors and imports below after dependencies land — overlapping writers deliberately run in sequence.
3. Apply each per-file block and complete its bounded FILL IN items — preserve public contracts outside this task's scope.
4. Implement the behavioral cases below with real temporary stores where persistence matters — mocks alone cannot prove durability.
5. Run the narrow validation commands and scoped style checks — do not mark missing backend evidence as a passing persistence test.

### `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py` (MODIFY)

Add next to `apply_review` (anchor: `    async def apply_review(self, command: ReviewCommand) -> ReviewReceipt:`, exactly 1 occurrence):

```python
async def list_reviews(self, namespace: MemoryNamespace, *, limit: int | None = None) -> list[dict[str, Any]]:
    """Return committed reviews for one namespace in a deterministic total order."""
```

- Each row is a dict with exactly: `dedupe_key`, `outcome_id`, `outcome_revision`, `ref_key`, `apply_revision`, `recorded_at`, `command` (the stored `payload` parsed from JSON).
- **Scope**: every item of `namespace.build_filter()` is applied in SQL `WHERE` against the committed command's namespace
  (`json_extract(payload, '$.ref.namespace.<field>') = ?`) **before** `ORDER BY` and `LIMIT`. `limit` is applied last;
  `None` means all rows; a non-positive `limit` raises `ValueError`.
- **Order**: `ORDER BY recorded_at ASC, dedupe_key ASC` (total order; `dedupe_key` is unique).
- Use `self._require_database()` like the other methods (closed backend fails visibly). No writes, no schema change.

### `packages/ai-parrot/src/parrot/memory/episodic/store.py` (MODIFY)

Add next to `review` (anchor: `    async def review(`, exactly 1 occurrence):

```python
async def list_reviews(self, namespace: MemoryNamespace, *, limit: int | None = None) -> list[dict[str, Any]]:
    """List committed reviews for one namespace; fails visibly when the backend cannot."""
```

Delegate to `self._backend.list_reviews`. If the backend has no callable `list_reviews`, raise
`RuntimeError("review listing is unavailable: backend has no list_reviews capability")` — never return an empty list.

### Persisted review record — `sqlite.py`, `store.py`, `review_log.py` (Owner Decision 2)

`sqlite.py`:

```python
async def apply_review(
    self,
    command: ReviewCommand,
    *,
    grade: Grade | None = None,
    memory_error_signature: str | None = None,
    parameters: MemoryParameters | None = None,
) -> ReviewReceipt:
```

- `grade` and `parameters` must be supplied together (exactly one => `ValueError` before any write); neither => legacy behavior,
  record columns stay NULL, every existing result/receipt is unchanged.
- With a record: inside the existing `BEGIN IMMEDIATE` transaction, after the duplicate/ignored/stale/CAS checks and before the
  insert, read the current `memory_state` row (`apply_revision`, `state`); `before = MemoryState.model_validate(state["memory_state"])`
  when that key is present, otherwise the neutral `MemoryState()`; `after = fsrs.transition(before, grade, reviewed_at=<the same
  aware-UTC instant written to reviews.recorded_at>, parameters=parameters)`. A `transition` failure (for example a parameter_id
  mismatch) rolls the transaction back and propagates — nothing is committed.
- The review `INSERT` also writes `grade` (int), `before_state` / `after_state` (compact `json.dumps(model_dump(mode="json"), sort_keys=True)`),
  `parameter_id`, and `memory_error_signature` (the argument; at most 2000 characters, longer values truncated) — **same transaction, same
  commit** as the review row and the `memory_state` upsert. The `memory_state.state` JSON gains `"memory_state": <after json>` only for
  rows written with a record. `payload_digest`, dedupe, conflict, stale and ignored semantics are unchanged.
- **Migration (spec D8):** `_SCHEMA_VERSION = 3`. In `configure()`, after `executescript(_SCHEMA)`, add any missing column among
  `grade INTEGER`, `before_state TEXT`, `after_state TEXT`, `parameter_id TEXT`, `memory_error_signature TEXT` with
  `ALTER TABLE reviews ADD COLUMN ...` (nullable, no default, **no backfill**), discovering existing ones via `PRAGMA table_info(reviews)`;
  tolerate a concurrent "duplicate column name" error; then set `user_version` to 3 only when it is lower. Re-opening is a no-op, a
  half-migrated database is completed, a newer-than-supported version still raises. Leave the `CREATE TABLE IF NOT EXISTS reviews` DDL as is.
- `list_reviews` rows gain a `"record"` key **only** when `grade IS NOT NULL`: `{"grade": int, "before": dict, "after": dict,
  "parameter_id": str, "memory_error_signature": str | None}`. Legacy rows (NULL grade) have **no `record` key at all**.

`store.py`: define one module-level neutral review-parameters constant (`MemoryParameters(algorithm="fsrs-6", time_policy="days-v1",
parameter_id="episodic-neutral-v1", provenance="episodic-review")`); `review()` passes `grade=grade`, `memory_error_signature=episode.error_message or
episode.error_type`, `parameters=<constant>` through `_apply_review_with_current_revision` (add `**record` keywords; behavior of the retry loop unchanged).

`review_log.py`: extend the `ReviewBackend.apply_review` Protocol signature with the same three optional keywords.

### `packages/ai-parrot/src/parrot/memory/dynamics/export.py` (MODIFY — rebuild; remove the placeholder-era design)

```python
async def export_reviews(
    *,
    namespace: MemoryNamespace,
    destination: Path,
    store: EpisodicMemoryStore | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Export the committed reviews the configured store holds for ``namespace`` as a replayable archive."""
```

- `store is None` -> `ValueError("export requires the configured episodic store")`. Never write an empty archive for a missing store.
- Read with `await store.list_reviews(namespace)`; a visible store failure propagates unchanged (no archive written).
- `exported_at` = `(clock or utcnow)()` as ISO-8601 UTC — the real time by default, injectable in tests. Do not hard-code a date.
- Archive (JSON, `sort_keys=True`, compact separators): `format`, `exported_at`, `namespace`, `reviews` (a **list**, backend order, one
  record per committed review keyed by `dedupe_key` — two reviews of the same memory version must both appear), and a
  `provenance` object naming the source (`backend`, table `reviews`), the always-present persisted fields (`command`, `apply_revision`,
  `recorded_at`) and the optional `record` fields (`grade`, `before`, `after`, `parameter_id`, `memory_error_signature`) that exist **only** for
  reviews committed with a record. Review records are exported exactly as `list_reviews` returns them: legacy rows carry no `record` key; never
  synthesize one.
- Identical source evidence + identical injected clock => byte-identical archive and identical `content_hash`.
- Return metadata: `export_path`, `record_count` (= `len(reviews)` actually written), `content_hash`, `format_version`.
- Write without blocking the event loop: build bytes, then `await asyncio.to_thread(...)` a helper that writes a unique temp file in the
  destination directory (`tempfile.mkstemp(dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp")`), flushes+fsyncs,
  then `os.replace`s it onto `destination`; on any failure remove the temp file and raise `ExportError` (keep that class). A failed export
  never touches the store (reviews are already committed; nothing is re-applied).
- `retry_export(...)`: either implement a real exponential backoff with an injectable `sleep` parameter, or delete it. A docstring must not claim backoff that is absent.
- No optimizer/fitter import, no new dependency.

### `packages/ai-parrot/src/parrot/memory/dynamics/cli.py` (MODIFY)

`export-reviews --output PATH` must export what the store holds: build `MemoryNamespace` from the configured settings, resolve the
store from the opened toolkit manager (`episodic`), and call `export_reviews(namespace=..., destination=output, store=store)`.
If the configured manager has no episodic store, raise `click.ClickException` (visible). Remove every placeholder comment and the empty-data path.

### Tests

- `tests/memory/dynamics/test_export.py` (rewrite): real `SQLiteEpisodeBackend` + `EpisodicMemoryStore` under `tmp_path`, episodes stored,
  reviews committed through `backend.apply_review` (or `store.review`, which calls it) — no hand-built review lists. Cases:
  1. two reviews of the same memory version (different `outcome_id`) both survive and `record_count == 2`;
  2. determinism: two exports with the same injected clock are byte-identical; default clock writes a real current timestamp;
  3. scope: another namespace's reviews are excluded;
  4. **replay**: parse the archive, re-validate each `command` with `ReviewCommand.model_validate`, apply them into a fresh store holding the
     same episodes -> every receipt `applied` with the same `apply_revision`; re-applying into the source store -> `duplicate` (no double apply); a second export from the fresh store has the same review set;
  5. write failure (`os.replace` patched to raise): `ExportError`, no temp file left behind, store reviews unchanged, a later export succeeds with the same content;
  6. a store whose backend lacks `list_reviews` -> visible `RuntimeError`, no file written;
  7. `store=None` -> `ValueError`;
  8. CLI `export-reviews` via `click.testing.CliRunner` on a real temp store exports a non-empty archive equal to the library export.
- Record/migration tests (real temporary SQLite; `tests/memory/dynamics/test_sqlite_backend.py`): (a) a database created by hand at schema version 2 (old `reviews` DDL, `PRAGMA user_version=2`, one legacy review + memory_state row) opens, migrates to version 3, keeps the legacy row without a `record`, a second open is a no-op, and a database with only some of the new columns is completed; (b) `apply_review(command, grade=..., parameters=..., memory_error_signature=...)` commits the review row, the new columns and `memory_state` together — a forced `transition` failure leaves no review row and no state change; a second review of the same memory has `before == the first review's after`; (c) a call without a grade writes NULL record columns and an unchanged receipt; grade without parameters raises `ValueError`.
- `tests/memory/dynamics/test_sqlite_backend.py`: `list_reviews` applies scope before `limit` (a limit smaller than the other-namespace rows must still return in-scope rows), deterministic order, closed backend fails visibly.
- `tests/memory/dynamics/test_store_reviews.py`: store delegation and visible failure on a backend without the capability; `store.review` persists the record (grade equals `select_grade`'s choice — for example AGAIN for a matching error signature —, `memory_error_signature` equals the episode's error text, `parameter_id == "episodic-neutral-v1"`, `after.status == "reviewed"`).
- `tests/memory/dynamics/test_export.py` additions: the archive carries `record` for rows committed with one; an archive exported from a previous-schema database contains the legacy rows with no `record`; replaying an archive that carries records (applying only each `command`) yields exactly one `applied` per review, then `duplicate`, and works identically when the `record` keys are stripped from the archive.

### FILL IN checklist

- [ ] `sqlite.py` `list_reviews` and `store.py` `list_reviews` implemented per the bullets above.
- [ ] `export.py` rebuilt on real store data; `cli.py` exports what the store holds; no placeholder comments or empty-data path remain.
- [ ] All three test files extended with the cases above (real temporary SQLite store, reviews through `apply_review`, archive replay).
- [ ] Replace every stub with working behavior; completed implementation files contain no placeholders.

## Acceptance Criteria

- [ ] Owner (1): `SQLiteEpisodeBackend.list_reviews` and `EpisodicMemoryStore.list_reviews` exist; every filter is applied before any limit; order is deterministic; a backend without the capability fails visibly.
- [ ] Owner (2): `export_reviews(*, namespace, destination, ...)` exports what the configured store holds; the CLI command exports a non-empty archive from a store that has reviews; no placeholder or empty-data path.
- [ ] Owner (3): two reviews of the same memory version both survive; `exported_at` is real time (injectable); retry backs off or makes no such claim; no blocking write in an async function; no shared `.tmp` name.
- [ ] Owner (4): tests use a real temporary SQLite store with reviews applied through `apply_review` and cover replay of the exported archive.
- [ ] Owner Decision 2: the full review record (grade, before/after state, parameter_id, error signature) is persisted in the same transaction as the review row; the schema migration is additive, idempotent and NULL-only; legacy rows are exported without a `record`; `list_reviews` and the archive carry the record; replay is unaffected; tested including a database created at the previous schema version.
- [ ] AC18/U4: identical source evidence + clock produces stable mappings/order and a byte-identical archive. AC12/AC18: a failed export neither loses nor re-applies reviews.
- [ ] AC18: no fit.py, fitting CLI or optimizer/dependency changes are introduced.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_export.py packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py packages/ai-parrot/tests/memory/dynamics/test_store_reviews.py -q`

## Test Specification

- `two_reviews_same_version_survive`, `deterministic_export_and_real_clock`, `scope_excludes_other_namespace`, `archive_replay_no_double_apply`, `write_failure_leaves_store_and_dir_clean`, `backend_without_listing_fails_visibly`, `missing_store_raises`, `cli_exports_store_contents` (see Tests above).
- Backend/store: `list_reviews_scope_before_limit`, `list_reviews_deterministic_order`, `list_reviews_closed_backend_fails`, `store_list_reviews_delegates_and_fails_visibly`.

Use deterministic clocks, runtime-derived identities and isolated temporary stores. Preserve
CancelledError. Use subprocesses for crash/multiprocess checks, never shared production data.

## Agent Instructions

1. Use the FEAT-892 worktree provisioned by sdd-start; never implement on dev.
2. Check every Depends-on task is done and each Release Preconditions item is met; blocked is not runnable.
3. Read the full spec and reverify this task's Codebase Contract; refresh stale evidence before editing.
4. Implement only declared files plus normal SDD state; preserve concurrent/unrelated changes.
5. Run validation, commit scoped implementation, and finalize with `parrot sdd task finalize`
   using real TaskCompletionEvidence and the exact implementation HEAD. Let finalization own
   the completion note and active-to-completed move; do not fabricate completion evidence.

## Completion Note

- Task: TASK-5679
- Feature: agent-memory-mixin
- Implementation SHA: 8fd85474ae86056209f1e557a8634400235eabcc
- Closed at (UTC): 2026-11-16T02:23:04+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| AC12 | met: replay yields one application per review, failed export loses/re-applies nothing |
| AC18 | met end to end: archive carries command, apply_revision, recorded_at and, for reviews committed with a record, grade, before/after MemoryState, parameter_id and memory_error_signature; legacy rows export without a record (never fabricated); deterministic; replay does not depend on the record |
| issues | issue:cef9e1a8c0e6 resolved by this delivery; issue:ca240b187f61 resolved by fe3561614b |
| note | recall.py keeps its own inline neutral-parameter literal (parameter_id episodic-neutral-v1); store.py defines the review parameters once - drift risk flagged, recall.py was out of scope |
| scope | Reopened twice by owner decision: (1) review read API + real export (merge 19d6dae59a, fix fe3561614b), (2) persisted ReviewRecord + additive v3 migration (this delivery). |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 (second extension) · Duration: 526s · Tokens: n/a |
