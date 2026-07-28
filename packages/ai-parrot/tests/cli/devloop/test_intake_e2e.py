"""Intake-to-dispatch end-to-end test (FEAT-388 TASK-1972).

Exercises the *full* chain: free text -> ``FeatureDraft`` (mocked intake
LLM) -> a real ``FeatureIntake.write_document()`` call (writing to a
tmp-path-scoped ``sdd/proposals/``, no mocking of the document-rendering
logic itself) -> ``FeatureBrief`` -> ``DevLoopConsole`` dispatch through a
fake runner. No live LLM, Redis, or `claude` binary is used anywhere —
every external dependency is faked, mirroring the existing
``test_console.py`` (``StubRunner``) and ``test_intake.py``
(``FakeClient``) patterns (TASK-1898's fake-flow style).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from parrot.cli.devloop.console import DevLoopConsole
from parrot.cli.devloop.intake import FeatureDraft
from rich.console import Console

# ── Fake intake LLM client (mirrors test_intake.py's FakeClient) ──────────


class InvokeResultStub:
    """Minimal stand-in for ``InvokeResult`` — only ``.output`` is read."""

    def __init__(self, output: Any) -> None:
        self.output = output


class FakeIntakeClient:
    """Fake ``AbstractClient`` — ``invoke()`` returns a canned FeatureDraft."""

    def __init__(self, draft: FeatureDraft) -> None:
        self._draft = draft
        self.prompts: list[str] = []

    async def invoke(self, prompt: str, *, output_type: Any = None, **kwargs: Any):
        self.prompts.append(prompt)
        return InvokeResultStub(self._draft)


# ── Fake runner (mirrors test_console.py's StubRunner) ────────────────────


@dataclass
class StubFlowResult:
    status: str = "completed"
    responses: dict = field(default_factory=dict)
    errors: dict = field(default_factory=dict)


class StubRunner:
    """Records every brief ``run()`` receives — the dispatch proof."""

    def __init__(self) -> None:
        self.received_briefs: list[Any] = []
        self._hosts: dict[str, Any] = {}
        self._active: set[str] = set()
        self._parked: set[str] = set()

    def get_host(self, run_id: str):
        return self._hosts.get(run_id)

    @property
    def active_runs(self) -> set[str]:
        return set(self._active)

    @property
    def parked_runs(self) -> set[str]:
        return set(self._parked)

    async def run(self, brief: Any, run_id: str | None = None, **kwargs: Any) -> StubFlowResult:
        self.received_briefs.append(brief)
        return StubFlowResult()


@dataclass
class StubRuntime:
    runner: Any
    flow: Any = None
    dispatcher: Any = None
    jira_toolkit: Any = None
    redis_url: str = ""
    reporter: str = "test@example.com"
    escalation_assignee: str = "oncall@example.com"


@pytest.mark.asyncio
async def test_intake_to_dispatch_e2e(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """free text -> FeatureDraft (mock LLM) -> document written with
    frontmatter -> FeatureBrief -> fake runner.run received it."""
    # FeatureIntake.write_document() defaults to Path("sdd/proposals")
    # relative to cwd — chdir into tmp_path so the REAL write happens in
    # an isolated, disposable directory (no mocking of document rendering).
    monkeypatch.chdir(tmp_path)

    draft = FeatureDraft(
        title="Add dark mode",
        slug="add-dark-mode",
        problem_statement="Users want a dark theme across the app.",
        requirements=["Toggle in settings", "Persist preference"],
        acceptance_criteria=["Theme persists across sessions"],
    )
    fake_client = FakeIntakeClient(draft)

    session = AsyncMock()
    session.prompt_async = AsyncMock(side_effect=[
        "3",                            # kind picker: feature
        "I want a dark mode toggle",    # multiline free text, line 1
        "",                             # empty line ends multiline input
        "accept",                       # confirm loop
        "n",                            # dev-agent pool: skip
        "n",                            # judge panel: skip
    ])
    console = Console(record=True, force_terminal=True, width=120)
    runner = StubRunner()
    dc = DevLoopConsole(console=console, session=session)
    dc._runtime = StubRuntime(runner=runner)

    with patch("parrot.clients.factory.LLMFactory.create", return_value=fake_client):
        brief = await dc._collect_work_brief()
        await dc._dispatch_run(brief)

    # The LLM was actually invoked with the user's free text.
    assert fake_client.prompts
    assert "I want a dark mode toggle" in fake_client.prompts[0]

    # FeatureBrief assembled correctly.
    assert brief.kind == "feature"
    assert brief.document_kind == "brainstorm"

    # The document was really written to disk with FEAT-145 frontmatter.
    document_path = Path(brief.document_path)
    assert document_path.is_file()
    assert document_path.resolve() == (
        tmp_path / "sdd" / "proposals" / "add-dark-mode.brainstorm.md"
    ).resolve()
    text = document_path.read_text(encoding="utf-8")
    assert "type: feature" in text
    assert "base_branch: dev" in text
    assert "# Brainstorm: Add dark mode" in text
    assert "Toggle in settings" in text

    # The (fake) runner actually received this exact brief for dispatch.
    assert len(runner.received_briefs) == 1
    assert runner.received_briefs[0] is brief

    output = console.export_text()
    assert "Dispatched run" in output
