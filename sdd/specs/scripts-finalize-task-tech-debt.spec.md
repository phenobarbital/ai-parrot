---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [sdd, sdd-coder, finalize-task, review-evidence, ledger-fix]
---

# Feature Specification: finalize_task binds the ReviewArtifact to the feature and the branch history

**Feature ID**: FEAT-867
**Date**: 2026-11-10
**Author**: Jesus Lara
**Status**: approved
**Target version**: next patch
**Discovered-from**: `issue:2d1816987583`

---

## 1. Motivation & Business Requirements

### Problem Statement

`parrot sdd task finalize` (`packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py`) accepts
`TaskCompletionEvidence.review_evidence` only if it resolves to a durable `ReviewArtifact`
(hotfix `review-evidence-producer`, PR #2070). `_verify_evidence_refs` (line 152) checks the
artifact's hash/size and `review_artifact.task_id == evidence.task_id`, and nothing else. Three of
the artifact's identity fields are never compared:

- `feature_slug`: plain `TASK-<N>` ids repeat across briefs (`HOTFIX-<KEY>-<N>`, and legacy
  features), so a review recorded for the same task id in another feature passes.
- `head_sha`: a review recorded on another branch, or in another clone, passes.
- `fix_commits`: a review whose reviewer corrections are missing from the evidence passes, so the
  Completion Note and the fidelity check (`_collect_changed_files`) silently omit those commits.

Source: ledger `issue:2d1816987583` (discovered from `review:HOTFIX-review-evidence-producer-2`).

### Goals

- finalize refuses a `ReviewArtifact` recorded for another feature.
- finalize refuses a `ReviewArtifact` whose `head_sha` is not in the history of the
  implementation revision being finalized.
- finalize refuses a `ReviewArtifact` whose reviewer corrections are not all in the evidence.
- Every refusal is an `InvalidEvidenceError` raised BEFORE any mutation (same contract as the
  existing checks), with a message naming the field, both values and the artifact path.

### Non-Goals

- Changing how reviews are recorded (`SddCoderEngine.record_review`,
  `review_checkpoint._run_record`). Those two functions are being reworked in parallel for
  `issue:f64fd3bb663f`, so slug normalization at write time is filed as a separate ledger issue
  (see §7) instead of being done here.
- Requiring `head_sha == implementation_sha`. The review-evidence-producer brief rejected
  equality because lint/twin-sync commits legitimately move HEAD after the review is recorded.
- Brief indexes in finalize (`sdd/briefs/<slug>.index.json`). finalize reads only
  `sdd/tasks/index/<slug>.json` today, and that is unchanged.

## 2. Architectural Design

All three checks live in `_verify_evidence_refs`, right after the existing `task_id` comparison.
They run inside the existing "validation: never mutates anything" block of `finalize_task`
(line 545), after `_validate_expected_head` has already proven that the worktree HEAD equals
`evidence.implementation_sha`.

1. **Feature binding**: `review_artifact.feature_slug == evidence.feature_slug` (exact string
   equality). Both documented producers write the per-spec index slug: the engine writes the
   index header's `feature`, which equals the file stem for every live index, and
   `/sdd-start` documents `review record --feature <slug>`. Normalizing other forms (a FEAT-ID
   passed to the CLI, or one of the 4 legacy indexes whose header `feature` differs from its file
   stem) is the producer-side follow-up. finalize fails closed on them, and the error message
   names the expected slug so the caller can re-record.
2. **Lineage binding**: `git merge-base --is-ancestor <review_artifact.head_sha>
   <evidence.implementation_sha>` run in the repository root. Exit 0 (ancestor or equal) passes.
   Exit 1 (not an ancestor) and any other exit (for example 128 for an object unknown to this
   repository) both raise `InvalidEvidenceError` (fail-closed). `_verify_evidence_refs` gains a
   `repo_root: Path` parameter for this, and its only caller passes the `repo_root` it already
   holds.
3. **Correction binding**: `set(review_artifact.fix_commits) <= set(evidence.fix_commits)`. The
   error lists the missing SHAs. The evidence may list more commits than the review, but never
   fewer.

No model changes, no CLI changes and no new dependencies are needed.

## 3. Module Breakdown

| Module | Change |
|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py` | `_verify_evidence_refs(durable_root, evidence, repo_root)`: add the three checks and update its docstring; update the call at line 545. |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py` | Add regression tests (§4). Existing fixtures already write `feature_slug == evidence.feature_slug` and `head_sha == implementation_sha`, so the existing tests keep passing unchanged. `_build_repo`, `_build_evidence` and `_git` are imported by `test_optimization_workflow_contracts.py`: keep their signatures backward compatible (new parameters are keyword-only with defaults). |

Single task.

## 4. Test Specification

### Unit Tests

New tests in `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py`. Each one
builds a real temporary repository with the existing `_build_repo` / `_build_evidence` /
`_review_artifact_bytes` helpers, and each refusal also asserts that nothing was mutated (no
journal, task still under `active/`, same as `test_review_artifact_must_match_task_id`):

- `test_review_artifact_must_match_feature_slug`: artifact `feature_slug` differs → `InvalidEvidenceError` naming `feature_slug`.
- `test_review_head_must_be_ancestor_of_implementation`: artifact `head_sha` is a commit on a side branch that is not an ancestor of HEAD → `InvalidEvidenceError` naming `head_sha`.
- `test_review_head_unknown_to_repo_is_refused`: artifact `head_sha` is a well-formed SHA that does not exist in the repository → `InvalidEvidenceError`.
- `test_review_head_older_ancestor_is_accepted`: the review is recorded at commit X, then a later commit (simulating an engine lint commit) becomes HEAD and the `implementation_sha` → finalize succeeds.
- `test_review_fix_commits_must_be_in_evidence`: artifact `fix_commits=[X]`, evidence `fix_commits=[]` → `InvalidEvidenceError` listing X.

### Validation Contract

tests:
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_workflow_contracts.py::test_stale_fix_and_full_compatibility
markers: none

## 5. Acceptance Criteria

- [ ] AC1: a `ReviewArtifact` with another `feature_slug` is refused with `InvalidEvidenceError` before any mutation.
- [ ] AC2: a `ReviewArtifact` whose `head_sha` is not an ancestor of (or equal to) `implementation_sha` is refused, including a SHA unknown to the repository.
- [ ] AC3: a `ReviewArtifact` whose `head_sha` is a strict ancestor of `implementation_sha` is accepted.
- [ ] AC4: a `ReviewArtifact` whose `fix_commits` are not all in `evidence.fix_commits` is refused, and the message lists the missing SHAs.
- [ ] AC5: every existing test in `test_finalize_task.py` and `test_optimization_workflow_contracts.py::test_stale_fix_and_full_compatibility` (which finalizes through the shared `test_finalize_task` helpers) still passes.
- [ ] AC6: `ruff check` is clean on the changed files.

## 6. Codebase Contract

### Verified Imports

- `from parrot.flows.dev_loop.sdd_coder.optimization_models import EvidenceRef, ReviewArtifact, TaskCompletionEvidence` (`finalize_task.py:50`)

### Existing Class Signatures

- `optimization_models.py:134` `class ReviewArtifact(OptimizationModel)`: `feature_slug: str`, `task_id: str`, `execution_id: str`, `source`, `summary`, `fix_commits: list[str]` (full SHAs), `head_sha: str` (full SHA), `recorded_at`, `attempt_uid`, `backend`, `model`.
- `optimization_models.py:244` `class TaskCompletionEvidence(OptimizationModel)`: `feature_slug: str`, `task_id: str`, `implementation_sha: str`, `validation_refs: list[EvidenceRef]`, `review_evidence: EvidenceRef`, `fix_commits: list[str]`, `completion_facts`.
- `finalize_task.py:71` `class InvalidEvidenceError(FinalizeTaskError)`.
- `finalize_task.py:108` `def _run_git(args, *, cwd, env=None, check=True) -> subprocess.CompletedProcess[str]`.
- `finalize_task.py:137` `def _validate_expected_head(evidence, expected_head, repo_root) -> None`: guarantees worktree HEAD == `implementation_sha` before line 545 runs.

### Edit Sites (Blueprint Anchors)

- `finalize_task.py:152` `def _verify_evidence_refs(durable_root: Path, evidence: TaskCompletionEvidence) -> None:`
- `finalize_task.py:174` `if review_artifact.task_id != evidence.task_id:` (new checks go right after this block)
- `finalize_task.py:545` `_verify_evidence_refs(durable_root, evidence)`

### Does NOT Exist (Anti-Hallucination)

- No helper in `finalize_task.py` resolves a FEAT-ID to an index slug; do not add one here (producer-side follow-up).
- `ReviewArtifact` has no `implementation_sha` field; the lineage anchor is `head_sha`.

## 7. Implementation Notes & Constraints

- Keep the "never mutates before validation passes" property: the new checks only read the
  artifact and run one read-only `git merge-base --is-ancestor`.
- Use `_run_git([...], cwd=repo_root, check=False)` and branch on `returncode`. Never treat a
  non-zero exit other than 1 as success.
- **Follow-up (separate ledger issue, not this feature)**: make both producers write the canonical
  index slug. That means `review_checkpoint._run_record` rejecting a `--feature` that does not
  resolve through `task_scheduler.resolve_index_path`, and `SddCoderEngine.record_review` writing
  the index slug instead of the header `feature` (they differ for `FEAT-156.json`,
  `FEAT-213-telegram-voice-reply-tts.json`, `FEAT-217-graph-expanded-retrieval.json`,
  `lyria-toolkit.json`). Both functions are under rework for `issue:f64fd3bb663f`.

## 8. Open Questions

None.

## Worktree Strategy

Single task, one feature worktree `feat-FEAT-867-scripts-finalize-task-tech-debt` off `origin/dev`.

## Revision History

- 2026-11-10: created by /sdd-fix from `issue:2d1816987583`.
