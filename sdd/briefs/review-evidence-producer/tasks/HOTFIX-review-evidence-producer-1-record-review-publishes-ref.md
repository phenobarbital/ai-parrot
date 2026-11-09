# HOTFIX-review-evidence-producer-1: `coder_record_review` publishes the review and returns its `EvidenceRef`

**Feature**: review-evidence-producer — produce the review evidence that `parrot sdd task finalize` requires
**Spec**: `sdd/briefs/review-evidence-producer.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`finalize` needs `review_evidence` as a durable `EvidenceRef`, and nothing produces one (brief, Root cause).
This task makes `coder_record_review` the producer for the MCP worker path: it publishes a `ReviewArtifact`
into the execution's durable store and returns the reference next to the ledger receipt. The worker prompts
then record the review **before** `finalize` and pass the returned reference.

## Scope

In `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py`, next to `EvidenceRef`:

- `ReviewArtifact(OptimizationModel)`:
  - `schema_version: Literal[1] = 1`
  - `kind: Literal["task_review"] = "task_review"`
  - `feature_slug: str = Field(min_length=1)`
  - `task_id: str = Field(pattern=_TASK_ID_PATTERN)`
  - `execution_id: str = Field(min_length=1)`
  - `source: Literal["coder_review", "manual"]`
  - `summary: str = Field(min_length=1, max_length=4000)`
  - `fix_commits: list[str] = Field(default_factory=list)`, each a full SHA (`_check_full_sha`)
  - `head_sha: str`, a full SHA (`_check_full_sha`); informational, never compared by `finalize`
  - `recorded_at: datetime`
  - `attempt_uid: str | None = None`, `backend: str | None = None`, `model: str | None = None`
- `CoderReviewReceipt(OptimizationModel)`: `feedback_id: str`, `review_ref: EvidenceRef | None = None`.

In `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py`: widen `CoderReview.task_id` to the
same pattern as `_TASK_ID_PATTERN` (`TASK-NNN` or a brief's `HOTFIX-<KEY>-<n>`), written inline as a string.
Do not import from `sdd_coder` (the ledger package must not depend on it).

In `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py`, `SddCoderEngine.record_review`:

- Return type becomes `CoderReviewReceipt`.
- After the existing attempt and fix-commit checks, and only when `execution_id` is not `None`:
  1. `self._evidence_store is None` → `CoderFailure("evidence_persistence_failed", ...)` before any write.
  2. Read the feature worktree HEAD with the module's `_git("rev-parse", "HEAD", cwd=ctx.worktree)`.
  3. Build `ReviewArtifact(source="coder_review", feature_slug=ctx.feature, task_id=review.task_id,
     execution_id=execution_id, summary=review.review_evidence, fix_commits=review.fix_commits, head_sha=<HEAD>,
     recorded_at=<UTC now>, attempt_uid=..., backend=..., model=...)`.
  4. `ref = await self._evidence_store.put_artifact(execution_id, artifact)`; map `ValueError`, `OSError` and
     the store's corruption error to `CoderFailure("evidence_persistence_failed", ...)`.
- Then the existing ledger append. Publish **before** the ledger append (brief, Decisions).
- Return `CoderReviewReceipt(feedback_id=<ledger receipt>.feedback_id, review_ref=ref)`; `review_ref=None`
  when `execution_id` is `None` (ledger-only, as today).

In `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py`: extend the `coder_record_review`
docstring (it is the LLM-facing description): the result carries `review_ref`, the `EvidenceRef` to pass as
`TaskCompletionEvidence.review_evidence` to `parrot sdd task finalize`.

Worker prompts, each pair kept byte-identical:
`.claude/agents/sdd-worker.md` = `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md`, and
`.agents/agents/sdd-worker/agent.md` = `packages/ai-parrot/src/parrot/sdd/_assets/agents/agents/sdd-worker/agent.md`.

- Step 4, `merged` → on green: before writing the `TaskCompletionEvidence`, finish the semantic review and call
  `coder_record_review`; set `review_evidence` to the `review_ref` from its result. Never hand-write an
  artifact into the evidence store.
- "Measure every reviewed delivery": say the call returns `review_ref` for `finalize`, and record each review
  before that task's `finalize` (today it says "before the next chunk").

**NOT in scope**: `finalize` validation of the artifact (task 2); the `parrot sdd task review record` CLI and
the `/sdd-start` prompts (task 3); `CoderFeedbackReceipt` (shared with `record_feedback`, unchanged);
`inspection.py`'s `"review_evidence": "unknown"` field; the managed-runtime crash `issue:cb467a1f6ade`.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py` | MODIFY | `ReviewArtifact`, `CoderReviewReceipt` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py` | MODIFY | `CoderReview.task_id` accepts `HOTFIX-<KEY>-<n>` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | `record_review` publishes and returns the ref |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` | MODIFY | `coder_record_review` docstring |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py` | MODIFY | new tests below |
| `.claude/agents/sdd-worker.md` | MODIFY | close step uses `review_ref` |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md` | MODIFY | byte-identical twin |
| `.agents/agents/sdd-worker/agent.md` | MODIFY | close step uses `review_ref` |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/agents/sdd-worker/agent.md` | MODIFY | byte-identical twin |

## Codebase Contract (Anti-Hallucination)

### Verified anchors (origin/dev @ b410d43ac4, 2026-11-09)

- `optimization_models.py:35` — `_TASK_ID_PATTERN = r"^(?:TASK-\d{1,5}|HOTFIX-[A-Za-z0-9][A-Za-z0-9._-]*-\d{1,5})$"`
- `optimization_models.py:81` — `def _check_full_sha(value: str) -> str:`
- `optimization_models.py:118` — `class OptimizationModel(BaseModel):` (`extra="forbid"`)
- `optimization_models.py:124` — `class EvidenceRef(OptimizationModel):`
- `coder_reviews.py:29` — `task_id: str = Field(pattern=r"^TASK-\d{1,5}$")` (inside `class CoderReview`)
- `coder_reviews.py:34` — `review_evidence: str = Field(min_length=1, max_length=600)`
- `engine.py:251` — `class _FeatureCtx:` with `worktree`, `feature_id`, `feature`, `feature_branch`
- `engine.py:578` — `self._evidence_store = ExecutionEvidenceStore(durable_root)`
- `engine.py:1627` — `if self._evidence_store is None:` (the `record_native_observation` precedent)
- `engine.py:2740` — `async def record_review(` ; `engine.py:2781` — `return await CoderReviewStore(store.log).record(measurement)`
- `evidence.py:170` — `async def put_artifact(self, execution_id: str, payload: BaseModel) -> EvidenceRef:`
- `toolkit.py:381` — `async def coder_record_review(`
- `.claude/agents/sdd-worker.md:406` — `` `review_evidence=<this task's own recorded `` ; `:492` — `**Measure every reviewed delivery**`
- `.agents/agents/sdd-worker/agent.md:405` and `:510` — the same two passages
- `tests/flows/dev_loop/sdd_coder/test_feedback.py:237` — `test_review_commit_validation_and_zero_fix_baseline`

### Existing Signatures to Use

- `ExecutionEvidenceStore.put_artifact(execution_id, payload) -> EvidenceRef` (canonical JSON at
  `executions/<id>/artifacts/<sha256>.json`, `media_type="application/json"`; `execution_id` must be a UUID)
- `CoderReviewStore(store.log).record(measurement) -> CoderFeedbackReceipt`
- `CoderFailure(code, message)`

### Does NOT Exist

- `ReviewArtifact`, `CoderReviewReceipt` (this task creates them)
- any `review_ref` / `EvidenceRef` in today's `record_review` result
- a `parrot sdd task review record` subcommand (task 3)

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py", "action": "MODIFY"},
    {"path": ".claude/agents/sdd-worker.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md", "action": "MODIFY"},
    {"path": ".agents/agents/sdd-worker/agent.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/agents/agents/sdd-worker/agent.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.record_review",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py#SddCoderToolkit.coder_record_review",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/evidence.py#ExecutionEvidenceStore.put_artifact",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py#EvidenceRef",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py#CoderReview"
  ]
}
```

## Acceptance Criteria

- [ ] `record_review(..., execution_id=<uuid>)` returns a `CoderReviewReceipt` whose `review_ref` resolves
      under the durable root, and the file parses as a `ReviewArtifact` with `kind="task_review"`,
      `source="coder_review"`, the review's `task_id` and the worktree HEAD.
- [ ] With `execution_id` and no durable store, `record_review` raises `evidence_persistence_failed` and the
      ledger has no new review row.
- [ ] Without `execution_id`, the ledger row is written and `review_ref` is `None`.
- [ ] `CoderReview(task_id="HOTFIX-review-evidence-producer-1", ...)` validates; `TASK-12345` still does.
- [ ] Over MCP, `coder_record_review` returns `data.feedback_id` and `data.review_ref`.
- [ ] Both prompt pairs are byte-identical; neither tells the worker to write into the evidence store by hand.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_mcp_local.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_agy_worker_prompt.py -q`

## Test Specification

Add to `test_feedback.py`, reusing the existing `git_sandbox_feature` setup of
`test_review_commit_validation_and_zero_fix_baseline` and a temporary durable root:

- `test_record_review_publishes_review_artifact` — the ref resolves, hash and size match, and the parsed
  `ReviewArtifact` carries `source`, `task_id`, `execution_id` and `head_sha`.
- `test_record_review_without_store_fails_before_ledger_write` — `evidence_persistence_failed`, no ledger row.
- `test_record_review_without_execution_id_is_ledger_only` — `review_ref is None`.
- `test_coder_review_accepts_brief_task_ids`.

## Agent Instructions

Read the brief first. Touch only the listed files. Keep each prompt pair byte-identical (copy the edited file
over its twin). Run the validation commands with `PYTHONPATH=packages/ai-parrot/src` from the worktree root.

## Completion Note

Pending; populated by the task finalizer after implementation and validation.
