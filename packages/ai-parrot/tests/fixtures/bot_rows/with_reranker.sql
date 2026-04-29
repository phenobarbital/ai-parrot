-- Fixture: bot row with full FEAT-133 reranker + parent-searcher config.
--
-- Precondition: creation.sql must have been applied first (it is idempotent).
-- Used by: tests/manager/test_bot_loading_with_factories.py (TASK-911 AC6).
--
-- NOTE: ``create_reranker`` and ``create_parent_searcher`` must be patched
-- in the test so that no real cross-encoder weights are downloaded.

INSERT INTO navigator.ai_bots (
    name,
    llm,
    model_name,
    use_vector,
    vector_store_config,
    reranker_config,
    parent_searcher_config
) VALUES (
    'test_bot_full',
    'openai',
    'gpt-4o-mini',
    TRUE,
    '{"name": "postgres", "schema": "public", "table": "test_chunks", "dimension": 384}'::JSONB,
    '{"type": "local_cross_encoder", "model_name": "cross-encoder/ms-marco-MiniLM-L-6-v2", "device": "cpu"}'::JSONB,
    '{"type": "in_table", "expand_to_parent": true}'::JSONB
)
ON CONFLICT (name) DO UPDATE
    SET reranker_config        = EXCLUDED.reranker_config,
        parent_searcher_config = EXCLUDED.parent_searcher_config;
