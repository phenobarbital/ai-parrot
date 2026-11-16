# TASK-5679: Deterministic review export and replayable archives

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: in-progress (reopened — owner decision, scope extended)
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
| `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py` | MODIFY | Add `SQLiteEpisodeBackend.list_reviews` (scoped before limit, deterministic order) |
| `packages/ai-parrot/src/parrot/memory/episodic/store.py` | MODIFY | Add `EpisodicMemoryStore.list_reviews`; backend without it fails visibly |
| `packages/ai-parrot/src/parrot/memory/dynamics/export.py` | MODIFY | Rebuild on real store data: `export_reviews(*, namespace, destination, store=None, clock=None)` |
| `packages/ai-parrot/src/parrot/memory/dynamics/cli.py` | MODIFY | Export command exports what the configured store holds |
| `packages/ai-parrot/tests/memory/dynamics/test_export.py` | MODIFY | Real temporary SQLite store, reviews via apply_review, replay of the archive |
| `packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py` | MODIFY | Backend `list_reviews` scope/limit/order/closed-backend tests |
| `packages/ai-parrot/tests/memory/dynamics/test_store_reviews.py` | MODIFY | Store `list_reviews` delegation and visible failure tests |

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
from parrot.memory.dynamics.models import ReviewCommand
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
- Test fixtures to reuse: `tests/memory/dynamics/test_store_reviews.py` (real `SQLiteEpisodeBackend` + `EpisodicMemoryStore` under `tmp_path`) and `test_sqlite_backend.py`.

### Does NOT Exist

- `SQLiteEpisodeBackend.list_reviews` and `EpisodicMemoryStore.list_reviews` do not exist yet — this task adds them.
- No persisted per-review grade, before/after `MemoryState` or `parameter_id` exists anywhere in the SQLite backend; never fabricate them.
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
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.review"
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
  `provenance` object naming the source (`backend`, table `reviews`) and listing exactly the persisted fields
  (`command`, `apply_revision`, `recorded_at`). **Do not** add grades, before/after state or `parameter_id`: they are not persisted.
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
- `tests/memory/dynamics/test_sqlite_backend.py`: `list_reviews` applies scope before `limit` (a limit smaller than the other-namespace rows must still return in-scope rows), deterministic order, closed backend fails visibly.
- `tests/memory/dynamics/test_store_reviews.py`: store delegation and visible failure on a backend without the capability.

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
- Status: **done-with-issues** (closed by hand; `parrot sdd task finalize` only records `done`)
- Closed at (UTC): 2026-11-16T01:52:45+00:00
- Delivery: rework merged as 19d6dae59a (seat gpt-5.6-terra, codex, attempt 1, 617s) + review fix fe3561614b (real-clock assertion tightened). Replaces the first, rejected delivery (438c492521).
- Validation: merge-tier 99 passed on the delivery; 5 passed on the final HEAD (test_export.py). Artifacts: 3b568f295cde5b177593bd900e5d6d2e0a5c6ecd164cd3d27fe1a3f0a37904a9, 3ab7745f39ad97f7f52e7dba80d2c89e902c2adf7207d0035e9bd54ae597664b. Review: e3769a4fc5a74baa1542f657553e5d21e07d89b0fa4927b394b93f1af7d4e41d. Feedback: coder-feedback:24a316f0bf2e51f75f222f43 (terra, weak assertion), coder-feedback:c8a070acc23bf6bd00971522 (minimax, first attempt placeholder).

### Owner decision — what was done

1. `SQLiteEpisodeBackend.list_reviews(namespace, *, limit=None)`: every `namespace.build_filter()` item applied in SQL against the committed command's namespace before `ORDER BY recorded_at, dedupe_key` and before `LIMIT`; `limit<=0` raises; closed backend fails visibly. `EpisodicMemoryStore.list_reviews` delegates and raises `RuntimeError` when the backend has no such capability (never an empty list).
2. `export_reviews(*, namespace, destination, store=None, clock=None)` exports what the store holds; `store=None` raises `ValueError`. CLI `export-reviews` resolves the store from the opened toolkit manager and fails visibly (`ClickException`) when episodic memory is not enabled. No placeholder or empty-data path remains.
3. Smaller issues: reviews are a list keyed by `dedupe_key` (two reviews of one memory version both survive, `record_count` matches); `exported_at` is the real UTC time via an injectable clock; `retry_export` was deleted (a re-run is idempotent; no unbacked backoff claim); the write runs in `asyncio.to_thread` using a unique `mkstemp` file in the destination directory, fsynced, `os.replace`d and removed on failure.
4. Tests (real temporary SQLite store, reviews committed through `apply_review`): two reviews of one version survive; byte-identical export with an injected clock and a real-time bracket for the default clock; other namespaces excluded; archive replay into a fresh store gives `applied` with the same `apply_revision`, re-applying into the source gives `duplicate` (no double apply) and a re-export has the same review set; write failure leaves no temp file and the store unchanged; missing/incapable store fails with no file written; CLI exports a non-empty archive. Backend tests cover scope-before-limit, deterministic order and closed-backend failure; store tests cover delegation and visible failure.

### Interpretation recorded for the owner

The blueprint signature has no store parameter, but a store cannot be derived from `namespace` and `destination`. `namespace` and `destination` remain the required keyword-only parameters; `store` and `clock` were added as optional keyword-only parameters and the CLI supplies the configured store. Scope uses `MemoryNamespace.build_filter()` semantics (unset dimensions are unconstrained), not literal equality on every dimension.

### AC12 / AC18 — what is met and what is still missing

- **AC12 met:** replay of the exported archive produces one application per review (verified by the duplicate result), and a failed export neither loses nor re-applies reviews.
- **AC18 met:** no optimizer/fitting code or dependency; the export is deterministic (stable scope, order and bytes for the same evidence and clock).
- **AC18 NOT fully met — "usable by a later fitting feature":** the SQLite review log persists only the validated `ReviewCommand` plus `apply_revision` and `recorded_at`. The FSRS grade, the before/after `MemoryState` and the `parameter_id` are never stored, so the archive cannot carry them (and must not invent them), and the memory's error signature that `select_grade` compares is not in the archive either. A fitter cannot reconstruct grades from the archive alone. Needs an owner decision: persist grade + before/after state + parameter_id at `apply_review` time (ReviewCommand/apply_review change plus migration), or retain an episode snapshot for reconstruction. Tracked as issue:cef9e1a8c0e6. The previous gap (no read API) is closed (issue:ca240b187f61, resolved by fe3561614b; unpushed, lands with the FEAT-892 PR).

### Also found while verifying (not part of this task)

TASK-5678 registers the memory command group with an eager module-level import in `knowledge/wiki/cli.py`, so every `wikitoolkit` start imports `parrot.memory`; in the worker sandbox that crashes `wikitoolkit` (navconfig log directory). Tracked as issue:76c09075409e.
