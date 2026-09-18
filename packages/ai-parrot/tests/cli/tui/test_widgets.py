"""Widget tests for parrot.cli.tui.widgets (FEAT-573, spec §4)."""

from __future__ import annotations

from typing import Any, List

import pytest

textual = pytest.importorskip("textual")

from prompt_toolkit.history import InMemoryHistory  # verified: repl.py:16
from textual.app import App, ComposeResult  # verified: textual 8.2.8 probe

from parrot.cli.events import TextDelta, ToolFinished, ToolStarted, TurnCompleted, TurnEventKind, TurnStarted
from parrot.cli.tui.widgets import Composer, StatusBar, ToolActivity, TranscriptView, TurnPanel


class _Harness(App[None]):
    """Minimal app mounting the widgets under test."""

    def compose(self) -> ComposeResult:
        yield TranscriptView(id="transcript")
        yield Composer(history=InMemoryHistory(), completions=lambda: ["/help", "/tools"], id="composer")
        yield StatusBar(id="status")


def _started(turn_id: str = "t1", query: str = "hi") -> TurnStarted:
    return TurnStarted(kind=TurnEventKind.STARTED, turn_id=turn_id, seq=0, query=query, streaming=True)


@pytest.mark.asyncio
async def test_transcript_begin_turn_mounts_panel_and_follows():
    app = _Harness()
    async with app.run_test() as pilot:
        view = app.query_one("#transcript", TranscriptView)
        await view.apply(_started())
        await pilot.pause()
        assert len(view.query(TurnPanel)) == 1 and view.following is True


@pytest.mark.asyncio
async def test_tool_rows_only_from_tool_started():
    app = _Harness()
    async with app.run_test() as pilot:
        view = app.query_one("#transcript", TranscriptView)
        await view.apply(_started())
        panel = view.query_one(TurnPanel)

        # A text delta that merely *mentions* a tool must never create a row (AC8).
        await view.apply(TextDelta(kind=TurnEventKind.DELTA, turn_id="t1", seq=1, text="running tool X now"))
        await pilot.pause()
        assert panel._tools.display is False
        assert len(panel._tools._rows) == 0

        await view.apply(ToolStarted(kind=TurnEventKind.TOOL_STARTED, turn_id="t1", seq=2, call_id="c1", tool_name="X"))
        await pilot.pause()
        assert panel._tools.display is True
        assert len(panel._tools._rows) == 1

        await view.apply(
            ToolFinished(
                kind=TurnEventKind.TOOL_FINISHED,
                turn_id="t1",
                seq=3,
                call_id="c1",
                tool_name="X",
                duration_ms=12.0,
                result_status="ok",
                result_size_bytes=10,
            )
        )
        await pilot.pause()
        assert len(panel._tools._rows) == 1


@pytest.mark.asyncio
async def test_composer_enter_submits_and_ctrl_j_newline():
    app = _Harness()
    async with app.run_test() as pilot:
        composer = app.query_one("#composer", Composer)
        posted: List[Composer.Submitted] = []
        composer.post_message = lambda message: posted.append(message)  # type: ignore[method-assign]
        composer.focus()
        await pilot.pause()

        await pilot.press("h", "i")
        await pilot.press("enter")
        await pilot.pause()
        assert composer.text == ""
        assert len(posted) == 1 and posted[0].text == "hi"
        assert composer._history.get_strings() == ["hi"]

        await pilot.press("h")
        await pilot.press("ctrl+j")
        await pilot.press("j")
        await pilot.pause()
        assert composer.text == "h\nj"


@pytest.mark.asyncio
async def test_status_bar_waiting_then_streaming_then_na_usage():
    app = _Harness()
    async with app.run_test():
        status = app.query_one("#status", StatusBar)
        calls: List[str] = []
        status.update = lambda content="", *, layout=True: calls.append(str(content))  # type: ignore[method-assign]

        status.apply(_started())
        assert "waiting" in calls[-1]

        status.apply(TextDelta(kind=TurnEventKind.DELTA, turn_id="t1", seq=1, text="hi"))
        assert "streaming" in calls[-1]

        class _Message:
            usage = None
            tool_calls: List[Any] = []

        status.apply(TurnCompleted(kind=TurnEventKind.COMPLETED, turn_id="t1", seq=2, text="done", message=_Message()))
        assert "n/a" in calls[-1]


@pytest.mark.asyncio
async def test_transcript_cap_hides_old_turns():
    app = _Harness()
    async with app.run_test() as pilot:
        view = app.query_one("#transcript", TranscriptView)
        for i in range(205):
            await view.apply(_started(turn_id=f"t{i}", query=f"q{i}"))
        await pilot.pause()
        assert len(view.query(TurnPanel)) <= 200
        assert view._hidden_count == 5
        assert view._hidden_notice is not None
        assert "hidden" in view._hidden_notice_text
