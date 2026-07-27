"""Integration tests for ``parrot devloop`` console against a scripted runner.

Exercises the full console↔runner↔host pipeline with monkeypatched
bootstrap (no Redis, claude CLI, Jira, or external services).

The ``parrot.flows.dev_loop.models`` import chain pulls in Cython
(``parrot.utils.types``), which requires a compiled ``.so`` not
available in worktrees. Tests mock ``_collect_work_brief`` /
``_collect_revision_brief`` to return plain objects, keeping the
integration target at console↔runner↔host.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console

from parrot.cli.devloop.console import DevLoopConsole

from .conftest import ScriptedRunner, StubHost, StubRuntime


def _make_session(inputs: list[str]) -> AsyncMock:
    session = AsyncMock()
    session.prompt_async = AsyncMock(side_effect=inputs)
    return session


def _patch_bootstrap(stub_runtime: StubRuntime):
    """Patch build_runtime at the import site inside console.py."""
    async def fake_build_runtime(**kwargs):
        return stub_runtime
    return patch(
        "parrot.cli.devloop.bootstrap.build_runtime",
        fake_build_runtime,
    )


@dataclass
class FakeBrief:
    kind: str = "bug"
    summary: str = "integration test"
    affected_component: str = "cli"
    acceptance_criteria: list = field(default_factory=list)
    reporter: str = "test@x.com"
    escalation_assignee: str = "oncall@x.com"


@dataclass
class FakeRevisionBrief:
    repo_path: str = "/tmp/repo"
    branch: str = "feat-test"
    pr_number: int = 42
    repository: str = "org/repo"
    jira_issue_key: str = "TEST-1"
    feedback: str = "add tests"
    head_sha: str = "abc123"


async def _run_console(dc: DevLoopConsole, **start_kwargs) -> int:
    """Run console.start(), catching SystemExit from /quit."""
    try:
        return await asyncio.wait_for(dc.start(**start_kwargs), timeout=10.0)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0


@pytest.mark.asyncio
async def test_console_e2e_fake_flow(scripted_runner: ScriptedRunner, stub_runtime: StubRuntime):
    """Full e2e: brief → dispatch → gate approve → run completes → exit 0."""
    inputs = [
        "a",           # approve gate
        "looks good",  # gate comment
        "/quit",       # exit console
    ]
    session = _make_session(inputs)
    console = Console(record=True, force_terminal=True, width=120)
    dc = DevLoopConsole(console=console, session=session)

    async def fake_collect_work_brief(_brief_file=None):
        return FakeBrief()

    with _patch_bootstrap(stub_runtime), \
         patch.object(dc, "_collect_work_brief", fake_collect_work_brief):
        exit_code = await _run_console(dc)

    assert exit_code == 0
    assert len(scripted_runner._resolve_calls) == 1
    assert scripted_runner._resolve_calls[0]["resolution"] == "approved"

    output = console.export_text()
    assert "Dispatched run" in output


@pytest.mark.asyncio
async def test_console_revision_e2e(scripted_runner: ScriptedRunner, stub_runtime: StubRuntime):
    """Revision mode: brief → run_revision → completes → exit 0."""
    inputs = ["/quit"]
    session = _make_session(inputs)
    console = Console(record=True, force_terminal=True, width=120)
    dc = DevLoopConsole(console=console, session=session)

    async def fake_collect_revision_brief(_brief_file=None):
        return FakeRevisionBrief()

    with _patch_bootstrap(stub_runtime), \
         patch.object(dc, "_collect_revision_brief", fake_collect_revision_brief):
        exit_code = await _run_console(dc, revision=True)

    assert exit_code == 0
    output = console.export_text()
    assert "Dispatched revision run" in output


@pytest.mark.asyncio
async def test_console_two_runs_attach_e2e(scripted_runner: ScriptedRunner, stub_runtime: StubRuntime):
    """Two runs registered; /runs lists both; /attach switches active run."""
    console = Console(record=True, force_terminal=True, width=120)
    dc = DevLoopConsole(console=console, session=AsyncMock())
    dc._runtime = stub_runtime

    async def noop():
        return MagicMock(status="completed")
    dc._runs["run-aaa"] = asyncio.create_task(noop())
    dc._runs["run-bbb"] = asyncio.create_task(noop())
    await asyncio.sleep(0.05)

    from parrot.cli.devloop.renderer import RunView
    host_a = StubHost("run-aaa")
    host_b = StubHost("run-bbb")
    scripted_runner._hosts["run-aaa"] = host_a
    scripted_runner._hosts["run-bbb"] = host_b
    dc._views["run-aaa"] = RunView(host_a, console, run_id="run-aaa")
    dc._views["run-bbb"] = RunView(host_b, console, run_id="run-bbb")

    await dc._cmd_runs("")
    output = console.export_text()
    assert "run-aaa" in output
    assert "run-bbb" in output

    await dc._cmd_attach("run-bbb")
    assert dc._active_run_id == "run-bbb"
