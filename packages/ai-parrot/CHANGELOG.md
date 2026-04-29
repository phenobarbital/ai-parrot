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
