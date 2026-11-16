---
id: FC-003
query_id: Q013
type: read
intent: "Find the datamodel bound to ai_bots and its column list (source of truth for current schema)."
executed_at: 2026-11-12T20:40:22Z
duration_ms: 500
parent_id: null
depth: 0
---

# FC-003 — BotModel: strict asyncdb Model, 49 fields, tolerates legacy columns in code

## Summary

`BotModel(Model)` (datamodel/asyncdb, `driver = "pg"`, `name = PARROT_BOTS_TABLE`, `schema = PARROT_SCHEMA`,
`strict = True`) declares 49 fields. Because the driver SELECTs/INSERTs every declared field by name, a column the
model declares but the table lacks breaks **every bot load** — schema drift is a hard runtime failure, not a soft one.
The model's docstring embeds yet another copy of the CREATE TABLE (incl. FEAT-752 columns), and legacy columns
dropped from the model (`model_name, temperature, max_tokens, top_k, top_p, embedding_model`) are folded in code via
`_fold_legacy_bot_columns` so both pre- and post-fold databases keep working; the comment tells operators to run
`sdd/migrations/FEAT-fold-*.sql` by hand.

## Citations

- path: `packages/ai-parrot/src/parrot/models/bots.py`
  lines: 461-468
  symbol: `BotModel.Meta`
  excerpt: |
    class Meta:
        driver = "pg"
        name = PARROT_BOTS_TABLE
        schema = PARROT_SCHEMA
        strict = True
        frozen = False

- path: `packages/ai-parrot/src/parrot/models/bots.py`
  lines: 24-40
  symbol: `_LEGACY_LLM_COLUMNS`
  excerpt: |
    # Older ``navigator.ai_bots`` tables still carry the pre-fold standalone
    # columns, and a row hydrated from such a table reaches ``BotModel`` as
    # unexpected keyword arguments, which ``Meta.strict = True`` rejects.
    # Run ``sdd/migrations/FEAT-fold-legacy-llm-columns.sql`` and
    # ``sdd/migrations/FEAT-fold-embedding-model-into-vector-store-config.sql``
    _LEGACY_LLM_COLUMNS = ("model_name", "temperature", "max_tokens", "top_k", "top_p")
    _LEGACY_EMBEDDING_COLUMN = "embedding_model"

- path: `packages/ai-parrot/src/parrot/models/bots.py`
  lines: 43-44
  symbol: `_fold_legacy_bot_columns`
  excerpt: |
    def _fold_legacy_bot_columns(kwargs: dict) -> None:
        """Fold the legacy ``ai_bots`` columns found in *kwargs* into the canonical JSONB.

- path: `packages/ai-parrot/src/parrot/models/bots.py`
  lines: 100-109
  symbol: `BotModel`
  excerpt: |
    class BotModel(Model):
        """Unified Bot Model combining chatbot and agent functionality.
        SQL Table Creation (matches production):
        CREATE TABLE IF NOT EXISTS navigator.ai_bots (

- path: `packages/ai-parrot/src/parrot/models/bots.py`
  lines: 156-161
  excerpt: |
    -- Follow-up suggestion chips (FEAT-752)
    enable_suggestions BOOLEAN DEFAULT FALSE,
    suggest_followups BOOLEAN DEFAULT FALSE,
    suggestion_timeout_s REAL DEFAULT 4.0,
    max_suggestions INTEGER DEFAULT 6,
    suggestion_model VARCHAR,

## Notes

Fields (49): chatbot_id name description avatar enabled timezone role goal backstory rationale capabilities
system_prompt_template human_prompt_template pre_instructions prompt_config llm model_config tools_enabled
auto_tool_detection tool_threshold tools toolkit_config mcp_servers operation_mode use_kb kb custom_kbs use_vector
vector_store_config reranker_config parent_searcher_config context_search_limit context_score_threshold memory_type
memory_config max_context_turns use_conversation_history enable_suggestions suggest_followups suggestion_timeout_s
max_suggestions suggestion_model bot_class permissions language disclaimer created_at created_by updated_at.
Same file also defines other navigator.* models (Meta.schema="navigator" at lines 513/595/670; ChatbotUsage is bigquery).
Three copies of the ai_bots schema exist (creation.sql, BotModel docstring, sdd/migrations) — a model-vs-DB
column diff (`--check`) is a natural feature for the migration command.
