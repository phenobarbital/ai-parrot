"""RunView delegates its Live handling to LiveRegion (FEAT-573 TASK-3414, spec M14)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from parrot.cli.console import LiveRegion  # provided by TASK-3400
from parrot.cli.devloop.renderer import RunView


class _Host:
    def __init__(self) -> None:
        self.state = MagicMock(run_id="run-x", phase="running", summary="", jira_issue_key="", pr_url="", gates={})

    def replay_since(self, last_seq: int):
        return []


def _view() -> RunView:
    return RunView(_Host(), Console(record=True, force_terminal=True, width=100), run_id="run-x")


def test_runview_owns_a_live_region():
    view = _view()
    assert isinstance(view.region, LiveRegion)
    assert not hasattr(view, "_live")


def test_pause_resume_delegate(monkeypatch):
    view = _view()
    calls = []
    monkeypatch.setattr(view.region, "pause", lambda: calls.append("pause"))
    monkeypatch.setattr(view.region, "resume", lambda: calls.append("resume"))
    view.pause()
    assert view._paused is True
    view.resume()
    assert view._paused is False
    assert calls == ["pause", "resume"]


@pytest.mark.asyncio
async def test_run_live_starts_updates_and_stops(monkeypatch):
    view = _view()
    events = []
    monkeypatch.setattr(view.region, "start", lambda: events.append("start"))
    monkeypatch.setattr(view.region, "stop", lambda: events.append("stop"))
    monkeypatch.setattr(view.region, "update", lambda r: events.append("update"))
    stop = asyncio.Event()
    task = asyncio.create_task(view.run_live(stop))
    await asyncio.sleep(0.2)
    stop.set()
    await task
    # The region is started once (after the initial content is staged via
    # update()) and stopped exactly once, with at least the initial update
    # plus one poll-loop update happening in between.
    assert events.count("start") == 1
    assert events.count("stop") == 1
    assert events[-1] == "stop"
    assert events.index("start") < events.index("stop")
    assert events.count("update") >= 2
