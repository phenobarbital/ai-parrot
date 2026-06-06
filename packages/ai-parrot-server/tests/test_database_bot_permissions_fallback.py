"""Tests for database bot permissions fallback behavior."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_bot_model(name: str, permissions: Any) -> MagicMock:
    bot_model = MagicMock()
    bot_model.name = name
    bot_model.permissions = permissions
    bot_model.chatbot_id = f"uuid-{name}"
    bot_model.description = ""
    bot_model.operation_mode = "chat"
    bot_model.llm = None
    bot_model.model_config = {}
    bot_model.role = None
    bot_model.goal = None
    bot_model.backstory = None
    bot_model.rationale = None
    bot_model.capabilities = None
    bot_model.system_prompt_template = None
    bot_model.human_prompt_template = None
    bot_model.pre_instructions = None
    bot_model.use_vector = False
    bot_model.vector_store_config = {}
    bot_model.context_search_limit = 10
    bot_model.context_score_threshold = 0.5
    bot_model.tools_enabled = False
    bot_model.auto_tool_detection = False
    bot_model.tool_threshold = 0.5
    bot_model.tools = []
    bot_model.memory_type = None
    bot_model.memory_config = {}
    bot_model.max_context_turns = 10
    bot_model.use_conversation_history = False
    bot_model.language = "en"
    bot_model.disclaimer = None
    bot_model.reranker_config = {}
    bot_model.parent_searcher_config = {}
    bot_model.prompt_config = {}
    bot_model.bot_class = None
    return bot_model


def _make_fake_db(all_bots: list[MagicMock]) -> tuple[MagicMock, MagicMock]:
    fake_conn = MagicMock()
    fake_conn.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_conn.__aexit__ = AsyncMock(return_value=False)

    fake_db = MagicMock()

    async def _acquire() -> MagicMock:
        return fake_conn

    fake_db.acquire = _acquire

    fake_bot_model = MagicMock()
    fake_bot_model.Meta = MagicMock()
    fake_bot_model.filter = AsyncMock(return_value=all_bots)

    app = MagicMock()
    app.__getitem__ = MagicMock(return_value=fake_db)
    app.get = MagicMock(return_value=None)
    return app, fake_bot_model


@pytest.mark.parametrize(
    "permissions",
    [
        {"users": [], "groups": [], "programs": [], "job_codes": []},
        ["agent:resolve"],
        "legacy",
    ],
)
@pytest.mark.asyncio
async def test_load_database_bots_ignores_noncanonical_permissions(
    permissions: Any,
) -> None:
    from parrot.manager.manager import BotManager

    bot_model = _make_bot_model(
        name="Assembly360Concierge",
        permissions=permissions,
    )
    app, fake_bot_model = _make_fake_db([bot_model])

    manager = BotManager()
    manager.app = app

    fake_bot = MagicMock()
    fake_bot.name = "Assembly360Concierge"
    fake_bot.store = None
    fake_bot.configure = AsyncMock()
    fake_bot.model_id = None
    fake_bot_class = MagicMock(return_value=fake_bot)

    with (
        patch.dict(
            "sys.modules",
            {"parrot.handlers.models": MagicMock(BotModel=fake_bot_model)},
        ),
        patch.object(manager, "_resolve_database_bot_class", return_value=fake_bot_class),
        patch("parrot.manager.manager.create_reranker", return_value=None),
        patch("parrot.manager.manager.create_parent_searcher", return_value=None),
        patch.object(manager.registry, "register_db_bot_policies", return_value=0) as mock_reg,
        patch.object(manager, "add_bot") as mock_add,
    ):
        await manager._load_database_bots(app)

    assert fake_bot_class.call_args.kwargs["permissions"] == {}
    mock_reg.assert_called_once_with("Assembly360Concierge", {})
    mock_add.assert_called_once_with(fake_bot)
