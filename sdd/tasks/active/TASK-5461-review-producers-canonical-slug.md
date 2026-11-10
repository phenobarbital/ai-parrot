# TASK-5461: Review producers write the canonical index slug that `finalize_task` requires

**Feature**: FEAT-869 — Review Producers Write the Canonical Index Slug That `finalize_task` Requires
**Spec**: `sdd/specs/sdd-coder-engine-tech-debt.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:b9ff30bf709e`

---

## Context

Since FEAT-867, `finalize_task` refuses a `ReviewArtifact` whose `feature_slug` differs from the per-spec index file
stem it opens (`sdd/tasks/index/<feature_slug>.json`). Two producers can still write another form:
`review_checkpoint._run_record` stores the raw `--feature` value unchecked (a FEAT-ID, a substring or a path is
stored as given), and `SddCoderEngine.record_review` stores the index header's `feature`, which differs from the
file name for four legacy indexes (`FEAT-156.json`, `FEAT-213-telegram-voice-reply-tts.json`,
`FEAT-217-graph-expanded-retrieval.json`, `lyria-toolkit.json`). Finalize then fails closed. Implements spec §2 A + B,
Modules 1 and 2.

---

## Scope

- `review_checkpoint.py`: new `_require_index(worktree, feature)` that raises `ValueError` when `feature` is not a
  plain file name or names no index (`resolve_index_path(...).is_file()` is false); `_run_record` calls it through
  `asyncio.to_thread` right after the HEAD read.
- `engine.py`: new module-level `_index_slug(index_path)` (inverse of `resolve_index_path`); `record_review` stores
  `feature_slug=_index_slug(ctx.index_path)`.
- Tests per spec §4: two new CLI tests, one existing CLI test extended; two new engine tests, one existing engine
  test extended.

**NOT in scope**: canonicalizing a FEAT-ID/substring in `record` (reject only); rewriting the legacy index headers;
`finalize_task.py`; `prepare` / `validate`; the other `ctx.feature` uses in `engine.py`; the
`Path(ctx.index_path).stem` calls for `task_context` / `delivery_report` (`engine.py:1744`, `:1796`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py` | MODIFY | `_require_index` + call in `_run_record` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | `_index_slug` + `record_review` uses it |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py` | MODIFY | 2 new tests, 1 extended |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py` | MODIFY | 2 new tests, 1 extended |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

Verified against `origin/dev` @ `6eb680a977`.

### Verified Imports
```python
from parrot.flows.dev_loop.task_scheduler import resolve_index_path  # verified: task_scheduler.py:38; checkpoint.py:67 imports it
from parrot.flows.dev_loop.task_scheduler import BRIEF_INDEX_DIR, BRIEF_INDEX_SUFFIX  # verified: task_scheduler.py:33-34
from parrot.flows.dev_loop.task_scheduler import TaskScheduler, iter_index_files  # verified: engine.py:58 (line to extend)
from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine  # verified: test_feedback.py:12
from parrot.flows.dev_loop.sdd_coder.optimization_models import ReviewArtifact  # verified: test_feedback.py:14; test_review_checkpoint.py:20
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat  # verified: test_feedback.py:13
from parrot.knowledge.wiki.ledger.coder_reviews import CoderReview  # verified: test_feedback.py:17
from .conftest import _run_git  # verified: test_feedback.py:241 (local import inside a test)
from .test_engine_dispatch import _git  # verified: test_feedback.py:277 (local import inside a test)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py
TASK_INDEX_DIR = Path("sdd") / "tasks" / "index"  # :32
BRIEF_INDEX_DIR = Path("sdd") / "briefs"  # :33
BRIEF_INDEX_SUFFIX = ".index.json"  # :34
def resolve_index_path(worktree_path: str | Path, feature_slug: str) -> Path  # :38; returns the missing feature path when neither exists
# packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py
import asyncio  # :14 ; from pathlib import Path  # :20
def _build_store(worktree: Path) -> ExecutionEvidenceStore  # :66
async def _run_record(*, feature, task, worktree: Path, summary, execution_id, fix_commits, store) -> dict[str, object]  # :91
#   head_sha = stdout.strip()  # :111 ; ReviewArtifact(feature_slug=feature, ...)  # :112-121
def main(argv: list[str] | None = None) -> int  # :126; except (ValidationError, ValueError) -> invalid_input / exit 2 :199-201
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
from pathlib import Path  # :26
async def _git(*args: str, cwd: str) -> Tuple[int, str, str]  # :183 (module-level)
class _FeatureCtx  # :253 — index_path: str
async def SddCoderEngine.record_review(self, feature, worktree, review: CoderReview, execution_id: Optional[str] = None) -> CoderReviewReceipt  # :2742
#   feature_slug=ctx.feature,  # :2787
# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py
EXECUTION_ID = "33333333-3333-4333-8333-333333333333"  # :24; FEATURE_SLUG = "checkpoint-demo" :25; FEATURE_ID = "FEAT-9101" :26
def _build_repo(tmp_path: Path) -> Path  # :42 — index at sdd/tasks/index/checkpoint-demo.json
def _record_argv(worktree: Path, *extra: str) -> list[str]  # :386 — passes --feature FEATURE_SLUG
# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py
FEATURE_ID = "FEAT-549"  # :77 ; FEATURE_SLUG = "demo"  # :78 ; index file sdd/tasks/index/demo.json
async def git_sandbox_feature(tmp_path)  # :141 — (worktree, branch, base_path, index_path)
```

### Does NOT Exist
- No index check in `_run_record` or in the `record` branch of `main`; no `resolve_index_path` import in
  `review_checkpoint.py`.
- No `_require_index` in `review_checkpoint.py`; no `_index_slug` (or any path-to-slug inverse) in `engine.py` or
  `task_scheduler.py`.
- No `index_slug` / `slug_for_index` helper in `task_scheduler.py` — do not import one.

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
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.record_review",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py#resolve_index_path"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Keep `print(json.dumps(...))` in `main`; no new `except` branch is needed (`ValueError` already maps to
  `invalid_input` / exit 2).
- Run `_require_index` through `asyncio.to_thread` — it stats files; never block the event loop.
- Put the index check AFTER the HEAD read: `test_record_reports_git_failures_as_json[not_a_repository]` runs `record`
  in an empty directory with no index and must keep returning `operation_error` / exit 1.
- Tests run in the worktree with `PYTHONPATH=packages/ai-parrot/src`.

### References in Codebase
- `checkpoint._index_path` / `_load_index_sync` (`checkpoint.py:186-193`) — the same `resolve_index_path` lookup,
  run through `asyncio.to_thread` at `:460`.
- `test_record_review_publishes_review_artifact` (`test_feedback.py:275`) — the shape for the renamed-index test.

---

## Implementation Blueprint

### Steps (in order)
1. `review_checkpoint.py`: import, `_require_index`, the call in `_run_record`.
2. `engine.py`: extend the `task_scheduler` import, add `_index_slug`, switch `feature_slug=`.
3. Tests; confirm the FEAT-ID/substring/traversal and renamed-index tests fail with the source reverted.

### `packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py` (MODIFY)
```python
# AFTER `from parrot.flows.dev_loop.sdd_coder.telemetry import resolve_durable_root` (verified: :37)
# occurrences: 1 (verified: grep -c)
from parrot.flows.dev_loop.task_scheduler import resolve_index_path
```
```python
# BEFORE `def _build_store(worktree: Path) -> ExecutionEvidenceStore:` (verified: :66) — occurrences: 1
def _require_index(worktree: Path, feature: str) -> None:
    """Reject a ``--feature`` that is not the slug of an index in ``worktree``.

    ``finalize_task`` matches ``ReviewArtifact.feature_slug`` against the per-spec index file stem, so a review
    recorded under a FEAT-ID, a substring or a path could never finalize (issue:b9ff30bf709e). The lookup is the
    one ``prepare`` uses (``resolve_index_path``: per-spec index, then brief index).

    Raises:
        ValueError: ``feature`` contains a path separator or names no existing index.
    """
    # FILL IN: raise ValueError when `Path(feature).name != feature` or
    #   `not resolve_index_path(worktree, feature).is_file()` — bounded by AC-1; the message names `feature`,
    #   both accepted paths (sdd/tasks/index/<feature>.json, sdd/briefs/<feature>.index.json) and says to pass
    #   the index file's slug, not a FEAT-ID or a substring.
```
```python
# AFTER `    head_sha = stdout.strip()` (verified: :111) — occurrences: 1
    await asyncio.to_thread(_require_index, worktree, feature)
```
**Why**: rejecting at record time turns a late, confusing finalize refusal into an immediate `invalid_input`; the
separator check stops `../index/<slug>` from reaching a real index through traversal.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY)
```python
# REPLACE (verified: :58) — occurrences: 1
from parrot.flows.dev_loop.task_scheduler import TaskScheduler, iter_index_files  # verified: task_scheduler.py:53
# WITH (keep the trailing comment as it was)
from parrot.flows.dev_loop.task_scheduler import (  # verified: task_scheduler.py:53
    BRIEF_INDEX_DIR,
    BRIEF_INDEX_SUFFIX,
    TaskScheduler,
    iter_index_files,
)
```
```python
# BEFORE `async def _git(*args: str, cwd: str) -> Tuple[int, str, str]:` (verified: :183) — occurrences: 1
def _index_slug(index_path: str) -> str:
    """The slug ``resolve_index_path`` maps to ``index_path`` (its inverse).

    A per-spec index ``sdd/tasks/index/<slug>.json`` yields its file stem; a brief index
    ``sdd/briefs/<slug>.index.json`` yields its name minus ``.index.json``. This, not the index header's
    ``feature``, is the slug ``finalize_task`` matches a ``ReviewArtifact`` against (issue:b9ff30bf709e).
    """
    path = Path(index_path)
    if path.parent.name == BRIEF_INDEX_DIR.name and path.name.endswith(BRIEF_INDEX_SUFFIX):
        return path.name[: -len(BRIEF_INDEX_SUFFIX)]
    return path.stem
```
```python
# REPLACE `                    feature_slug=ctx.feature,` (verified: :2787) — occurrences: 1
                    feature_slug=_index_slug(ctx.index_path),
```
**Why**: legacy index headers differ from their file names; the file name is what finalize opens.

### Tests (MODIFY)
- `test_review_checkpoint.py`: in `test_record_publishes_manual_review_artifact`, after
  `assert artifact.fix_commits == [head_sha]` (:309, occurrences 1) add `assert artifact.feature_slug == FEATURE_SLUG`.
  Append at end of file:
  - `test_record_rejects_feature_without_index` parametrized over `FEATURE_ID`, `"checkpoint"` and
    `f"../index/{FEATURE_SLUG}"` — `_build_repo`, argv as `_record_argv` but with that `--feature` (FILL IN: build
    the argv — `_record_argv` hard-codes `FEATURE_SLUG`); assert exit 2, `error == "invalid_input"`, the value in the
    message, and no `executions/<EXECUTION_ID>/artifacts` directory.
  - `test_record_accepts_brief_index_slug` — write `sdd/briefs/brief-demo.index.json` (any JSON object) in the
    `_build_repo` worktree, run `record --feature brief-demo`; assert exit 0 and the stored artifact's
    `feature_slug == "brief-demo"`.
- `test_feedback.py`: in `test_record_review_publishes_review_artifact` add `assert artifact.feature_slug == "demo"`.
  Before `async def test_record_review_without_store_fails_before_ledger_write(` (:314, occurrences 1) add:
  - `test_index_slug_inverts_resolve_index_path` (sync, parametrized): `/wt/sdd/tasks/index/FEAT-156.json` →
    `FEAT-156`; `/wt/sdd/tasks/index/lyria-toolkit.json` → `lyria-toolkit`;
    `/wt/sdd/briefs/agy-permission-hook.index.json` → `agy-permission-hook`. Import `_index_slug` from
    `parrot.flows.dev_loop.sdd_coder.engine` locally in the test.
  - `test_record_review_writes_index_file_slug` — `git mv sdd/tasks/index/demo.json sdd/tasks/index/FEAT-549-demo.json`
    and commit (via `_run_git` from `.conftest`) BEFORE building the engine; then the flow of
    `test_record_review_publishes_review_artifact` with a fresh execution id; assert the stored artifact's
    `feature_slug == "FEAT-549-demo"` (the header `feature` stays `demo`).

---

## Acceptance Criteria

- [ ] AC-1: `record` with a `--feature` that names no index in `--worktree`, or contains a path separator, prints
      `invalid_input`, exits 2 and writes no artifact.
- [ ] AC-2: `record` accepts a per-spec index slug and a brief index slug and stores that slug as `feature_slug`.
- [ ] AC-3: a git failure in `record` is still `operation_error` / exit 1, also in a directory without an index.
- [ ] AC-4: `record_review` stores `_index_slug(ctx.index_path)`; for an index whose header `feature` differs from its
      file name, the stored slug is the file name's slug.
- [ ] AC-5: the FEAT-ID/substring/traversal and renamed-index tests fail with the source changes reverted and pass
      with them; both Validation Commands pass.
- [ ] AC-6: `ruff check` is clean on the four files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py -q`

---

## Test Specification

See spec §4: `test_record_rejects_feature_without_index`, `test_record_accepts_brief_index_slug`,
`test_index_slug_inverts_resolve_index_path`, `test_record_review_writes_index_file_slug`, plus the two extended
tests. The rest of both files is unchanged and must keep passing (notably
`test_record_reports_git_failures_as_json`).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug sdd-coder-engine-tech-debt --feature-id FEAT-869`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing ANY code
5. **Update status** in `sdd/tasks/index/sdd-coder-engine-tech-debt.json` → `"in-progress"` (set `started_at`) and
   commit only that index file
6. **Implement** — follow the Implementation Blueprint
7. **Verify** all acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5461 sdd-coder-engine-tech-debt verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
