"""Integration tests for BotManager._load_database_bots PBAC wiring — FEAT-153 TASK-1052.

Tests cover the try/except ValueError block (lines 478-484 in manager.py) that:
  - Skips bots with malformed permissions (ValueError path → ``continue``).
  - Loads bots with valid permissions and registers policies.
  - Loads bots with no permissions field normally (no policy call needed).

Strategy: the three full-pipeline tests mock ``_load_database_bots`` at the
``register_db_bot_policies`` layer — the exact integration seam that FEAT-153
added.  The last two tests exercise ``register_db_bot_policies`` directly (no DB
needed) so the parse → load_policies chain is validated without import complexity.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bot_model(
    name: str = "test_bot",
    permissions: Any = None,
) -> MagicMock:
    """Return a MagicMock that quacks like a BotModel row.

    Only the fields accessed by ``_load_database_bots`` are set; the rest
    default to ``None`` / falsy to minimise the mock surface.
    """
    m = MagicMock()
    m.name = name
    m.permissions = permissions
    m.chatbot_id = f"uuid-{name}"
    m.description = ""
    m.operation_mode = "chat"
    m.llm = None
    m.model_config = {}
    m.role = None
    m.goal = None
    m.backstory = None
    m.rationale = None
    m.capabilities = None
    m.system_prompt_template = None
    m.human_prompt_template = None
    m.pre_instructions = None
    m.use_vector = False
    m.vector_store_config = {}
    m.context_search_limit = 10
    m.context_score_threshold = 0.5
    m.tools_enabled = False
    m.auto_tool_detection = False
    m.tool_threshold = 0.5
    m.tools = []
    m.memory_type = None
    m.memory_config = {}
    m.max_context_turns = 10
    m.use_conversation_history = False
    m.language = "en"
    m.disclaimer = None
    m.reranker_config = {}
    m.parent_searcher_config = {}
    m.prompt_config = {}
    m.bot_class = "BasicBot"
    return m


def _make_fake_db(all_bots):
    """Build a minimal async DB mock that satisfies _load_database_bots."""
    fake_conn = MagicMock()
    fake_conn.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_conn.__aexit__ = AsyncMock(return_value=False)

    fake_db = MagicMock()

    async def _acquire():
        return fake_conn

    fake_db.acquire = _acquire

    fake_BotModel = MagicMock()
    fake_BotModel.Meta = MagicMock()
    fake_BotModel.filter = AsyncMock(return_value=all_bots)

    # app['database'] → fake_db
    app = MagicMock()
    app.__getitem__ = MagicMock(return_value=fake_db)
    app.get = MagicMock(return_value=None)

    return app, fake_BotModel


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLoadDatabaseBotsPBAC:
    """Tests for _load_database_bots PBAC policy-registration wiring."""

    # ------------------------------------------------------------------
    # Test 1 — bot with no permissions (None) loads normally
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_bot_with_no_permissions_loads_normally(self):
        """A bot with permissions=None (public bot) is loaded into _bots.

        The try/except ValueError block is entered (register_db_bot_policies
        called) but returns 0 (no rules) — no ValueError raised, add_bot called.
        """
        from parrot.manager.manager import BotManager

        bot_model = _make_bot_model(name="public_bot", permissions=None)
        app, fake_BotModel = _make_fake_db([bot_model])

        manager = BotManager()
        manager.app = app

        fake_bot = MagicMock()
        fake_bot.name = "public_bot"
        fake_bot.store = None
        fake_bot.is_configured = True
        fake_bot.configure = AsyncMock()
        fake_bot.model_id = None

        # Patch the internal import of BotModel inside _load_database_bots
        # and other heavy dependencies so the loop runs to completion.
        with (
            patch(
                "parrot.manager.manager.BotModel",
                fake_BotModel,
                create=True,
            ),
            patch(
                "parrot.handlers.models.BotModel",
                fake_BotModel,
                create=True,
            ),
            patch("parrot.manager.manager.create_reranker", return_value=None),
            patch("parrot.manager.manager.create_parent_searcher", return_value=None),
            patch.object(manager, "get_bot_class", return_value=MagicMock(return_value=fake_bot)),
            patch.object(manager.registry, "register_db_bot_policies", return_value=0) as mock_reg,
            patch.object(manager, "add_bot") as mock_add,
        ):
            # Patch the local import inside the method
            with patch.dict(
                "sys.modules",
                {"parrot.handlers.models": MagicMock(BotModel=fake_BotModel)},
            ):
                await manager._load_database_bots(app)

        mock_reg.assert_called_once_with("public_bot", {})
        mock_add.assert_called_once_with(fake_bot)

    # ------------------------------------------------------------------
    # Test 2 — bot with valid permissions registers policies AND is loaded
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_bot_with_valid_permissions_registers_policies(self):
        """A bot with well-formed permissions registers N > 0 policies and is loaded.

        The real register_db_bot_policies is exercised (not mocked) so that
        the parse → convert → load_policies chain is validated end-to-end.
        """
        from parrot.manager.manager import BotManager

        valid_permissions = {
            "permissions": [
                {
                    "action": "agent:resolve",
                    "effect": "allow",
                    "groups": ["engineering"],
                },
            ],
        }
        bot_model = _make_bot_model(name="finance_bot", permissions=valid_permissions)
        app, fake_BotModel = _make_fake_db([bot_model])

        manager = BotManager()
        manager.app = app

        # Wire a real mock evaluator so load_policies is called
        mock_evaluator = MagicMock()
        mock_evaluator.load_policies = MagicMock()
        manager.registry._evaluator = mock_evaluator

        fake_bot = MagicMock()
        fake_bot.name = "finance_bot"
        fake_bot.store = None
        fake_bot.is_configured = True
        fake_bot.configure = AsyncMock()
        fake_bot.model_id = None

        with (
            patch("parrot.manager.manager.create_reranker", return_value=None),
            patch("parrot.manager.manager.create_parent_searcher", return_value=None),
            patch.object(manager, "get_bot_class", return_value=MagicMock(return_value=fake_bot)),
            patch.object(manager, "add_bot") as mock_add,
        ):
            with patch.dict(
                "sys.modules",
                {"parrot.handlers.models": MagicMock(BotModel=fake_BotModel)},
            ):
                await manager._load_database_bots(app)

        # The evaluator's load_policies must have been called with the
        # correctly formatted policy dicts.
        mock_evaluator.load_policies.assert_called_once()
        policy_dicts = mock_evaluator.load_policies.call_args[0][0]
        assert policy_dicts[0]["resources"] == ["agent:finance_bot"]

        # The bot must still have been added.
        mock_add.assert_called_once_with(fake_bot)

    # ------------------------------------------------------------------
    # Test 3 — bot with malformed permissions is SKIPPED (ValueError path)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_malformed_permissions_skips_bot_does_not_crash(self):
        """A bot with malformed permissions triggers the ValueError path.

        The bot must NOT appear in _bots (``add_bot`` not called for it)
        but the loop must continue so that subsequent bots ARE loaded.
        This is the key invariant of the try/except ValueError block.
        """
        from parrot.manager.manager import BotManager

        bad_model = _make_bot_model(
            name="bad_bot",
            permissions={"permissions": "not-a-list"},  # malformed → ValueError
        )
        good_model = _make_bot_model(
            name="good_bot",
            permissions=None,  # public → loads normally
        )
        app, fake_BotModel = _make_fake_db([bad_model, good_model])

        manager = BotManager()
        manager.app = app
        manager.registry._evaluator = MagicMock()

        good_fake_bot = MagicMock()
        good_fake_bot.name = "good_bot"
        good_fake_bot.store = None
        good_fake_bot.is_configured = True
        good_fake_bot.configure = AsyncMock()
        good_fake_bot.model_id = None

        bad_fake_bot = MagicMock()
        bad_fake_bot.name = "bad_bot"
        bad_fake_bot.store = None
        bad_fake_bot.is_configured = True
        bad_fake_bot.configure = AsyncMock()
        bad_fake_bot.model_id = None

        # Side-effect: first call (bad_bot) raises ValueError; second (good_bot) returns 0
        mock_reg = MagicMock(side_effect=[ValueError("malformed"), 0])

        with (
            patch("parrot.manager.manager.create_reranker", return_value=None),
            patch("parrot.manager.manager.create_parent_searcher", return_value=None),
            patch.object(manager.registry, "register_db_bot_policies", mock_reg),
            patch.object(manager, "add_bot") as mock_add,
        ):
            # bot class factory: returns different bots by call order
            call_count = [0]

            def _get_class(_):
                call_count[0] += 1
                which = bad_fake_bot if call_count[0] == 1 else good_fake_bot
                return MagicMock(return_value=which)

            manager.get_bot_class = _get_class

            with patch.dict(
                "sys.modules",
                {"parrot.handlers.models": MagicMock(BotModel=fake_BotModel)},
            ):
                await manager._load_database_bots(app)

        # bad_bot must NOT have been added (ValueError → continue)
        added_names = [c.args[0].name for c in mock_add.call_args_list]
        assert "bad_bot" not in added_names, (
            "bad_bot had malformed permissions and must be skipped"
        )

        # good_bot must have been added (loop continues after bad_bot)
        assert "good_bot" in added_names, (
            "good_bot must be loaded even after bad_bot was skipped"
        )

    # ------------------------------------------------------------------
    # Tests 4 & 5 — register_db_bot_policies unit smoke-tests (no DB needed)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_register_db_bot_policies_returns_zero_for_none(self):
        """register_db_bot_policies(name, None) → 0 and no evaluator call."""
        from parrot.manager.manager import BotManager

        manager = BotManager()
        mock_evaluator = MagicMock()
        manager.registry._evaluator = mock_evaluator

        result = manager.registry.register_db_bot_policies("any_bot", None)

        assert result == 0
        mock_evaluator.load_policies.assert_not_called()

    @pytest.mark.asyncio
    async def test_register_db_bot_policies_raises_for_malformed(self):
        """register_db_bot_policies raises ValueError for malformed permissions.

        This confirms the exact exception type that _load_database_bots catches
        in its try/except ValueError block.
        """
        from parrot.manager.manager import BotManager

        manager = BotManager()
        manager.registry._evaluator = MagicMock()

        with pytest.raises(ValueError):
            manager.registry.register_db_bot_policies(
                "bad_bot", {"permissions": "not-a-list"}
            )
