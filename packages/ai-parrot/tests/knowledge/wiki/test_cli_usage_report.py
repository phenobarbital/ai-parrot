"""FEAT-783 AC-12 / AC-14 — usage CLI + MCP tool."""

from __future__ import annotations

import asyncio
import json
import subprocess
import typing
from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.usage_operations import UsageReportInput, op_usage_report
from parrot.observability.recorders.models import UsageRecord


def _write_rows(root: Path) -> None:
    """Write representative attributed rows to the feature JSONL file."""
    rows = [
        UsageRecord(
            provider="openai",
            model="gpt-5",
            input_tokens=10,
            output_tokens=4,
            cost_usd=0.25,
            equivalent_usd=0.50,
            feat_id="FEAT-1",
            task_id="TASK-1",
            attempt_uid="attempt-1",
            roster_seat="development.w1",
        ),
        UsageRecord(
            provider="anthropic",
            model="claude",
            input_tokens=20,
            output_tokens=8,
            cost_usd=0.75,
            equivalent_usd=1.00,
            feat_id="FEAT-1",
            task_id="TASK-2",
            attempt_uid="attempt-2",
            roster_seat="qa",
        ),
    ]
    root.mkdir(parents=True, exist_ok=True)
    (root / "FEAT-1.jsonl").write_text(
        "".join(f"{row.model_dump_json()}\n" for row in rows),
        encoding="utf-8",
    )


def test_cli_renders_report_from_rows(tmp_path: Path) -> None:
    """The CLI renders tokens and cost for each supported grouping."""
    _write_rows(tmp_path)
    expected_groups = {
        "task": {"TASK-1", "TASK-2"},
        "model": {"gpt-5", "claude"},
        "seat": {"development.w1", "qa"},
    }

    for grouping, expected in expected_groups.items():
        result = CliRunner().invoke(
            wiki,
            ["usage", "report", "--feat", "FEAT-1", "--by", grouping, "--root", str(tmp_path), "--format", "json"],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert {agent["seat"] for agent in payload["agents"]} == expected
        assert payload["total_input_tokens"] == 30
        assert payload["total_output_tokens"] == 12
        assert payload["total_cost_usd"] == 1.0
        assert payload["total_equivalent_usd"] == 1.5


@pytest.mark.asyncio
async def test_mcp_tool_matches_cli(tmp_path: Path) -> None:
    """The shared MCP operation returns exactly the CLI JSON payload."""
    _write_rows(tmp_path)
    cli_result = await asyncio.to_thread(
        CliRunner().invoke,
        wiki,
        ["usage", "report", "--feat", "FEAT-1", "--by", "seat", "--root", str(tmp_path), "--format", "json"],
    )

    operation_result = await op_usage_report(UsageReportInput(feat_id="FEAT-1", by="seat"), root=tmp_path)

    assert cli_result.exit_code == 0, cli_result.output
    assert not operation_result.is_error
    cli_data = json.loads(cli_result.output)
    assert operation_result.data is not None
    operation_result.data.pop("generated_at")
    cli_data.pop("generated_at")
    assert operation_result.data == cli_data


def test_no_usage_ledger_event_kind() -> None:
    """Usage reporting never extends the work-ledger event vocabulary."""
    from parrot.knowledge.wiki.ledger.events import LedgerEventKind

    assert not [kind for kind in typing.get_args(LedgerEventKind) if str(kind).startswith("usage")]


def test_feature_does_not_modify_wiki_ledger_files() -> None:
    """The feature branch keeps usage reporting outside the wiki ledger plane."""
    repository = Path(__file__).resolve().parents[5]
    base = subprocess.run(
        ["git", "rev-parse", "--verify", "origin/dev"],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    if base.returncode != 0:
        pytest.skip("origin/dev is unavailable in this checkout")
    changed = subprocess.run(
        ["git", "diff", "--name-only", "origin/dev...HEAD"],
        cwd=repository,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()

    assert not [path for path in changed if "/knowledge/wiki/ledger/" in path]
