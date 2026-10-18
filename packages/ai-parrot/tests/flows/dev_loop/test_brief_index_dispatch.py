"""Brief runs reach the scheduler through ResearchOutput.index_path — FEAT-698 / TASK-4432."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from parrot.flows.dev_loop.models import DevAgentPoolConfig, DevAgentSpec, ResearchOutput
from parrot.flows.dev_loop.nodes.development import DevelopmentNode

INDEX_REL = "sdd/briefs/demo-fix.index.json"


def _research(worktree: Path, index_path: str = INDEX_REL, feat_id: str = "") -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/briefs/demo-fix.brief.md",
        feat_id=feat_id,
        branch_name="hotfix-ops-1-demo-fix",
        worktree_path=str(worktree),
        log_excerpts=[],
        index_path=index_path,
    )


def _write_index(worktree: Path, ids: list[str]) -> None:
    path = worktree / INDEX_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"tasks": [{"id": tid, "status": "pending", "depends_on": []} for tid in ids]}))


def _node() -> DevelopmentNode:
    return DevelopmentNode(dispatcher=MagicMock())


class TestIndexPathField:
    def test_alias_and_serialization(self, tmp_path):
        out = ResearchOutput(
            jira_issue_key="OPS-1",
            spec_path="s",
            feat_id="",
            branch_name="b",
            worktree_path=str(tmp_path),
            index="x.json",
        )
        assert out.index_path == "x.json"
        assert out.model_dump()["index_path"] == "x.json"


@pytest.mark.asyncio
class TestBriefDispatch:
    async def test_split_brief_builds_two_task_scheduler(self, tmp_path):
        _write_index(tmp_path, ["HOTFIX-1", "HOTFIX-2"])
        scheduler = await _node()._build_scheduler(_research(tmp_path))
        assert scheduler is not None
        assert {t.id for t in scheduler.next_wave()} == {"HOTFIX-1", "HOTFIX-2"}

    async def test_single_task_brief_collapses_to_one_seat(self, tmp_path):
        _write_index(tmp_path, ["HOTFIX-1"])
        node = _node()
        research = _research(tmp_path)
        scheduler = await node._build_scheduler(research)
        assert scheduler is not None
        assert len(scheduler.next_wave()) == 1
        cfg = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code", count=3)])
        collapsed = node._collapse_for_single_task({}, cfg, scheduler, research)
        assert sum(spec.count for spec in collapsed.agents) == 1

    async def test_no_index_path_and_empty_feat_id_returns_none(self, tmp_path):
        _write_index(tmp_path, ["HOTFIX-1"])
        assert await _node()._build_scheduler(_research(tmp_path, index_path="")) is None

    @pytest.mark.parametrize("bad", ["../x.json", "sdd/../../x.json"])
    async def test_escaping_relative_path_ignored_with_warning(self, tmp_path, bad, caplog):
        worktree = tmp_path / "wt"
        worktree.mkdir()
        (tmp_path / "x.json").write_text(json.dumps({"tasks": [{"id": "T-1", "status": "pending"}]}))
        node = _node()
        with caplog.at_level(logging.WARNING):
            scheduler = await node._build_scheduler(_research(worktree, index_path=bad))
        assert scheduler is None
        assert "Ignoring index_path" in caplog.text

    async def test_absolute_path_ignored_with_warning(self, tmp_path, caplog):
        outside = tmp_path / "abs.json"
        outside.write_text(json.dumps({"tasks": [{"id": "T-1", "status": "pending"}]}))
        worktree = tmp_path / "wt"
        worktree.mkdir()
        with caplog.at_level(logging.WARNING):
            scheduler = await _node()._build_scheduler(_research(worktree, index_path=str(outside)))
        assert scheduler is None
        assert "Ignoring index_path" in caplog.text

    async def test_escaping_path_falls_back_to_legacy_scan(self, tmp_path):
        idx = tmp_path / "sdd" / "tasks" / "index"
        idx.mkdir(parents=True)
        (idx / "f.json").write_text(
            json.dumps({"feature_id": "FEAT-1", "feature": "f", "tasks": [{"id": "TASK-1", "status": "pending"}]})
        )
        scheduler = await _node()._build_scheduler(_research(tmp_path, index_path="../x.json", feat_id="FEAT-1"))
        assert scheduler is not None
