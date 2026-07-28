"""Unit tests for the console kind picker + feature intake path (FEAT-388, Module 3).

Uses a fake ``FeatureIntake`` (patched at its definition site,
``parrot.cli.devloop.intake.FeatureIntake``, so the deferred
``from parrot.cli.devloop.intake import FeatureIntake`` inside
``console.py`` resolves to the fake) — mirrors the ``FakeClient``/mocked-
session pattern used in ``test_intake.py`` and ``test_console.py``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from parrot.cli.devloop.console import DevLoopConsole
from rich.console import Console


def _make_console(inputs: list[str]) -> DevLoopConsole:
    session = AsyncMock()
    session.prompt_async = AsyncMock(side_effect=inputs)
    console = Console(record=True, force_terminal=True, width=120)
    return DevLoopConsole(console=console, session=session)


class FakeDraft:
    """Stand-in for ``FeatureDraft`` — only the attributes console.py reads."""

    def __init__(self, **kwargs: Any) -> None:
        self.title = kwargs.get("title", "Add dark mode")
        self.slug = kwargs.get("slug", "add-dark-mode")
        self.problem_statement = kwargs.get("problem_statement", "Users want dark mode.")
        self.requirements = kwargs.get("requirements", ["Toggle in settings"])
        self.acceptance_criteria = kwargs.get("acceptance_criteria", ["Theme persists"])
        self.affected_areas = kwargs.get("affected_areas", [])
        self.out_of_scope = kwargs.get("out_of_scope", [])
        self.open_questions = kwargs.get("open_questions", [])

    def model_copy(self, update: dict | None = None) -> FakeDraft:
        data = dict(self.__dict__)
        data.update(update or {})
        return FakeDraft(**data)


class FakeBrief:
    """Stand-in for the ``FeatureBrief`` returned by ``build_brief``."""

    def __init__(
        self,
        *,
        document_path: str = "",
        dev_agents: Any = None,
        judge_panel: Any = None,
    ) -> None:
        self.document_kind = "brainstorm"
        self.document_path = document_path
        self.dev_agents = dev_agents
        self.judge_panel = judge_panel


class FakeFeatureIntake:
    """Fake ``FeatureIntake`` — records calls, never touches an LLM or disk."""

    instances: list[FakeFeatureIntake] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.generate_calls: list[str] = []
        self.regenerate_calls: list[tuple] = []
        FakeFeatureIntake.instances.append(self)

    async def generate(self, text: str) -> FakeDraft:
        self.generate_calls.append(text)
        return FakeDraft()

    async def regenerate(self, text: str, guidance: str) -> FakeDraft:
        self.regenerate_calls.append((text, guidance))
        return FakeDraft(problem_statement=f"Revised: {guidance}")

    def write_document(self, draft: FakeDraft) -> Path:
        return Path(f"/tmp/{draft.slug}.brainstorm.md")

    def build_brief(
        self,
        draft: FakeDraft,
        document_path: Path,
        *,
        dev_agents: Any = None,
        judge_panel: Any = None,
    ) -> FakeBrief:
        return FakeBrief(
            document_path=str(document_path), dev_agents=dev_agents, judge_panel=judge_panel
        )


def _patch_intake():
    return patch("parrot.cli.devloop.intake.FeatureIntake", FakeFeatureIntake)


@pytest.mark.asyncio
async def test_kind_picker_bug_reaches_workbrief_wizard():
    """Picking 'bug' pre-fills WorkBrief.kind and reaches the existing wizard."""
    dc = _make_console(["1"])  # kind picker: bug
    captured: dict = {}

    async def fake_workbrief_wizard(kind: str, *, dev_agents_flag=None):
        captured["kind"] = kind
        return "workbrief-sentinel"

    with patch.object(dc, "_collect_workbrief_wizard", fake_workbrief_wizard):
        result = await dc._collect_work_brief()

    assert captured["kind"] == "bug"
    assert result == "workbrief-sentinel"


@pytest.mark.asyncio
async def test_kind_picker_feature_runs_intake():
    """Picking 'feature' routes to intake; never asks for Jira/log sources (G3)."""
    dc = _make_console(
        [
            "3",  # kind picker: feature
            "I want dark mode",  # multiline free text, line 1
            "",  # empty line ends multiline input
            "accept",  # confirm loop
            "n",  # dev-agent pool: skip
            "n",  # judge panel: skip
        ]
    )

    with _patch_intake():
        brief = await dc._collect_work_brief()

    assert brief.document_kind == "brainstorm"
    output = dc.console.export_text()
    assert "jira" not in output.lower()
    assert "log source" not in output.lower()
    assert FakeFeatureIntake.instances[-1].generate_calls == ["I want dark mode"]


@pytest.mark.asyncio
async def test_feature_command_enters_intake():
    """/feature jumps straight into intake — no kind picker prompt."""
    dc = _make_console(
        [
            "accept",  # confirm loop
            "n",  # dev-agent pool: skip
            "n",  # judge panel: skip
        ]
    )
    dispatched: list[Any] = []

    async def fake_dispatch_run(brief: Any) -> str:
        dispatched.append(brief)
        return "run-1"

    with _patch_intake(), patch.object(dc, "_dispatch_run", fake_dispatch_run):
        await dc._cmd_feature("a dark mode toggle please")

    assert len(dispatched) == 1
    assert dispatched[0].document_kind == "brainstorm"
    assert FakeFeatureIntake.instances[-1].generate_calls == ["a dark mode toggle please"]


@pytest.mark.asyncio
async def test_redo_regenerates_with_guidance():
    """'redo <guidance>' calls FeatureIntake.regenerate and re-shows the draft."""
    dc = _make_console(
        [
            "redo make it cover mobile too",
            "accept",
            "n",
            "n",
        ]
    )

    with _patch_intake():
        brief = await dc._collect_work_brief(intake_text="dark mode request")

    assert brief.document_kind == "brainstorm"
    assert FakeFeatureIntake.instances[-1].regenerate_calls == [
        ("dark mode request", "make it cover mobile too")
    ]


@pytest.mark.asyncio
async def test_cancel_dispatches_nothing():
    """'cancel' raises EOFError and never reaches dispatch (G5)."""
    dc = _make_console(
        [
            "3",  # kind picker: feature
            "some text",
            "",  # end multiline
            "cancel",
        ]
    )
    dispatched: list[Any] = []

    async def fake_dispatch_run(brief: Any) -> str:
        dispatched.append(brief)
        return "run-1"

    with _patch_intake(), patch.object(dc, "_dispatch_run", fake_dispatch_run):
        with pytest.raises(EOFError):
            await dc._collect_work_brief()

    assert dispatched == []


# ── Post-review fixes: --yes on the interactive feature path, Brief error:
# consistency on /new + /feature, and "no input = no change" for list edits ──


@pytest.mark.asyncio
async def test_yes_skips_confirm_loop_on_interactive_feature_path():
    """skip_confirm (--yes) applies even when 'feature' is chosen via the
    interactive kind picker, not just via --text."""
    dc = _make_console(
        [
            "3",  # kind picker: feature
            "I want dark mode",  # multiline free text, line 1
            "",  # empty line ends multiline input
            # No further inputs consumed: skip_confirm=True means no
            # confirm loop, no dev-agent pool prompt, no judge-panel prompt.
        ]
    )

    with _patch_intake():
        brief = await dc._collect_work_brief(skip_confirm=True)

    assert brief.document_kind == "brainstorm"
    assert brief.dev_agents is None
    assert brief.judge_panel is None


@pytest.mark.asyncio
async def test_cmd_feature_empty_text_shows_brief_error():
    """An empty free-text request surfaces 'Brief error:' (G5), not a raw exception."""
    dc = _make_console([""])  # multiline prompt immediately ends with no lines
    dispatched: list[Any] = []

    async def fake_dispatch_run(brief: Any) -> str:
        dispatched.append(brief)
        return "run-1"

    with _patch_intake(), patch.object(dc, "_dispatch_run", fake_dispatch_run):
        await dc._cmd_feature("")

    assert dispatched == []
    output = dc.console.export_text()
    assert "Brief error" in output
    assert "Traceback" not in output


@pytest.mark.asyncio
async def test_edit_list_field_empty_line_keeps_unchanged():
    """'edit <list-field>' with an immediate empty line leaves the list
    unchanged, matching the scalar-field branch's "no input = no change"."""
    from parrot.cli.devloop.intake import FeatureDraft as RealFeatureDraft

    dc = _make_console([""])  # immediate empty line
    draft = RealFeatureDraft(
        title="Add dark mode",
        slug="add-dark-mode",
        problem_statement="Users want dark mode.",
        requirements=["existing requirement"],
    )

    result = await dc._edit_draft_field(draft, "requirements")

    assert result.requirements == ["existing requirement"]
