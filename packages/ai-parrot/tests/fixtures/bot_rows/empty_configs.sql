-- Fixture: bot row with empty (default) FEAT-133 configs.
--
-- Precondition: creation.sql must have been applied first (it is idempotent).
-- Used by: tests/manager/test_bot_loading_with_factories.py (TASK-911 AC7).
--
-- The JSONB DEFAULT '{}'::JSONB on both columns means omitting them here
-- is equivalent to passing empty configs — no reranker, no parent-searcher.

INSERT INTO navigator.ai_bots (
    name,
    llm,
    model_name,
    use_vector
) VALUES (
    'test_bot_empty',
    'openai',
    'gpt-4o-mini',
    FALSE
)
ON CONFLICT (name) DO NOTHING;

-- Explicit comment: reranker_config and parent_searcher_config default to
-- '{}'::JSONB so create_reranker({}) and create_parent_searcher({}, store=…)
-- both return None — preserving pre-FEAT-133 behaviour.
