"""Tests for LedgerService: facade, scoped queries, and snapshot export."""

from __future__ import annotations

import json

import pytest

from parrot.knowledge.wiki.ledger.index import LedgerIndex
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.store import LedgerStore
from parrot.knowledge.wiki.project import WikiProjectConfig, save_project_config
from parrot.knowledge.wiki.store import SQLitePragmaPolicy


@pytest.fixture
def ledger_service(tmp_path):
    """A LedgerService wired directly (no git/shared-root resolution)."""
    ledger_dir = tmp_path / ".parrot" / "ledger"
    ledger_dir.mkdir(parents=True)
    store = LedgerStore(
        ledger_dir / "ledger.db",
        wiki_name="ledger",
        sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1.0),
    )
    log = LedgerLog(str(ledger_dir / "events.jsonl"))
    index = LedgerIndex(store, log)
    return LedgerService(index, store, log, tmp_path)


class TestFromRoot:
    async def test_from_root_targets_shared_ledger_directory_from_linked_worktree(self, tmp_path):
        main_root = tmp_path / "main"
        main_root.mkdir()
        (main_root / ".git").mkdir()
        save_project_config(main_root, WikiProjectConfig())

        worktree_root = tmp_path / "worktree"
        worktree_root.mkdir()
        wt_gitdir = main_root / ".git" / "worktrees" / "wt"
        wt_gitdir.mkdir(parents=True)
        (wt_gitdir / "commondir").write_text("../..\n", encoding="utf-8")
        (worktree_root / ".git").write_text(f"gitdir: {wt_gitdir}\n", encoding="utf-8")

        service = LedgerService.from_root(worktree_root)

        assert service.shared_root == main_root.resolve()
        assert (main_root / ".parrot" / "ledger").is_dir()
        # Never a per-worktree copy.
        assert not (worktree_root / ".parrot").exists()

    def test_from_root_never_adds_ledger_specific_sqlite_keys(self, tmp_path):
        (tmp_path / ".git").mkdir()
        config = WikiProjectConfig(sqlite_busy_timeout=7.0)
        save_project_config(tmp_path, config)

        service = LedgerService.from_root(tmp_path)

        assert service.store._policy.busy_timeout_s == 7.0


class TestOpenReadyClaim:
    async def test_open_issue_appends_event_and_materializes_via_sync(self, ledger_service):
        issue_id = await ledger_service.open_issue(
            title="Leak in connection pool",
            body="Body",
            discovered_from="task:TASK-3200",
        )

        assert issue_id.startswith("issue:")
        ready = await ledger_service.ready_work()
        assert [item["issue_id"] for item in ready] == [issue_id]

    async def test_ready_work_filters_by_kind(self, ledger_service):
        bug_id = await ledger_service.open_issue(title="A bug", body="b", kind="bug", discovered_from="task:TASK-1")
        debt_id = await ledger_service.open_issue(
            title="Some debt", body="d", kind="tech_debt", discovered_from="task:TASK-1"
        )

        bugs = await ledger_service.ready_work(kind="bug")
        assert [item["issue_id"] for item in bugs] == [bug_id]
        debts = await ledger_service.ready_work(kind="tech_debt")
        assert [item["issue_id"] for item in debts] == [debt_id]

    async def test_claim_delegates_to_index(self, ledger_service):
        issue_id = await ledger_service.open_issue(title="Claimable", body="b", discovered_from="task:TASK-1")

        assert await ledger_service.claim(issue_id, "task:TASK-3205") is True
        assert await ledger_service.claim(issue_id, "task:TASK-9999") is False


class TestAcknowledgeAndClose:
    async def test_acknowledge_refuses_non_human_actor_and_leaves_status_open(self, ledger_service):
        issue_id = await ledger_service.open_issue(
            title="Critical", body="b", severity="critical", discovered_from="task:TASK-1"
        )

        accepted = await ledger_service.acknowledge(issue_id, "known issue", actor="agent:sdd")

        assert accepted is False
        ready = await ledger_service.ready_work()
        assert ready[0]["issue_id"] == issue_id
        assert ready[0]["acknowledged"] is False

    async def test_acknowledge_accepts_human_actor(self, ledger_service):
        issue_id = await ledger_service.open_issue(
            title="Critical", body="b", severity="critical", discovered_from="task:TASK-1"
        )

        accepted = await ledger_service.acknowledge(issue_id, "tracked elsewhere", actor="human:jesus")

        assert accepted is True
        ready = await ledger_service.ready_work()
        assert ready[0]["acknowledged"] is True
        assert ready[0]["status"] == "open"

    async def test_close_issue(self, ledger_service):
        issue_id = await ledger_service.open_issue(title="Fixable", body="b", discovered_from="task:TASK-1")

        closed = await ledger_service.close_issue(issue_id, "fixed", actor="human:jesus")

        assert closed is True
        assert await ledger_service.ready_work() == []


class TestContextAndBlockers:
    async def test_get_context_scopes_to_matching_file_paths(self, ledger_service):
        matching = await ledger_service.open_issue(
            title="Touches target file",
            body="b",
            discovered_from="task:TASK-1",
            about=["sym:pkg/mod.py#Func"],
        )
        await ledger_service.open_issue(
            title="Unrelated issue",
            body="b",
            discovered_from="task:TASK-1",
            about=["sym:other/file.py#Other"],
        )

        context = await ledger_service.get_context(["pkg/mod.py"])

        assert matching in context
        assert "Unrelated issue" not in context

    async def test_get_context_empty_file_paths_returns_empty_string(self, ledger_service):
        assert await ledger_service.get_context([]) == ""

    async def test_merge_blockers_scoped_to_requesting_feature_only(self, ledger_service, tmp_path):
        index_dir = tmp_path / "sdd" / "tasks" / "index"
        index_dir.mkdir(parents=True)
        (index_dir / "feature-a.json").write_text(
            json.dumps({"feature_id": "FEAT-100", "tasks": [{"id": "TASK-100"}]}), encoding="utf-8"
        )
        (index_dir / "feature-b.json").write_text(
            json.dumps({"feature_id": "FEAT-200", "tasks": [{"id": "TASK-200"}]}), encoding="utf-8"
        )

        own_critical = await ledger_service.open_issue(
            title="Blocks FEAT-100", body="b", severity="critical", discovered_from="task:TASK-100"
        )
        await ledger_service.open_issue(
            title="Blocks FEAT-200 only", body="b", severity="critical", discovered_from="task:TASK-200"
        )
        await ledger_service.open_issue(
            title="Minor, not critical", body="b", severity="minor", discovered_from="task:TASK-100"
        )

        blockers = await ledger_service.merge_blockers("FEAT-100")

        assert [b["issue_id"] for b in blockers] == [own_critical]

    async def test_merge_blockers_excludes_acknowledged(self, ledger_service, tmp_path):
        index_dir = tmp_path / "sdd" / "tasks" / "index"
        index_dir.mkdir(parents=True)
        (index_dir / "feature-a.json").write_text(
            json.dumps({"feature_id": "FEAT-100", "tasks": [{"id": "TASK-100"}]}), encoding="utf-8"
        )
        issue_id = await ledger_service.open_issue(
            title="Acked critical", body="b", severity="critical", discovered_from="task:TASK-100"
        )
        await ledger_service.acknowledge(issue_id, "accepted risk", actor="human:jesus")

        assert await ledger_service.merge_blockers("FEAT-100") == []


class TestExportSnapshot:
    async def test_export_snapshot_byte_identical_and_reports_unchanged_on_second_export(
        self, ledger_service, tmp_path
    ):
        await ledger_service.open_issue(title="First", body="b1", discovered_from="task:TASK-1")
        await ledger_service.open_issue(title="Second", body="b2", discovered_from="task:TASK-2")
        dest = tmp_path / "sdd" / "ledger" / "issues.jsonl"

        changed_first = await ledger_service.export_snapshot(dest)
        content_first = dest.read_text(encoding="utf-8")

        changed_second = await ledger_service.export_snapshot(dest)
        content_second = dest.read_text(encoding="utf-8")

        assert changed_first is True
        assert changed_second is False
        assert content_first == content_second

        lines = [json.loads(line) for line in content_first.splitlines()]
        assert [row["issue_id"] for row in lines] == sorted(row["issue_id"] for row in lines)
        for row in lines:
            assert "ts" not in row
            assert list(row.keys()) == sorted(row.keys())

    async def test_export_snapshot_changes_after_new_issue(self, ledger_service, tmp_path):
        dest = tmp_path / "sdd" / "ledger" / "issues.jsonl"
        await ledger_service.export_snapshot(dest)

        await ledger_service.open_issue(title="Added later", body="b", discovered_from="task:TASK-1")

        assert await ledger_service.export_snapshot(dest) is True


class TestCompactAndAudit:
    async def test_compact_delegates_to_index(self, ledger_service):
        issue_id = await ledger_service.open_issue(title="Old", body="b", discovered_from="task:TASK-1")
        await ledger_service.close_issue(issue_id, "fixed", actor="human:jesus")

        folded = await ledger_service.compact(older_than_days=-1)

        assert folded == 1

    async def test_audit_reports_counts_lag_and_sqlite_settings(self, ledger_service):
        # discovered_from points at a task: page that was never ingested by
        # SDDGraphIngest in this isolated test, so its discovered-from edge
        # is a genuinely dangling reference — exactly what `broken_edges`
        # exists to surface.
        await ledger_service.open_issue(title="Audited", body="b", discovered_from="task:TASK-1")

        report = await ledger_service.audit()

        assert report["event_counts"]["issue.opened"] == 1
        assert report["total_events"] == 1
        assert report["cursor_lag_events"] == 0
        assert report["broken_edges"] == 1
        assert "busy_timeout_s" in report["sqlite"] or report["sqlite"]
        assert report["log_size_bytes"] > 0
