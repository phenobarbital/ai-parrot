---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [flows, sdd, ledger-fix]
docs:
  policy: none
---

# Feature Specification: `task review record` Reports Store/git Errors as JSON and Stops Blocking the Loop

**Feature ID**: FEAT-866
**Date**: 2026-11-10
**Author**: /sdd-fix (agent:sdd-fix:88be2347)
**Status**: approved
**Target version**: 2.1.3

**Discovered-from**: `issue:f64fd3bb663f`

> Ledger-driven fix. Drains the `/sdd-fix` group `fixgroup:598e64d75d73` (`issue:f64fd3bb663f`, major bug), a
> deferred review finding from the `review-evidence-producer` brief (merged into `dev` by PR #2070). No brainstorm or
> proposal: the issue body is the requirement.

---

## 1. Motivation & Business Requirements

### Problem Statement

`parrot sdd task review record` (`packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py`) publishes a
manual semantic review as a durable `ReviewArtifact` that `finalize_task` later accepts as `review_evidence`. Its
`main` promises JSON output and the exit codes `0` success, `1` operation error, `2` invalid input, `3` stale/busy
(`review_checkpoint.py:123`). Four gaps remain on `dev` @ `25e8f657c5`:

1. **Store corruption escapes as a traceback.** `ExecutionEvidenceStore.put_artifact` can raise
   `EvidenceCorruptionError`, which subclasses `RuntimeError` (`evidence.py:65`). `main` catches `ValidationError`,
   `ValueError`, `subprocess.CalledProcessError`, the `Checkpoint*` errors and `OSError` (`:184-198`), so a corrupted
   evidence directory prints a Python traceback instead of `{"ok": false, "error": "operation_error", ...}`.
   (`OSError` and `FileNotFoundError` for a missing git binary are already caught by the `except OSError` branch.)
2. **A blocking call inside the event loop.** `_run_record` is `async`, but reads HEAD with a synchronous
   `subprocess.run(["git", "-C", worktree, "rev-parse", "HEAD"], check=True, ...)` (`:100-105`). It blocks the loop
   that `put_artifact`'s lock and `asyncio.to_thread` write run on, and the git child has no deadline and inherits an
   interactive environment.
3. **A silent random execution id.** Without `--execution-id`, `main` generates `str(uuid.uuid4())` (`:172`). The
   output's `execution_id` is the only trace; neither `--help` nor the output says the id was generated. The
   documented `/sdd-start` call omits the flag on purpose (`.claude/commands/sdd-start.md:278`), so the flag cannot
   become required.
4. **The engine path leaks a raw `ValidationError`.** `SddCoderEngine.record_review` builds `ReviewArtifact(...)`
   (`engine.py:2784`) before the `try` that maps store errors to `CoderFailure("evidence_persistence_failed")`
   (`:2797-2800`). `record_review` never validates its `execution_id` argument, so a non-UUID id reaches the
   artifact's UUID validator and escapes as `pydantic.ValidationError` instead of a `CoderFailure` the toolkit can map
   to `CoderResult.error`.

### Goals
- `record` reports `EvidenceCorruptionError` as `operation_error` with exit `1`, like `OSError`.
- `_run_record` reads HEAD without blocking the event loop, with a deadline and a headless git environment, and a
  failed or missing git still yields `operation_error` with exit `1` and git's stderr in the message.
- A generated execution id is visible: `--help` describes the fallback and the output carries
  `execution_id_generated` (`true` when generated, `false` when supplied).
- `record_review` turns a `ReviewArtifact` validation failure into `CoderFailure("invalid_arguments")` and writes
  nothing to the ledger.

### Non-Goals (explicitly out of scope)
- Making `--execution-id` required (it would break the documented `/sdd-start` call).
- `finalize_task`'s checks on a `ReviewArtifact` (feature slug, HEAD freshness): that is `issue:2d1816987583`, planned
  as its own group.
- The `prepare` / `validate` subcommands, `_build_store`, and the `EvidenceConflictError` mapping (it subclasses
  `ValueError` and already maps to `invalid_input`).
- Validating `execution_id` earlier in `record_review` (before the fix-commit checks); the `try` is enough.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:48bdfc4dfcaed1c1dcc3f42be3507678839a1da3dfccc9b21210396978f52bcc evaluation_digest=sha256:c205fdb627803798687d46922c63b36c5dfaaf237991f1d38e2dce4c163614ef rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

Two source files, two test files, no new module.

**A. `review_checkpoint._run_record`.** Replace the `subprocess.run` call with
`await run_bounded(argv, timeout_s=GIT_TIMEOUT_S, env=git_env())` from `parrot.flows.dev_loop.procs`, the bounded,
headless helper that `checkpoint.py` and `engine.py` already use for git. `run_bounded` never raises for a git
failure: it returns `(rc, stdout, stderr)`, with rc `124` on timeout and `127` when git cannot be spawned. On a
non-zero rc, `_run_record` raises `subprocess.CalledProcessError(rc, argv, output=stdout, stderr=stderr)`, so the
existing `except subprocess.CalledProcessError` branch in `main` keeps owning the `operation_error`/exit-1 mapping.
`GIT_TIMEOUT_S` is imported from `checkpoint.py` (`:105`), so `prepare` and `record` share one git deadline.

**B. `review_checkpoint.main`.**
- `except OSError` becomes `except (OSError, EvidenceCorruptionError)`.
- The `CalledProcessError` branch appends the stripped `exc.stderr` to the message when present (a missing git binary
  is otherwise reported only as "exit status 127").
- `--execution-id` gets a help text describing the fallback; the `record` branch records whether it generated the id
  and adds `"execution_id_generated": <bool>` to the result. The output stays a superset of today's keys.
- `main`'s docstring states the fallback and the new key.

**C. `SddCoderEngine.record_review`.** Wrap the `ReviewArtifact(...)` construction in
`try/except PydanticValidationError` and raise `CoderFailure("invalid_arguments", ...)` from it. The `put_artifact`
`try` and its `evidence_persistence_failed` mapping stay as they are. `invalid_arguments` (not
`evidence_persistence_failed`) because the fields that can fail validation come from the caller: `execution_id`,
`task_id`, `fix_commits`, `summary`. The ledger row is still written only after the artifact is stored.

### Integration Points
| Existing component | Interaction |
|---|---|
| `parrot sdd task review record` → `review_checkpoint.main` | unchanged CLI; one extra output key |
| `checkpoint.GIT_TIMEOUT_S`, `procs.run_bounded`, `procs.git_env` | reused, unchanged |
| `toolkit` → `SddCoderEngine.record_review` | gets a `CoderFailure` instead of a raw `ValidationError` |
| `finalize_task` | unchanged; still consumes the printed `review_ref` |

## 3. Module Breakdown

### Module 1: `record` error handling and non-blocking git
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py`
- **Responsibility**: A and B above.
- **Interface Skeleton**:
```python
async def _run_record(*, feature: str, task: str, worktree: Path, summary: str, execution_id: str,
                      fix_commits: list[str], store: ExecutionEvidenceStore) -> dict[str, object]:
    # verified: review_checkpoint.py:89 (signature unchanged)
    argv = ["git", "-C", str(worktree), "rev-parse", "HEAD"]
    rc, stdout, stderr = await run_bounded(argv, timeout_s=GIT_TIMEOUT_S, env=git_env())
    if rc:
        raise subprocess.CalledProcessError(rc, argv, output=stdout, stderr=stderr)
    head_sha = stdout.strip()
    ...
```
- **Tests**: `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py`.

### Module 2: `record_review` validation failure as `CoderFailure`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py`
- **Responsibility**: C above.
- **Tests**: `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py`.

### Delegation-eligible modules
| Module | Eligible | Decided patterns / contracts |
|---|---|---|
| 1, 2 | no | small edits; implemented in the `/sdd-fix` session |

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_record_reports_store_errors_as_json` | 1 | parametrized: `put_artifact` raises `OSError` / `EvidenceCorruptionError` → exit 1, `operation_error`, no traceback; the corruption case fails on `dev` |
| `test_record_reports_git_failures_as_json` | 1 | parametrized: worktree is not a git repo / no git on `PATH` → exit 1, `operation_error` |
| `test_record_reads_head_without_blocking_subprocess_run` | 1 | `subprocess.run` replaced by a function that raises; `record` still succeeds; fails on `dev` |
| `test_record_generates_execution_id_when_omitted` | 1 | existing; also asserts `execution_id_generated is True` |
| `test_record_publishes_manual_review_artifact` | 1 | existing; also asserts `execution_id_generated is False` |
| `test_record_rejects_invalid_input_without_writing` | 1 | existing; unchanged |
| `test_record_review_invalid_artifact_raises_coder_failure` | 2 | `record_review` with a non-UUID `execution_id` → `CoderFailure("invalid_arguments")`, ledger unchanged; fails on `dev` |
| `test_record_review_publishes_review_artifact`, `test_record_review_without_store_fails_before_ledger_write` | 2 | existing; unchanged |

### Validation Contract

tests:
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py
markers: none

## 5. Acceptance Criteria
- [ ] `_run_record` no longer calls `subprocess.run`; it reads HEAD through `run_bounded` with `GIT_TIMEOUT_S` and
      `git_env()`, and raises `subprocess.CalledProcessError` on a non-zero rc.
- [ ] `main` maps `EvidenceCorruptionError` to `operation_error` / exit 1; the `CalledProcessError` message includes
      git's stderr when there is any.
- [ ] `record` output carries `execution_id_generated`; `--help` for `--execution-id` describes the fallback.
- [ ] `record_review` raises `CoderFailure("invalid_arguments")` when `ReviewArtifact` validation fails, before any
      ledger write; the `put_artifact` error mapping is unchanged.
- [ ] The three new CLI tests and the new engine test exist; the corruption, blocking-call and engine tests fail
      without the fix and pass with it.
- [ ] Both Validation Contract files pass; `ruff check` is clean on the changed files.

## 6. Codebase Contract

Verified against `origin/dev` @ `25e8f657c5`.

### Verified Imports
```python
from parrot.flows.dev_loop.procs import git_env, run_bounded  # verified: checkpoint.py:58 uses the same import
from parrot.flows.dev_loop.sdd_coder.checkpoint import GIT_TIMEOUT_S  # verified: checkpoint.py:105 (module constant)
from parrot.flows.dev_loop.sdd_coder.evidence import EvidenceCorruptionError, ExecutionEvidenceStore  # verified: evidence.py:65; review_checkpoint.py:33 imports ExecutionEvidenceStore
from pydantic import ValidationError as PydanticValidationError  # verified: engine.py:29
from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine  # verified: test_feedback.py:12
from parrot.knowledge.wiki.ledger.coder_reviews import CoderReview  # verified: test_feedback.py:17
```

### Existing Signatures
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/procs.py
async def run_bounded(argv: Sequence[str], *, cwd: Optional[str] = None, timeout_s: float = ..., env: Optional[Mapping[str, str]] = None) -> Tuple[int, str, str]  # 124 timeout, 127 spawn failure; never raises for those
def git_env(base: Optional[Mapping[str, str]] = None) -> Dict[str, str]
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/evidence.py
class EvidenceConflictError(ValueError)  # :61
class EvidenceCorruptionError(RuntimeError)  # :65
async def ExecutionEvidenceStore.put_artifact(self, execution_id: str, payload: BaseModel) -> EvidenceRef  # :170
# packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py
async def _run_record(*, feature, task, worktree, summary, execution_id, fix_commits, store) -> dict[str, object]  # :89; subprocess.run :100-105; return :117
def main(argv: list[str] | None = None) -> int  # :120; docstring exit codes :123; --execution-id :144; uuid fallback :172; except CalledProcessError :187; except OSError :196
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
class CoderFailure(Exception): def __init__(self, code: str, message: str, **details: Any)  # :167
async def SddCoderEngine.record_review(self, feature: str, worktree: str, review: CoderReview, execution_id: Optional[str] = None) -> CoderReviewReceipt  # :2742; ReviewArtifact( :2784; try/put_artifact :2797-2800
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py
ERROR_CODES  # :49, contains "invalid_arguments"
```

### Does NOT Exist
- No `execution_id_generated` key anywhere in the `record` output.
- No catch of `EvidenceCorruptionError` in `review_checkpoint.main`.
- No validation of `record_review`'s `execution_id` argument before `ReviewArtifact(...)`.
- No async git helper in `review_checkpoint.py` (only the synchronous `subprocess.run`).

### Edit Sites (Blueprint Anchors)
| File | Anchor | Line | Count | Action |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py` | `from parrot.flows.dev_loop.sdd_coder.checkpoint import (` | 24 | 1 | MODIFY (procs import before; `GIT_TIMEOUT_S` into the list) |
| same | `from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore` | 33 | 1 | MODIFY |
| same | `    head_sha = subprocess.run(` | 100 | 1 | MODIFY (through `).stdout.strip()` :105) |
| same | `    Exit codes: 0 success, 1 operation error, 2 invalid input, 3 stale/busy.` | 123 | 1 | MODIFY (docstring after) |
| same | `    record_parser.add_argument("--execution-id")` | 144 | 1 | MODIFY |
| same | `            execution_id = args.execution_id or str(uuid.uuid4())` | 172 | 1 | MODIFY |
| same | `    except subprocess.CalledProcessError as exc:` | 187 | 1 | MODIFY |
| same | `    except OSError as exc:` | 196 | 1 | MODIFY |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | `            artifact = ReviewArtifact(` | 2784 | 1 | MODIFY (wrap in try) |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py` | end of file | 381 | 1 | MODIFY |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py` | `def test_coder_review_accepts_brief_task_ids() -> None:` | 372 | 1 | MODIFY (new test before) |

## 7. Implementation Notes & Constraints
- Keep `print(json.dumps(...))` in `main`: it is the CLI's output contract, as in the existing branches.
- Tests must not depend on git's message language: assert the error code and exit code, not git's stderr text.
- In the no-git test, put an empty directory first on `PATH`; `run_bounded` resolves `git` through the child
  environment that `git_env()` copies from `os.environ`.
- In the not-a-repo test, set `GIT_CEILING_DIRECTORIES` to `tmp_path` so git cannot find a parent repository.
- Run the tests in the worktree with `PYTHONPATH=packages/ai-parrot/src`.
- Ledger linkage: `issue:f64fd3bb663f`.

### Known Risks / Gotchas
- `run_bounded` puts the spawn-failure reason in stderr and returns rc 127; without appending stderr, a missing git
  binary would read "returned non-zero exit status 127".
- `pydantic.ValidationError` subclasses `ValueError`; moving the construction into the existing `put_artifact` `try`
  would map it to `evidence_persistence_failed`, so the construction gets its own `try`.

## Worktree Strategy
One feature worktree, two modules, one task. No shared files, no exclusive resources, no cross-feature dependency.
`issue:2d1816987583` (`finalize_task.py`, planned as FEAT-867 by another session) touches a different file.

## Decisions

## Decision Waivers

## Consequences

<!-- decision-audit: input_digest=sha256:48bdfc4dfcaed1c1dcc3f42be3507678839a1da3dfccc9b21210396978f52bcc evaluation_digest=sha256:c205fdb627803798687d46922c63b36c5dfaaf237991f1d38e2dce4c163614ef rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/sdd-coder-engine-fixes-4.spec.md; message: no fenced yaml block under '## Decisions'

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
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/sdd-coder-engine-fixes-4.spec.md"
    }
  ],
  "evaluation_digest": "sha256:c205fdb627803798687d46922c63b36c5dfaaf237991f1d38e2dce4c163614ef",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:48bdfc4dfcaed1c1dcc3f42be3507678839a1da3dfccc9b21210396978f52bcc",
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
- [x] Require `--execution-id` or document the fallback? — *Resolved in /sdd-fix research*: document it and surface
      `execution_id_generated`; `/sdd-start` relies on the fallback.
- [x] Map an artifact `ValidationError` to `invalid_arguments` or `evidence_persistence_failed`? — *Resolved*:
      `invalid_arguments`; the failing fields come from the caller.

## 9. Design Research Cross-Check
Status: skipped (no accepted exploration document)

## 10. Documentation
None: the CLI help text and `main`'s docstring describe the fallback; no wiki page documents `task review record`.

## Revision History
| Date | Change |
|---|---|
| 2026-11-10 | Initial spec from `/sdd-fix` group `fixgroup:598e64d75d73` |
