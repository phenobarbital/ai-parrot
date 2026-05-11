"""Tests for ToolCallDispatcher — Jinja2 rendering, safety filters, credential
forwarding, empty-team gate, and AuthorizationRequired propagation.

Covers FEAT-158 Module 4 acceptance criteria.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, call

from parrot.knowledge.ontology.tool_dispatcher import RenderError, ToolCallDispatcher
from parrot.knowledge.ontology.schema import ToolCallSpec
from parrot.auth.exceptions import AuthorizationRequired


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tool():
    """Mocked tool object with an async execute method."""
    t = MagicMock()
    t.execute = AsyncMock(return_value={"issues": [{"key": "T-1"}]})
    return t


@pytest.fixture
def tool_manager(tool):
    """Mocked ToolManager whose get_tool returns the mocked tool."""
    tm = MagicMock()
    # get_tool is synchronous in the real implementation
    tm.get_tool = MagicMock(return_value=tool)
    return tm


@pytest.fixture
def dispatcher(tool_manager) -> ToolCallDispatcher:
    """ToolCallDispatcher backed by the mocked tool manager."""
    return ToolCallDispatcher(tool_manager=tool_manager)


def _spec(**overrides) -> ToolCallSpec:
    """Helper: build a ToolCallSpec with sensible defaults."""
    base: dict = dict(
        toolkit="JiraToolkit",
        method="jira_search_issues",
        parameters={
            "jql": "assignee in ({{ graph.team | jira_accounts }})",
        },
        result_binding="issues",
        empty_team_behavior="short_circuit",
    )
    base.update(overrides)
    return ToolCallSpec(**base)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDispatcher:
    """Core ToolCallDispatcher behaviour."""

    @pytest.mark.asyncio
    async def test_renders_basic_jql(
        self, dispatcher: ToolCallDispatcher, tool: MagicMock
    ) -> None:
        """Jinja2 renders jira_accounts filter and passes rendered jql to the tool."""
        spec = _spec()
        graph = [
            {"jira_account_id": "557058:abc"},
            {"jira_account_id": "557058:def"},
        ]
        out = await dispatcher.dispatch(
            spec, graph,
            user_context={"user_id": "u1", "channel": "telegram"},
        )
        tool.execute.assert_awaited_once()
        kwargs = tool.execute.await_args.kwargs
        assert '"557058:abc"' in kwargs["jql"]
        assert '"557058:def"' in kwargs["jql"]

    @pytest.mark.asyncio
    async def test_strict_undefined_raises_render_error(
        self, dispatcher: ToolCallDispatcher
    ) -> None:
        """Missing binding in StrictUndefined mode raises RenderError."""
        spec = _spec(parameters={"jql": "assignee = {{ ctx.unknown_var }}"})
        with pytest.raises(RenderError):
            await dispatcher.dispatch(
                spec, [{"a": 1}],
                user_context={"user_id": "u1"},
            )

    @pytest.mark.asyncio
    async def test_jql_quote_escapes_adversarial_input(
        self, dispatcher: ToolCallDispatcher, tool: MagicMock
    ) -> None:
        """jql_quote escapes double-quotes in user-supplied values."""
        spec = _spec(parameters={"jql": 'assignee = {{ ctx.name | jql_quote }}'})
        adversarial = 'Jesús" OR project="OTHER'
        await dispatcher.dispatch(
            spec, [{"x": 1}],
            user_context={"user_id": "u1", "name": adversarial},
        )
        jql = tool.execute.await_args.kwargs["jql"]
        # The injection attempt must be neutralised
        assert '" OR project="OTHER' not in jql
        assert '\\"' in jql

    @pytest.mark.asyncio
    async def test_jira_accounts_rejects_bad_shape(
        self, dispatcher: ToolCallDispatcher
    ) -> None:
        """jira_accounts raises ValueError for invalid accountId shapes."""
        spec = _spec()
        bad_graph = [{"jira_account_id": "id; DROP TABLE users--"}]
        with pytest.raises(ValueError, match="invalid jira accountId"):
            await dispatcher.dispatch(
                spec, bad_graph,
                user_context={"user_id": "u1"},
            )

    @pytest.mark.asyncio
    async def test_empty_team_short_circuit(
        self, dispatcher: ToolCallDispatcher, tool: MagicMock
    ) -> None:
        """empty_team_behavior=short_circuit returns structured result without tool call."""
        spec = _spec(empty_team_behavior="short_circuit")
        out = await dispatcher.dispatch(spec, [], user_context={"user_id": "u1"})
        tool.execute.assert_not_awaited()
        assert out["issues"]["empty"] is True
        assert out["issues"]["items"] == []

    @pytest.mark.asyncio
    async def test_empty_team_fail_raises(
        self, dispatcher: ToolCallDispatcher, tool: MagicMock
    ) -> None:
        """empty_team_behavior=fail raises ValueError when graph is empty."""
        spec = _spec(empty_team_behavior="fail")
        with pytest.raises(ValueError, match="empty graph result"):
            await dispatcher.dispatch(spec, [], user_context={"user_id": "u1"})
        tool.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_team_call_anyway_invokes_tool(
        self, dispatcher: ToolCallDispatcher, tool: MagicMock
    ) -> None:
        """empty_team_behavior=call_anyway proceeds even with empty graph result."""
        spec = _spec(
            empty_team_behavior="call_anyway",
            parameters={"jql": "project = TROC"},
        )
        await dispatcher.dispatch(spec, [], user_context={"user_id": "u1"})
        tool.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_forwards_permission_context(
        self, dispatcher: ToolCallDispatcher, tool: MagicMock
    ) -> None:
        """_permission_context is forwarded with correct user_id and channel."""
        spec = _spec(parameters={"jql": "project = TROC"})
        await dispatcher.dispatch(
            spec, [{"x": 1}],
            user_context={"user_id": "alice@corp", "channel": "telegram"},
        )
        kwargs = tool.execute.await_args.kwargs
        assert "_permission_context" in kwargs
        pctx = kwargs["_permission_context"]
        assert pctx.user_id == "alice@corp"
        assert pctx.channel == "telegram"

    @pytest.mark.asyncio
    async def test_propagates_authorization_required(
        self, dispatcher: ToolCallDispatcher, tool: MagicMock
    ) -> None:
        """AuthorizationRequired raised by the tool propagates unchanged."""
        tool.execute.side_effect = AuthorizationRequired(
            tool_name="jira_search_issues",
            message="please reauth",
            auth_url="https://auth/url",
            provider="jira",
            scopes=["read:jira-work"],
        )
        spec = _spec(parameters={"jql": "project = TROC"})
        with pytest.raises(AuthorizationRequired) as exc_info:
            await dispatcher.dispatch(
                spec, [{"x": 1}],
                user_context={"user_id": "u1", "channel": "telegram"},
            )
        assert exc_info.value.auth_url == "https://auth/url"

    @pytest.mark.asyncio
    async def test_tool_not_registered_raises(
        self, dispatcher: ToolCallDispatcher, tool_manager: MagicMock
    ) -> None:
        """Raises ValueError when the tool is not found in ToolManager."""
        tool_manager.get_tool.return_value = None
        spec = _spec(parameters={"jql": "project = TROC"})
        with pytest.raises(ValueError, match="not registered"):
            await dispatcher.dispatch(
                spec, [{"x": 1}],
                user_context={"user_id": "u1"},
            )

    @pytest.mark.asyncio
    async def test_result_bound_under_binding_key(
        self, dispatcher: ToolCallDispatcher, tool: MagicMock
    ) -> None:
        """Tool output is stored under spec.result_binding in the return dict."""
        spec = _spec(
            parameters={"jql": "project = TROC"},
            result_binding="in_progress_issues",
        )
        out = await dispatcher.dispatch(
            spec, [{"x": 1}],
            user_context={"user_id": "u1"},
        )
        assert "in_progress_issues" in out

    @pytest.mark.asyncio
    async def test_non_string_parameters_pass_through(
        self, dispatcher: ToolCallDispatcher, tool: MagicMock
    ) -> None:
        """Integer and bool parameters are passed through without rendering."""
        spec = _spec(
            parameters={
                "max_results": 50,
                "json_result": True,
                "start_at": 0,
            }
        )
        await dispatcher.dispatch(spec, [{"x": 1}], user_context={"user_id": "u1"})
        kwargs = tool.execute.await_args.kwargs
        assert kwargs["max_results"] == 50
        assert kwargs["json_result"] is True
        assert kwargs["start_at"] == 0

    @pytest.mark.asyncio
    async def test_graph_team_alias_works(
        self, dispatcher: ToolCallDispatcher, tool: MagicMock
    ) -> None:
        """graph.team alias works identically to iterating graph directly."""
        spec = _spec(
            parameters={
                "jql": (
                    "assignee in ({{ graph.team | jira_accounts }})"
                ),
            }
        )
        graph = [{"jira_account_id": "acct:xyz"}]
        await dispatcher.dispatch(spec, graph, user_context={"user_id": "u1"})
        kwargs = tool.execute.await_args.kwargs
        assert '"acct:xyz"' in kwargs["jql"]
