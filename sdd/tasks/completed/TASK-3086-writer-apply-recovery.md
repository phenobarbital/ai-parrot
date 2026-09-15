# TASK-3086: writer_apply — hash-gated, precondition-checked, journaled application with rollback and recovery

**Feature**: FEAT-543 — Claude Code and Codex Tool Optimizations
**Spec**: `sdd/specs/tool-optimizations.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3085
**Assigned-to**: unassigned

---

## Context

Spec §2 "Delegation Packet and Writer Contract" — the `writer_apply`
paragraphs (reviewed hash, re-verification, staged-target refusal, locks,
adjacent temp files, per-file atomic replace, recovery journal,
`recovery_required`, `already_applied`, never stages/commits/pushes);
AC9 (apply half), AC10. Replaces the `not_implemented` stub left by
TASK-3085 in `writer.py`.

Multi-file filesystem mutation is **not globally atomic** — the design is
"all preconditions first, then per-file atomic replacement, then verify;
on failure restore only files that still match what we wrote".

---

## Scope

- Implement `TargetedWriterToolkit.writer_apply(self, artifact_id: str, reviewed_sha256: str) -> OperationResult`
  (`@tool_schema(WriterApplyArgs)`, member of `confirming_tools`):
  1. Validate args (`WriterApplyArgs`). `manifest, patch_text, packet_json = self._store.load(artifact_id)`
     (`artifact_tampered` / `artifact_not_found` → errors).
  2. `reviewed_sha256 != manifest.patch_sha256` → `review_hash_mismatch`
     (the thinking model must have read the stored patch and pass its
     hash — the hash proves artifact identity, not semantic review).
  3. Re-parse `packet_json` → `DelegationPacket`; recompute
     `packet_sha256` and compare to the manifest (`packet_mismatch`).
     Re-run `validate_contract(policy, task_path?)` — the packet's
     `task_id` is not a path; store `task_path` in the manifest? The
     manifest has no such field: **add `task_path: str` to
     `PatchManifest` in `models.py`** (TASK-3079 file; one-line
     addition, update its test) and populate it in TASK-3085's manifest
     (also a one-line change in `writer.py`). Re-validation covers scope,
     stale references and targets (`stale_target` etc. surface as-is).
  4. Discover the git layout (reuse `LocalGitToolkit._discover` by
     composing a private `LocalGitToolkit(repo_root=..., policy=self.policy)`
     instance — do NOT subclass) and take
     `async with WorktreeLock(layout.lock_path, timeout)`.
  5. Preconditions, ALL before any write:
     - `git diff --cached --name-only -z` (via the private git toolkit's
       `_run_git`) must not contain any target path → `staged_target`.
     - For each target: current sha256 (or absence) must equal
       `manifest.before_hashes[path]` → `target_changed`; a `create`
       target that now exists → `create_collision`. Exception: if
       **every** target's current sha equals `manifest.after_hashes[path]`
       → return `ok` with `data={"already_applied": True}` (idempotent
       re-run) after verifying all of them.
     - Journal from a previous attempt present with
       `state == "recovery_required"` → refuse `recovery_pending`
       (human must resolve; never auto-overwrite).
     - Re-apply the patch in memory (`apply_in_memory`) against the
       current bytes and compare each result's sha to
       `manifest.after_hashes` → `after_hash_mismatch`.
  6. Write journal `state="pending"` with one entry per target
     (`before_sha256`, `after_sha256`, `before_index`), and
     `save_before` for each modify target (bytes) / create target (`None`).
  7. Per file, in packet order: write `path.parent / f".{name}.parrot-tmp-{artifact_id[:8]}"`
     (adjacent, same filesystem), `fsync`, copy the original mode for
     modify (`0o644` default for create), `os.replace(tmp, path)`,
     journal entry → `written`, `write_journal`. Create parent
     directories for creates only if they are inside the root (already
     validated) — record created directories for rollback.
  8. Verify every written file's sha == after (`verified`), journal
     `state="applied"`. Return `ok` with `data={"applied": [...], "artifact_id", "journal_path"}`.
  9. Failure handling (any exception after step 6): for each entry in
     reverse order: if `state == "written"` and the file's current sha
     == `after_sha256` → restore `before` bytes (or unlink for create;
     remove directories we created if now empty) atomically →
     `restored`; if the current sha differs (concurrent edit) → mark
     `unrecoverable`, keep going for other files. If any entry is
     `unrecoverable` → journal `state="recovery_required"`, return
     `error/recovery_required` with the journal path and the list of
     files needing manual attention; else `state="rolled_back"`, return
     the original error code (e.g. `write_failed` with `errno`).
  10. Never run `git add`, `commit`, `push`, `reset`, `checkout` — grep test.
- Public helper `async def recovery_report(self, artifact_id: str) -> OperationResult`
  is NOT a tool (prefix with `_`: `_recovery_report`) — used by tests and
  docs to print the journal state.
- Tests: `packages/ai-parrot-tools/tests/tool_optimizations/test_apply.py`.

**NOT in scope**: MCP wiring, SDD workflow text, cross-process tests
(TASK-3091).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/writer.py` | MODIFY | Implement `writer_apply`, `_recovery_report`; set `task_path` in manifest |
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/models.py` | MODIFY | Add `PatchManifest.task_path: str` |
| `packages/ai-parrot-tools/tests/tool_optimizations/test_policy.py` | MODIFY | Cover the new manifest field |
| `packages/ai-parrot-tools/tests/tool_optimizations/test_apply.py` | CREATE | Apply/rollback/recovery/idempotency tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.tool_optimizations.models import OperationResult, OperationError, PatchManifest, DelegationPacket, WriterApplyArgs
from parrot_tools.tool_optimizations.patches import ArtifactStore, ApplyJournal, JournalEntry, PatchError, parse_patch, check_scope, apply_in_memory   # TASK-3084
from parrot_tools.tool_optimizations.contracts import validate_contract, ContractError        # TASK-3083
from parrot_tools.tool_optimizations.policy import WorktreeLock, LockTimeoutError, compact_json
from parrot_tools.tool_optimizations.git import LocalGitToolkit                                # TASK-3080/3081 (compose, do not subclass)
from parrot_tools.tool_optimizations.reader import sha256_stream, stat_regular                 # TASK-3082
```

### Existing Signatures to Use
```python
# TASK-3084 patches.py
class ArtifactStore: load(artifact_id) -> (PatchManifest, patch_text, packet_json); write_journal(id, ApplyJournal); read_journal(id) -> ApplyJournal|None; save_before(id, index, bytes|None); load_before(id, index)
class ApplyJournal(BaseModel): artifact_id, started_at, entries: list[JournalEntry], state: Literal["pending","applied","rolled_back","recovery_required"]
class JournalEntry(BaseModel): path, before_sha256: str|None, after_sha256: str, before_index: int, state: Literal["pending","written","verified","restored","unrecoverable"]
# TASK-3080 git.py
async def LocalGitToolkit._discover(self) -> RepoLayout | OperationResult   # .lock_path
async def LocalGitToolkit._run_git(self, args, ...) -> tuple[StepResult, bytes]
# TASK-3085 writer.py
class TargetedWriterToolkit: confirming_tools = frozenset({"writer_apply"}); self._store: ArtifactStore; self.policy
```

### Does NOT Exist
- ~~`os.rename` across filesystems~~ — temp files are adjacent to the target for this reason.
- ~~Global rollback guarantee~~ — restore only what still matches our after-hash; otherwise `recovery_required` (spec).
- ~~Deleting the journal after success~~ — keep it (it is the evidence); only `state` changes.
- ~~`git checkout -- <file>` for rollback~~ — forbidden; rollback uses the `before/` bytes we saved.
- ~~Applying without `reviewed_sha256`~~ — the argument is required by `WriterApplyArgs`.
- ~~A "force" or "skip preconditions" argument~~ — none exists.

---

## Implementation Notes

### Pattern to Follow
```python
async def _write_atomic(path: Path, data: bytes, mode: int) -> None:
    tmp = path.parent / f".{path.name}.parrot-tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError): os.unlink(tmp)
        raise

# rollback loop
for entry in reversed(journal.entries):
    if entry.state != "written": continue
    current = _sha_or_none(root / entry.path)
    if current != entry.after_sha256:
        entry.state = "unrecoverable"; continue
    before = self._store.load_before(artifact_id, entry.before_index)
    if before is None: os.unlink(root / entry.path)
    else: await asyncio.to_thread(_write_atomic, root / entry.path, before, mode)
    entry.state = "restored"
journal.state = "recovery_required" if any(e.state == "unrecoverable" for e in journal.entries) else "rolled_back"
self._store.write_journal(artifact_id, journal)
```

### Key Constraints
- Precondition order matters and is tested: a run with BOTH a staged
  target and a changed target must report `staged_target` (checked first)
  and write nothing.
- Blocking file I/O in `asyncio.to_thread`; the lock is held for the
  whole operation.
- Crash simulation: tests monkeypatch `os.replace` to raise on the second
  file; the first must be restored and the journal `rolled_back`.
- Concurrent edit simulation: tests patch `os.replace` to first write the
  file then mutate it after our write; the rollback must mark it
  `unrecoverable` and return `recovery_required` without overwriting the
  concurrent edit.
- Idempotent re-run after success → `already_applied`, no writes (assert
  mtimes unchanged).

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py:155-158` — `_write_settings` (simple write; here we need the atomic variant).

---

## Acceptance Criteria

- [ ] Wrong `reviewed_sha256` → `review_hash_mismatch`, nothing written.
- [ ] Tampered `patch.diff` → `artifact_tampered`; tampered `packet.json` → `packet_mismatch`.
- [ ] Target changed since generation → `target_changed`; reference changed → `stale_reference`; create target now exists → `create_collision`; target staged → `staged_target` (precedence tested).
- [ ] Happy path: files written byte-exact to `after_hashes`, journal `applied`, `git status` shows them unstaged, no commit created (`git rev-parse HEAD` unchanged).
- [ ] Re-run → `already_applied`, no writes.
- [ ] Crash on second file → first restored, journal `rolled_back`, error code from the failure.
- [ ] Concurrent edit during failure → `recovery_required`, concurrent content preserved, journal retained; subsequent `writer_apply` → `recovery_pending`.
- [ ] `_recovery_report` lists entries and states.
- [ ] Source grep: no `"add"`, `"commit"`, `"push"`, `"checkout"`, `"reset"` git argv in the apply path.
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_apply.py packages/ai-parrot-tools/tests/tool_optimizations/test_policy.py -v`; lint clean; log in `artifacts/logs/TASK-3086-pytest.log`.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/tool_optimizations/test_apply.py
import hashlib, os
import pytest
from parrot_tools.tool_optimizations.writer import TargetedWriterToolkit
from .conftest import git
from .fixtures import make_repo_with_target, make_valid_task, GOOD_PATCH
from .test_writer import FakeClient

async def _generated(tmp_path):
    repo = make_repo_with_target(tmp_path); git(repo, "init", "-q"); git(repo, "add", "."); git(repo, "commit", "-q", "-m", "base")
    task = make_valid_task(repo)
    tk = TargetedWriterToolkit(repo_root=repo, llm_client=FakeClient([GOOD_PATCH]))
    gen = await tk.writer_generate(task.relative_to(repo).as_posix())
    assert gen.status == "ok"
    return repo, tk, gen.data["artifact_id"], gen.data["patch_sha256"]

async def test_review_hash_gate(tmp_path):
    repo, tk, aid, sha = await _generated(tmp_path)
    res = await tk.writer_apply(aid, "0" * 64)
    assert res.error.code == "review_hash_mismatch" and not (repo / "pkg" / "greeter.py").exists()

async def test_apply_then_idempotent(tmp_path):
    repo, tk, aid, sha = await _generated(tmp_path)
    head = git(repo, "rev-parse", "HEAD").stdout
    ok = await tk.writer_apply(aid, sha)
    assert ok.status == "ok" and (repo / "pkg" / "greeter.py").exists()
    assert git(repo, "diff", "--cached", "--name-only").stdout == "" and git(repo, "rev-parse", "HEAD").stdout == head
    again = await tk.writer_apply(aid, sha)
    assert again.status == "ok" and again.data["already_applied"] is True

async def test_staged_target_refused_before_changed_target(tmp_path):
    repo, tk, aid, sha = await _generated(tmp_path)
    (repo / "pkg" / "__init__.py").write_text("changed\n"); git(repo, "add", "pkg/__init__.py")
    res = await tk.writer_apply(aid, sha)
    assert res.error.code == "staged_target"

async def test_crash_rolls_back_first_file(tmp_path, monkeypatch):
    repo, tk, aid, sha = await _generated(tmp_path)
    before = (repo / "pkg" / "__init__.py").read_bytes()
    real = os.replace; calls = {"n": 0}
    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 2: raise OSError(28, "No space left on device")
        return real(src, dst)
    monkeypatch.setattr(os, "replace", flaky)
    res = await tk.writer_apply(aid, sha)
    assert res.status == "error" and (repo / "pkg" / "__init__.py").read_bytes() == before
    assert tk._store.read_journal(aid).state == "rolled_back"

async def test_concurrent_edit_requires_recovery(tmp_path, monkeypatch):
    repo, tk, aid, sha = await _generated(tmp_path)
    real = os.replace; calls = {"n": 0}
    def race(src, dst):
        calls["n"] += 1; real(src, dst)
        if calls["n"] == 1: (repo / "pkg" / "__init__.py").write_text("user edit\n")   # someone edits our freshly written file
        if calls["n"] == 2: raise OSError(5, "I/O error")
    monkeypatch.setattr(os, "replace", race)
    res = await tk.writer_apply(aid, sha)
    assert res.error.code == "recovery_required" and (repo / "pkg" / "__init__.py").read_text() == "user edit\n"
    assert (await tk.writer_apply(aid, sha)).error.code == "recovery_pending"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-3085 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/tool-optimizations.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3086-writer-apply-recovery.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Opus 5, session_01G9NM1TzdkFLd5foNDmh72K)
**Date**: 2026-09-10
**Notes**:

Implemented `writer_apply`, `_rollback`, `_recovery_report` and the
`_write_atomic` / `_missing_parents` / `_sha_or_none` helpers, replacing
the TASK-3085 stub. Added the required `PatchManifest.task_path` field and
populated it. 14 tests in `test_apply.py`, 219 across the feature suite.

**Precondition order is load-bearing and is what the tests pin.** The
sequence is: artifact load -> review hash -> packet identity -> lock ->
`already_applied` -> `recovery_pending` -> `staged_target` -> per-target
`create_collision` / `target_changed` -> contract re-validation ->
in-memory re-apply -> after-hash check. Two orderings are deliberate:

1. `already_applied` must precede contract re-validation. After a
   successful apply the created file exists, so re-validating the contract
   would fail with `target_exists_for_create` and an idempotent retry would
   look like an error.
2. `staged_target` precedes `target_changed` (asserted directly by
   `test_staged_target_refused_before_changed_target`, which sets up both
   conditions at once) so the report names the blocker the user must
   actually resolve.

**A test-methodology bug found and fixed — worth reading.** The task's
sketch injects the write failure by counting `os.replace` calls
(`if calls["n"] == 2: raise`). That does not work here: `ArtifactStore`
publishes the journal with `os.replace` too, so call #1 is the *journal*
write, not a target file. Both fault-injection tests were therefore
"passing" while testing nothing:

- the crash test aborted on the journal write, so no file was ever
  written and the rollback loop had nothing to restore;
- the concurrent-edit test corrupted `journal.json` with the sabotage
  content instead of a target file, and produced `write_failed` rather
  than `recovery_required`.

Both now inject by **destination path**, so the crash lands on the second
real target and the sabotage lands on the first. `test_crash_rolls_back_first_file`
now asserts the actual rollback effect — `pkg/greeter.py` was written and
then removed, journal entry `restored`, the failed entry still `pending`,
errno 28 reported, and no `.parrot-tmp` files left behind.

Other properties covered:

- **Rollback never overwrites a concurrent editor.**
  `test_concurrent_edit_requires_recovery` has an outside writer rewrite
  the file we just wrote; rollback sees the hash no longer matches what it
  wrote, marks the entry `unrecoverable`, returns `recovery_required` and
  leaves the foreign content byte-intact. A retry then returns
  `recovery_pending` rather than steamrolling it.
- **Applying never stages, commits or pushes**: the happy-path test
  asserts `git diff --cached --name-only` is empty and `HEAD` is unchanged,
  and `test_apply_path_never_uses_mutating_git_verbs` greps the module for
  `"add"`, `"commit"`, `"push"`, `"checkout"` and `"reset"` argv literals.
- **Permissions are preserved on modify and defaulted on create**
  (0o640 stays 0o640; a new file is 0o644).
- The journal is retained as evidence after both success and idempotent
  re-run; only its `state` changes.

**Testing**: 219 tests pass; ruff and black clean. Log at
`artifacts/logs/TASK-3086-pytest.log`.

**Deviations from spec**: none, with three recorded file-scope notes:

1. `tests/tool_optimizations/test_patches.py` (TASK-3084's file) needed a
   one-line update because `PatchManifest.task_path` is a new **required**
   field and that test builds a manifest. Making the field optional was
   rejected: a manifest without provenance cannot be re-validated at apply
   time, which is the whole reason the field was added.
2. `test_writer.py`'s `test_writer_apply_is_not_implemented_yet` was
   replaced (it asserted the stub this task removes) with two real tests:
   unknown-artifact and argument validation.
3. `test_stale_reference_refused` from the task sketch was renamed to
   `test_unrelated_file_does_not_block_apply` and documents why: in this
   fixture the packet's only reference *is* a target, so changing it is
   caught earlier and more precisely as `target_changed`. Genuine
   reference staleness is already covered in `test_contracts.py`.
