---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [wiki, ledger, outbox, schema-plane, bugfix]
---

# Feature Specification: wikitoolkit CLI fixes — redundant ledger closes, outbox integrator cleanup, DDL diff range

**Feature ID**: FEAT-771
**Discovered-from**: `issue:28686ebe9af7`, `issue:81330c0acb9f`, `issue:7f50ee6aaa74`
**Date**: 2026-10-30
**Author**: Jesus Lara
**Status**: approved
**Origin**: `/sdd-fix issue:28686ebe9af7` (fix group `fixgroup:eb1b87cb5071`, SDD lane, max severity major).
Parents FEAT-758 (ledger outbox) and FEAT-770 are both closed, so this is a new feature.

---

## 1. Motivation & Business Requirements

### Problem Statement

Three open ledger issues hit the same four files of the wiki toolkit.

**A. A redundant close blocks every session's ledger delivery** (`issue:28686ebe9af7`, bug, major).
On 2026-10-30, `/sdd-done FEAT-770` could not deliver ledger events. A sealed outbox batch from
`feat-FEAT-769` held two `issue.closed` events for issues that `origin/dev` already had closed for the
same fix, with different close evidence (`reason` / `resolved_by`):

- `a72a1c30ede2` closed `issue:6756c929a450` ("fixed by PR #1863", no `resolved_by`); dev already had
  `005449ab55a6` from `/sdd-fix` (`resolved_by: commit:d6016f6…`).
- `ebf8d5b6c739` closed `issue:60de633baac2` (`resolved_by: task:TASK-4893`); dev already had
  `b0bff8c3d835` from a parallel `/sdd-done FEAT-746` (same `resolved_by`, different reason text).

`find_transition_conflicts` reports both as `conflicting-close`. Three things then compound:

1. `LedgerIntegrator._attempt` returns `conflict` for the whole batch, so none of its events land.
2. `ledger outbox integrate` (cli.py) stops at the first non-zero report, so every batch prepared after
   it, from any session, also stays pending. FEAT-770's batch was stuck behind it.
3. There is no supported way out. The CLI has only `prepare` / `integrate` / `status`. Editing the
   sealed batch is not enough, because `LedgerOutbox._prepare_sync` re-seals every shareable
   local-journal event that is absent from dev and not in a pending batch. It has no checkpoint, so the
   dropped events came straight back in a new batch. The only fix was to edit the local journal by hand.

**B. The integrator leaks its temp worktree on unexpected errors** (`issue:81330c0acb9f`, bug, major).
`_attempt` creates `.claude/worktrees/_ledger-outbox-<uuid>` and handles only `StrictLedgerReadError` and
`WikiStoreBusy`. Any other exception (an `OSError`, a `LedgerService` failure) leaves the worktree on disk
and propagates a traceback. `ledger_outbox_integrate` does not catch it, so the documented exit code 2
is never produced. `build_scratch_snapshot` never removes `outbox/scratch/<uuid>/`. The issue also lists
four smaller defects in the same code:
- `ledger_outbox_prepare` and `ledger_outbox_status` end in a bare `except Exception` that turns
  programmer errors into "remote unavailable".
- `integrate --batch-id <id>` of a batch that already has a receipt returns `unknown-batch` / exit 3
  instead of `already_delivered` / exit 0.
- `read_strict_events` tells an identity mismatch apart by matching `"does not match"` in `str(exc)`
  rather than by type.

**C. The post-commit DDL ingest diffs a stale `ORIG_HEAD`** (`issue:7f50ee6aaa74`, bug, minor).
`git_hook_block()` is shared by the post-commit and post-merge hooks, so `schema ingest-ddl --changed`
also runs after every plain commit. `_changed_ddl_paths` always diffs `ORIG_HEAD HEAD`. `ORIG_HEAD`
is set only by merge/reset/rebase/pull, so after a plain commit:
- the commit's own DDL change is missed;
- an old merge's DDL files are re-scanned on every commit;
- with no `ORIG_HEAD` at all, `git diff` fails, and the hook's `|| true` hides the error.

### Goals

- G1. An `issue.closed` whose issue is already terminal on dev is set aside as redundant. It is never a
  conflict and never appended to dev. It is recorded in the batch receipt, so `prepare` never re-seals it.
- G2. A conflicting batch does not stop `integrate` from delivering later batches.
- G3. No `_attempt` failure path leaks the temp worktree or the scratch directory. Unexpected
  integration errors become a `pending` report (exit 2).
- G4. `prepare` / `status` no longer swallow programmer errors. `integrate --batch-id` of a receipted
  batch reports `already_delivered`. The identity-mismatch check is typed.
- G5. `ingest-ddl --changed` diffs the right range for the operation that just ran, and takes an
  explicit `--range`.

### Non-Goals (explicitly out of scope)

- Changing `find_transition_conflicts`. Its `conflicting-close` reason is FEAT-758 policy, pinned by
  `test_transition_conflicts`. The integrator just stops passing it redundant closes (§2).
- An `outbox discard` command. With G1, a redundant close resolves itself, and the remaining conflict
  reasons (`competing-claim`, `unclaim-terminal`, `missing-predecessor`) still need human review.
- Changing the installed hook text. `_install_managed_git_hook` returns "already installed" when the
  marker block exists, so a changed hook would never reach existing clones. The fix lives in the
  `ingest-ddl` command, which every existing hook already calls.
- Log rotation, `ledger show` formatting (`issue:a7b9702c9b67`), remote-client hardening (`issue:af6eda2da356`).

---

## 2. Architectural Design

### Overview

**Module 1 — redundant closes (A).** A new pure function in `integration.py`,
`drop_redundant_closes(remote, plan) -> MergePlan`, replays the remote log with `_apply` and walks
`plan.new_events` in order. An `issue.closed` whose subject is already `TERMINAL` (closed or superseded)
at that point is moved to `MergePlan.redundant_closes` (event ids) and not applied. Every other event is
kept and applied, so a second close of the same issue inside the batch is also redundant.

`_attempt` calls it right after `merge_batch` and before `find_transition_conflicts`, so redundant closes
never reach the conflict check:
- Only the kept lines are appended to dev.
- Post-push verification and `verified_digest` cover the sealed events minus the redundant ones.
- The receipt records `skipped_event_ids`.
- If every event is redundant or already on dev, the report is `already_delivered` with no commit,
  as today.
- Each skipped close is logged at INFO with its subject, and the report carries the ids.

"First close on dev wins" is deliberate. Closing an issue twice has no state effect. Appending the
second close would make the reducer overwrite dev's recorded resolution with a later, often thinner one.
The superseded close's text stays in the local journal.

`LedgerOutbox._prepare_sync` and `_status_sync` exclude every event id listed in any receipt's
`skipped_event_ids` (new `_skipped_ids_sync()`, reading `receipts/*.json`). Receipts written before this
change have no such field and load with an empty list.

In `ledger_outbox_integrate`, a `conflict` or `unsupported` report no longer breaks the loop. Later
batches are still attempted. A batch that depends on an event in the conflicting batch fails on its own
with `missing-predecessor`, so ordering stays safe. `pending` still breaks the loop, since it means
I/O, lock or push trouble that later batches would hit too. The exit code is the highest code among
the reports (pending 2 < conflict 3 < unsupported 4).

**Module 2 — integrator cleanup (B).**
- `_attempt`: after `tmp` is created, an `except Exception` on the existing outer `try` (alongside the
  current `except StrictLedgerReadError`) logs the exception, runs `_remove_if_clean(tmp)` best-effort,
  and returns `pending` / `error_code="unexpected-error"` with `recovery_path` set only when the tree was
  kept. `integrate()` wraps each `_attempt` call the same way for failures before `tmp` exists.
  `CancelledError` is a `BaseException` and still propagates.
- `build_scratch_snapshot`: `try/finally` removes `scratch_dir` (`shutil.rmtree(..., ignore_errors=True)`
  via `asyncio.to_thread`). `LedgerIndex` opens a connection per transaction, so nothing is held open.
- `ledger_outbox_prepare`: the trailing `except Exception` becomes `except IntegrationError`.
  `ledger_outbox_status`: both `except Exception` blocks become `except (IntegrationError, OSError)`.
- `ledger_outbox_integrate --batch-id`: when the id is not pending but `outbox.receipt_for(id)` exists,
  emit an `already_delivered` report and exit 0. An unknown id keeps `unknown-batch` / exit 3.
- `outbox.py`: `class EventIdentityError(StrictLedgerReadError)`. `verify_event_identity` raises it,
  and `read_strict_events` checks `isinstance(exc, EventIdentityError)` instead of string matching.

**Module 3 — DDL diff range (C).**
- New `_git_changed_files(root, diff_range) -> list[str]` in cli.py.
- An explicit `diff_range` runs `git diff --name-only <diff_range>`.
- Otherwise the range is inferred from the last HEAD reflog subject (`git reflog -1 --format=%gs HEAD`):
  - `merge…`, `pull…` or `commit (merge)…` → `git diff --name-only ORIG_HEAD HEAD` (what the post-merge
    hook needs);
  - anything else, including a plain commit or an empty reflog → `git diff-tree --no-commit-id --name-only
    -r --root HEAD`, the last commit's own changes. `--root` also covers a repository's first commit.
- `_changed_ddl_paths(root, origin, diff_range=None)` filters that list as before.
- `schema ingest-ddl` gains `--range TEXT` (requires `--changed`). Git failures still raise
  `ClickException`.

### Component Diagram

```
outbox integrate (cli) ──► LedgerIntegrator.integrate ──► _attempt
   continue past conflict        catch-all → pending          merge_batch → drop_redundant_closes → find_transition_conflicts
   exit = max(code)                                          append kept lines → verify (minus redundant) → acknowledge(skipped_event_ids)
                                                                                                             │
outbox prepare/status ──► LedgerOutbox._prepare_sync/_status_sync ◄── receipts/*.json skipped_event_ids ◄────┘

post-commit/post-merge hook ──► schema ingest-ddl --changed [--range] ──► _changed_ddl_paths ──► _git_changed_files
```

### Integration Points

| File | Change |
|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/integration.py` | `MergePlan.redundant_closes`, `drop_redundant_closes`, `_attempt`/`integrate` wiring + catch-all, scratch cleanup |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/outbox.py` | receipt `skipped_event_ids`, report `skipped`, `acknowledge(..., skipped_event_ids=)`, `_skipped_ids_sync`, `EventIdentityError` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | integrate loop + exit code, receipted `--batch-id`, narrowed excepts, `_git_changed_files`, `--range` |
| `docs/sdd/ledger-outbox.md`, `docs/wiki/schema-plane.md` | behaviour notes |

### Data Models

```python
class MergePlan(BaseModel):                     # integration.py — add:
    redundant_closes: list[str] = Field(default_factory=list)

class LedgerReceipt(BaseModel):                 # outbox.py — add (schema_version stays 1):
    skipped_event_ids: list[str] = Field(default_factory=list)

class LedgerDeliveryReport(BaseModel):          # outbox.py — add:
    skipped: list[str] = Field(default_factory=list)

class EventIdentityError(StrictLedgerReadError): ...   # outbox.py — new
```

### New Public Interfaces

```python
def drop_redundant_closes(remote: Sequence[LedgerEvent], plan: MergePlan) -> MergePlan: ...
async def LedgerOutbox.acknowledge(self, batch, *, remote_head: str, verified_digest: str,
                                   skipped_event_ids: Sequence[str] = ()) -> None: ...
def _git_changed_files(root: Path, diff_range: str | None) -> list[str]: ...          # cli.py
def _changed_ddl_paths(root: Path, origin: str, diff_range: str | None = None) -> list[Path]: ...
# CLI: wikitoolkit schema ingest-ddl --changed --range <A..B>
```

---

## 3. Module Breakdown

### Module 1: Redundant closes never block delivery (TASK-4895) — `issue:28686ebe9af7`
`integration.py` (`MergePlan`, `drop_redundant_closes`, `_attempt` wiring), `outbox.py` (receipt / report
fields, `acknowledge`, `_skipped_ids_sync`, prepare / status exclusion), `cli.py` (integrate loop, exit code,
skipped ids in text output), `docs/sdd/ledger-outbox.md`, tests.

### Module 2: Integrator cleanup and CLI error mapping (TASK-4896) — `issue:81330c0acb9f`
Depends on TASK-4895 (same functions). `integration.py` (`_attempt` / `integrate` catch-all,
`build_scratch_snapshot` finally), `outbox.py` (`EventIdentityError`), `cli.py` (narrowed excepts,
receipted `--batch-id`), tests.

### Module 3: DDL changed-file range (TASK-4897) — `issue:7f50ee6aaa74`
Depends on TASK-4896 (same file, serial in one worktree). `cli.py` (`_git_changed_files`,
`_changed_ddl_paths`, `--range`), `docs/wiki/schema-plane.md`, tests (`test_cli_schema.py`, including the
existing lambda monkeypatch at line 96).

---

## 4. Test Specification

### Unit Tests

| Test | File | Asserts |
|---|---|---|
| `test_drop_redundant_closes_moves_close_of_closed_issue` | `test_ledger_outbox_integration.py` | remote open+close, new close (different evidence) → in `redundant_closes`, not in `new_events`/`new_lines` |
| `test_drop_redundant_closes_keeps_close_of_open_issue_and_second_in_batch_close` | same | first close kept, a second close of the same subject in the batch is redundant |
| `test_drop_redundant_closes_keeps_non_close_events` | same | claims, opens, non-issue events kept in order |
| `test_redundant_close_delivers_and_records_skipped` | same (`two_clones`) | batch = new open + redundant close → `delivered`; dev has the open only; receipt `skipped_event_ids == [close id]`; `report.skipped` set |
| `test_all_redundant_is_already_delivered_without_commit` | same | only a redundant close → `already_delivered`, `origin/dev` unchanged, receipt written |
| `test_prepare_never_reseals_skipped_event` | `test_ledger_outbox.py` | receipt with `skipped_event_ids` → `prepare` returns `None`; `status` counts 0 unsealed |
| `test_old_receipt_without_skipped_field_loads` | same | receipt JSON lacking the field → `receipt_for` ok, empty list |
| `test_integrate_continues_past_conflict` | `test_cli_ledger_outbox.py` | 2 batches, first `conflict` → second still integrated; exit 3 |
| `test_integrate_stops_on_pending` | same | first `pending` → second not attempted; exit 2 |
| `test_attempt_unexpected_error_removes_tmp_and_is_pending` | `test_ledger_outbox_integration.py` | patched `read_logical_log` raising `OSError` → `pending`/`unexpected-error`; no `_ledger-outbox-*` dir left |
| `test_scratch_snapshot_removes_scratch_dir` | same | after `build_scratch_snapshot`, `scratch_dir` does not exist |
| `test_integrate_receipted_batch_id_is_already_delivered` | `test_cli_ledger_outbox.py` | receipt exists, batch not pending → exit 0, `already_delivered` |
| `test_prepare_programmer_error_propagates` | same | `remote_event_ids` raising `RuntimeError` → not mapped to exit 2 (exception surfaces) |
| `test_identity_mismatch_raises_event_identity_error` | `test_ledger_outbox.py` | tampered line → `EventIdentityError` (a `StrictLedgerReadError`) |
| `test_git_changed_files_plain_commit_uses_last_commit` | `schema/test_cli_schema.py` | stale `ORIG_HEAD` from an earlier merge; plain commit of `db/b.sql` → only `db/b.sql` |
| `test_git_changed_files_no_orig_head` | same | fresh repo, one commit → that commit's files, no error |
| `test_git_changed_files_after_merge_uses_orig_head` | same | `git merge` of a branch adding `db/c.sql` → `db/c.sql` |
| `test_git_changed_files_explicit_range` | same | `--range HEAD~2..HEAD` → union of both commits |

### Validation Contract

runners:
- kind: pytest
  tests:
  - packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox.py
  - packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_integration.py
  - packages/ai-parrot/tests/knowledge/wiki/test_cli_ledger_outbox.py
  - packages/ai-parrot/tests/knowledge/wiki/schema/test_cli_schema.py
  - packages/ai-parrot/tests/knowledge/wiki/test_schema_hook_assets.py
  markers: none

### Test Data / Fixtures

Reuse `_ev`, `_opened`, `_line`, `_run_git`, `two_clones` and `_batch_for` from
`test_ledger_outbox_integration.py`, and `_batch` / `_local_mode` from `test_cli_ledger_outbox.py`.
DDL tests build a throwaway git repo in `tmp_path` with `subprocess.run(["git", ...])`
(`user.email` / `user.name` set locally). No network.

---

## 5. Acceptance Criteria

- [ ] A sealed batch closing an issue that dev already closed (any evidence) delivers its other events;
  the close is not appended to dev and is listed in the receipt's `skipped_event_ids`.
- [ ] After such a delivery, `outbox prepare` does not re-seal the skipped close and `outbox status` counts 0 unsealed.
- [ ] A conflicting batch does not prevent `integrate` from delivering a later independent batch; exit code is the max.
- [ ] `find_transition_conflicts` is unchanged (`test_transition_conflicts` still passes).
- [ ] An unexpected exception during `_attempt` leaves no `_ledger-outbox-*` worktree when the tree is clean and yields exit 2.
- [ ] `build_scratch_snapshot` leaves no scratch directory.
- [ ] `integrate --batch-id <receipted id>` exits 0 with `already_delivered`.
- [ ] `ingest-ddl --changed` after a plain commit sees that commit's DDL files, never a stale `ORIG_HEAD` range, and does not fail without `ORIG_HEAD`.
- [ ] The Validation Contract passes; `ruff check` is clean on changed files.

---

## 6. Codebase Contract

### Verified Imports

```python
from parrot.knowledge.wiki.ledger.integration import (LedgerIntegrator, MergePlan, merge_batch,
    find_transition_conflicts, build_scratch_snapshot, read_logical_log, IntegrationError, TERMINAL, _apply)
from parrot.knowledge.wiki.ledger.outbox import (LedgerOutbox, LedgerBatch, LedgerReceipt,
    LedgerDeliveryReport, LedgerDeliveryConflict, StrictLedgerReadError, OutboxLockedError,
    verify_event_identity, read_strict_events)
from parrot.knowledge.wiki.ledger.events import LedgerEvent, canonical_json_dumps
from parrot.knowledge.wiki.cli import ledger, schema   # click groups; cli.py:129-135 import outbox/integration
```

### Existing Signatures (origin/dev 404a66b44)

```python
# integration.py
TERMINAL = frozenset({"closed", "superseded"})                                   # :33
class MergePlan(BaseModel): new_lines: list[bytes]; new_events: list[LedgerEvent]; duplicates: int   # :36
def merge_batch(remote, batch) -> MergePlan                                      # :68
def find_transition_conflicts(remote, new) -> list[LedgerDeliveryConflict]       # :84
def _apply(state, event) -> None                                                 # :119 (claim on terminal is a no-op)
async def build_scratch_snapshot(merged, *, scratch_dir: Path, dest: Path) -> bool   # :144
class IntegrationError(RuntimeError)                                             # :185
class LedgerIntegrator:
    async def integrate(self, batch, *, max_attempts=3) -> LedgerDeliveryReport  # :242
    async def _remove_if_clean(self, path) -> str | None                         # :289
    async def _attempt(self, batch, attempt) -> LedgerDeliveryReport | None      # :297; tmp at :326,
        # plan = merge_batch(...) :344; conflicts :358; expected :509; verified_digest :524;
        # acknowledge :527; outer except StrictLedgerReadError :543
# outbox.py
class LedgerDeliveryReport(BaseModel)                                            # :51
class LedgerReceipt(BaseModel)  # schema_version Literal[1]                      # :66
class StrictLedgerReadError(ValueError)                                          # :79
def verify_event_identity(event) -> None                                         # :98
def read_strict_events(path, *, end_offset=None) -> StrictRead                   # :105; string match :138
class LedgerOutbox:
    def _prepare_sync(self, repo_root, source_ref, source_head, known_ids)       # :274; pending_ids :294
    async def acknowledge(self, batch, *, remote_head, verified_digest) -> None  # :358
    def _status_sync(self, known_ids) -> dict                                    # :404
# cli.py
_OUTBOX_EXIT = {"delivered": 0, "already_delivered": 0, "pending": 2, "conflict": 3, "unsupported": 4}  # :3681
def _emit_delivery_reports(reports, json_output, repo_root) -> None             # :3708
def ledger_outbox_prepare(...)   # :3733; bare except Exception :3771
def ledger_outbox_status(...)    # :3791; except Exception :3801, :3811
def ledger_outbox_integrate(...) # :3845; unknown-batch :3870; break :3882
def _changed_ddl_paths(root: Path, origin: str) -> list[Path]                   # :4086 (ORIG_HEAD diff :4096)
def schema_ingest_ddl(paths, origin, dialect, changed, as_json, quiet)          # :4185
```

### Does NOT Exist

- `drop_redundant_closes`, `MergePlan.redundant_closes`, `LedgerReceipt.skipped_event_ids`,
  `LedgerDeliveryReport.skipped`, `LedgerOutbox._skipped_ids_sync`, `EventIdentityError`,
  `_git_changed_files`, `ingest-ddl --range` — created by this spec.
- `LedgerService.close()` / `LedgerIndex.close()` — no such methods; connections are per-transaction.
- `wikitoolkit ledger outbox discard` — not created (Non-Goal).
