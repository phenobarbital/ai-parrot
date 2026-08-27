"""Tests for the AgentStudio meta-agent (FEAT-467 TASK-2521).

Covers model resolution (default + env override + BYOK), write-boundary
enforcement (negative test: no tool can write outside its sandboxed
directory), tool confirmation gating, the assistant's session-scoped
conversation, and the /api/v1/agents/factory alias contract.

All LLM calls are mocked — no network (``AnthropicClient`` is monkeypatched
out of ``AgentStudioAgent.__init__`` for every test that doesn't
specifically exercise LLM-client construction).
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.bots.studio import agent as agent_module
from parrot.bots.studio import tools as tools_module
from parrot.bots.studio.agent import AgentStudioAgent
from parrot.handlers.studio import meta_agent as meta_agent_module
from parrot.handlers.studio._base import StudioUser
from parrot.handlers.studio.meta_agent import StudioAssistantHandler


def _unwrap(method):
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


async def _decode(response: web.Response) -> dict:
    return json.loads(response.body)


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------


def _patch_fake_anthropic(monkeypatch):
    """Patch ``agent_module.AnthropicClient`` with a callable that records
    its construction kwargs and returns a ``MagicMock(spec=AnthropicClient)``
    — ``spec=`` makes ``isinstance(fake, AbstractClient)`` succeed, which
    the framework's LLM-resolution machinery (``configure_llm`` ->
    ``_create_llm_client``) requires to treat it as a real client instance
    instead of falling through to a (failing) provider-string lookup.
    """
    from parrot.clients.claude import AnthropicClient

    captured: dict = {}

    def _fake_constructor(*, api_key=None, model=None, **kwargs):
        captured["api_key"] = api_key
        captured["model"] = model
        instance = MagicMock(spec=AnthropicClient)
        instance.model = model
        return instance

    monkeypatch.setattr(agent_module, "AnthropicClient", _fake_constructor)
    monkeypatch.setattr(tools_module, "build_studio_tools", list)
    return captured


class TestModelResolution:
    def test_default_model(self, monkeypatch):
        monkeypatch.setattr(agent_module, "STUDIO_AGENT_MODEL", "claude-opus-5")
        captured = _patch_fake_anthropic(monkeypatch)

        AgentStudioAgent(name="test_studio_agent")

        assert captured["model"] == "claude-opus-5"
        assert captured["api_key"] is None

    def test_env_override(self, monkeypatch):
        monkeypatch.setattr(agent_module, "STUDIO_AGENT_MODEL", "claude-opus-5")
        captured = _patch_fake_anthropic(monkeypatch)

        AgentStudioAgent(name="test_studio_agent", model="claude-sonnet-4-5")

        assert captured["model"] == "claude-sonnet-4-5"

    def test_byok_api_key_passed_through(self, monkeypatch):
        captured = _patch_fake_anthropic(monkeypatch)

        AgentStudioAgent(name="test_studio_agent", api_key="sk-ant-byok-key")

        assert captured["api_key"] == "sk-ant-byok-key"

    def test_skill_paths_points_at_bundled_dir(self):
        assert len(AgentStudioAgent.skill_paths) == 1
        assert AgentStudioAgent.skill_paths[0].name == "skills"
        assert (AgentStudioAgent.skill_paths[0] / "agent-builder" / "SKILL.md").exists()
        assert (AgentStudioAgent.skill_paths[0] / "skill-writer" / "SKILL.md").exists()
        assert (AgentStudioAgent.skill_paths[0] / "kb-writer" / "SKILL.md").exists()


# ---------------------------------------------------------------------------
# Tool confirmation gating
# ---------------------------------------------------------------------------


class TestToolsConfirmationGated:
    @pytest.mark.parametrize("tool_fn_name", [
        "save_agent_draft",
        "create_yaml_agent",
        "write_identity_file",
        "write_kb_file",
        "write_skill_file",
        "publish_skill_to_catalog",
    ])
    def test_mutating_tools_require_confirmation(self, tool_fn_name):
        tool_fn = getattr(tools_module, tool_fn_name)
        assert tool_fn._tool_metadata["routing_meta"]["requires_confirmation"] is True

    @pytest.mark.parametrize("tool_fn_name", [
        "list_agent_base_classes", "list_available_tools", "list_existing_agents",
    ])
    def test_readonly_tools_not_gated(self, tool_fn_name):
        tool_fn = getattr(tools_module, tool_fn_name)
        assert tool_fn._tool_metadata["routing_meta"]["requires_confirmation"] is False

    def test_build_studio_tools_returns_all_nine(self):
        names = {t._tool_metadata["name"] for t in tools_module.build_studio_tools()}
        assert names == {
            "save_agent_draft", "create_yaml_agent", "write_identity_file",
            "write_kb_file", "write_skill_file", "publish_skill_to_catalog",
            "list_agent_base_classes", "list_available_tools", "list_existing_agents",
        }


# ---------------------------------------------------------------------------
# Write-boundary enforcement
# ---------------------------------------------------------------------------


class TestWriteBoundaryEnforced:
    @pytest.mark.asyncio
    async def test_save_agent_draft_stays_under_drafts_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tools_module, "AGENTS_DIR", tmp_path)
        ctx = SimpleNamespace(app=web.Application())  # no "database" key -> DB persist skipped
        monkeypatch.setattr(tools_module, "current_context", lambda: ctx)

        result = await _call_tool_fn(
            tools_module.save_agent_draft, name="my_agent", source="class MyAgent:\n    pass\n"
        )

        written = tmp_path / "_drafts" / "my_agent.py"
        assert written.exists()
        assert result["file_path"] == str(written)
        # Never lands directly in AGENTS_DIR root.
        assert not (tmp_path / "my_agent.py").exists()

    @pytest.mark.asyncio
    async def test_save_agent_draft_rejects_traversal_name(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tools_module, "AGENTS_DIR", tmp_path)

        with pytest.raises(ValueError):
            await _call_tool_fn(
                tools_module.save_agent_draft,
                name="../../etc/passwd", source="x = 1",
            )

    @pytest.mark.asyncio
    async def test_write_identity_file_rejects_traversal(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tools_module, "AGENTS_DIR", tmp_path)
        ctx = SimpleNamespace(app=web.Application())
        monkeypatch.setattr(tools_module, "current_context", lambda: ctx)

        with pytest.raises(ValueError):
            await _call_tool_fn(
                tools_module.write_identity_file,
                agent_name="myagent", filename="../../../etc/passwd", content="x",
            )

    @pytest.mark.asyncio
    async def test_write_identity_file_rejects_non_canonical_name(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tools_module, "AGENTS_DIR", tmp_path)
        ctx = SimpleNamespace(app=web.Application())
        monkeypatch.setattr(tools_module, "current_context", lambda: ctx)

        with pytest.raises(ValueError):
            await _call_tool_fn(
                tools_module.write_identity_file,
                agent_name="myagent", filename="not_a_real_identity_file.md", content="x",
            )

    def test_no_tool_accepts_a_raw_agents_dir_path(self):
        """Every write tool takes (agent_name, filename, content) or
        (name, source) — never a bare filesystem path — so there is
        structurally no way to target AGENTS_DIR/x.py directly."""
        import inspect

        for fn in (
            tools_module.write_identity_file,
            tools_module.write_kb_file,
            tools_module.write_skill_file,
        ):
            params = list(inspect.signature(fn._tool_metadata["function"]).parameters)
            assert params == ["agent_name", "filename", "content"]


async def _call_tool_fn(tool_fn, **kwargs):
    """Call the underlying function a ``@tool``-decorated callable wraps."""
    return await tool_fn._tool_metadata["function"](**kwargs)


# ---------------------------------------------------------------------------
# Assistant session instance
# ---------------------------------------------------------------------------


class _FakeSessionCtx:
    def __init__(self, bot):
        self._bot = bot

    async def __aenter__(self):
        return self._bot

    async def __aexit__(self, *_args):
        return False


class _FakeAssistantAgent:
    def __init__(self, name="agent_studio_test", api_key=None):
        self.name = name
        self.api_key = api_key
        self.configure_calls = 0
        self.ask_calls: list[str] = []

    async def configure(self, app):
        self.configure_calls += 1

    def session(self, request=None, app=None):
        return _FakeSessionCtx(self)

    async def ask(self, question: str):
        self.ask_calls.append(question)
        return SimpleNamespace(content="assistant reply", metadata={})


def _make_handler(app, *, method="POST", path="/assistant", json_body=None, session=None):
    request = make_mocked_request(method, path, app=app)
    if json_body is not None:
        request.json = AsyncMock(return_value=json_body)
    handler = StudioAssistantHandler(request)
    handler._get_user = AsyncMock(return_value=StudioUser(user_id="1"))
    handler._resolve_session = AsyncMock(return_value=session if session is not None else {})
    return handler


class TestAssistantSessionInstance:
    @pytest.mark.asyncio
    async def test_session_instance_reused(self, monkeypatch):
        app = web.Application()
        fake_agent = _FakeAssistantAgent()
        monkeypatch.setattr(
            meta_agent_module, "AgentStudioAgent", lambda **kw: fake_agent
        )
        monkeypatch.setattr(
            meta_agent_module, "resolve_user_api_key", AsyncMock(return_value=None)
        )

        session = {}
        handler1 = _make_handler(app, json_body={"query": "hi", "use_byok": False}, session=session)
        response1 = await _unwrap(StudioAssistantHandler.post)(handler1)
        assert response1.status == 200

        handler2 = _make_handler(app, json_body={"query": "again", "use_byok": False}, session=session)
        response2 = await _unwrap(StudioAssistantHandler.post)(handler2)
        assert response2.status == 200

        assert fake_agent.configure_calls == 1
        assert fake_agent.ask_calls == ["hi", "again"]

    @pytest.mark.asyncio
    async def test_byok_key_used_when_present(self, monkeypatch):
        app = web.Application()
        captured_kwargs = {}

        def _factory(**kw):
            captured_kwargs.update(kw)
            return _FakeAssistantAgent(api_key=kw.get("api_key"))

        monkeypatch.setattr(meta_agent_module, "AgentStudioAgent", _factory)
        monkeypatch.setattr(
            meta_agent_module, "resolve_user_api_key",
            AsyncMock(return_value="sk-ant-stored-key"),
        )

        handler = _make_handler(app, json_body={"query": "hi", "use_byok": True}, session={})
        response = await _unwrap(StudioAssistantHandler.post)(handler)

        assert response.status == 200
        assert captured_kwargs["api_key"] == "sk-ant-stored-key"

    @pytest.mark.asyncio
    async def test_delete_ends_session(self, monkeypatch):
        app = web.Application()
        fake_agent = _FakeAssistantAgent()
        monkeypatch.setattr(meta_agent_module, "AgentStudioAgent", lambda **kw: fake_agent)
        monkeypatch.setattr(
            meta_agent_module, "resolve_user_api_key", AsyncMock(return_value=None)
        )

        session = {}
        post_handler = _make_handler(app, json_body={"query": "hi", "use_byok": False}, session=session)
        await _unwrap(StudioAssistantHandler.post)(post_handler)
        assert meta_agent_module.SESSION_KEY in session

        delete_handler = _make_handler(app, method="DELETE", session=session)
        response = await _unwrap(StudioAssistantHandler.delete)(delete_handler)

        assert response.status == 200
        assert meta_agent_module.SESSION_KEY not in session


# ---------------------------------------------------------------------------
# /api/v1/agents/factory alias contract
# ---------------------------------------------------------------------------


class TestFactoryAliasContract:
    @pytest.mark.asyncio
    async def test_factory_endpoint_still_requires_description(self):
        from parrot.handlers.agents.factory import AgentFactoryHandler

        app = web.Application()
        request = make_mocked_request("POST", "/api/v1/agents/factory", app=app)
        request.json = AsyncMock(return_value={})
        handler = AgentFactoryHandler(request)

        response = await _unwrap(AgentFactoryHandler.post)(handler)

        assert response.status == 400
        body = json.loads(response.body)
        assert body["status"] == "error"
        assert "description is required" in body["message"]

    def test_finalize_agent_registration_shared_by_both_paths(self):
        """The meta-agent's create_yaml_agent and the factory orchestrator's
        finalize step call the literal same function object."""
        import inspect

        from parrot.bots.factory.orchestrator import AgentFactoryOrchestrator
        from parrot.bots.factory.tools.finalize import finalize_agent_registration

        source = inspect.getsource(AgentFactoryOrchestrator.run)
        assert "finalize_agent_registration" in source

        tool_source = inspect.getsource(tools_module.create_yaml_agent._tool_metadata["function"])
        assert "finalize_agent_registration" in tool_source
        assert finalize_agent_registration.__module__ == "parrot.bots.factory.tools.finalize"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
