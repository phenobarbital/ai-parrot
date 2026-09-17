---
id: F006
query_id: Q006
type: read
intent: Feedback migration has identity and retrieval compatibility risks
executed_at: 2026-09-17T21:50:09.640444+00:00
duration_ms: null
parent_id: null
depth: 1
---

# F006 — Feedback migration has identity and retrieval compatibility risks

## Summary

CoderFeedback.feedback_id is a stable coder-feedback: hash, with first occurrence winning on replay. context groups by pattern within backend/model, ranks file scope then recurrence then timestamp, applies max_age_days, and packs whole lessons including verification. PostgreSQL episodes use UUID keys, so feedback_id cannot universally become episode_id unchanged. Preserve a legacy alias and deterministic UUID mapping, historical timestamps, recurrence deduplication and full verification text. An embedding-only adapter would remove working feedback when no embedding provider is configured.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py`
  lines: 67-71
  symbol: `CoderFeedback.feedback_id`
  excerpt: |
        def feedback_id(self) -> str:
            """Stable occurrence key: retries of the recording call are not recurrences."""
            key = [self.backend, self.model, self.task_id, self.attempt_uid, self.pattern]

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py`
  lines: 96-185
  symbol: `CoderFeedbackStore.record / _read / context`
  excerpt: |
                fact=feedback.model_dump_json(),
                derived_from=f"task:{feedback.task_id}",
                about=[f"file:{path}" for path in feedback.files],
            )

- path: `packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py`
  lines: 118-149
  symbol: `PgVectorBackend episode DDL`
  excerpt: |
                await conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self._fqtn} (
                        episode_id      UUID PRIMARY KEY,
                        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

## Notes

Read-only inspection at dev HEAD 9ab95566e5982dbc3fe1cee8b03789ddcf6f161c. Proposed changes are inferences, not existing APIs. Range excerpts are locators; the summary uses the inspected surrounding range.

Amended 2026-09-18 (diagnostic review): the original citation ranges `77-85` / `101-215` were wrong — the file has 185 lines and line 77 is `CoderFeedbackReceipt.feedback_id` (a field), not the `CoderFeedback.feedback_id()` method. Ranges corrected to `67-71` and `96-185`; the summary was re-verified against the file and is unchanged.
