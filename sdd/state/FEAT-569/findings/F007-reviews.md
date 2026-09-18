---
id: F007
query_id: Q007
type: read
intent: Existing coder reviews cannot supply memory-level grades
executed_at: 2026-09-17T21:50:09.640444+00:00
duration_ms: null
parent_id: null
depth: 1
---

# F007 — Existing coder reviews cannot supply memory-level grades

## Summary

CoderReview records task/attempt/backend/model, fix commits, textual evidence and execution ID; no recalled IDs, checked patterns or machine outcome receipt. The engine checks known attempt identity and reachable correction commits, then stores exposure measured using the literal [coder-feedback: text marker. It does not verify a successful merge inside record_review. Replay selects the latest measurement for an attempt, unlike feedback replay which selects the first occurrence. Grading requires immutable outcome revisions and attribution receipts, not merely calling the existing review tool.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py`
  lines: 21-44
  symbol: `CoderReview / CoderReviewMeasurement`
  excerpt: |
    class CoderReview(BaseModel):
        """Review outcome including zero-fix deliveries, supplied by the worker.

        fix_commits includes only reviewer-confirmed corrections, never engine lint

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py`
  lines: 77-107
  symbol: `CoderReviewStore.record / _report`
  excerpt: |
        async def record(self, review: CoderReviewMeasurement) -> CoderFeedbackReceipt:
            """Record the completed review; subsequent records update its measurement."""
            key = json.dumps([review.backend, review.model, review.task_id, review.attempt_uid])
            subject = "coder-review:" + hashlib.sha256(key.encode()).hexdigest()[:24]

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py`
  lines: 1433-1500
  symbol: `SddCoderEngine._feedback_for / record_review`
  excerpt: |
        async def _feedback_for(self, ctx: _FeatureCtx, task: PlannedTask, backend: str, model: str) -> str:
            """Refresh preventive feedback before each dispatch, including retries."""
            policy = self.roster.feedback
            if not policy.enabled or policy.max_tokens == 0:

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py`
  lines: 165-170
  symbol: `FeedbackConfig`
  excerpt: |
    class FeedbackConfig(BaseModel):
        """Bound historical lessons and allow a measured baseline without injection."""

        enabled: bool = True

## Notes

Read-only inspection at dev HEAD 9ab95566e5982dbc3fe1cee8b03789ddcf6f161c. Proposed changes are inferences, not existing APIs. Range excerpts are locators; the summary uses the inspected surrounding range.
