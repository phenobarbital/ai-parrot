# TASK-5459: finalize binds the ReviewArtifact to feature, branch history and fix commits

**Feature**: FEAT-867 — finalize_task binds the ReviewArtifact to the feature and the branch history
**Spec**: `sdd/specs/scripts-finalize-task-tech-debt.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:2d1816987583`

---

## Context

`parrot sdd task finalize` accepts `TaskCompletionEvidence.review_evidence` when it resolves to a
durable `ReviewArtifact` whose `task_id` matches (`_verify_evidence_refs`, finalize_task.py:152).
It never compares the artifact's `feature_slug`, `head_sha` or `fix_commits`. So a review recorded
for the same task id in another feature, on another branch, or with reviewer corrections the evidence
omits, passes. This task implements spec §2 items 1–3 (feature, lineage and correction binding).

---

## Scope

- Add a `repo_root: Path` parameter to `_verify_evidence_refs` and pass it from `finalize_task`.
- Refuse a `ReviewArtifact` whose `feature_slug != evidence.feature_slug`.
- Refuse a `ReviewArtifact` whose `fix_commits` are not all in `evidence.fix_commits`, listing the missing SHAs.
- Refuse a `ReviewArtifact` whose `head_sha` is not an ancestor of (or equal to)
  `evidence.implementation_sha`, using `git merge-base --is-ancestor`. Any non-zero exit is a
  refusal (fail-closed).
- Update the `_verify_evidence_refs` docstring to state the new identity checks.
- Add the five regression tests from spec §4, and a keyword-only `fix_commits` parameter on the
  `_review_artifact_bytes` test helper.

**NOT in scope**: changing `SddCoderEngine.record_review` or `review_checkpoint._run_record`
(under rework for `issue:f64fd3bb663f`; slug normalization there is a separate follow-up);
requiring `head_sha == implementation_sha`; brief indexes in finalize; any model or CLI change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py` | MODIFY | Three identity checks in `_verify_evidence_refs`; pass `repo_root` from `finalize_task` |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py` | MODIFY | `fix_commits` kwarg on `_review_artifact_bytes`; five regression tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# finalize_task.py already imports everything it needs (no new imports):
from parrot.flows.dev_loop.sdd_coder.optimization_models import EvidenceRef, ReviewArtifact, TaskCompletionEvidence  # verified: finalize_task.py:50

# test_finalize_task.py already imports everything it needs (no new imports):
from parrot.flows.dev_loop.sdd_coder.optimization_models import EvidenceRef, ReviewArtifact, TaskCompletionEvidence  # verified: test_finalize_task.py:22
from scripts.sdd.finalize_task import InvalidEvidenceError, finalize_task  # verified: test_finalize_task.py:24-32
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py
class InvalidEvidenceError(FinalizeTaskError): ...                                   # line 71
def _run_git(args: Sequence[str], *, cwd: Path, env: dict[str, str] | None = None,
             check: bool = True) -> subprocess.CompletedProcess[str]: ...           # line 108
def _validate_expected_head(evidence, expected_head: str, repo_root: Path) -> None   # line 137 — proves worktree HEAD == implementation_sha
def _verify_evidence_refs(durable_root: Path, evidence: TaskCompletionEvidence) -> None:  # line 152 (only caller: line 545)
    #   line 167-173: review_artifact = ReviewArtifact.model_validate(...)
    #   line 174:     if review_artifact.task_id != evidence.task_id: raise InvalidEvidenceError(... {review_ref.relative_path!r})
    #   line 179:     for ref in evidence.validation_refs: _verify_one_ref(durable_root, ref)
def finalize_task(*, evidence, worktree: Path, expected_head: str) -> dict[str, object]:  # line 510
    #   line 520: repo_root = _git_toplevel(worktree)
    #   line 545: _verify_evidence_refs(durable_root, evidence)   (inside "validation: never mutates" block)

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py
class ReviewArtifact(OptimizationModel):           # line 134
    feature_slug: str                              # min_length=1
    task_id: str
    fix_commits: list[str]                         # full 40-hex SHAs (validated)
    head_sha: str                                  # full 40-hex SHA (validated)
class TaskCompletionEvidence(OptimizationModel):   # line 244
    feature_slug: str
    task_id: str
    implementation_sha: str                        # full 40-hex SHA
    review_evidence: EvidenceRef
    fix_commits: list[str]                         # full 40-hex SHAs

# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py
def _git(args: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]  # line 65
def _build_repo(repo_root: Path, *, task_id: str, feature_slug: str, impl_file: str = "src/demo/foo.py",
                extra_tracked_files: dict[str, bytes] | None = None) -> tuple[Path, Path, str]  # line 92 → (task_md_path, index_path, implementation_sha=HEAD)
def _make_evidence_ref(durable_root: Path, relative_path: str, content: bytes) -> EvidenceRef  # line 174
def _review_artifact_bytes(*, task_id: str, feature_slug: str, execution_id: str, implementation_sha: str) -> bytes  # line 188 (implementation_sha becomes head_sha)
def _build_evidence(durable_root: Path, *, task_id: str, feature_slug: str, implementation_sha: str,
                    completion_facts: dict[str, object] | None = None) -> TaskCompletionEvidence  # line 205 (fix_commits=[])
def test_review_artifact_must_match_task_id(...)   # line 312 — the pattern every new test follows
```
`_build_repo`, `_build_evidence` and `_git` are also imported by
`tests/flows/dev_loop/sdd_coder/test_optimization_workflow_contracts.py:42-44`. Do not change their signatures.

### Does NOT Exist
- ~~`ReviewArtifact.implementation_sha`~~: the artifact's lineage anchor is `head_sha`.
- ~~a FEAT-ID → slug resolver in `finalize_task.py`~~: do not add one (producer-side follow-up).
- ~~`_verify_review_binding` / `_verify_review_lineage`~~: no such helper exists. Put the checks inline in `_verify_evidence_refs`.
- ~~`fix_commits` parameter on `_review_artifact_bytes`~~: does not exist yet; this task adds it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py#_verify_evidence_refs",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py#finalize_task",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py#_run_git",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py#InvalidEvidenceError",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py#ReviewArtifact",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py#TaskCompletionEvidence",
    "sym:packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py#_review_artifact_bytes",
    "sym:packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py#_build_evidence",
    "sym:packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py#_build_repo",
    "sym:packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py#_make_evidence_ref"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
The existing `task_id` check (finalize_task.py:174) is the pattern: compare, then raise
`InvalidEvidenceError` with an f-string that ends in `{review_ref.relative_path!r}`. The existing tests
match on that path (`match="review-other-task"`), so every new message must also contain it.

### Key Constraints
- Read-only: the new checks only read the parsed artifact and run one `git merge-base --is-ancestor`.
  They run inside the existing "never mutates" block, before the index/task files are touched.
- `_run_git(..., check=False)` and branch on `returncode`: 0 = pass, everything else = refusal.
  Never let `CalledProcessError` escape from this check.
- Order the checks pure first (feature_slug, fix_commits), then git (lineage), so a cheap mismatch
  never spawns a subprocess.
- No new imports in either file.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` `SddCoderEngine.record_review` uses the same `merge-base --is-ancestor` idiom for `fix_commits` (read only, do not edit).

---

## Implementation Blueprint

### Steps (in order)
1. Change the `_verify_evidence_refs` signature to take `repo_root: Path` as the third parameter — *why*: the lineage check needs the repository the evidence belongs to, and `finalize_task` already holds it.
2. Update the call at line 545 to pass `repo_root` — *why*: it is the only caller.
3. Insert the three checks right after the `task_id` block (before `for ref in evidence.validation_refs:`) — *why*: spec §2 places them after the existing identity check, inside the non-mutating block.
4. Update the docstring of `_verify_evidence_refs` — *why*: it currently says only "a ReviewArtifact for the task being finalized".
5. Add `fix_commits` to `_review_artifact_bytes` as a keyword-only parameter defaulting to `None` — *why*: the correction-binding test needs a review that carries fix commits, and other callers (including `test_optimization_workflow_contracts.py`) must keep working unchanged.
6. Add the five tests after `test_review_artifact_non_json_is_refused` — *why*: they sit next to the existing review-evidence tests and reuse the same setup.
7. Run the Validation Commands and `ruff check` on both files.

### `packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py` (MODIFY — signature)
```python
# occurrences: 1 (verified: grep -c 'def _verify_evidence_refs(durable_root: Path, evidence: TaskCompletionEvidence) -> None:' finalize_task.py)
# REPLACE line 152 `def _verify_evidence_refs(durable_root: Path, evidence: TaskCompletionEvidence) -> None:` with:
def _verify_evidence_refs(durable_root: Path, evidence: TaskCompletionEvidence, repo_root: Path) -> None:
```
**Why**: a positional third parameter keeps the one call site simple. No test calls the function directly (verified: `grep -rn _verify_evidence_refs tests/` returns nothing).

### `packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py` (MODIFY — docstring)
```python
    """Resolve every evidence reference against durable storage; never trust a claim.

    Rejects an empty `validation_refs` (no settled validation recorded) and
    any `EvidenceRef` whose content does not durably exist with matching
    hash and size under *durable_root*. `review_evidence` must additionally
    be a `ReviewArtifact` bound to this evidence: same `task_id` and
    `feature_slug`, every reviewer correction in `fix_commits` also listed
    by the evidence, and a `head_sha` that is an ancestor of (or equal to)
    `implementation_sha` in *repo_root* (later lint commits may move HEAD
    past the review, so equality is not required). Validation references
    remain neutral raw evidence: this function does not inspect them or
    require a passing (`outcome == "completed"`) validation.
    """
```
**Why**: replaces the existing docstring of `_verify_evidence_refs` in full, so the contract states all four identity rules.

### `packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py` (MODIFY — checks)
```python
# occurrences: 1 (verified: grep -c '    if review_artifact.task_id != evidence.task_id:' finalize_task.py)
# AFTER — insert below the 3-line raise that follows `    if review_artifact.task_id != evidence.task_id:` (verified: finalize_task.py:174-177),
#         and above `    for ref in evidence.validation_refs:` (verified: finalize_task.py:179)
    if review_artifact.feature_slug != evidence.feature_slug:
        raise InvalidEvidenceError(
            f"review evidence feature_slug {review_artifact.feature_slug!r} does not match "
            f"{evidence.feature_slug!r} (re-record the review with feature {evidence.feature_slug!r}): "
            f"{review_ref.relative_path!r}"
        )
    missing_fix_commits = sorted(set(review_artifact.fix_commits) - set(evidence.fix_commits))
    if missing_fix_commits:
        raise InvalidEvidenceError(
            f"review evidence fix_commits {missing_fix_commits} are missing from evidence.fix_commits: "
            f"{review_ref.relative_path!r}"
        )
    lineage = _run_git(
        ["merge-base", "--is-ancestor", review_artifact.head_sha, evidence.implementation_sha],
        cwd=repo_root,
        check=False,
    )
    if lineage.returncode != 0:
        # FILL IN: raise InvalidEvidenceError naming `head_sha`, both SHAs and `{review_ref.relative_path!r}`;
        #          say "is not an ancestor of" for returncode 1 and include `lineage.stderr.strip()` for any
        #          other returncode (unknown object / git error) — bounded by AC2 (both cases refuse)
        ...
```
**Why**: spec §2 items 1–3, pure checks before the subprocess. `missing_fix_commits` is sorted so the
message is deterministic. The `lineage` call runs after `_validate_expected_head`, which already proved
HEAD == `implementation_sha`, so `implementation_sha` exists in `repo_root`.

### `packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py` (MODIFY — call site)
```python
# occurrences: 1 (verified: grep -c '        _verify_evidence_refs(durable_root, evidence)' finalize_task.py)
# REPLACE line 545 with:
        _verify_evidence_refs(durable_root, evidence, repo_root)
```
**Why**: `repo_root` is bound at line 520 (`repo_root = _git_toplevel(worktree)`).

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py` (MODIFY — helper)
```python
# occurrences: 1 (verified: grep -c 'def _review_artifact_bytes(' test_finalize_task.py)
# REPLACE the helper (line 188-202) with:
def _review_artifact_bytes(
    *,
    task_id: str,
    feature_slug: str,
    execution_id: str,
    implementation_sha: str,
    fix_commits: list[str] | None = None,
) -> bytes:
    """Build the canonical review artifact content expected by finalization."""
    return (
        ReviewArtifact(
            feature_slug=feature_slug,
            task_id=task_id,
            execution_id=execution_id,
            source="manual",
            summary="Review approved.",
            fix_commits=fix_commits or [],
            head_sha=implementation_sha,
            recorded_at=datetime(2026, 11, 9, tzinfo=timezone.utc),
        )
        .model_dump_json()
        .encode("utf-8")
    )
```
**Why**: the new parameter is keyword-only with a default, so every existing caller is unchanged.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py` (MODIFY — tests)
```python
# occurrences: 1 (verified: grep -c 'def test_crash_resume_and_twin_conflict(' test_finalize_task.py)
# BEFORE — insert above `def test_crash_resume_and_twin_conflict(` (verified: test_finalize_task.py:370),
#          i.e. right after the end of `test_review_artifact_non_json_is_refused`


def _replace_review(
    evidence: TaskCompletionEvidence,
    durable_root: Path,
    name: str,
    **artifact_fields: object,
) -> None:
    """Swap the evidence's review artifact for one built from *artifact_fields*."""
    execution_id = "11111111-1111-4111-8111-111111111111"
    fields: dict[str, object] = {
        "task_id": evidence.task_id,
        "feature_slug": evidence.feature_slug,
        "execution_id": execution_id,
        "implementation_sha": evidence.implementation_sha,
    }
    fields.update(artifact_fields)
    evidence.review_evidence = _make_evidence_ref(
        durable_root,
        f"executions/{execution_id}/artifacts/{name}.json",
        _review_artifact_bytes(**fields),  # type: ignore[arg-type]
    )


def test_review_artifact_must_match_feature_slug(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A review recorded for the same task id in another feature cannot finalize this one."""
    task_id = "TASK-9108"
    feature_slug = "finalize-demo-g"
    task_md_path, _index_path, implementation_sha = _build_repo(
        tmp_path / "repo", task_id=task_id, feature_slug=feature_slug
    )
    repo_root = task_md_path.parents[3]
    durable_root = tmp_path / "durable"
    monkeypatch.setenv("SDD_CODER_TELEMETRY_DIR", str(durable_root))
    evidence = _build_evidence(
        durable_root, task_id=task_id, feature_slug=feature_slug, implementation_sha=implementation_sha
    )
    _replace_review(evidence, durable_root, "review-other-feature", feature_slug="another-feature")

    with pytest.raises(InvalidEvidenceError, match="feature_slug.*review-other-feature"):
        finalize_task(evidence=evidence, worktree=repo_root, expected_head=implementation_sha)

    assert task_md_path.is_file()
    assert not (repo_root / "sdd" / "tasks" / "completed").exists()


def test_review_head_must_be_ancestor_of_implementation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A review recorded on unrelated history is refused."""
    # FILL IN: TASK-9109 / finalize-demo-h; side_sha = _git(["commit-tree", "HEAD^{tree}", "-m", "side"], cwd=repo_root)
    #          .stdout.strip() (a root commit that is NOT an ancestor of HEAD — no branch switch needed);
    #          _replace_review(..., "review-side-branch", implementation_sha=side_sha);
    #          expect InvalidEvidenceError matching "head_sha.*review-side-branch"; assert nothing mutated (AC2)


def test_review_head_unknown_to_repo_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A well-formed head_sha that does not exist in the repository is refused (fail-closed)."""
    # FILL IN: TASK-9110 / finalize-demo-i; _replace_review(..., "review-unknown-head", implementation_sha="f" * 40);
    #          expect InvalidEvidenceError matching "review-unknown-head"; assert nothing mutated (AC2)


def test_review_head_older_ancestor_is_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A review recorded before a later (lint) commit still finalizes the moved HEAD."""
    # FILL IN: TASK-9111 / finalize-demo-j; review_sha = implementation_sha from _build_repo;
    #          rewrite src/demo/foo.py (e.g. "value = 1  # lint\n"), `git add` + `git commit -m "style: TASK-9111 lint"`,
    #          new_head = rev-parse HEAD; evidence = _build_evidence(..., implementation_sha=new_head);
    #          _replace_review(evidence, durable_root, "review-before-lint", implementation_sha=review_sha);
    #          result = finalize_task(evidence=evidence, worktree=repo_root, expected_head=new_head);
    #          assert result["replayed"] is False and the completed copy exists (AC3)


def test_review_fix_commits_must_be_in_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A review's reviewer corrections must all appear in the evidence's fix_commits."""
    # FILL IN: TASK-9112 / finalize-demo-k; fix_sha = _git(["rev-parse", "HEAD~1"], cwd=repo_root).stdout.strip();
    #          _replace_review(..., "review-with-fixes", fix_commits=[fix_sha]) while evidence.fix_commits stays [];
    #          expect InvalidEvidenceError whose message contains fix_sha and "review-with-fixes"; nothing mutated (AC4)
```
**Why**: one complete test fixes the pattern; the other four are bounded stubs over the same setup.
`_replace_review` keeps each test to the one field it varies. Task ids `TASK-9108`..`TASK-9112` are
unused in this module and in `test_optimization_workflow_contracts.py` (verified: they use 9001, 9101-9107, 9199).

### FILL IN checklist
- [ ] `finalize_task.py::_verify_evidence_refs` lineage refusal message — returncode 1 vs other; bounded by AC2
- [ ] `test_review_head_must_be_ancestor_of_implementation` body — bounded by AC2
- [ ] `test_review_head_unknown_to_repo_is_refused` body — bounded by AC2
- [ ] `test_review_head_older_ancestor_is_accepted` body — bounded by AC3
- [ ] `test_review_fix_commits_must_be_in_evidence` body — bounded by AC4

---

## Acceptance Criteria

- [ ] AC1: a `ReviewArtifact` with another `feature_slug` is refused with `InvalidEvidenceError` before any mutation.
- [ ] AC2: a `ReviewArtifact` whose `head_sha` is not an ancestor of (or equal to) `implementation_sha` is refused, including a SHA unknown to the repository.
- [ ] AC3: a `ReviewArtifact` whose `head_sha` is a strict ancestor of `implementation_sha` is accepted.
- [ ] AC4: a `ReviewArtifact` whose `fix_commits` are not all in `evidence.fix_commits` is refused, and the message lists the missing SHAs.
- [ ] AC5: every existing test in `test_finalize_task.py` and `test_optimization_workflow_contracts.py::test_stale_fix_and_full_compatibility` still passes.
- [ ] AC6: `ruff check packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py` is clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_workflow_contracts.py::test_stale_fix_and_full_compatibility -q`

---

## Test Specification

See the blueprint's test block: `test_review_artifact_must_match_feature_slug` (complete),
`test_review_head_must_be_ancestor_of_implementation`, `test_review_head_unknown_to_repo_is_refused`,
`test_review_head_older_ancestor_is_accepted`, `test_review_fix_commits_must_be_in_evidence`.
Every refusal test asserts that the task file is still under `active/` and that no `completed/`
directory exists.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug scripts-finalize-task-tech-debt --feature-id FEAT-867`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/scripts-finalize-task-tech-debt.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
   (prefix with `PYTHONPATH=packages/ai-parrot/src` inside the worktree)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5459 scripts-finalize-task-tech-debt verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: claude-opus-5-5 via /sdd-fix (actor `agent:sdd-fix:c445f42d`)
**Date**: 2026-11-10
**Notes**: `_verify_evidence_refs(durable_root, evidence, repo_root)` now refuses a `ReviewArtifact`
whose `feature_slug` differs from the evidence, whose `fix_commits` are not all in
`evidence.fix_commits` (the message lists the missing SHAs, sorted), or whose `head_sha` is not an
ancestor of (or equal to) `implementation_sha`. `git merge-base --is-ancestor` exit 1 reports
"is not an ancestor of"; any other non-zero exit reports git's stderr. Both refuse (fail-closed).
The pure checks run before the git call. The only caller (`finalize_task`) passes `repo_root`.
Implementation commit: `9653ed45b3dc3e163db3b2f1d2ab270b600fc8f1`.

Validation: `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py
packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_workflow_contracts.py::test_stale_fix_and_full_compatibility -q`
gives 12 passed (with `PYTHONPATH=packages/ai-parrot/src`, import path checked to be the worktree);
`ruff check` and `black --check -l 120` are clean on both files. Regression proof: a copy of the
new test file run against the unfixed `dev` code (`finalize_task.py` without `repo_root`) gives
4 failed (`DID NOT RAISE InvalidEvidenceError` for feature_slug, side-branch head, unknown head,
missing fix commit) and 1 passed (older ancestor accepted).

**Deviations from spec**: none. One small addition to the blueprint: a test-only
`_review_binding_setup` helper shares the repo/durable-root setup across the five new tests.
Resolves `issue:2d1816987583`.
