---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling, dev-loop, docs]
tags: [ledger, outbox, concurrency, worktrees, git-hooks, sdd]
---

# Feature Specification: Durable Ledger Outbox and Independent Integration into dev

**Feature ID**: FEAT-758
**Date**: 2026-10-27
**Author**: Jesus Lara (with Codex)
**Status**: approved
**Target version**: Next release; version unassigned

## 1. Motivation & Business Requirements

### Problem Statement

SDD agents discover deferred work while implementing unrelated features. These findings belong in the shared
work ledger but their transport currently modifies the feature PR: the managed pre-commit hook exports and
stages `sdd/ledger/events.jsonl` in every checkout. Meanwhile sdd-done exports the snapshot and rotates the log
in a separate base-branch worktree. Parallel features therefore edit shared generated artifacts despite the
existing final integration step. `merge=union` does not reconcile snapshots or semantic state transitions.

Accepted conversation intent: keep code and task artifacts in the feature PR; retain discovered events in a
durable local pending list; let sdd-done deliver them independently to dev. Use a detached temporary checkout
of origin/dev instead of modifying the user's active dev checkout. Reconcile events on each rejected push,
rather than cherry-picking textual ledger diffs.

### Goals

- G1. Normal worker/coder commits and feature PR diffs contain no changes to canonical ledger data.
- G2. A finding acknowledged locally survives process exit and feature-worktree removal before publication.
- G3. sdd-done publishes ledger-only commits to origin/dev independently of the feature PR destination.
- G4. Concurrent publishers preserve all distinct events, retry without force-push, and never publish stale snapshots.
- G5. Delivery is idempotent and confirmed against remote content, including a crash after push but before receipt.
- G6. Keep immediate local visibility, blockers, and claims through the existing ledger service.
- G7. Upgrade installed hooks, cover all workflow hosts, and expose failed/pending delivery explicitly.

### Non-Goals (explicitly out of scope)

- Distributed exclusive claims or a new global reducer/clock protocol; semantic issue similarity matching.
- Replacing SQLite, changing event IDs, introducing a queue server, or modifying provider clients.
- Automatic history rewriting of already-published feature branches.
- Automatic remote backup of unshipped local events. Local durability does not survive loss of the source machine.
- Rootless remote-MCP transport: it needs a separate export/ack API. This feature detects that configuration and
  reports unsupported source instead of silently reading an unrelated local ledger.
- FEAT/TASK ID reservations (`sdd/ledger/id-ledger.json` if present) and task-index concurrency are separate concerns.

## 2. Architectural Design

### Overview

Use the existing shared local event journal as the durable source of pending delivery, not a second mandatory
producer write. `LedgerService.from_root()` already resolves the primary checkout; its local log survives linked
worktree removal. Producers continue calling existing service/MCP operations and immediately update the local view.
Preparation seals a finite prefix of complete local records into an immutable batch outside tracked source files.
An event written after that prefix remains eligible for the next batch. No producer requires a Git operation.

The outbox lives at `<resolved-ledger-dir>/outbox/`, beside `LedgerService.log.path`, never inside the feature
checkout. It contains `pending/<batch-id>/{manifest.json,events.jsonl}`, `receipts/<batch-id>.json`, and a preparation
lock. Batch publication uses write/fsync/atomic rename plus parent-directory fsync. A failed seal has no successful
receipt and is recoverable from the unchanged source log. Receipt files are also atomically replaced. No automatic
deletion of batches or source-log truncation is introduced in this feature.

Preparation is repository-wide, not filtered by feature: all shareable local events absent from the observed
origin/dev logical log are candidates. This deliberately preserves predecessor events and includes abandoned
worktree findings and coder feedback. `source_ref`/`source_head` identify the delivery initiator, not ownership of
every event; per-event attribution remains `actor`, `discovered_from`, and existing payload fields. Existing
`is_shareable()` exclusions still keep coder suspensions local. Overlapping batches are safe by event identity.

### Delivery transaction

1. Seal/reuse pending batches before any feature cleanup. Record the source log's complete-line byte boundary,
   SHA-256 of captured bytes, ordered event IDs, source HEAD/ref, and destination `origin/dev`.
2. Fetch destination dev, resolve its exact object ID, and create an owned detached temporary worktree there.
   Never switch, reset, stage, or commit in the active feature or primary checkout.
3. Strictly parse archives plus current log in the existing `shared_log_files()` order. Deduplicate by `event_id`;
   validate identity against content. Equal IDs with unequal canonical content, malformed complete lines,
   unsupported schemas, or missing issue-open predecessors fail closed without publishing or acknowledging.
4. Append missing batch events in captured source order. Preserve the remote prefix order; do not sort by wall clock,
   event ID, or branch name. Exact duplicates are transport duplicates; similar issues are not auto-collapsed.
5. Build an isolated scratch LedgerService with `from_dir()`, replay the merged logical log, await strict index sync,
   and export the snapshot from THAT service. Never export the source machine's existing SQLite view. Carry forward
   remote snapshot rows unknown to the replayed log using existing `reconcile=True` semantics for legacy snapshots.
   Busy sync is a delivery failure, not permission to publish a partial view. Never rebuild the live shared index.
6. Compare issue transitions with the state before each new event. A competing claim, conflicting close evidence,
   or unclaim against a terminal issue blocks that batch with structured conflict evidence.
   Do not silently drop the event or choose a winner by timestamp. Identical repeated effects may be accepted;
   they remain separate events when their IDs differ. Immutable batches are never edited to resolve conflicts:
   after review, reconcile the destination through existing explicit ledger operations and retry, or retain the
   batch as blocked. This feature does not add a discard/force-ack operation.
7. Commit only `sdd/ledger/events.jsonl` and `sdd/ledger/issues.jsonl`. This new delivery path does not rotate logs;
   archives are read and preserved. Existing rotation remains an explicit maintenance command outside normal
   sdd-done delivery. This supersedes FEAT-694's automatic sdd-done rotation requirement.
8. Inspect the actual commit tree and staged state after hooks run: expected canonical bytes, no unrelated changes,
   and a parent matching the fetched destination. A hook that introduces extra changes blocks publication.
9. Push normally to `refs/heads/dev`. On non-fast-forward, discard only clean owned temporary checkouts, fetch,
   and recalculate against a fresh base (maximum three attempts). Auth/network/protection failures remain pending;
   they are not treated as merge races. Never force-push and never cherry-pick the rejected ledger commit.
10. Fetch/verify remote logical content contains the batch IDs with matching content; write a local receipt only
    after that verification. If an earlier attempt already published all IDs, verify and acknowledge without a
    duplicate commit. Receipts are optimization/audit data, never the sole proof for remote completeness.

An uncertain push outcome is resolved by remote verification on retry. Events arriving during delivery are not
acknowledged by the earlier receipt. Report remaining events and whether the remote observation is fresh.
Known archive/current duplicate IDs are normalized in replay; do not rewrite archives solely to deduplicate them.

### Coordination and workflow boundaries

`claim`/`unclaim` continue acting on the shared local ledger immediately; they do not wait for sdd-done. Their
cross-machine publication is asynchronous as before, now through this explicit delivery path. This feature does
not promise globally exclusive claims or converge divergent live indexes automatically. Conflict diagnostics
must prevent sdd-done from claiming full success when coordination requires review.

sdd-done runs preparation/integration after its final local ledger mutations and before cleanup. Feature and
hotfix flows both deliver to dev, regardless of the code PR base; never push ledger data to main. If a later
post-merge step records a closure, run another delivery pass before cleanup. Existing review, blockers, merge,
and main-branch approval gates are unchanged. Publishing a finding is not proof that its referenced code merged.

On pending/conflict/unsupported delivery, retain the batch, report its location and retry command, and do not
declare closeout complete or remove the feature worktree. A code PR already pushed may remain open. Do not roll
it back. A later sdd-done or explicit outbox integration can resume without the originating worktree.

### Component Diagram

```text
worker / coder / CLI / MCP
          |
          v
shared local journal + immediate local index
          |
          v
immutable outbox batch (untracked, outside feature checkout)
          |
          v
sdd-done integrator --> fresh origin/dev checkout --> canonical log + scratch snapshot
          ^                         |                            |
          |                         +-- rejected push: retry ----+
          +-- receipt after remote verification <--- successful push

feature checkout --> code + task artifacts --> feature PR (no canonical ledger diff)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `LedgerService.from_root/from_dir` | reuse | Source discovery and isolated canonical replay; no producer API change |
| `LedgerLog`, `LedgerEvent` | reuse | Original identities and durable journal; no source-log rewrite |
| `shared_log.is_shareable/shared_log_files` | reuse | Filtering and historical logical-log layout |
| `cli.ledger` | extend | Local outbox commands and stale-hook export guard |
| Managed ledger hooks | modify | Pre-commit stops exporting/staging; import hooks remain |
| sdd-done workflow twins | replace snapshot step | Invoke tested integrator rather than reproducing shell retry logic |
| Worker/coder guidance | clarify | Ledger operations use services; tracked canonical data stays out of delivery commits |

### Data Models

New Pydantic v2 models in `ledger/outbox.py`; existing `LedgerEvent` remains unchanged.

```python
class LedgerBatch(BaseModel):
    schema_version: Literal[1] = 1
    batch_id: str
    source_ref: str
    source_head: str
    source_end_offset: int
    source_sha256: str
    events_sha256: str
    event_ids: list[str]
    remote: str = "origin"
    branch: Literal["dev"] = "dev"

class LedgerDeliveryConflict(BaseModel):
    event_id: str
    subject: str
    reason: str

class LedgerDeliveryReport(BaseModel):
    status: Literal["delivered", "already_delivered", "pending", "conflict", "unsupported"]
    batch_id: str
    attempts: int
    remote_head: str | None
    commit_sha: str | None
    added: int
    remaining: int
    conflicts: list[LedgerDeliveryConflict]
    error_code: str | None
    recovery_path: str | None
```

Conflict policy: a claim on an issue claimed by a different owner conflicts; a claim by the same owner is an
idempotent effect. Closing an already terminal issue with different close evidence, or unclaiming a terminal
issue, conflicts. A mutation of an unknown issue fails missing-predecessor validation. Other events follow the
existing reducer, including repeated no-op effects. This does not detect every cross-machine stale intent:
events currently carry no expected revision or expected previous owner. In particular it cannot prove that an
unclaim of a currently claimed issue observed that same owner. Revision-aware coordination remains out of scope.

`batch_id` is UUID4; the manifest hashes the exact sealed JSONL bytes. A receipt contains the validated batch
manifest hash, observed remote HEAD and destination, and the verified event-set digest. IDs/path components are
validated; reject symlinks escaping the owned outbox and manifests selecting another repository or destination.

### New Public Interfaces

```text
wikitoolkit ledger outbox prepare --repo-root PATH [--ledger-dir PATH] [--json]
wikitoolkit ledger outbox status --repo-root PATH [--ledger-dir PATH] [--json]
wikitoolkit ledger outbox integrate --repo-root PATH [--ledger-dir PATH] [--batch-id UUID] [--json]
```

No `--batch-id` integrates pending batches in preparation order and stops at the first failure. Preparing before
integration captures unsealed journal events; integrate alone resumes existing batches. `--ledger-dir` explicitly
selects a local source; without it, a configured remote-only ledger returns `unsupported` with no writes. All
commands are local-only CLI operations and do not add MCP registry entries. Status never acknowledges or pushes.
Exit codes: 0 delivered/no-op/prepared, 2 pending I/O/lock/retry exhaustion, 3 invalid content/semantic conflict,
4 unsupported source/destination/legacy PR contamination. JSON uses structured reports; workflows gate on codes.

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1 Outbox storage | yes | Immutable sealed prefix, model schema, fsync, flock, stable IDs | — |
| M2 Canonical integrator | yes | Fresh base per retry, strict replay, snapshot isolation, remote receipts | — |
| M3 CLI boundary | yes | Three commands, exit codes, local-only source checks | — |
| M4 Hooks | yes | Upgrade marker block, no pre-commit export, retain imports | — |
| M5 Workflow and producer guidance | yes | Three done hosts, pending blocks cleanup, dev destination | — |
| M6 Adversarial acceptance and migration docs | yes | Two-clone race/crash fixtures and recovery matrix | — |

### Module 1: Durable outbox preparation and receipts

- **Paths**: create `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/outbox.py` and
  `packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox.py`.
- **Responsibility**: schema, strict event reader, bounded complete-prefix capture, atomic batch/receipt writes,
  pending status and preparation lock. Only one preparer per ledger directory; producers do not acquire this lock.
- **Depends on**: existing event/log/filter contracts (§6).
- **Interface Skeleton** (new; imports verified in §6):

```python
class LedgerOutbox:
    """Own durable pending batches beside one resolved local event journal."""
    def __init__(self, ledger_dir: Path) -> None:
        """Bind an existing local ledger directory without selecting another checkout."""
    async def prepare(self, *, repo_root: Path, source_ref: str, source_head: str) -> LedgerBatch | None:
        """Seal complete shareable events absent from the fetched dev baseline; return None if empty."""
    async def pending(self) -> list[LedgerBatch]:
        """Return validated unacknowledged batches in preparation order."""
    async def acknowledge(self, batch: LedgerBatch, *, remote_head: str, verified_digest: str) -> None:
        """Persist a receipt only for the exact remotely verified batch."""
```

Truncated final records are left pending and reported, never marked delivered; malformed complete records fail
closed. Reads have a captured byte bound so a busy producer cannot make preparation run indefinitely. Source
events remain authoritative if preparation crashes. Existing append implementation is not redesigned here.

### Module 2: Optimistic canonical integration

- **Paths**: create `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/integration.py` and
  `packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_integration.py`.
- **Responsibility**: execute §2 transaction, strict semantic validation, isolated replay, commit allowlist,
  bounded Git subprocesses, three attempts, content verification, receipts and owned-worktree cleanup.
- **Depends on**: M1 models/storage; existing service/index/export contracts.
- **Interface Skeleton**:

```python
class LedgerIntegrator:
    """Deliver immutable batches to origin/dev without touching active checkouts."""
    def __init__(self, repo_root: Path, outbox: LedgerOutbox) -> None:
        """Bind repository identity and local outbox; destination is origin/dev."""
    async def integrate(self, batch: LedgerBatch, *, max_attempts: int = 3) -> LedgerDeliveryReport:
        """Recompute after rejected pushes; acknowledge only matching remote event content."""
    async def check_feature_diff(self, feature_ref: str) -> list[str]:
        """List canonical ledger paths changed since merge-base with origin/dev; never edit them."""
```

Local publication lock is per repository/destination and advisory; OS release on process death avoids stale
PID locks. Never hold a source journal lock across Git/network work. Two independent clones synchronize via
normal fast-forward push rejection, not the local lock. Temporary worktrees are UUID-named and owned by the
integrator; interrupted or unexpectedly dirty ones are retained and reported without force removal.

### Module 3: CLI operations and stale-hook protection

- **Paths**: modify `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` and
  `tests/knowledge/wiki/test_cli_ledger_shared_log.py`; create
  `packages/ai-parrot/tests/knowledge/wiki/test_cli_ledger_outbox.py`.
- **Depends on**: M1 and M2.
- **Interface Skeleton** (existing attachment verified: `cli.py:3652`):

```python
def ledger_outbox_prepare(repo_root: str, ledger_dir: str | None, json_output: bool) -> None:
    """Resolve local source, capture a batch, and report its durable location."""
def ledger_outbox_status(repo_root: str, ledger_dir: str | None, json_output: bool) -> None:
    """Show sealed/unsealed pending delivery without side effects beyond read-only Git queries."""
def ledger_outbox_integrate(repo_root: str, ledger_dir: str | None, batch_id: str | None, json_output: bool) -> None:
    """Deliver pending batches and map typed outcomes to documented exit codes."""
def ledger_export_log(repo_root: str | None, stage: bool, quiet: bool) -> None:
    """Preserve explicit non-staging export; reject obsolete --stage with an outbox migration message."""
```

Reject `export-log --stage` before any write so an old installed hook invoking the upgraded CLI cannot keep
contaminating commits. Non-staging manual export remains available for diagnostics, outside normal SDD flow.
The integrator uses Python APIs and explicit staging, never this old export command.

### Module 4: Managed hook migration

- **Paths**: modify `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py`,
  `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py`, and
  `tests/knowledge/wiki/test_installer_ledger_hooks.py`.
- **Depends on**: no code dependency on M1–M3; hook pre-commit block becomes an explanatory no-op.
- **Interface Skeleton** (existing signatures preserved):

```python
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py:218
def ledger_hook_block(root: Path, hook_name: str) -> str:
    """Generate no-export pre-commit block and existing import-only post hooks."""
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py:973
def _install_ledger_hooks(root: Path) -> list[str]:
    """Replace outdated managed ledger blocks, preserving unrelated hook bytes and executable mode."""
```

Scope marker replacement to ledger blocks. `_install_managed_git_hook` currently treats marker presence as
already installed; migrate before that shortcut without changing unrelated wiki-hook installation semantics.
Idempotent reinstall reports unchanged only when contents match. Preserve custom shell hooks and refuse to
append shell code to non-shell scripts; provide actionable migration diagnostics.

### Module 5: SDD workflow and producer contracts

- **Paths**: modify `.claude/commands/sdd-done.md`, `.agents/skills/sdd-done/SKILL.md`,
  `.agent/workflows/sdd-done.md`, `.claude/agents/sdd-worker.md`, `.codex/agents/sdd-worker.toml`,
  `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md`, and
  `tests/sdd/test_ledger_workflow_twins.py`.
- **Depends on**: M3 command contract; M4 installed-hook behavior.
- **Interface Skeleton** (workflow contract; no Python API added):

```text
before feature publication: check canonical diff; report legacy contamination without dropping it
after final ledger mutations: outbox prepare --repo-root <feature>
then: outbox integrate --repo-root <feature>
exit 0: continue ordinary closeout; report delivery receipt and any later pending events
exit 2/3/4: retain worktree/batch; report pending/conflict/unsupported and exact retry command
```

The three hosts must express identical outcomes. Findings use ledger service/MCP calls with task/review
attribution; never append tracked JSONL directly. A coder without a ledger tool returns findings to its worker
for registration. Local task/feature SDD state remains in its own worktree. Existing fidelity protections stay.

### Module 6: Recovery, migration and end-to-end acceptance

- **Paths**: create `docs/sdd/ledger-outbox.md` and
  `packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_acceptance.py`.
- **Depends on**: M1–M5 for runnable acceptance.
- **Interface Skeleton** (documented operational procedures, not new runtime methods):

```text
migrate installed hooks -> seal legacy local events -> deliver -> verify remote content
legacy feature ledger diff -> retain backup/import missing events -> deliver -> reviewed scoped cleanup
retry after crash -> integrate same batch -> remote verification -> idempotent receipt
source machine unavailable -> pending data requires recovery from its journal/outbox backup
```

Do not automatically strip old feature commits. Detect contamination against the feature merge base and report
the exact paths. Document an explicit reviewed recovery, preserving all events before restoring canonical paths
to their merge-base contents and committing the cleanup. Never restore an entire `sdd/ledger/` directory: the
ID allocator and unrelated files are outside scope. Existing canonical archives remain readable during migration.

## 4. Test Specification

### Unit Tests

| Test case | Module | Required assertion |
|---|---|---|
| Complete-prefix sealing | M1 | Concurrent later append remains pending; malformed complete record fails |
| Crash during seal/receipt | M1 | Source retained; no partial batch accepted; no false receipt |
| Identity collision | M1/M2 | Equal ID/different body rejected before commit |
| Scratch replay | M2 | Local stale issue cannot override remote closed issue; legacy snapshot-only rows preserved |
| Semantic conflicts | M2 | Conflicting claim/close/unclaim reports event and subject; no push/ack |
| CLI codes and remote-only mode | M3 | Stable JSON/codes; no silent local fallback or write on unsupported mode |
| Installed hook upgrade | M4 | Old export block replaced; custom bytes preserved; second install unchanged |
| Legacy staged export | M3/M4 | Old --stage invocation produces no canonical writes or index changes |
| Host parity | M5 | Same destination, pending outcome, hotfix handling and cleanup gate |

### Integration Tests

| Scenario | Required evidence |
|---|---|
| Two linked worktrees discover issues | Shared journal preserves both; feature diffs/indexes contain no canonical data |
| Two independent clones race pushes | Barrier forces same baseline; loser retries; both events occur once remotely |
| Push succeeded, response/receipt lost | Retry observes remote content; no duplicate commit/event |
| New event after seal | First receipt covers only captured IDs; later prepare delivers new event |
| Rejected three times / network failure | Typed pending result, retained batch/worktree, no false closeout success |
| Foreign event never seen locally | Remote event/state survives snapshot regeneration |
| Hook mutates integration commit | Actual commit tree allowlist/hash check blocks push |
| Feature worktree deleted externally | Shared journal and sealed batch remain recoverable from primary checkout |
| Hotfix based on main | Ledger commit goes only to dev; main unchanged; post-merge closure gets another pass |
| Mixed archives/current log | Strict dedup and legacy replay compatibility; no archive rotation during delivery |

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox.py
- packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_integration.py
- packages/ai-parrot/tests/knowledge/wiki/test_cli_ledger_outbox.py
- packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_acceptance.py
- tests/knowledge/wiki/test_cli_ledger_shared_log.py
- tests/knowledge/wiki/test_installer_ledger_hooks.py
- tests/sdd/test_ledger_workflow_twins.py
- packages/ai-parrot/tests/knowledge/wiki/test_ledger_export_snapshot.py
- packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py
markers: none

> The first four operands are CREATE deliverables, not existing tests. Freeze concrete node IDs during sdd-task.
> Existing root-level tests are edited in place; new tests live with their distribution. No LLM/network fixture.

### Test Data / Fixtures

Local bare origin plus two independent clones and linked feature worktrees; Git identity configured in each
fixture. Independent ledger directories, barriers around pre-push, mocked transient network failures, deterministic
event timestamps, live competing subprocesses, and fsync/rename failure injection. Capture test logs under
`artifacts/logs/`; do not exercise the actual project remote. This is a pytest Git integration suite, not a
parrot-e2e target, so no E2E policy metadata is declared.

## 5. Acceptance Criteria

- [ ] Workers/coders record findings without writing/staging canonical ledger files in feature PRs.
- [ ] Acknowledged findings remain in the shared local journal across process and linked-worktree removal.
- [ ] Sealed batches are immutable, bounded, validated, and distinguish delivered from still-pending events.
- [ ] Independent sdd-done publishers integrate into origin/dev using at most three fresh-base attempts.
- [ ] Snapshot state comes from remote plus batch replay; unrelated remote and legacy snapshot-only issues survive.
- [ ] Duplicate transport is idempotent; conflicting identity/content and incompatible state transitions fail closed.
- [ ] No receipt is written before remote verification, including uncertain push outcomes and replayed retries.
- [ ] Active primary/feature tracked files and Git indexes are unchanged by the integrator.
- [ ] Installed ledger hook blocks migrate; old --stage commands cannot reintroduce tracked events.
- [ ] All three done hosts handle hotfixes, late closure events and pending delivery consistently.
- [ ] Pending delivery prevents successful closeout/cleanup; no destructive retry or force-push exists.
- [ ] Existing contaminated branches receive a recovery report without automated event/history loss.
- [ ] No new dependency, producer API change, or live shared-index rebuild is introduced.
- [ ] Validation contract passes, including two-clone races and crash recovery; recovery documentation is complete.

## 6. Codebase Contract

Verified against base commit `472b0a2fba5dffd33b2880eda163a02025581bd1`.
Imports below are verified by source definitions and existing consumers, not an environment import smoke test.

### Verified Imports

```python
from parrot.knowledge.wiki.ledger.events import LedgerEvent, canonical_json_dumps, compute_event_id
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py:83,88,103
from parrot.knowledge.wiki.ledger.log import LedgerLog
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py:10
from parrot.knowledge.wiki.ledger.service import LedgerService
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:149
from parrot.knowledge.wiki.ledger.shared_log import is_shareable, shared_log_files
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py:73,105
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
class LedgerService:
    @classmethod
    def from_root(cls, root: Path | None = None) -> "LedgerService":  # :167
        """Resolve the shared primary ledger."""
    @classmethod
    def from_dir(cls, ledger_dir: Path, *, sqlite_policy: SQLitePragmaPolicy | None = None) -> "LedgerService":  # :197
        """Open an explicit isolated ledger directory."""
    async def open_issue(  # :243
        self, title: str, body: str, kind: IssueKind = "bug", severity: str = "minor",
        discovered_from: str = "", about: list[str] | None = None, actor: str = "agent:sdd",
    ) -> str:
        """Append a durable issue event before best-effort index sync."""
    async def export_snapshot(self, dest: Path, *, reconcile: bool = True) -> bool:  # :532
        """Export state, retaining destination rows unknown to this service."""
    async def export_shared_log(self, repo_root: Path | None = None) -> "SharedLogExportReport":  # :577
        """Export local shareable events to a checkout."""
    async def import_shared_log(self, repo_root: Path | None = None, *, force: bool = False) -> "SharedLogImportReport":  # :590
        """Import shared events and report claim conflicts."""
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py:263
async def sync(self, conn: "aiosqlite.Connection | None" = None) -> int:
    """Incrementally synchronize the materialized index."""
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py:21
def append(self, event: LedgerEvent) -> tuple[str, int]:
    """Append one event and return identity plus informational byte offset."""
```

Service attributes `index`, `store`, `log`, `shared_root` are assigned at `service.py:161–164`.
`open_issue()` appends before best-effort index sync (`service.py:272–273`). A busy index cannot erase the finding.
`LedgerEvent.model_post_init()` only computes an absent ID (`events.py:113`); supplied IDs need explicit content
validation in the new strict reader. The current shared-log reader skips malformed lines (`shared_log.py:78`);
do not use it alone to authorize delivery. `LedgerIndex.rebuild()` deletes pages/edges (`index.py:353–377`);
never invoke it on the live shared store as a reconciliation shortcut.

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| Outbox preparation | Source service | `Path(service.log.path).parent` | `service.py:152–194` |
| Canonical replay | Scratch service | `LedgerService.from_dir()` then `index.sync()` | `service.py:197`, `index.py:263` |
| Snapshot builder | Scratch service | `export_snapshot(dest, reconcile=True)` | `service.py:532` |
| Hook migration | Managed installer | Replace marker block before existing-marker early return | `installer.py:933–936` |
| Outbox commands | Click ledger group | Adjacent to `ledger_export_log` | `cli.py:3647–3652` |
| Workflow replacement | Done twins | Replace snapshot shell algorithm with typed CLI outcome | Edit Sites below |

### Does NOT Exist (Anti-Hallucination)

- `LedgerOutbox`, `LedgerIntegrator`, `ledger outbox`, and their proposed source files are new in this spec.
- No current remote receipt API or transaction makes event export + push + acknowledgement atomic.
- `LedgerService.from_root(temp_worktree)` does not select an isolated ledger; it resolves the shared primary root.
- A fresh clone cannot recover unshipped events from another machine merely by fetching the code PR.
- `merge=union` is not an event identity validator or a snapshot reducer.

### Edit Sites (Blueprint Anchors)

The table below lists all module-owned changes, including tests and workflow twins. Anchors were counted against
the recorded base; sdd-task must revalidate them. New paths are declared, not claimed to exist.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | <code>def ledger_export_log(repo_root: str &#124; None, stage: bool, quiet: bool) -> None:</code> | `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:3652` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` | MODIFY | <code>def ledger_hook_block(root: Path, hook_name: str) -> str:</code> | `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py:218` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | <code>def _install_ledger_hooks(root: Path) -> list[str]:</code> | `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py:973` | 1 |
| `tests/knowledge/wiki/test_cli_ledger_shared_log.py` | MODIFY | <code>def test_cli_export_log_stage_runs_git_add(tmp_path: Path, monkeypatch) -> None:</code> | `tests/knowledge/wiki/test_cli_ledger_shared_log.py:16` | 1 |
| `tests/knowledge/wiki/test_installer_ledger_hooks.py` | MODIFY | <code>def test_ledger_hooks_installed_on_four_events(tmp_path: Path) -> None:</code> | `tests/knowledge/wiki/test_installer_ledger_hooks.py:48` | 1 |
| `.claude/commands/sdd-done.md` | MODIFY | <code>### 9.1. Snapshot Ledger Issues (FEAT-566)</code> | `.claude/commands/sdd-done.md:475` | 1 |
| `.agents/skills/sdd-done/SKILL.md` | MODIFY | <code>11. Snapshot ledger issues (feature flows only):</code> | `.agents/skills/sdd-done/SKILL.md:186` | 1 |
| `.agent/workflows/sdd-done.md` | MODIFY | <code>### 9.1. Snapshot Ledger Issues (FEAT-566)</code> | `.agent/workflows/sdd-done.md:378` | 1 |
| `.claude/agents/sdd-worker.md` | MODIFY | <code>6. **CODE AND STATE LIVE TOGETHER IN THE WORKTREE (FEAT-145).**</code> | `.claude/agents/sdd-worker.md:95` | 1 |
| `.codex/agents/sdd-worker.toml` | MODIFY | <code>Push:</code> | `.codex/agents/sdd-worker.toml:138` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md` | MODIFY | <code>6. **YOU NEVER TOUCH &#96;sdd/tasks/&#96; OR &#96;sdd/ledger/&#96;.**</code> | `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md:78` | 1 |
| `tests/sdd/test_ledger_workflow_twins.py` | MODIFY | <code>class TestDoneTwins:</code> | `tests/sdd/test_ledger_workflow_twins.py:87` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/outbox.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/integration.py` | CREATE | — | — | — |
| `docs/sdd/ledger-outbox.md` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_integration.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/wiki/test_cli_ledger_outbox.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_acceptance.py` | CREATE | — | — | — |

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Pydantic v2 models; standard-library hashing, JSON, UUID, atomic filesystem operations and POSIX `fcntl` locking.
  No new dependency. Restrict filesystem support to the project's local POSIX deployment; remote/NFS lock
  guarantees are not claimed. Unsupported locking fails pending with a diagnostic.
- Async public service methods; Git through bounded async subprocess calls. Blocking filesystem work must use
  the repository's existing I/O offload pattern, never block the event loop. Strict type hints and Google docstrings.
- Preserve raw event identity and causal source order; no timestamp regeneration on retries.
- Read-only changes to hooks/import behavior must not turn into implicit network pushes on ordinary commits.
- Canonical path allowlist is exact: events and issues only; read archives but never stage the whole ledger directory.
- Source/batch paths must stay outside the disposable worktree. Do not mutate shared environments from temporary checkouts.
- Follow the current repository conventions. This spec supersedes FEAT-694's pre-commit transport and automatic
  done-time rotation requirements, not its event schema, archive reader compatibility or local filtering policy.

### Known Risks / Gotchas

- A shared log includes work from other active features. Repository-wide delivery is intentional; provenance must
  not suggest all events were produced by the feature closing now.
- Local claim state can disagree across machines; this feature reports conflicting events rather than promising
  a distributed lock or silently replacing live graph/index state. Such batches require explicit review.
- Rootless remote-MCP deployment needs future server-side batch transport. Until then delivery must be reported
  unsupported, never successful with an empty local source.
- A batch can reference code not merged yet. Preserve discovery attribution and do not auto-close new findings.
- Local journals/outboxes need normal backup for machine-loss recovery. No feature PR is their backup anymore.
- Existing installed pre-commit hooks and legacy feature diffs require migration; changing the generator alone is insufficient.
- No automatic log rotation during delivery means canonical history grows. Maintenance remains explicit until a
  separate retention policy is approved; removing rotation from done is a deliberate tradeoff for a smaller transaction.
- Git server policy may prohibit direct dev pushes. Report pending and retain data; this feature does not bypass
  protection or fall back to pushing main. A separate ledger PR/queue can be designed if that policy changes.

### External Dependencies

| Package/tool | Existing evidence | Reason |
|---|---|---|
| Pydantic v2 | `packages/ai-parrot/pyproject.toml:54` | Existing schema validation |
| Click | Existing `cli.py` ledger command declarations | CLI integration |
| Git | Existing sdd-done and ID allocator workflows | Fetch, isolated worktree, ledger-only commit and optimistic push |
| Python standard library | Existing ledger filesystem/hash usage | Durable files, UUID, locking, subprocesses |

## 8. Open Questions

- [x] Keep ledger data out of feature PRs? — Resolved in conversation: yes; sdd-done delivers events separately to dev.
- [x] Modify active primary checkout? — Resolved in conversation: use a temporary checkout of dev to avoid interference.
- [x] How to handle rejected pushes? — Resolved in conversation: recompute against the new base and deduplicate by event ID.
- [x] Should coordination wait for done? — Resolved in conversation: no; local service operations remain immediate.
- [x] Where is the temporary list durable? — Design resolution: existing shared local journal plus sealed batches alongside it.
- [x] Per-feature filtering? — Design resolution: repository-wide pending events, retaining predecessors and provenance.
- [x] Hotfix destination? — Design resolution: always dev for ledger delivery, independent of code base branch.
- [x] Publish failure? — Design resolution: retain batch/worktree and report incomplete closeout; explicit retry.
- [ ] Assign release version — Owner: maintainer; non-blocking for task decomposition.

## 9. Design Research Cross-Check

Status: skipped. Direct request and accepted conversation design; no accepted brainstorm/proposal artifact or
completed intake exists, so the optional independent design-research precondition is not met. Source contracts
were inspected locally; no independent review is claimed.

## Worktree Strategy

- Isolation: one feature worktree for this spec; sdd-coder may create task sub-worktrees within it.
- Module graph: M2 → M1 (batch/models); M3 → M1,M2 (commands call storage/integrator);
  M5 → M3,M4 (CLI and migrated hooks); M6 → M1,M2,M3,M4,M5 (acceptance). M4 can run concurrently with M1/M2.
- Shared files: assign `cli.py` only to M3 and each workflow file only to M5. Tests are owned by the module that
  changes their contract. Split module tasks may serialize only where they share an actual file.
- Exclusive resources: automated tests use private bare repositories and private ledgers. No implementation task
  may push the real dev branch to test delivery. Manual hook installation on the user's checkout is an exclusive
  post-implementation operation; fixture installation is parallel-safe.
- Cross-feature dependencies: existing FEAT-694/FEAT-671 APIs are present in the verified base; no unmerged dependency.
- This spec was authored on `spec/ledger-outbox-integration` in an isolated checkout because the primary dev
  worktree contained unrelated edits. Bring its spec commit into the planning base before creating task worktrees.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-27 | Jesus Lara / Codex | Initial draft from accepted outbox/integration design |
