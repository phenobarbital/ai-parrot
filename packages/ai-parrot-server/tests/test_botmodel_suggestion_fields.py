"""Tests for the FEAT-752 follow-up suggestion chip fields on BotModel and the DB load path."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.handlers.models.bots import BotModel
from parrot.manager.manager import BotManager

FIELDS = {
    "enable_suggestions": False,
    "suggest_followups": False,
    "suggestion_timeout_s": 4.0,
    "max_suggestions": 6,
    "suggestion_model": None,
}


def test_defaults_match_constructor() -> None:
    model = BotModel(name="x")
    assert {k: getattr(model, k) for k in FIELDS} == FIELDS


def test_to_bot_config_forwards_fields() -> None:
    model = BotModel(
        name="x",
        enable_suggestions=True,
        suggest_followups=True,
        suggestion_timeout_s=2.5,
        max_suggestions=3,
        suggestion_model="gemini-2.5-flash-lite",
    )
    cfg = model.to_bot_config()
    assert cfg["enable_suggestions"] is True
    assert cfg["suggest_followups"] is True and cfg["max_suggestions"] == 3
    assert cfg["suggestion_timeout_s"] == 2.5
    assert cfg["suggestion_model"] == "gemini-2.5-flash-lite"


class _Captured:
    kwargs = None

    def __init__(self, **kwargs):
        _Captured.kwargs = kwargs
        self.configure = AsyncMock()
        self.store = MagicMock()
        self.llm_client = MagicMock()


@pytest.mark.asyncio
async def test_build_database_bot_passes_fields(monkeypatch) -> None:
    monkeypatch.setattr("parrot.manager.manager.create_reranker", MagicMock(return_value=None))
    monkeypatch.setattr("parrot.manager.manager.create_parent_searcher", MagicMock(return_value=None))
    mgr = BotManager.__new__(BotManager)
    mgr.logger = MagicMock()
    mgr._resolve_database_bot_class = MagicMock(return_value=_Captured)
    mgr._normalize_database_bot_permissions = MagicMock(return_value={})
    mgr._apply_prompt_config = MagicMock()
    mgr.registry = MagicMock()
    mgr.registry.register_db_bot_policies = MagicMock(return_value=0)
    values = {
        "enable_suggestions": True,
        "suggest_followups": True,
        "suggestion_timeout_s": 2.5,
        "max_suggestions": 3,
        "suggestion_model": "m",
    }
    bot_model = SimpleNamespace(
        chatbot_id="c",
        name="n",
        description="d",
        prompt_config={},
        llm="openai:gpt-4o-mini",
        model_config={},
        role="assistant",
        goal="g",
        backstory="",
        rationale="",
        capabilities=[],
        system_prompt_template=None,
        human_prompt_template=None,
        pre_instructions=None,
        use_vector=False,
        vector_store_config={},
        context_search_limit=5,
        context_score_threshold=0.5,
        tools_enabled=True,
        auto_tool_detection=False,
        tool_threshold=0.7,
        tools=[],
        toolkit_config={},
        mcp_servers=[],
        operation_mode="default",
        memory_type="in_memory",
        memory_config={},
        max_context_turns=10,
        use_conversation_history=True,
        permissions=None,
        language="en",
        disclaimer=None,
        reranker_config={},
        parent_searcher_config={},
        **values,
    )
    await mgr._build_database_bot(bot_model, app=MagicMock())
    for key, val in values.items():
        assert _Captured.kwargs[key] == val
