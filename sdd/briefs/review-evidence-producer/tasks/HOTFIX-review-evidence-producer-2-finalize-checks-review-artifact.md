# HOTFIX-review-evidence-producer-2: `finalize` requires a review artifact for the same task

**Feature**: review-evidence-producer — produce the review evidence that `parrot sdd task finalize` requires
**Spec**: `sdd/briefs/review-evidence-producer.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: HOTFIX-review-evidence-producer-1
**Assigned-to**: unassigned

---

## Context

`_verify_evidence_refs` only proves the review reference points at a durable file with a matching hash and
size. It never opens the file, so a validation log or any other artifact passes as review evidence. Task 1
creates `ReviewArtifact`; this task makes `finalize` require one, for the task being closed (brief,
Decision 1).

## Scope

In `packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py`:

- After `_verify_one_ref` has checked `evidence.review_evidence`, read the same bytes, parse them as JSON and
  validate them with `ReviewArtifact.model_validate` (import it next to the existing
  `EvidenceRef, TaskCompletionEvidence` import).
- Raise `InvalidEvidenceError` when the content is not valid JSON, is not a `ReviewArtifact` (this covers a
  wrong `kind`), or has `task_id != evidence.task_id`. Each message names the reference's `relative_path`.
- Do not compare `head_sha` with `implementation_sha` (brief, Decision 1), and do not inspect
  `validation_refs` beyond today's checks.
- Update the `_verify_evidence_refs` docstring: the review reference must now be a `ReviewArtifact` for the
  same task.

In `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py`: `_build_evidence` (L187) writes
a canonical `ReviewArtifact` JSON instead of `{"verdict": "approved"}` (L197), with `task_id` set to the task
being finalized. Add the tests below.

**NOT in scope**: producing the artifact (task 1 and task 3); journal replay of already-finalized tasks;
`validation_refs` content; the managed-runtime crash `issue:cb467a1f6ade`.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py` | MODIFY | parse and check the review artifact |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py` | MODIFY | real fixture + new tests |

## Codebase Contract (Anti-Hallucination)

### Verified anchors (origin/dev @ b410d43ac4, 2026-11-09)

- `finalize_task.py:50` — `from parrot.flows.dev_loop.sdd_coder.optimization_models import EvidenceRef, TaskCompletionEvidence`
- `finalize_task.py:71` — `class InvalidEvidenceError(FinalizeTaskError):`
- `finalize_task.py:152` — `def _verify_evidence_refs(durable_root: Path, evidence: TaskCompletionEvidence) -> None:`
- `finalize_task.py:167` — `for ref in (evidence.review_evidence, *evidence.validation_refs):`
- `finalize_task.py:171` — `def _verify_one_ref(durable_root: Path, ref: EvidenceRef) -> None:`
- `finalize_task.py:533` — `_verify_evidence_refs(durable_root, evidence)`
- `test_finalize_task.py:173` — `def _make_evidence_ref(durable_root: Path, relative_path: str, content: bytes) -> EvidenceRef:`
- `test_finalize_task.py:187` — `def _build_evidence(` ; `:197` — `... review-{task_id}.json", b'{"verdict": "approved"}'`

### Existing Signatures to Use

- `ReviewArtifact` (created by task 1 in `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py`)
- `_verify_one_ref(durable_root, ref)` — keep it as the hash/size gate; add the content check after it

### Does NOT Exist

- any content check of `review_evidence` in `finalize_task.py` today

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py#_verify_evidence_refs",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py#_verify_one_ref"
  ]
}
```

## Acceptance Criteria

- [ ] `finalize` accepts a `ReviewArtifact` reference for the same `task_id`.
- [ ] `finalize` rejects with `InvalidEvidenceError`, before any file is moved or staged: a validation log
      used as review evidence, a `ReviewArtifact` for another `task_id`, and non-JSON content.
- [ ] The existing `test_finalize_task.py` tests pass with the new fixture.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_models.py -q`

## Test Specification

Add to `test_finalize_task.py`:

- `test_review_evidence_must_be_a_review_artifact` — a validation-log reference as `review_evidence` is refused.
- `test_review_artifact_must_match_task_id` — a `ReviewArtifact` for another task is refused.
- `test_review_artifact_non_json_is_refused`.

## Agent Instructions

Read the brief first. Touch only the listed files. Run the validation commands with
`PYTHONPATH=packages/ai-parrot/src` from the worktree root.

## Completion Note

Pending; populated by the task finalizer after implementation and validation.
