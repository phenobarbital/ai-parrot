# Changelog

All notable changes to `ai-parrot` are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added

- **FEAT-133** — DB-persisted reranker (FEAT-126) and parent-searcher
  (FEAT-128) configuration for AI bots.

  Two new JSONB columns on `navigator.ai_bots`:
  - `reranker_config JSONB DEFAULT '{}'::JSONB` — factory config for
    cross-encoder or LLM-based result reranking.
  - `parent_searcher_config JSONB DEFAULT '{}'::JSONB` — factory config for
    parent-document expansion after vector search.

  New factory modules:
  - `parrot.rerankers.factory.create_reranker(config, *, bot_llm_client=None)`
    — resolves `reranker_config` into a concrete `AbstractReranker` instance
    (or `None` for empty configs).  Supported types: `local_cross_encoder`,
    `llm`.
  - `parrot.stores.parents.factory.create_parent_searcher(config, *, store)`
    — resolves `parent_searcher_config` into a concrete
    `AbstractParentSearcher` instance (or `None`).  Supported types:
    `in_table`.

  `BotManager._load_database_bots` wiring:
  - Calls `create_reranker()` **before** bot construction and passes the
    result via the `reranker=` constructor kwarg.
  - Reads `parent_searcher_config["expand_to_parent"]` and forwards it as the
    `expand_to_parent=` kwarg to the bot constructor.
  - After `await bot.configure(app)` (when `bot.store` is available), calls
    `create_parent_searcher()` and assigns the result to
    `bot.parent_searcher`.
  - Patches the LLM reranker's `client` attribute post-configure when the
    reranker type is `llm` (option a from spec).
  - Logs an INFO line per loaded bot showing the resolved reranker and
    parent-searcher class names.
  - Unknown `type` values raise `parrot.exceptions.ConfigError` (fail-loud).
    The bot is not silently registered without its configured features.

  Validation:
  - `handlers/bots.py` POST/PUT handlers apply shallow validation
    (`isinstance(value, dict)`) on both new fields; non-dict values return
    HTTP 400.

  Back-compat:
  - Empty `{}` for either field preserves pre-FEAT-133 behaviour — no
    reranker, no parent-searcher.  Existing rows with the old schema require
    only the DDL migration to gain the new columns (idempotent ALTER TABLE
    included in `creation.sql`).

  Spec: `sdd/specs/bot-reranker-and-parent-searcher-config.spec.md`

### Changed

- **FEAT-164** — `DatabaseAgent` homologated to the `PandasAgent` shape.

  `DatabaseAgent` now inherits from `BasicAgent` (was `AbstractBot`) and
  exposes a real LLM-backed `ask()` flow that returns a strict structured
  `QueryResponse` instead of a free-text blob.

  - New base class: `parrot.bots.database.DatabaseAgent` is now a
    `parrot.bots.agent.BasicAgent` subclass.
  - System prompts assembled via a class-level
    `_prompt_builder = _build_database_prompt_builder()` mirroring
    `PandasAgent`.
  - Structured output contract: `ask()` returns an `AIMessage` whose
    `output` is a `parrot.bots.database.QueryResponse` Pydantic model
    (with optional `QueryDataset` payload). Free-text fallback when the
    provider does not honour the schema.
  - `QueryRetryConfig` is now wired end-to-end: pass
    `retry_config=QueryRetryConfig(...)` to the constructor and the agent
    re-asks the LLM after a retryable `execute_query` failure (up to
    `max_retries` attempts).

  **Breaking**: the `enable_retry: bool` parameter on `DatabaseAgent.ask`
  is removed. Pass `retry_config=QueryRetryConfig(...)` to the constructor
  instead (or omit it to disable retries entirely). No deprecation shim
  is shipped.

  **Migration path**: no production code currently imports
  `AbstractDBAgent`. Downstream code calling
  `DatabaseAgent(..., enable_retry=True)` must switch to
  `DatabaseAgent(..., retry_config=QueryRetryConfig())`. Code that read
  `AIMessage.response` for a string answer continues to work; code that
  wants the structured payload should read `AIMessage.output` (a
  `QueryResponse`).

  Spec: `sdd/specs/database-agent-homologation.spec.md`

- **FEAT-164** — `parrot.bots.database.QueryResponse` and
  `parrot.bots.database.QueryDataset` Pydantic models defining the
  `DatabaseAgent` structured-output contract.

- **FEAT-164** — `parrot.bots.database.toolkits.DatabaseAgentToolkit`, an
  internal `AbstractToolkit` collecting 16 helpers ported from the
  deleted `AbstractDBAgent` (explain-plan formatting, optimization tips,
  SQL extraction, schema docs, etc.). Auto-registered by
  `DatabaseAgent.configure()`; individual tools are gated by the
  active `OutputComponent` flags of each request.

### Removed

- **FEAT-164** — `parrot.bots.database.abstract.AbstractDBAgent` (3067 LOC,
  legacy). All still-useful helpers were migrated to
  `DatabaseAgentToolkit`. No backwards-compatibility shim is provided.
