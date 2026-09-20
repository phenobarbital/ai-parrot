"""CLI tests for `ledger plan-fix`, `ledger unclaim` and `ledger close --resolved-by` (FEAT-572 Module 4)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import _dedupe_slugs, _spec_parent_ids, ledger
from parrot.knowledge.wiki.ledger.events import SEVERITY_ORDER
from parrot.knowledge.wiki.ledger.fix_planner import FixPlan
from parrot.knowledge.wiki.ledger.index import LedgerIndex
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.store import LedgerStore
from parrot.knowledge.wiki.store import SQLitePragmaPolicy, WikiStoreBusy

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FROM_ROOT = "parrot.knowledge.wiki.cli.LedgerService.from_root"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def snapshot_rows() -> list[dict]:
    path = _REPO_ROOT / "sdd" / "ledger" / "issues.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture
def mock_service(tmp_path: Path, snapshot_rows) -> MagicMock:
    service = MagicMock(spec=LedgerService)
    service.shared_root = tmp_path
    service.ready_work = AsyncMock(return_value=snapshot_rows)
    service.feature_index_status = AsyncMock(
        return_value={
            "FEAT-551": "2026-09-15T13:46:35Z",
            "FEAT-559": "2026-09-16T09:21:54Z",
            "FEAT-560": "2026-09-15T23:44:12Z",
        }
    )
    service.close_issue = AsyncMock(return_value=True)
    service.unclaim = AsyncMock(return_value=True)
    return service


def _real_service(tmp_path: Path) -> LedgerService:
    ledger_dir = tmp_path / ".parrot" / "ledger"
    ledger_dir.mkdir(parents=True)
    store = LedgerStore(
        ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1.0)
    )
    log = LedgerLog(str(ledger_dir / "events.jsonl"))
    return LedgerService(LedgerIndex(store, log), store, log, tmp_path)


# STALE-DATA NOTE (updated 2026-09-19 by the sdd-worker orchestrator): `snapshot_rows` reads
# the live, committed sdd/ledger/issues.jsonl, which grows continuously from unrelated
# /sdd-codereview activity in other concurrent sessions. As of this writing it has 44+ rows,
# no group count is stable, and it currently contains ZERO `kind == "vulnerability"` issues.
# Do NOT assert a literal `len(plan.groups) == N` against it, and do NOT rely on it containing
# any specific issue_id or kind — inject synthetic rows via `mock_service.ready_work.return_value`
# (or a local list, same shape as `snapshot_rows` entries) wherever a test needs a *specific*
# severity/kind/file combination (e.g. the vulnerability-refusal test below).


def test_cli_plan_fix_json_matches_fixplan_schema(runner, mock_service):
    with patch(_FROM_ROOT, return_value=mock_service):
        result = runner.invoke(ledger, ["plan-fix", "--json"])
    assert result.exit_code == 0, result.output
    plan = FixPlan.model_validate_json(result.output)
    assert len(plan.groups) > 0
    ranks = [SEVERITY_ORDER[g.max_severity] for g in plan.groups]
    assert ranks == sorted(ranks)
    for group in plan.groups:
        for parent in group.parents:
            assert parent.open is False


def test_cli_plan_fix_busy_falls_back_to_snapshot(runner, mock_service, tmp_path):
    snapshot_rows = [
        {
            "issue_id": f"issue:{status}",
            "title": f"{status} issue",
            "kind": "bug",
            "severity": "minor",
            "status": status,
            "discovered_from": None,
            "about": ["file:pkg/example.py"],
        }
        for status in ("open", "closed")
    ]
    ledger_dir = tmp_path / "sdd" / "ledger"
    ledger_dir.mkdir(parents=True)
    snapshot_path = ledger_dir / "issues.jsonl"
    snapshot_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in snapshot_rows), encoding="utf-8")
    mock_service.ready_work.side_effect = WikiStoreBusy(tmp_path, "ledger.sync", 5.0)
    with patch(_FROM_ROOT, return_value=mock_service):
        result = runner.invoke(ledger, ["plan-fix", "--json"])
    assert result.exit_code == 0, result.output
    plan = FixPlan.model_validate_json(result.stdout)
    assert "planning from committed snapshot" in result.stderr
    assert plan.total_open == 1
    assert [issue.issue_id for group in plan.groups for issue in group.issues] == ["issue:open"]


def test_cli_plan_fix_dedupes_slug_against_existing_specs(runner, mock_service, tmp_path):
    with patch(_FROM_ROOT, return_value=mock_service):
        first = runner.invoke(ledger, ["plan-fix", "--json"])
    assert first.exit_code == 0, first.output
    first_plan = FixPlan.model_validate_json(first.output)
    slug = first_plan.groups[0].suggested_slug

    specs_dir = tmp_path / "sdd" / "specs"
    specs_dir.mkdir(parents=True)
    (specs_dir / f"{slug}.spec.md").write_text("# spec\n", encoding="utf-8")

    with patch(_FROM_ROOT, return_value=mock_service):
        second = runner.invoke(ledger, ["plan-fix", "--json"])
    assert second.exit_code == 0, second.output
    second_plan = FixPlan.model_validate_json(second.output)
    assert second_plan.groups[0].suggested_slug == f"{slug}-2"


def test_cli_plan_fix_survives_unreadable_index_dir(runner, mock_service):
    mock_service.feature_index_status.side_effect = OSError("denied")
    with patch(_FROM_ROOT, return_value=mock_service):
        result = runner.invoke(ledger, ["plan-fix", "--json"])
    assert result.exit_code == 0, result.output
    plan = FixPlan.model_validate_json(result.stdout)
    for group in plan.groups:
        for parent in group.parents:
            assert parent.open is False


def test_cli_plan_fix_refuses_fast_override_on_vulnerability(runner, mock_service):
    mock_service.ready_work = AsyncMock(
        return_value=[
            {
                "issue_id": "issue:synthetic-vuln",
                "title": "t",
                "kind": "vulnerability",
                "severity": "minor",
                "status": "open",
                "discovered_from": None,
                "about": ["sym:pkg/a.py#X"],
            }
        ]
    )
    with patch(_FROM_ROOT, return_value=mock_service):
        result = runner.invoke(ledger, ["plan-fix", "--lane", "fast"])
    assert result.exit_code == 1
    assert "Refused" in result.output


def test_cli_close_accepts_resolved_by(runner, mock_service):
    with patch(_FROM_ROOT, return_value=mock_service):
        result = runner.invoke(ledger, ["close", "issue:abc", "--reason", "fixed", "--resolved-by", "commit:deadbeef"])
    assert result.exit_code == 0
    mock_service.close_issue.assert_awaited_once_with("issue:abc", "fixed", "agent:cli", resolved_by="commit:deadbeef")


def test_cli_unclaim_roundtrip(runner, tmp_path):
    service = _real_service(tmp_path)
    issue_id = asyncio.run(service.open_issue(title="Round trip", body="b", discovered_from="task:TASK-1"))
    assert asyncio.run(service.claim(issue_id, "agent:test")) is True
    with patch(_FROM_ROOT, return_value=service):
        assert runner.invoke(ledger, ["unclaim", issue_id, "--reason", "released"]).exit_code == 0
        ready = runner.invoke(ledger, ["ready"])
    assert issue_id in ready.output


def test_spec_parent_ids_only_feat_form():
    rows = [
        {"discovered_from": "spec:FEAT-551"},
        {"discovered_from": "spec:codex-dispatch-stdin-isolation"},
        {"discovered_from": "task:TASK-1"},
    ]
    assert _spec_parent_ids(rows) == {"FEAT-551"}
