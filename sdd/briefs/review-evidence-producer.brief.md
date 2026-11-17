---
kind: brief
slug: review-evidence-producer
key: review-evidence-producer
base_branch: dev
source:
  type: text
  ref: "operator report 2026-11-09: FEAT-860 sdd-worker blocked closing tasks with parrot sdd task finalize"
  url: null
jira_issue_key: null
ledger_issue: null
created: "2026-11-09"
---

# Brief: Produce the review evidence that `parrot sdd task finalize` requires

<!-- FEAT-698. One brief = one fix. Task files live in sdd/briefs/<slug>/tasks/. -->

## Problem

The FEAT-860 `sdd-worker` (2026-11-09) merged TASK-5443 and TASK-5444, got green merge-tier validation, and
then stopped instead of closing them:

> I've paused on closing the first two tasks because I can't build the review_evidence that parrot sdd task
> finalize requires. [...] Nothing I have can create one. parrot sdd task review only has prepare and validate,
> and coder_record_review takes a plain string, not a reference. The only way I see is calling
> ExecutionEvidenceStore.put_artifact from Python and writing my own review summary into the store.

Chunk 1 could not be dispatched until the two tasks were closed. Earlier closes (for example passkey-support,
2026-10-30) only worked because the orchestrator hand-wrote a `<sha256>.md` file into
`executions/<id>/artifacts/` and referenced it. The manual `/sdd-start` path has the same gap: its close step
also requires `review_evidence` and nothing in its toolset produces it.

## Root cause

`parrot sdd task finalize` requires `TaskCompletionEvidence.review_evidence` to be an `EvidenceRef`
(`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py:216`), and
`_verify_evidence_refs` resolves it by hash and size under the durable root
(`packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py:167`). No component produces that reference.
`CoderReview.review_evidence` is a 600-character string
(`packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py:34`). `SddCoderEngine.record_review`
only appends a ledger measurement and returns `CoderFeedbackReceipt(feedback_id)`
(`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:2742`, `:2781`). `review_checkpoint.py`
exposes only `prepare` and `validate`. `inspection.py:351` says so directly: "No producer in this task's scope
yet publishes lint/test/review evidence". The worker prompt (`.claude/agents/sdd-worker.md:406` on
`origin/dev`) asks for "this task's own recorded review evidence ref" and never says how to record one.
Separately, `finalize` never opens the review artifact, so any durable file passes as review evidence,
including a validation log.

## Research findings

- **Precedent.** `record_native_observation` (`engine.py:1562`) checks identity against the engine's own
  bookkeeping, raises `CoderFailure("evidence_persistence_failed", ...)` before writing anything when
  `self._evidence_store is None` (`engine.py:1627`), and returns an `EvidenceRef`.
- **Store.** `ExecutionEvidenceStore.put_artifact` (`evidence.py:170`) writes canonical JSON to
  `executions/<execution_id>/artifacts/<sha256>.json` with `media_type="application/json"`. The
  `execution_id` must be a canonical UUID (`evidence.py:194`).
- **One durable root.** The engine binds its store at `engine.py:578`. `finalize_task.py:511` and
  `review_checkpoint._build_store` both resolve the root with
  `resolve_durable_root(<SDD_CODER_TELEMETRY_DIR env or None>, worktree_base_path=...)`, so a reference
  published by the engine or by the CLI resolves in `finalize`.
- **Blast radius of `record_review`.** `SddCoderToolkit.coder_record_review` (`toolkit.py:381`) and two tests
  in `tests/flows/dev_loop/sdd_coder/test_feedback.py` (L237, L522). `CoderFeedbackReceipt` is shared with
  `record_feedback`, so it must not change shape.
- **Prompt copies that describe the close.** `.claude/agents/sdd-worker.md` and its `_assets/claude/agents`
  twin; `.agents/agents/sdd-worker/agent.md` and its `_assets/agents/agents` twin;
  `.agents/skills/sdd-start/SKILL.md` and its twin; `.claude/commands/sdd-start.md` and its
  `_assets/claude/commands` twin. Each pair is byte-identical today.
- **Ledger.** `issue:cb467a1f6ade` (major, open): `finalize_task` / `review_checkpoint` crash in a managed
  runtime without the navconfig env tree. Not fixed here; the new `record` subcommand inherits it.
- **Prior art.** PR #1968 (merged 2026-11-05) fixed `record_review` model validation over MCP. It is
  unrelated to the evidence reference.

## Decisions

1. **Finalize hardening (Q&A):** `finalize` opens the review artifact and requires a `ReviewArtifact` for the
   same `task_id`. It does not require the recorded HEAD to equal `implementation_sha`, because later lint
   commits would break that.
2. **Manual path (Q&A):** add `parrot sdd task review record`, so `/sdd-start` can publish its review too.

Settled by research, not asked:

- One shared model, `ReviewArtifact`, in `optimization_models.py`, used by the engine, the CLI and
  `finalize`. A second model, `CoderReviewReceipt`, is the new return type of `record_review`.
- `record_review` with an `execution_id`: the durable store is required (no store means
  `evidence_persistence_failed` before any write). The artifact is published **before** the ledger append,
  because an orphan content-addressed artifact is harmless and a ledger row without evidence is not. Without
  an `execution_id` (direct historical callers) the behaviour stays ledger-only and `review_ref` is `None`.
- `review record --execution-id` is optional; when omitted the command generates a UUID4 and prints it.
- The manual path's `validation_refs` gap is out of scope.

## Fix plan

- **HOTFIX-review-evidence-producer-1** — `ReviewArtifact` and `CoderReviewReceipt` models;
  `record_review` publishes the artifact and returns its reference; worker prompts (four files) record the
  review before `finalize` and pass the returned `review_ref`.
- **HOTFIX-review-evidence-producer-2** — `finalize` opens the review artifact and requires
  `kind == "task_review"` and a matching `task_id`; test fixtures publish real `ReviewArtifact`s. Depends on 1.
- **HOTFIX-review-evidence-producer-3** — `parrot sdd task review record` subcommand; `/sdd-start` prompts
  (four files) use it. Depends on 1.

## Validation commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_agy_worker_prompt.py -q`
