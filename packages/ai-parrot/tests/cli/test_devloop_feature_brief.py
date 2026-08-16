"""Loader + CLI-wiring tests for the FEAT-378 feature-brief support (TASK-1926).

Covers ``DevLoopConsole``'s union-aware brief loading (``kind: feature`` ->
``FeatureBrief``, everything else -> ``WorkBrief``, byte-identical to the
pre-FEAT-378 behavior), the friendly-error path for an invalid feature
brief, and ``parrot devloop run --brief ... --yes`` CLI wiring (mirrors
``test_click_wiring.py``'s ``DevLoopConsole``-mocking pattern).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner
from rich.console import Console

from parrot.cli.devloop.console import DevLoopConsole
from parrot.flows.dev_loop.models import FeatureBrief, WorkBrief


def _console() -> DevLoopConsole:
    console = Console(record=True, force_terminal=True, width=120)
    return DevLoopConsole(console=console, session=MagicMock())


# ── Loader roundtrip (kind-based union routing, TASK-1918's parse_brief) ──


async def test_feature_brief_yaml_roundtrip(tmp_path):
    doc = tmp_path / "proposal.md"
    doc.write_text("# proposal")
    brief_file = tmp_path / "feature.yaml"
    brief_file.write_text(
        "kind: feature\n"
        f"document_path: {doc}\n"
        "document_kind: proposal\n"
        "jira_issue_key: OPS-42\n"
    )

    dc = _console()
    result = await dc._collect_work_brief(str(brief_file))

    assert isinstance(result, FeatureBrief)
    assert result.kind == "feature"
    assert result.document_path == str(doc)
    assert result.document_kind == "proposal"
    assert result.jira_issue_key == "OPS-42"


async def test_workbrief_yaml_unchanged(tmp_path):
    brief_file = tmp_path / "bug.yaml"
    brief_file.write_text(
        "kind: bug\n"
        "summary: customer sync drops the last row\n"
        "affected_component: etl/customers/sync.yaml\n"
        "acceptance_criteria:\n"
        "  - kind: shell\n"
        "    name: lint\n"
        "    command: ruff check .\n"
        "escalation_assignee: a@example.com\n"
        "reporter: b@example.com\n"
    )

    dc = _console()
    result = await dc._collect_work_brief(str(brief_file))

    assert isinstance(result, WorkBrief)
    assert result.kind == "bug"
    assert result.summary == "customer sync drops the last row"


async def test_workbrief_yaml_no_kind_defaults_to_bug(tmp_path):
    """Zero behavior change: a file with no `kind` key still loads as WorkBrief."""
    brief_file = tmp_path / "no_kind.yaml"
    brief_file.write_text(
        "summary: customer sync drops the last row\n"
        "affected_component: etl/customers/sync.yaml\n"
        "acceptance_criteria:\n"
        "  - kind: shell\n"
        "    name: lint\n"
        "    command: ruff check .\n"
        "escalation_assignee: a@example.com\n"
        "reporter: b@example.com\n"
    )

    dc = _console()
    result = await dc._collect_work_brief(str(brief_file))

    assert isinstance(result, WorkBrief)
    assert result.kind == "bug"


async def test_load_brief_file_still_works_for_revision_brief(tmp_path):
    """`_load_brief_file` (used by RevisionBrief) is untouched by this task."""
    from pydantic import BaseModel

    class SimpleBrief(BaseModel):
        title: str
        count: int = 1

    brief_file = tmp_path / "brief.json"
    brief_file.write_text('{"title": "test brief", "count": 5}')

    dc = _console()
    result = dc._load_brief_file(str(brief_file), SimpleBrief)
    assert result.title == "test brief"
    assert result.count == 5


# ── Friendly error handling (no raw traceback) ───────────────────────────


async def test_feature_brief_missing_document_friendly_error(tmp_path):
    brief_file = tmp_path / "feature.yaml"
    brief_file.write_text(
        "kind: feature\n"
        f"document_path: {tmp_path / 'does-not-exist.md'}\n"
        "document_kind: proposal\n"
    )

    dc = _console()

    async def fake_build_runtime(**kwargs):
        return MagicMock()

    with patch("parrot.cli.devloop.bootstrap.build_runtime", fake_build_runtime):
        exit_code = await dc.start(brief_file=str(brief_file))

    assert exit_code == 1
    output = dc.console.export_text()
    assert "Brief error" in output
    assert "Traceback" not in output


async def test_brief_file_not_found_friendly_error(tmp_path):
    dc = _console()

    async def fake_build_runtime(**kwargs):
        return MagicMock()

    with patch("parrot.cli.devloop.bootstrap.build_runtime", fake_build_runtime):
        exit_code = await dc.start(brief_file=str(tmp_path / "missing.yaml"))

    assert exit_code == 1
    output = dc.console.export_text()
    assert "Brief error" in output
    assert "Traceback" not in output


# ── CLI wiring: --yes non-interactive dispatch (mirrors test_click_wiring.py) ──


def test_run_yes_noninteractive_feature(tmp_path):
    """``run --brief feature.yaml --yes`` reaches DevLoopConsole.start(brief_file=...)."""
    doc = tmp_path / "proposal.md"
    doc.write_text("# proposal")
    brief_file = tmp_path / "feature.yaml"
    brief_file.write_text(
        "kind: feature\n"
        f"document_path: {doc}\n"
        "document_kind: proposal\n"
    )

    mock_console_cls = MagicMock()
    mock_instance = MagicMock()
    mock_instance.start = AsyncMock(return_value=0)
    mock_console_cls.return_value = mock_instance

    from parrot.cli.devloop import devloop

    runner = CliRunner()
    with patch("parrot.cli.devloop.console.DevLoopConsole", mock_console_cls):
        result = runner.invoke(devloop, ["run", "--brief", str(brief_file), "--yes"])

    assert result.exit_code == 0
    mock_instance.start.assert_called_once()
    call_kwargs = mock_instance.start.call_args
    assert (
        call_kwargs[1].get("brief_file") == str(brief_file)
        or call_kwargs[0][0] == str(brief_file)
    )
