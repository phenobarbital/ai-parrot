---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [flows, sdd, ledger-fix]
docs:
  policy: none
---

# Feature Specification: Review Producers Write the Canonical Index Slug That `finalize_task` Requires

**Feature ID**: FEAT-869
**Date**: 2026-11-10
**Author**: /sdd-fix (agent:sdd-fix:f3822408)
**Status**: approved
**Target version**: 2.1.3

**Discovered-from**: `issue:b9ff30bf709e`

> Ledger-driven fix. Drains the `/sdd-fix` group `fixgroup:99e4b365d836` (`issue:b9ff30bf709e`, minor tech debt),
> a follow-up deliberately left out of FEAT-867 (PR #2075) because both producers were being reworked by FEAT-866
> (PR #2073). Both PRs are merged into `dev`. No brainstorm or proposal: the issue body is the requirement.

---

## 1. Motivation & Business Requirements

### Problem Statement

Since FEAT-867, `finalize_task` refuses a `ReviewArtifact` whose `feature_slug` differs from
`TaskCompletionEvidence.feature_slug` (`finalize_task.py:182`), and that slug is the per-spec index file stem: finalize
opens `sdd/tasks/index/<feature_slug>.json` (`:579`). The refusal is fail-closed with a clear "re-record the review"
message, but two producers can still write another form of the slug:

1. **`parrot sdd task review record` stores `--feature` unchecked.** `review_checkpoint._run_record` copies the raw
   value into `ReviewArtifact(feature_slug=feature, ...)` (`review_checkpoint.py:113`). `--feature FEAT-123`, a
   substring of the slug, or a path is stored as given, while `prepare`/`validate` resolve the same flag through
   `task_scheduler.resolve_index_path` (`checkpoint.py:186-188`). The mistake only surfaces later, at finalize.
2. **`SddCoderEngine.record_review` writes the index header, not the file stem.** It stores `ctx.feature`
   (`engine.py:2787`), which `_resolve_feature` reads from the index header's `feature` key (`:1867`). For four
   legacy indexes on `dev` @ `3a4b0b941e` the header differs from the file name:

   | Index file | Header `feature` |
   |---|---|
   | `FEAT-156.json` | `agentcrew-from-definition` |
   | `FEAT-213-telegram-voice-reply-tts.json` | `telegram-voice-reply-tts` |
   | `FEAT-217-graph-expanded-retrieval.json` | `graph-expanded-retrieval` |
   | `lyria-toolkit.json` | `Lyria Toolkit for Natural Language Music Generation` |

   A coder review recorded for a task of those features can never finalize.

### Goals
- `record` rejects a `--feature` that does not name an existing index in `--worktree` (a per-spec index
  `sdd/tasks/index/<slug>.json` or a brief index `sdd/briefs/<slug>.index.json`, the same lookup `prepare` uses) with
  `invalid_input` / exit 2, and writes nothing.
- `record` also rejects a `--feature` that is not a plain file name (contains a path separator), so a value such as
  `../index/<slug>` cannot resolve to an index through traversal.
- `record_review` stores the slug derived from `ctx.index_path`: the file stem of a per-spec index, the file name
  minus `.index.json` of a brief index.

### Non-Goals (explicitly out of scope)
- Canonicalizing a FEAT-ID or substring into the slug in `record`: the issue asks for rejection, and the error names
  the expected file so the caller can fix the flag.
- Renaming or rewriting the four legacy index headers.
- `finalize_task` itself (unchanged), and `prepare` / `validate` (they already resolve through `resolve_index_path`).
- The other `ctx.feature` uses in the engine (commit-message scopes, plan-cache keys): they never reach finalize.
- `engine.py`'s `Path(ctx.index_path).stem` calls for `task_context` / `delivery_report` (`:1744`, `:1796`), which
  yield `<slug>.index` for a brief index: a separate defect, filed to the ledger rather than widened into this fix.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:5a50353ee2c81273d536b216146f4ac868ef158837075b22132b1f8499ea5921 evaluation_digest=sha256:44019bbfdf8c5387799886a007ad64cdccb0dea150ae0dbf44c3c9300b1e96d5 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

Two source files, two test files, no new module.

**A. `review_checkpoint._run_record`.** After the HEAD read and before building the `ReviewArtifact`, run a new
synchronous helper `_require_index(worktree, feature)` through `asyncio.to_thread` (it stats files; the event loop
stays free, as in `checkpoint._load_index_sync`). The helper raises `ValueError` when `Path(feature).name != feature`
(a path separator) or when `resolve_index_path(worktree, feature)` is not a file. `main` already maps `ValueError`
to `{"ok": false, "error": "invalid_input", ...}` / exit 2, so no new error branch is needed. The message names both
accepted locations and says to pass the index file's slug, not a FEAT-ID or a substring.

The check runs after the HEAD read on purpose: the existing `not_a_repository` case
(`test_record_reports_git_failures_as_json`) runs `record` in an empty directory that has no index, and must keep
reporting the git failure as `operation_error` / exit 1. Either order writes nothing on failure.

**B. `SddCoderEngine.record_review`.** Add a module-level helper `_index_slug(index_path: str) -> str` to `engine.py`:
when the path's parent directory is `BRIEF_INDEX_DIR.name` (`briefs`) and its name ends with `BRIEF_INDEX_SUFFIX`
(`.index.json`), return the name minus that suffix; otherwise return `Path(index_path).stem`. It is the inverse of
`resolve_index_path`. `record_review` passes `feature_slug=_index_slug(ctx.index_path)` instead of `ctx.feature`.
`BRIEF_INDEX_DIR` and `BRIEF_INDEX_SUFFIX` join the existing `task_scheduler` import.

### Integration Points
| Existing component | Interaction |
|---|---|
| `parrot sdd task review record` → `review_checkpoint.main` | unchanged CLI; a wrong `--feature` now fails at record time |
| `task_scheduler.resolve_index_path`, `BRIEF_INDEX_DIR`, `BRIEF_INDEX_SUFFIX` | reused, unchanged |
| `toolkit` → `SddCoderEngine.record_review` | the stored `feature_slug` now matches the index file name |
| `finalize_task` | unchanged; now accepts reviews recorded for the four legacy indexes |

## 3. Module Breakdown

### Module 1: `record` rejects a `--feature` that names no index
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py`
- **Responsibility**: A above.
- **Interface Skeleton**:
```python
def _require_index(worktree: Path, feature: str) -> None:
    """Raise ValueError unless `feature` is a plain slug naming an index in `worktree`."""
    if Path(feature).name != feature or not resolve_index_path(worktree, feature).is_file():
        raise ValueError(...)

# in _run_record, after `head_sha = stdout.strip()`:
    await asyncio.to_thread(_require_index, worktree, feature)
```
- **Tests**: `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py`.

### Module 2: `record_review` writes the index file slug
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py`
- **Responsibility**: B above.
- **Interface Skeleton**:
```python
def _index_slug(index_path: str) -> str:
    """The slug `resolve_index_path` maps to `index_path` (the inverse lookup)."""
    path = Path(index_path)
    if path.parent.name == BRIEF_INDEX_DIR.name and path.name.endswith(BRIEF_INDEX_SUFFIX):
        return path.name[: -len(BRIEF_INDEX_SUFFIX)]
    return path.stem
```
- **Tests**: `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py`.

### Delegation-eligible modules
| Module | Eligible | Decided patterns / contracts |
|---|---|---|
| 1, 2 | no | small edits; implemented in the `/sdd-fix` session |

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_record_rejects_feature_without_index` | 1 | parametrized `--feature`: the FEAT-ID, a substring of the slug, and `../index/<slug>` (resolves to the real index through traversal) → exit 2, `invalid_input`, the value appears in the message, no artifact directory; all three fail on `dev` |
| `test_record_accepts_brief_index_slug` | 1 | a brief index `sdd/briefs/<slug>.index.json` in the worktree → exit 0 and the stored artifact's `feature_slug` is that slug |
| `test_record_reports_git_failures_as_json` | 1 | existing; unchanged (git failure still wins over the missing index) |
| `test_record_publishes_manual_review_artifact` | 1 | existing; also asserts `artifact.feature_slug == FEATURE_SLUG` |
| `test_index_slug_inverts_resolve_index_path` | 2 | parametrized: per-spec `FEAT-156.json` → `FEAT-156`, `lyria-toolkit.json` → `lyria-toolkit`, brief `agy-permission-hook.index.json` → `agy-permission-hook` |
| `test_record_review_writes_index_file_slug` | 2 | the fixture index is renamed to `FEAT-549-demo.json` (header `feature` stays `demo`) and committed; `record_review` with an execution id stores `feature_slug == "FEAT-549-demo"`; fails on `dev` |
| `test_record_review_publishes_review_artifact` | 2 | existing; also asserts `artifact.feature_slug == "demo"` |

### Validation Contract

tests:
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py
markers: none

## 5. Acceptance Criteria
- [ ] `record` with a `--feature` that names no index in `--worktree`, or that contains a path separator, prints
      `{"ok": false, "error": "invalid_input", ...}`, exits 2 and writes no artifact.
- [ ] `record` accepts both a per-spec index slug and a brief index slug, and stores that slug as
      `ReviewArtifact.feature_slug`.
- [ ] A git failure in `record` is still `operation_error` / exit 1, also when the directory has no index.
- [ ] `record_review` stores `_index_slug(ctx.index_path)` as `feature_slug`; for an index whose header `feature`
      differs from its file name, the stored slug is the file name's slug.
- [ ] The new tests exist; the FEAT-ID/substring/traversal and the renamed-index tests fail without the fix and pass
      with it.
- [ ] Both Validation Contract files pass; `ruff check` is clean on the changed files.

## 6. Codebase Contract

Verified against `origin/dev` @ `3a4b0b941e`.

### Verified Imports
```python
from parrot.flows.dev_loop.task_scheduler import resolve_index_path  # verified: task_scheduler.py:38; checkpoint.py:67 imports it
from parrot.flows.dev_loop.task_scheduler import BRIEF_INDEX_DIR, BRIEF_INDEX_SUFFIX  # verified: task_scheduler.py:33-34 (module constants)
from parrot.flows.dev_loop.task_scheduler import TaskScheduler, iter_index_files  # verified: engine.py:58 (existing line to extend)
from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine  # verified: test_feedback.py:12
from parrot.flows.dev_loop.sdd_coder.optimization_models import ReviewArtifact  # verified: test_feedback.py:14, test_review_checkpoint.py:20
from .conftest import _run_git  # verified: test_feedback.py:241 (local import inside a test)
```

### Existing Signatures
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py
TASK_INDEX_DIR = Path("sdd") / "tasks" / "index"  # :32
BRIEF_INDEX_DIR = Path("sdd") / "briefs"  # :33
BRIEF_INDEX_SUFFIX = ".index.json"  # :34
def resolve_index_path(worktree_path: str | Path, feature_slug: str) -> Path  # :38; feature index, then brief index, else the (missing) feature path
# packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py
async def _run_record(*, feature: str, task: str, worktree: Path, summary: str, execution_id: str, fix_commits: list[str], store: ExecutionEvidenceStore) -> dict[str, object]  # :91; head_sha :111; ReviewArtifact( :112; feature_slug=feature :113
def main(argv: list[str] | None = None) -> int  # :126; except (ValidationError, ValueError) -> invalid_input / 2 :199-201
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
class _FeatureCtx  # :253; fields worktree, feature_id, feature, feature_branch, index_path: str, spec_path, base_branch
async def SddCoderEngine._resolve_feature(self, feature: str, worktree: str) -> _FeatureCtx  # :1809; feature=header.get("feature") :1867; index_path=str(index_path) :1869
async def SddCoderEngine.record_review(self, feature: str, worktree: str, review: CoderReview, execution_id: Optional[str] = None) -> CoderReviewReceipt  # :2742; feature_slug=ctx.feature :2787
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py
class ReviewArtifact  # feature_slug: str = Field(min_length=1) :139
# packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py
review_artifact.feature_slug != evidence.feature_slug  # :182 (refusal); per-spec index path :579
# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py
FEATURE_ID = "FEAT-549"  # :77
FEATURE_SLUG = "demo"  # :78; index file sdd/tasks/index/demo.json
```

### Does NOT Exist
- No index check in `review_checkpoint._run_record` or in the `record` branch of `main`.
- No `_require_index` in `review_checkpoint.py`; no `_index_slug` (or any index-path-to-slug inverse) in `engine.py`
  or `task_scheduler.py`.
- No `resolve_index_path` import in `review_checkpoint.py`.

### Edit Sites (Blueprint Anchors)
| File | Anchor | Line | Count | Action |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py` | `from parrot.flows.dev_loop.sdd_coder.telemetry import resolve_durable_root` | 37 | 1 | MODIFY (add the `task_scheduler` import after) |
| same | `def _build_store(worktree: Path) -> ExecutionEvidenceStore:` | 66 | 1 | MODIFY (new `_require_index` before) |
| same | `    head_sha = stdout.strip()` | 111 | 1 | MODIFY (index check after) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | `from parrot.flows.dev_loop.task_scheduler import TaskScheduler, iter_index_files` | 58 | 1 | MODIFY |
| same | `async def _git(*args: str, cwd: str) -> Tuple[int, str, str]:` | 183 | 1 | MODIFY (new `_index_slug` before) |
| same | `                    feature_slug=ctx.feature,` | 2787 | 1 | MODIFY |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py` | end of file | 482 | 1 | MODIFY |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py` | `async def test_record_review_without_store_fails_before_ledger_write(` | 314 | 1 | MODIFY (new tests before) |

## 7. Implementation Notes & Constraints
- Keep `print(json.dumps(...))` in `main`: it is the CLI's output contract.
- `_require_index` runs through `asyncio.to_thread`; never stat files directly on the event loop.
- `Path(feature).name != feature` also rejects `""` only through the missing-file check; argparse already requires
  the flag.
- Run the tests in the worktree with `PYTHONPATH=packages/ai-parrot/src`.
- Ledger linkage: `issue:b9ff30bf709e`.

### Known Risks / Gotchas
- `resolve_index_path` returns the missing feature path rather than raising, so the check must test `.is_file()`.
- A brief index's `Path.stem` is `<slug>.index`; `_index_slug` must strip `.index.json`, not `.json`.
- In the renamed-index engine test, commit the rename: `begin_execution` / `prepare_native` work from the committed
  tree.

## Worktree Strategy
One feature worktree, two modules, one task. No shared files, no exclusive resources, no cross-feature dependency:
FEAT-866 and FEAT-867, which last touched these files, are merged into `dev`.

## Decisions

## Decision Waivers

## Consequences

<!-- decision-audit: input_digest=sha256:5a50353ee2c81273d536b216146f4ac868ef158837075b22132b1f8499ea5921 evaluation_digest=sha256:44019bbfdf8c5387799886a007ad64cdccb0dea150ae0dbf44c3c9300b1e96d5 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/sdd-coder-engine-tech-debt.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, sdd-tooling, skills, tools
- Unmapped tags: ledger-fix
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "sdd-tooling",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "ledger-fix"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/sdd-coder-engine-tech-debt.spec.md"
    }
  ],
  "evaluation_digest": "sha256:44019bbfdf8c5387799886a007ad64cdccb0dea150ae0dbf44c3c9300b1e96d5",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:5a50353ee2c81273d536b216146f4ac868ef158837075b22132b1f8499ea5921",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions
- [x] Reject or canonicalize a non-slug `--feature` in `record`? — *Resolved in /sdd-fix research*: reject, as the
      issue specifies; the message names the expected index file.
- [x] Index check before or after the HEAD read? — *Resolved*: after, so a git failure keeps its
      `operation_error` / exit 1 contract in a directory without an index; neither order writes anything on failure.

## 9. Design Research Cross-Check
Status: skipped (no accepted exploration document)

## 10. Documentation
None: the CLI error message names the expected index file; no wiki page documents `task review record`.

## Revision History
| Date | Change |
|---|---|
| 2026-11-10 | Initial spec from `/sdd-fix` group `fixgroup:99e4b365d836` |
