# TASK-4859: LedgerIntegrator — optimistic delivery to origin/dev with verified receipts

**Feature**: FEAT-758 — Durable Ledger Outbox and Independent Integration into dev
**Spec**: `sdd/specs/ledger-outbox-integration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4858
**Assigned-to**: unassigned

---

## Context

Spec §2 "Delivery transaction" steps 2 and 7–10, and §3 Module 2's `LedgerIntegrator` skeleton. Using the
Git-free building blocks from TASK-4858 and the outbox from TASK-4857, this task delivers one sealed batch to
`origin/dev` from an **owned detached temporary worktree** (never the active primary or feature checkout),
retries on non-fast-forward against a fresh base (max three attempts, never force-push, never cherry-pick),
verifies the remote content and only then writes the receipt. It also adds `check_feature_diff()` (legacy PR
contamination report) and `remote_event_ids()` (the baseline TASK-4860's `prepare` passes to
`LedgerOutbox.prepare(known_ids=...)`).

---

## Scope

- Append to `integration.py` (below TASK-4858's functions): `GitResult`, `_git()`, `IntegrationError`,
  and `class LedgerIntegrator` with `__init__`, `integrate`, `check_feature_diff`, `remote_event_ids`.
- `integrate(batch, max_attempts=3)` per attempt:
  1. `git fetch <remote> dev`; resolve `refs/remotes/<remote>/dev` object id (`base_sha`).
  2. `git worktree add --detach <tmp> <base_sha>` where `<tmp>` = `<primary>/.claude/worktrees/_ledger-outbox-<uuid4>`
     (`<primary>` = parent of `git rev-parse --path-format=absolute --git-common-dir`).
  3. `read_logical_log(tmp)`; `outbox.batch_events(batch)`; `merge_batch`; if every batch id is already present
     with equal content → go to verification without committing (status `already_delivered`).
  4. `find_transition_conflicts` → non-empty ⇒ return `status="conflict"` (no commit, no push, no receipt).
  5. Append `new_lines` to `tmp/sdd/ledger/events.jsonl` (create parents; add a separator newline if the
     file does not end with one); `build_scratch_snapshot(all logical raw lines + new_lines,
     scratch_dir=<outbox root>/scratch/<uuid4>, dest=tmp/sdd/ledger/issues.jsonl)`.
  6. `git add -- sdd/ledger/events.jsonl sdd/ledger/issues.jsonl`; `git commit -m "sdd: ledger delivery <batch_id>"`.
  7. Inspect: `git diff-tree --no-commit-id --name-only -r HEAD` ⊆ the two allowlisted paths;
     `git rev-parse HEAD^` == `base_sha`; for each path `git rev-parse HEAD:<path>` ==
     `git hash-object <tmp>/<path>`; `git status --porcelain` empty. Any failure ⇒ `status="pending"`,
     `error_code="hook-mutated-commit"`, retain `tmp`, no push.
  8. `git push <remote> HEAD:refs/heads/dev` (no `--force`, no `--force-with-lease`). Rejection whose stderr
     contains `non-fast-forward`, `fetch first` or `[rejected]` ⇒ remove the clean owned worktree, next attempt.
     Any other failure (auth/network/protection/timeout) ⇒ `status="pending"`, `error_code="push-failed"`.
  9. Verify: fetch, `git -C <tmp> checkout --detach <remote>/dev`, `read_logical_log(tmp)` must contain every
     batch id with content equal to the batch's; only then `outbox.acknowledge(batch, remote_head=...,
     verified_digest=...)`. Uncertain push outcome (timeout) is resolved by this same verification on the next
     call.
- Exhausting `max_attempts` ⇒ `status="pending"`, `error_code="retry-exhausted"`.
- `batch.remote != self.remote` or `batch.branch != "dev"` ⇒ `status="unsupported"`, no Git writes.
- Per-repository advisory lock `fcntl.flock` on `<outbox root>/integrate-<remote>-dev.lock` held for the whole
  call; never hold any source-journal lock.
- Remove owned temp worktrees only when clean (`git worktree remove <tmp>`, never `--force`); a dirty or
  interrupted one is retained and reported in `recovery_path`.
- Append Git-backed tests to `test_ledger_outbox_integration.py` using a local bare origin + two clones.

**NOT in scope**: CLI commands and exit-code mapping (TASK-4860); hooks (TASK-4861); rotation (never during
delivery); MCP registration (spec §2: local-only CLI).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/integration.py` | MODIFY | Add `LedgerIntegrator` + Git helpers |
| `packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_integration.py` | MODIFY | Add bare-origin delivery tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already imported at the top of integration.py by TASK-4858:
from parrot.knowledge.wiki.ledger.outbox import LedgerDeliveryConflict, StrictLedgerReadError, read_strict_events
# add to that import line (all created by TASK-4857):
from parrot.knowledge.wiki.ledger.outbox import LedgerBatch, LedgerDeliveryReport, LedgerOutbox
from parrot.knowledge.wiki.ledger.shared_log import ARCHIVE_REL_DIR, SHARED_LOG_REL_PATH
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py:22-23
#   SHARED_LOG_REL_PATH = Path("sdd/ledger/events.jsonl"); ARCHIVE_REL_DIR = Path("sdd/ledger/archive")
```
Standard library: `asyncio` (`create_subprocess_exec`, `wait_for`), `fcntl`, `hashlib`, `uuid`.

### Existing Signatures to Use
```python
# integration.py (TASK-4858)
def read_logical_log(repo_root: Path) -> list[tuple[bytes, LedgerEvent]]
def merge_batch(remote, batch) -> MergePlan          # MergePlan.new_lines / new_events / duplicates
def find_transition_conflicts(remote, new) -> list[LedgerDeliveryConflict]
async def build_scratch_snapshot(merged: Sequence[bytes], *, scratch_dir: Path, dest: Path) -> bool

# outbox.py (TASK-4857)
class LedgerOutbox:
    root: Path                     # <ledger_dir>/outbox
    async def batch_events(self, batch: LedgerBatch) -> StrictRead   # .raw_lines / .events
    async def acknowledge(self, batch: LedgerBatch, *, remote_head: str, verified_digest: str) -> None
    async def status(self, known_ids: set[str] | None = None) -> dict[str, int | bool]
class LedgerDeliveryReport(BaseModel): status, batch_id, attempts, remote_head, commit_sha, added,
    remaining, conflicts, error_code, recovery_path
```
Existing precedent for the throwaway-worktree location: `.claude/commands/sdd-done.md:490` uses
`$WORKTREES_DIR/_ledger-snapshot-$$` under the primary checkout because the worktree sandbox only lets agents
write the primary's `.claude/worktrees/` (`.claude/rules/worktree-management.md` §4).

### Does NOT Exist
- ~~`parrot.knowledge.wiki.git` / a shared async Git helper~~ — none in the ledger package; define `_git()`
  locally. Do NOT import `subprocess.run` (blocking) — use `asyncio.create_subprocess_exec`.
- ~~`LedgerService.export_shared_log` in the delivery path~~ — the integrator appends batch lines itself; the
  old exporter reads the live local log, not the sealed batch.
- ~~`git push --force*`, `git cherry-pick`, `git reset --hard`~~ — forbidden by spec §2 step 9.
- ~~`rotate_events` during delivery~~ — spec §2 step 7.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/integration.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_integration.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py#SHARED_LOG_REL_PATH",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py#ARCHIVE_REL_DIR"
  ]
}
```

---

## Implementation Notes

- `verified_digest` = SHA-256 over `f"{event_id}\0{canonical}\n"` for the batch's events in batch order.
- `remaining` = `(await outbox.status(known_ids=<verified remote ids>))["pending_events"] +
  ["unsealed_events"]` minus this batch once acknowledged — i.e. events still awaiting a later pass.
- Every `_git()` call has a timeout (default 120 s); a timeout returns `GitResult(returncode=-1, ...)`.
- Run `git` with `env` augmented by `GIT_TERMINAL_PROMPT=0` so auth never blocks.
- Tests: create `origin.git` (`git init --bare`), clone A and B, configure `user.name/email` per clone, set the
  bare repo's default branch to `dev` and push an initial commit; build `LedgerOutbox` over
  `tmp_path/<clone>/.parrot/ledger`. Never touch the project's real remote.

---

## Implementation Blueprint

### Steps (in order)
1. Extend the outbox import line and add the Git helper block — *why*: every step shells out through one
   bounded, non-blocking helper.
2. Add `LedgerIntegrator` — *why*: spec §3 M2 skeleton (signatures fixed).
3. Append the Git tests — *why*: spec §4 integration rows (two-clone race, lost receipt, hook mutation).

### `integration.py` (MODIFY) — Git helper
```python
# occurrences: 1 (verified: grep -c '^async def build_scratch_snapshot' integration.py — created by TASK-4858)
# AFTER — append below the end of `build_scratch_snapshot` (end of file)
class GitResult(BaseModel):
    returncode: int
    stdout: str
    stderr: str


async def _git(*args: str, cwd: Path, timeout: float = 120.0) -> GitResult:
    """Run one git command without blocking the loop; a timeout yields returncode -1."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(cwd), *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return GitResult(returncode=-1, stdout="", stderr=f"git {' '.join(args)} timed out")
    return GitResult(returncode=proc.returncode or 0, stdout=out.decode(), stderr=err.decode())


ALLOWLIST: tuple[str, ...] = (str(SHARED_LOG_REL_PATH), "sdd/ledger/issues.jsonl")
_NON_FF_MARKERS: tuple[str, ...] = ("non-fast-forward", "fetch first", "[rejected]")
```
(Add `import fcntl, hashlib, os, uuid` to the module imports.)

### `integration.py` (MODIFY) — `LedgerIntegrator`
```python
class LedgerIntegrator:
    """Deliver immutable batches to origin/dev without touching active checkouts."""

    def __init__(self, repo_root: Path, outbox: LedgerOutbox, *, remote: str = "origin") -> None:
        """Bind repository identity and local outbox; destination is origin/dev."""
        self.repo_root = Path(repo_root).resolve()
        self.outbox = outbox
        self.remote = remote
        self.branch = "dev"
        self.logger = logging.getLogger(__name__)

    async def _primary_root(self) -> Path:
        res = await _git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=self.repo_root)
        # FILL IN: returncode != 0 -> IntegrationError("not-a-git-repo"); return Path(stdout.strip()).parent
        raise NotImplementedError

    async def remote_event_ids(self) -> set[str]:
        """Fetch origin/dev and return every event id in its archives + current log (read-only)."""
        # FILL IN: fetch; `git ls-tree -r --name-only <remote>/dev -- sdd/ledger`; for archive paths
        #   (ARCHIVE_REL_DIR/events-*.jsonl) then SHARED_LOG_REL_PATH: `git show <remote>/dev:<path>`, parse each
        #   non-blank line's "event_id" — no checkout, no writes.
        raise NotImplementedError

    async def integrate(self, batch: LedgerBatch, *, max_attempts: int = 3) -> LedgerDeliveryReport:
        """Recompute after rejected pushes; acknowledge only matching remote event content."""
        if batch.remote != self.remote or batch.branch != self.branch:
            return LedgerDeliveryReport(status="unsupported", batch_id=batch.batch_id, attempts=0, remote_head=None,
                                        commit_sha=None, added=0, remaining=len(batch.event_ids),
                                        error_code="destination-mismatch")
        # FILL IN: take fcntl.flock on outbox.root/f"integrate-{remote}-dev.lock" (LOCK_EX|LOCK_NB; busy ->
        #   pending/"integration-locked"); loop attempts 1..max_attempts calling self._attempt(); on
        #   "retry" outcome clean up and continue; return the first terminal report; after the loop return
        #   pending/"retry-exhausted". Always release the lock in finally — bounded by spec §2 step 9.
        raise NotImplementedError

    async def _attempt(self, batch: LedgerBatch, attempt: int) -> LedgerDeliveryReport | None:
        """One fresh-base attempt; ``None`` means non-fast-forward (retry)."""
        # FILL IN: steps 1-9 of this task's Scope, in order. Keep tmp only when dirty/hook-mutated/interrupted
        #   (report path in recovery_path); otherwise `git worktree remove <tmp>` (no --force). StrictLedger
        #   ReadError -> status="conflict", error_code="invalid-content". WikiStoreBusy from the scratch replay
        #   -> pending/"index-busy". Log attempt, base_sha, added count at info level.
        raise NotImplementedError

    async def check_feature_diff(self, feature_ref: str) -> list[str]:
        """List canonical ledger paths changed since merge-base with origin/dev; never edit them."""
        # FILL IN: merge-base <remote>/dev feature_ref; `git diff --name-only <base> <feature_ref> --
        #   sdd/ledger/events.jsonl sdd/ledger/issues.jsonl`; return sorted list (empty = clean).
        raise NotImplementedError
```
**Why this shape**: spec fixes `__init__(repo_root, outbox)`, `integrate(batch, *, max_attempts=3)` and
`check_feature_diff(feature_ref)`; `remote` is a keyword with the spec's default so tests can use a bare
origin under another name. Splitting `_attempt` keeps every attempt on a brand-new worktree at a freshly
fetched base — never reuse a rejected commit.

### `test_ledger_outbox_integration.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^async def test_scratch_replay_remote_closed_wins_and_legacy_rows_survive' — TASK-4858)
# AFTER — append at end of file
import subprocess  # test-only: fixtures build bare repos synchronously

from parrot.knowledge.wiki.ledger.integration import LedgerIntegrator
from parrot.knowledge.wiki.ledger.outbox import LedgerOutbox


@pytest.fixture
def two_clones(tmp_path: Path) -> tuple[Path, Path, Path]:
    # FILL IN: bare origin with branch dev + initial commit; clones a/ and b/ with user.name/email configured
    raise NotImplementedError


async def test_delivers_batch_and_writes_receipt(two_clones) -> None: ...  # FILL IN
async def test_two_clone_race_loser_retries_both_present_once(two_clones) -> None: ...  # FILL IN: barrier via a pre-push hook in clone a
async def test_lost_receipt_retry_is_already_delivered_no_duplicate_commit(two_clones) -> None: ...  # FILL IN
async def test_conflict_blocks_push_and_receipt(two_clones) -> None: ...  # FILL IN
async def test_hook_mutating_commit_blocks_push(two_clones) -> None: ...  # FILL IN: pre-commit hook adds a file
async def test_push_failure_is_pending_and_retains_batch(two_clones) -> None: ...  # FILL IN: point remote at a missing path
async def test_active_checkouts_untouched(two_clones) -> None: ...  # FILL IN: `git status --porcelain` + HEAD of clone unchanged
async def test_check_feature_diff_reports_contamination(two_clones) -> None: ...  # FILL IN
```

### FILL IN checklist
- [ ] `_primary_root`, `remote_event_ids` — read-only Git; bounded by spec §2 step 2
- [ ] `integrate` — lock, attempt loop, exhaustion; bounded by spec §2 step 9 (≤3 attempts, no force)
- [ ] `_attempt` — steps 1-9; receipt only after remote verification (AC "No receipt is written before remote verification")
- [ ] `check_feature_diff` — read-only; bounded by spec §3 M6 ("never edit them")
- [ ] Fixture + 8 tests (replace each `...` with a real body)

---

## Acceptance Criteria

- [ ] Two independent clones racing: loser retries on a fresh base; both events occur exactly once remotely
- [ ] Push succeeded but receipt lost: retry verifies remote content, no duplicate commit/event
- [ ] A hook that mutates the integration commit blocks the push
- [ ] Rejected three times / network failure → typed pending result, batch retained, no receipt
- [ ] Active primary/feature tracked files and Git indexes are unchanged by the integrator
- [ ] No `--force`, `cherry-pick`, `reset --hard` or `subprocess.run` in `integration.py`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_integration.py -q`

---

## Test Specification

See the test blueprint above. Save the pytest log under `artifacts/logs/` per CLAUDE.md.

---

## Agent Instructions

1. Work in the feature worktree; TASK-4858 must be `done`.
2. Read spec §2 "Delivery transaction" (all ten steps) and §3 Module 2.
3. Verify the Codebase Contract, including TASK-4857/4858 names, before coding.
4. Implement, run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`, commit only the two files.
5. Close with `scripts/sdd/close_task.sh TASK-4859 ledger-outbox-integration verified`.

---

## Completion Note

*(Agent fills this in when done)*
