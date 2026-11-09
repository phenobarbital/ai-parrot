# TASK-5458: `task review record` reports store/git errors as JSON and reads HEAD without blocking

**Feature**: FEAT-866 — `task review record` Reports Store/git Errors as JSON and Stops Blocking the Loop
**Spec**: `sdd/specs/sdd-coder-engine-fixes-4.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:f64fd3bb663f`

---

## Context

`parrot sdd task review record` (`packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py`) promises JSON
output with exit codes 0/1/2/3, but a corrupted evidence store (`EvidenceCorruptionError`, a `RuntimeError`) escapes
as a traceback; `_run_record` reads HEAD with a blocking `subprocess.run` inside an `async` function; and a missing
`--execution-id` silently becomes a random UUID. On the engine path, `SddCoderEngine.record_review` builds its
`ReviewArtifact` outside the `try`, so a non-UUID `execution_id` escapes as a raw `pydantic.ValidationError`.
Implements spec §2 A + B + C, Modules 1 and 2.

---

## Scope

- `_run_record`: read HEAD through `run_bounded(argv, timeout_s=GIT_TIMEOUT_S, env=git_env())`; raise
  `subprocess.CalledProcessError` on a non-zero rc.
- `main`: catch `EvidenceCorruptionError` with `OSError` (`operation_error`, exit 1); append git's stderr to the
  `CalledProcessError` message; help text for `--execution-id`; `execution_id_generated` in the `record` output;
  docstring sentence on the fallback.
- `record_review`: wrap `ReviewArtifact(...)` in `try/except PydanticValidationError` →
  `CoderFailure("invalid_arguments", ...)`.
- Tests per spec §4: three new CLI tests, two existing CLI tests extended, one new engine test.

**NOT in scope**: requiring `--execution-id`; `finalize_task.py` (`issue:2d1816987583`); the `prepare` / `validate`
subcommands; `_build_store`; the `put_artifact` error mapping in `record_review`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py` | MODIFY | non-blocking git, error mapping, `execution_id_generated`, help/docstring |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | `ReviewArtifact` validation → `CoderFailure` |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py` | MODIFY | 3 new tests, 2 extended, `_record_argv` helper |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py` | MODIFY | 1 new test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

Verified against `origin/dev` @ `ce70cd7523`.

### Verified Imports
```python
from parrot.flows.dev_loop.procs import git_env, run_bounded  # verified: checkpoint.py:58 (same import)
from parrot.flows.dev_loop.sdd_coder.checkpoint import GIT_TIMEOUT_S  # verified: checkpoint.py:105
from parrot.flows.dev_loop.sdd_coder.evidence import EvidenceCorruptionError, ExecutionEvidenceStore  # verified: evidence.py:65; review_checkpoint.py:33
from pydantic import ValidationError as PydanticValidationError  # verified: engine.py:29
from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine  # verified: test_feedback.py:12
from parrot.knowledge.wiki.ledger.coder_reviews import CoderReview  # verified: test_feedback.py:17
from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedbackStore  # verified: test_feedback.py:15
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat  # verified: test_feedback.py:13
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/procs.py
async def run_bounded(argv, *, cwd=None, timeout_s=..., env=None) -> Tuple[int, str, str]  # rc 124 timeout, 127 spawn failure (reason in stderr)
def git_env(base=None) -> Dict[str, str]  # copy of os.environ with prompts/editor/pager disabled
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/evidence.py
class EvidenceCorruptionError(RuntimeError)  # :65
async def ExecutionEvidenceStore.put_artifact(self, execution_id: str, payload: BaseModel) -> EvidenceRef  # :170
async def ExecutionEvidenceStore.read_artifact(self, execution_id, artifact_id, offset=0, limit=8192) -> dict[str, object]
# packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py
async def _run_record(*, feature, task, worktree, summary, execution_id, fix_commits, store) -> dict[str, object]  # :89
#   head_sha = subprocess.run(["git", "-C", str(worktree), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()  # :100-105
def main(argv: list[str] | None = None) -> int  # :120; "Exit codes" :123; --execution-id :144; uuid fallback :172; asyncio.run(_run_record(...)) :173-183
#   except subprocess.CalledProcessError :187-189; except OSError :196-198
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
class CoderFailure(Exception): def __init__(self, code: str, message: str, **details)  # :167
async def SddCoderEngine.record_review(self, feature, worktree, review: CoderReview, execution_id: Optional[str] = None) -> CoderReviewReceipt  # :2742
#   artifact = ReviewArtifact(... model=review.model,)  # :2784-2796; try: put_artifact :2797-2800
# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py
EXECUTION_ID = "33333333-3333-4333-8333-333333333333"  # :24; FEATURE_SLUG = "checkpoint-demo" :25
def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]  # :37
def _build_repo(tmp_path: Path) -> Path  # :41 — real git repo, returns the worktree
# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py
async def git_sandbox_feature(tmp_path)  # :141 — (worktree, branch, base_path, index)
def noop_probe() -> RosterProbe  # :210
```

### Does NOT Exist
- No `execution_id_generated` key in the `record` output; no help text on `--execution-id`.
- No catch of `EvidenceCorruptionError` in `review_checkpoint.main`.
- No validation of `record_review`'s `execution_id` before `ReviewArtifact(...)`.
- No `_record_argv` helper in `test_review_checkpoint.py` (each test spells out its argv today).
- `pydantic.ValidationError` subclasses `ValueError`: putting the construction inside the existing `put_artifact`
  `try` would map it to `evidence_persistence_failed` — it needs its own `try`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py#_run_record",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py#main",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.record_review",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/procs.py#run_bounded",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/procs.py#git_env",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/evidence.py#EvidenceCorruptionError"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Keep `print(json.dumps(...))` in `main` (the CLI output contract); keep every existing output key.
- Tests assert error codes and exit codes, never git's stderr text (git localizes it).
- Tests run in the worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is editable-installed against
  the main checkout).

### References in Codebase
- `checkpoint._git` (`checkpoint.py:164`) and `engine._git` (`engine.py:183`) — the same `run_bounded` + `git_env`
  pattern for git.
- `test_record_review_without_store_fails_before_ledger_write` (`test_feedback.py:314`) — same ledger-unchanged
  assertion shape.

---

## Implementation Blueprint

### Steps (in order)
1. Imports in `review_checkpoint.py`; rewrite the HEAD read in `_run_record`.
2. `main`: docstring, `--execution-id` help, `execution_id_generated`, the two `except` changes.
3. `engine.record_review`: own `try` around `ReviewArtifact(...)`.
4. Tests; confirm the three "fails on dev" tests fail with the source reverted.

### `packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py` (MODIFY)
```python
# BEFORE `from parrot.flows.dev_loop.sdd_coder.checkpoint import (` (verified: :24) insert:
from parrot.flows.dev_loop.procs import git_env, run_bounded
# and add `GIT_TIMEOUT_S,` as the first name inside that import list.
# REPLACE :33 with:
from parrot.flows.dev_loop.sdd_coder.evidence import EvidenceCorruptionError, ExecutionEvidenceStore
```
```python
# REPLACE :100-105 (`head_sha = subprocess.run(` … `).stdout.strip()`) with:
    argv = ["git", "-C", str(worktree), "rev-parse", "HEAD"]
    rc, stdout, stderr = await run_bounded(argv, timeout_s=GIT_TIMEOUT_S, env=git_env())
    if rc:
        raise subprocess.CalledProcessError(rc, argv, output=stdout, stderr=stderr)
    head_sha = stdout.strip()
```
```python
# main(): after the "Exit codes" docstring line (:123) add a paragraph saying `record` without --execution-id
# generates a fresh UUID, reported as `execution_id` with `execution_id_generated: true`.
# :144 → add_argument("--execution-id", help=<the same fallback, one sentence>)
# :172 → compute `execution_id_generated = not args.execution_id` before the fallback, and after the
#        asyncio.run(...) that ends at :183 set result["execution_id_generated"] = execution_id_generated
# :187 → message = f"{exc}: {exc.stderr.strip()}" when exc.stderr is non-empty, else str(exc)
# :196 → except (OSError, EvidenceCorruptionError) as exc:
```

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY)
```python
# WRAP :2784-2796 (`artifact = ReviewArtifact(` … `)`) in:
            try:
                artifact = ReviewArtifact(...)  # unchanged arguments
            except PydanticValidationError as exc:
                raise CoderFailure(
                    "invalid_arguments", f"review cannot be recorded as durable evidence: {exc}"
                ) from exc
# the following `try: review_ref = await self._evidence_store.put_artifact(...)` block stays as is.
```

### Tests (MODIFY)
- `test_review_checkpoint.py`: import `EvidenceCorruptionError` next to `ExecutionEvidenceStore` (:19); in
  `test_record_publishes_manual_review_artifact` assert `result["execution_id_generated"] is False`; in
  `test_record_generates_execution_id_when_omitted` assert it is `True`; append `_record_argv(worktree, *extra)` and
  the three new tests from spec §4 (store errors parametrized over `OSError` / `EvidenceCorruptionError` via a
  monkeypatched `ExecutionEvidenceStore.put_artifact`; git failures parametrized over a plain directory with
  `GIT_CEILING_DIRECTORIES=tmp_path` and an empty directory as `PATH`; blocking-call guard that replaces
  `subprocess.run` with a function raising `AssertionError` and checks the stored artifact's `head_sha`).
- `test_feedback.py`: before `def test_coder_review_accepts_brief_task_ids() -> None:` (:372) add
  `test_record_review_invalid_artifact_raises_coder_failure` — `begin_execution` with a valid UUID, `prepare_native`,
  then `record_review(..., "not-a-uuid")` raises `CoderFailure` with code `invalid_arguments` and the ledger events
  are unchanged.

---

## Acceptance Criteria

- [ ] AC-1: `_run_record` has no `subprocess.run`; it uses `run_bounded` with `GIT_TIMEOUT_S` and `git_env()` and
      raises `subprocess.CalledProcessError` on a non-zero rc.
- [ ] AC-2: `main` maps `EvidenceCorruptionError` to `operation_error` / exit 1, and the `CalledProcessError` message
      carries git's stderr when present.
- [ ] AC-3: `record` output has `execution_id_generated`; `--execution-id` has help text describing the fallback.
- [ ] AC-4: `record_review` raises `CoderFailure("invalid_arguments")` on a `ReviewArtifact` validation failure,
      with no ledger write.
- [ ] AC-5: the store-corruption, blocking-call and engine tests fail with the source changes reverted and pass with
      them; both Validation Commands pass.
- [ ] AC-6: `ruff check` is clean on the four files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py -q`

---

## Test Specification

See spec §4: `test_record_reports_store_errors_as_json`, `test_record_reports_git_failures_as_json`,
`test_record_reads_head_without_blocking_subprocess_run`, `test_record_review_invalid_artifact_raises_coder_failure`,
plus the two extended `record` tests. The rest of both files is unchanged and must keep passing.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug sdd-coder-engine-fixes-4 --feature-id FEAT-866`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing ANY code
5. **Update status** in `sdd/tasks/index/sdd-coder-engine-fixes-4.json` → `"in-progress"` (set `started_at`) and
   commit only that index file
6. **Implement** — follow the Implementation Blueprint
7. **Verify** all acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5458 sdd-coder-engine-fixes-4 verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
