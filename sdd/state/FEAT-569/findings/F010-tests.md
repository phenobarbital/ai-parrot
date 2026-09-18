---
id: F010
query_id: Q010
type: read
intent: Existing tests encode contracts worth preserving
executed_at: 2026-09-17T21:50:09.640444+00:00
duration_ms: null
parent_id: null
depth: 1
---

# F010 — Existing tests encode contracts worth preserving

## Summary

Read tests assert default strategy delegation, default importance, feedback deduplication and backend/model isolation, file-scope ordering and bounded complete-lesson packing. Metadata tests use real FAISS and mocked PostgreSQL/Redis; they do not demonstrate concurrent review safety. Tests were inspected, not executed; there is no implementation change in this proposal.

## Citations

- path: `packages/ai-parrot/tests/memory/episodic/test_store_integration.py`
  lines: 44-99
  symbol: `TestDefaultBehaviorUnchanged`
  excerpt: |
        """Tests verifying default behavior without scorer/strategy is unchanged."""

        def test_store_constructs_without_scorer_strategy(
            self, mock_backend: AsyncMock, mock_embedding_provider: AsyncMock

- path: `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py`
  lines: 41-80
  symbol: `feedback replay and scope tests`
  excerpt: |
    @pytest.fixture
    def store(tmp_path: Path) -> CoderFeedbackStore:
        """Use an isolated durable ledger without external services."""
        return CoderFeedbackStore(LedgerLog(str(tmp_path / "events.jsonl")))

- path: `tests/memory/dream/test_update_metadata.py`
  lines: 1-75
  symbol: `TestFAISSUpdateMetadata`
  excerpt: |
    """Unit tests for AbstractEpisodeBackend.update_metadata() (TASK-1985).

    Covers all three backend implementations (FAISS real; PgVector/Redis
    mocked) plus the ``EpisodicMemoryStore.mark_consolidated()`` passthrough.

## Notes

Read-only inspection at dev HEAD 9ab95566e5982dbc3fe1cee8b03789ddcf6f161c. Proposed changes are inferences, not existing APIs. Range excerpts are locators; the summary uses the inspected surrounding range.
