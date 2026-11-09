"""FEAT-848 — AbstractClient.supports_tool_loop: the declared text ask() tool-loop capability."""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from parrot.clients.base import AbstractClient
from parrot.clients.factory import LLMFactory
from parrot.tools.manager import ToolManager

# Classes whose text ask() runs no tool loop (spec §6 provider audit): name -> (module, attribute).
KNOWN_FALSE: dict[str, tuple[str, str]] = {
    "TransformersClient": ("parrot.clients.hf.client", "TransformersClient"),
    "JevClient": ("parrot.clients.jev.client", "JevClient"),
    "GeminiLiveClient": ("parrot.clients.google.live", "GeminiLiveClient"),
}

TOOL_EXECUTION_METHODS: frozenset[str] = frozenset(
    {"_run_tool_call_loop", "_execute_tool", "_handle_multiturn_function_calls", "_run_tool_loop"}
)
# Registered manager tools are exposed through CodexToolBridge / ClaudeAgentToolBridge; the client drives the
# external agent to completion before ask() returns. Each entry is backed by a bridge exposure test.
EXTERNAL_LOOP_CLIENTS: frozenset[str] = frozenset({"OpenAICodexClient", "ClaudeAgentClient"})


def _installed_classes() -> dict[str, type[AbstractClient]]:
    """Enumerate LLMFactory.supported_clients; skip confirmed absent extras, fail other loader errors."""
    out: dict[str, type[AbstractClient]] = {}
    for provider, value in LLMFactory.supported_clients().items():
        try:
            out[provider] = value() if callable(value) and not isinstance(value, type) else value
        except ModuleNotFoundError:
            continue
    return out


def _parse_function(func: object) -> ast.AST | None:
    """Parse one function's own source; None when no source is available."""
    try:
        source = inspect.getsource(inspect.unwrap(func))
    except (OSError, TypeError):
        return None
    for candidate in (textwrap.dedent(source), "class _Wrapper:\n" + source):
        try:
            node = ast.parse(candidate).body[0]
        except SyntaxError:
            continue
        return node.body[0] if isinstance(node, ast.ClassDef) else node
    return None


def _self_method_calls(func: object, unresolved: list[str]) -> set[str]:
    """Executable self.<name>(...) / super().<name>(...) calls in func's body, outside nested definitions."""
    node = _parse_function(func)
    if node is None:
        unresolved.append(getattr(func, "__qualname__", repr(func)))
        return set()
    calls: set[str] = set()

    def visit(parent: ast.AST) -> None:
        for child in ast.iter_child_nodes(parent):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                target = child.func.value
                if isinstance(target, ast.Name) and target.id == "self":
                    calls.add(child.func.attr)
                elif isinstance(target, ast.Call) and isinstance(target.func, ast.Name) and target.func.id == "super":
                    calls.add("super()." + child.func.attr)
            visit(child)

    visit(node)
    return calls


def _resolved_ask_calls(cls: type, unresolved: list[str] | None = None) -> frozenset[str]:
    """Self-method call names from reachable ask bodies (MRO via super().ask) and one-hop helpers."""
    sink: list[str] = unresolved if unresolved is not None else []
    calls: set[str] = set()
    for owner in cls.__mro__:
        if "ask" not in vars(owner):
            continue
        own = _self_method_calls(vars(owner)["ask"], sink)
        calls |= own
        if "super().ask" not in own:
            break
    for name in [call for call in calls if not call.startswith("super().")]:
        helper = getattr(cls, name, None)
        if inspect.isfunction(helper) or inspect.ismethod(helper):
            calls |= _self_method_calls(helper, sink)
    return frozenset(calls)


def test_default_is_true() -> None:
    """The base class declares the flag itself, defaulting to True."""
    assert AbstractClient.supports_tool_loop is True
    assert "supports_tool_loop" in vars(AbstractClient)


@pytest.mark.parametrize("name", sorted(KNOWN_FALSE))
def test_known_false_classes(name: str) -> None:
    """hf / jev / google-live declare False on their own class body; skipped when the satellite is absent."""
    module_name, attribute = KNOWN_FALSE[name]
    module = pytest.importorskip(module_name)
    cls = getattr(module, attribute)
    assert cls.supports_tool_loop is False
    assert "supports_tool_loop" in vars(cls)


class _CommentOnly:
    async def ask(self, prompt):
        """Mentions self._execute_tool(prompt) only in a docstring."""
        note = "self._run_tool_call_loop()"  # self._execute_tool(prompt)
        return note


class _HelperBase:
    async def ask(self, prompt):
        return await self._drive(prompt)

    async def _drive(self, prompt):
        return await self._run_tool_call_loop(prompt)


class _InheritsLoop(_HelperBase):
    async def ask(self, prompt):
        return await super().ask(prompt)


class _DeadNested:
    async def ask(self, prompt):
        def _never():
            return self._execute_tool(prompt)

        handle = self._execute_tool
        return handle is None


@pytest.mark.parametrize("provider", sorted(_installed_classes()))
def test_flag_matches_resolved_ask(provider: str) -> None:
    """The declared flag equals AST tool-loop evidence, except for the documented agent bridges."""
    cls = _installed_classes()[provider]
    unresolved: list[str] = []
    runs_loop = bool(_resolved_ask_calls(cls, unresolved) & TOOL_EXECUTION_METHODS)
    expected = runs_loop or cls.__name__ in EXTERNAL_LOOP_CLIENTS
    assert cls.supports_tool_loop is expected, (
        f"{provider}: {cls.__name__} runs_loop={runs_loop}, "
        f"supports_tool_loop={cls.supports_tool_loop}, unresolved={unresolved}"
    )


def test_comment_and_string_markers_do_not_count() -> None:
    assert not (_resolved_ask_calls(_CommentOnly) & TOOL_EXECUTION_METHODS)


def test_executable_marker_counts_through_mro_and_helper() -> None:
    assert "_run_tool_call_loop" in _resolved_ask_calls(_InheritsLoop)


def test_uncalled_nested_marker_does_not_count() -> None:
    assert not (_resolved_ask_calls(_DeadNested) & TOOL_EXECUTION_METHODS)


def test_claude_bridge_exposes_registered_tools() -> None:
    """A tool registered in ClaudeAgentClient is exposed by the bridge built by ask()."""
    pytest.importorskip("claude_agent_sdk")
    claude_agent = pytest.importorskip("parrot.clients.anthropic.claude_agent")
    from parrot.clients.anthropic.claude_agent_bridge import ClaudeAgentToolBridge

    client = claude_agent.ClaudeAgentClient()
    client.tool_manager = ToolManager(include_search_tool=False)

    async def feat848_sentinel(value: str) -> str:
        return value

    client.tool_manager.register_tool(
        name="feat848_sentinel",
        description="Echo a value (FEAT-848 sentinel).",
        input_schema={"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
        function=feat848_sentinel,
    )
    bridge = ClaudeAgentToolBridge(client.tool_manager, tool_timeout=None)
    selected = bridge.select("", claude_agent.ClaudeAgentRunOptions().max_exposed_tools)
    assert "feat848_sentinel" in [getattr(tool, "name", None) for tool in selected]
    bridge.build_server(selected)
    assert "mcp__parrot__feat848_sentinel" in bridge.exposed_names()
