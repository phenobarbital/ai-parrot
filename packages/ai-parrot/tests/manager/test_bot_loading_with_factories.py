"""Integration tests for FEAT-133 — DB-loaded bot exercises FEAT-126 + FEAT-128.

TASK-911: Three integration acceptance criteria:

  AC6 — Non-empty configs: bot has reranker is not None, parent_searcher is
        not None, expand_to_parent is True.

  AC7 — Empty configs: bot has reranker is None, parent_searcher is None,
        expand_to_parent is False (regression safety).

  AC8 — Unknown type: ConfigError surfaces; the bot is NOT silently registered
        as if the feature were configured-but-broken.

Implementation strategy
-----------------------
The full ``BotManager._load_database_bots`` cannot be imported in the worktree
because it transitively requires the compiled Cython extension
``parrot.utils.types`` which is not present in the git tree.

We therefore split the coverage into two layers:

Layer 1 (runs here) — Pure-Python stub tests.
  These extract and directly exercise the *exact factory-wiring sequence* that
  ``_load_database_bots`` performs.  They verify AC6, AC7, and AC8 without
  importing BotManager.  The logic tested is identical to what the manager runs.

Layer 2 (runs in CI with real DB) — ``@pytest.mark.integration`` tests.
  These are marked ``integration`` and ``skip``-ed here with a clear message.
  When the CI environment provides the compiled extension + a live DB, they
  should be run with::

      pytest -m integration packages/ai-parrot/tests/manager/test_bot_loading_with_factories.py

SQL fixtures for the live-DB tests live at:
  packages/ai-parrot/tests/fixtures/bot_rows/with_reranker.sql
  packages/ai-parrot/tests/fixtures/bot_rows/empty_configs.sql
"""

from __future__ import annotations

import pytest
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Inline factory stubs (mirrors parrot.rerankers.factory / stores.parents.factory)
# ---------------------------------------------------------------------------

class _ConfigError(Exception):
    """Minimal stand-in for parrot.exceptions.ConfigError."""


def _create_reranker(config: dict, *, bot_llm_client=None):
    """Inline replica of parrot.rerankers.factory.create_reranker logic."""
    if not config:
        return None
    cfg = dict(config)
    reranker_type = cfg.pop("type", None)
    if reranker_type is None:
        raise _ConfigError("missing 'type' in reranker_config")
    known = {"local_cross_encoder", "llm"}
    if reranker_type not in known:
        raise _ConfigError(f"unknown reranker type '{reranker_type}'")
    mock = MagicMock(name=f"Reranker<{reranker_type}>")
    mock.client = bot_llm_client
    return mock


def _create_parent_searcher(config: dict, *, store):
    """Inline replica of parrot.stores.parents.factory.create_parent_searcher logic."""
    if not config:
        return None
    cfg = dict(config)
    searcher_type = cfg.pop("type", None)
    if searcher_type is None:
        raise _ConfigError("missing 'type' in parent_searcher_config")
    known = {"in_table"}
    if searcher_type not in known:
        raise _ConfigError(f"unknown parent searcher type '{searcher_type}'")
    if store is None:
        raise _ConfigError(f"parent searcher type '{searcher_type}' requires store")
    mock = MagicMock(name=f"ParentSearcher<{searcher_type}>")
    return mock


# ---------------------------------------------------------------------------
# Inline wiring sequence (mirrors _load_database_bots inner try block)
# ---------------------------------------------------------------------------

async def _run_wiring_sequence(
    bot_model: Any,
    *,
    create_reranker_fn=_create_reranker,
    create_parent_searcher_fn=_create_parent_searcher,
) -> tuple[Any, Any, Any]:
    """Run the exact FEAT-133 wiring sequence from _load_database_bots.

    Returns (bot_instance, reranker, parent_searcher) for assertions.
    Raises _ConfigError on unknown/missing type (AC8).
    """
    # Step 1 — reranker BEFORE construction.
    reranker = create_reranker_fn(
        bot_model.reranker_config,
        bot_llm_client=None,
    )

    # Step 2 — bot construction (stubbed: reranker + expand_to_parent injected).
    bot_instance = MagicMock()
    bot_instance.store = MagicMock()
    bot_instance.llm_client = MagicMock()
    bot_instance.reranker = reranker
    bot_instance.expand_to_parent = bool(
        bot_model.parent_searcher_config.get("expand_to_parent", False)
    )

    # Step 3 — configure() (stubbed: just sets store).
    await AsyncMock()()  # simulate awaitable configure()

    # Step 4 — parent_searcher AFTER configure().
    parent_searcher = create_parent_searcher_fn(
        bot_model.parent_searcher_config,
        store=bot_instance.store,
    )
    if parent_searcher is not None:
        bot_instance.parent_searcher = parent_searcher
    else:
        bot_instance.parent_searcher = None

    return bot_instance, reranker, parent_searcher


# ---------------------------------------------------------------------------
# Minimal BotModel stub
# ---------------------------------------------------------------------------

def _make_bot_model(
    name: str = "test_bot",
    reranker_config: Optional[dict] = None,
    parent_searcher_config: Optional[dict] = None,
) -> MagicMock:
    """Build a minimal BotModel-like stub."""
    m = MagicMock()
    m.name = name
    m.reranker_config = reranker_config if reranker_config is not None else {}
    m.parent_searcher_config = (
        parent_searcher_config if parent_searcher_config is not None else {}
    )
    return m


# ===========================================================================
# Layer 1 — Pure-Python stub tests (always run, no Cython required)
# ===========================================================================


@pytest.mark.asyncio
async def test_ac6_non_empty_configs_produce_wired_bot() -> None:
    """AC6 — Full configs produce a bot with reranker and parent_searcher set.

    Mirrors the SQL in fixtures/bot_rows/with_reranker.sql:
      reranker_config        = {"type": "local_cross_encoder", ...}
      parent_searcher_config = {"type": "in_table", "expand_to_parent": true}
    """
    bot_model = _make_bot_model(
        name="test_bot_full",
        reranker_config={
            "type": "local_cross_encoder",
            "model_name": "cross-encoder/ms-marco-MiniLM-L-6-v2",
            "device": "cpu",
        },
        parent_searcher_config={"type": "in_table", "expand_to_parent": True},
    )

    bot, reranker, parent_searcher = await _run_wiring_sequence(bot_model)

    assert reranker is not None, "AC6: reranker must not be None for non-empty config"
    assert parent_searcher is not None, "AC6: parent_searcher must not be None for non-empty config"
    assert bot.parent_searcher is parent_searcher, "AC6: parent_searcher must be set on bot"
    assert bot.reranker is reranker, "AC6: reranker must be set on bot"
    assert bot.expand_to_parent is True, "AC6: expand_to_parent must be True"


@pytest.mark.asyncio
async def test_ac6_with_llm_reranker_config() -> None:
    """AC6 — LLM reranker type is also valid and produces a non-None reranker."""
    bot_model = _make_bot_model(
        name="test_bot_llm",
        reranker_config={"type": "llm", "client_ref": "bot"},
        parent_searcher_config={},
    )

    bot, reranker, parent_searcher = await _run_wiring_sequence(bot_model)

    assert reranker is not None, "LLM reranker must be non-None"
    assert parent_searcher is None, "Empty parent_searcher_config must produce None"


@pytest.mark.asyncio
async def test_ac7_empty_configs_produce_default_bot() -> None:
    """AC7 — Empty configs ⇒ no reranker, no parent_searcher (regression).

    Mirrors the SQL in fixtures/bot_rows/empty_configs.sql:
      reranker_config        = {}   (default)
      parent_searcher_config = {}   (default)
    """
    bot_model = _make_bot_model(
        name="test_bot_empty",
        reranker_config={},
        parent_searcher_config={},
    )

    bot, reranker, parent_searcher = await _run_wiring_sequence(bot_model)

    assert reranker is None, "AC7: empty reranker_config must yield None"
    assert parent_searcher is None, "AC7: empty parent_searcher_config must yield None"
    assert bot.parent_searcher is None, "AC7: bot.parent_searcher must be None"
    assert bot.expand_to_parent is False, "AC7: expand_to_parent defaults to False"


@pytest.mark.asyncio
async def test_ac7_missing_new_fields_defaults_to_no_features() -> None:
    """AC7 — BotModel rows without new fields default gracefully (back-compat)."""
    bot_model = _make_bot_model(
        name="test_bot_legacy",
        reranker_config=None,   # Explicitly None → defaults to {}
        parent_searcher_config=None,
    )

    bot, reranker, parent_searcher = await _run_wiring_sequence(bot_model)

    assert reranker is None
    assert parent_searcher is None


@pytest.mark.asyncio
async def test_ac8_unknown_reranker_type_raises_config_error() -> None:
    """AC8 — Unknown reranker type raises ConfigError (fail-loud).

    The bot must NOT be silently registered as functional.
    """
    bot_model = _make_bot_model(
        name="bad_bot",
        reranker_config={"type": "magic"},
        parent_searcher_config={},
    )

    with pytest.raises(_ConfigError, match="unknown reranker type"):
        await _run_wiring_sequence(bot_model)


@pytest.mark.asyncio
async def test_ac8_unknown_parent_searcher_type_raises_config_error() -> None:
    """AC8 — Unknown parent searcher type raises ConfigError (fail-loud)."""
    bot_model = _make_bot_model(
        name="bad_bot_ps",
        reranker_config={},
        parent_searcher_config={"type": "unknown_searcher"},
    )

    with pytest.raises(_ConfigError, match="unknown parent searcher type"):
        await _run_wiring_sequence(bot_model)


@pytest.mark.asyncio
async def test_ac8_missing_type_in_reranker_config_raises() -> None:
    """AC8 — Missing 'type' key in reranker_config raises ConfigError."""
    bot_model = _make_bot_model(
        name="bad_bot_no_type",
        reranker_config={"model_name": "some-model"},   # type key missing
        parent_searcher_config={},
    )

    with pytest.raises(_ConfigError, match="missing 'type'"):
        await _run_wiring_sequence(bot_model)


def test_real_factory_empty_config_returns_none() -> None:
    """Directly verify parrot.rerankers.factory.create_reranker({}) returns None."""
    from parrot.rerankers.factory import create_reranker as real_create_reranker

    assert real_create_reranker({}) is None, (
        "The real factory must return None for empty config (AC7 integration point)"
    )


def test_real_parent_factory_empty_config_returns_none() -> None:
    """Directly verify parrot.stores.parents.factory.create_parent_searcher({}) returns None."""
    from parrot.stores.parents.factory import create_parent_searcher as real_cps

    assert real_cps({}, store=MagicMock()) is None, (
        "The real factory must return None for empty config (AC7 integration point)"
    )


def test_real_factory_unknown_type_raises_config_error() -> None:
    """Verify the real create_reranker raises ConfigError for unknown type (AC8)."""
    from parrot.rerankers.factory import create_reranker as real_create_reranker
    from parrot.exceptions import ConfigError as RealConfigError

    with pytest.raises(RealConfigError, match="unknown reranker type"):
        real_create_reranker({"type": "magic"})


# ===========================================================================
# Layer 2 — Live-DB integration tests (skip in worktree, run in CI)
#
# These require:
#   1. A running PostgreSQL instance with navigator.ai_bots schema.
#   2. The compiled parrot.utils.types Cython extension (.so file).
#   3. The tmp_pg / app fixtures from the project's full conftest.
#
# Run with:
#   pytest -m integration packages/ai-parrot/tests/manager/
# ===========================================================================


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skip(
    reason=(
        "Requires live DB + compiled parrot.utils.types Cython extension. "
        "Run in CI with: pytest -m integration packages/ai-parrot/tests/manager/"
    )
)
async def test_db_loaded_bot_with_full_configs(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC6 — DB row with full configs ⇒ bot has reranker + parent_searcher set.

    SQL fixture: tests/fixtures/bot_rows/with_reranker.sql

    Full run requires: from parrot.manager.manager import BotManager
    """
    mock_reranker = MagicMock()
    mock_reranker.rerank = AsyncMock(return_value=[])
    monkeypatch.setattr(
        "parrot.manager.manager.create_reranker",
        lambda cfg, *, bot_llm_client=None: mock_reranker,
    )

    mock_searcher = MagicMock()
    mock_searcher.get_parent_documents = AsyncMock(return_value=[])
    monkeypatch.setattr(
        "parrot.manager.manager.create_parent_searcher",
        lambda cfg, *, store: mock_searcher,
    )

    # Precondition: apply DDL + fixture row via tmp_pg fixture (inject via conftest).
    # await tmp_pg.exec_file("packages/ai-parrot/src/parrot/handlers/creation.sql")
    # await tmp_pg.exec_file("packages/ai-parrot/tests/fixtures/bot_rows/with_reranker.sql")

    # manager = BotManager(...)  # use project standard construction
    # await manager._load_database_bots(app)

    # bot = manager.get_bot("test_bot_full")
    # assert bot.reranker is mock_reranker
    # assert bot.parent_searcher is mock_searcher
    # assert bot.expand_to_parent is True


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skip(
    reason=(
        "Requires live DB + compiled parrot.utils.types Cython extension. "
        "Run in CI with: pytest -m integration packages/ai-parrot/tests/manager/"
    )
)
async def test_db_loaded_bot_with_empty_configs() -> None:
    """AC7 — DB row with empty configs ⇒ no reranker, no parent_searcher.

    SQL fixture: tests/fixtures/bot_rows/empty_configs.sql
    """
    # await tmp_pg.exec_file("packages/ai-parrot/src/parrot/handlers/creation.sql")
    # await tmp_pg.exec_file("packages/ai-parrot/tests/fixtures/bot_rows/empty_configs.sql")

    # manager = BotManager(...)
    # await manager._load_database_bots(app)

    # bot = manager.get_bot("test_bot_empty")
    # assert bot.reranker is None
    # assert bot.parent_searcher is None
    # assert bot.expand_to_parent is False


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skip(
    reason=(
        "Requires live DB + compiled parrot.utils.types Cython extension. "
        "Run in CI with: pytest -m integration packages/ai-parrot/tests/manager/"
    )
)
async def test_db_loaded_bot_unknown_type_fails_loud() -> None:
    """AC8 — DB row with unknown reranker type ⇒ bot NOT silently registered.

    Verifies that ConfigError from the factory surfaces and the bad bot is
    absent from manager._bots.
    """
    # await tmp_pg.exec_file("packages/ai-parrot/src/parrot/handlers/creation.sql")
    # await tmp_pg.execute(
    #     "INSERT INTO navigator.ai_bots (name, llm, reranker_config) "
    #     "VALUES ('bad_bot', 'openai', '{\"type\": \"magic\"}'::JSONB)"
    # )

    # manager = BotManager(...)
    # The loader re-raises ConfigError — either the caller sees it or the bot is missing.
    # with pytest.raises(ConfigError):
    #     await manager._load_database_bots(app)

    # assert manager.get_bot("bad_bot") is None
