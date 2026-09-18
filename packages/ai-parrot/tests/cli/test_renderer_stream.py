"""Streaming renderer tests (FEAT-573 TASK-3405, spec §4)."""
from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from rich.console import Console  # verified: renderer.py:13
from rich.markdown import Markdown  # verified: renderer.py:14

from parrot.cli.commands import ConversationTurn  # verified: commands.py:38
from parrot.cli.console import LiveRegion  # provided by TASK-3400
from parrot.cli.renderer import ResponseRenderer


@pytest.fixture
def buf_console() -> Console:
    return Console(file=io.StringIO(), force_terminal=True, width=100)


@pytest.fixture
def renderer_with_spy(buf_console):
    region = MagicMock(spec=LiveRegion)
    return ResponseRenderer(console=buf_console, region=region), region


def test_renderer_stream_chunk_never_writes_stdout(renderer_with_spy, capsys):
    renderer, region = renderer_with_spy
    renderer.render_stream_start()
    renderer.render_stream_chunk("# hi")
    assert capsys.readouterr().out == ""
    region.update.assert_called()
    renderable = region.update.call_args.args[0]
    assert isinstance(renderable, Markdown)


def test_renderer_partial_markdown_does_not_raise(buf_console):
    r = ResponseRenderer(console=buf_console)
    r.render_stream_start()
    r.render_stream_chunk("```python\nprint(1")
    r.render_stream_chunk("\n| a | b\n| --")
    r.render_stream_end(None)  # must not raise


def test_renderer_usage_unknown_not_zero(buf_console):
    r = ResponseRenderer(console=buf_console)
    r.render_stream_start()
    r.render_stream_end(SimpleNamespace(tool_calls=[], usage=None))
    out = buf_console.file.getvalue()
    assert "n/a" in out and "total=0" not in out


def test_renderer_lazy_region_uses_swapped_console():
    r = ResponseRenderer()
    swapped = Console(file=io.StringIO(), force_terminal=True)
    r.console = swapped
    assert r.region.console is swapped


def test_renderer_render_history():
    # highlight=False: the default ReprHighlighter otherwise wraps digit runs in
    # their own ANSI span, splitting "sess-123"/"2+2" across escape codes.
    console = Console(file=io.StringIO(), force_terminal=True, width=100, highlight=False)
    r = ResponseRenderer(console=console)
    turn1 = ConversationTurn(
        query="what is 2+2?",
        response=SimpleNamespace(output="4", response=None, tool_calls=[], usage=None),
    )
    turn2 = ConversationTurn(
        query="and 3+3?",
        response=SimpleNamespace(output="6", response=None, tool_calls=[], usage=None),
    )
    r.render_history([turn1, turn2], session_id="sess-123")
    out = console.file.getvalue()
    assert "Resumed session" in out
    assert "sess-123" in out
    assert "what is 2+2?" in out
    assert "and 3+3?" in out


def test_blocking_safe_file_removed():
    import parrot.cli.renderer as mod
    assert not hasattr(mod, "_BlockingSafeFile")
    import inspect
    assert "sys.stdout.write" not in inspect.getsource(mod)  # AC11
