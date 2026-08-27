"""Unit tests for the sibling-overlap base-branch guard — FEAT-466 /
TASK-2505.

Reproduces the PR #1250 topology with a real (local, no-network) git repo:
an ancestry check alone would wave the incident through, so
``test_ancestry_alone_would_pass`` documents WHY the guard exists before the
guard tests themselves run.
"""

from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop import (
    BugBrief,
    DevelopmentOutput,
    FlowtaskCriterion,
    QAReport,
    ResearchOutput,
)
from parrot.flows.dev_loop.nodes.base import (
    BaseBranchMismatch,
    assert_base_is_clean,
)
from parrot.flows.dev_loop.nodes.deployment_handoff import DeploymentHandoffNode
from parrot.flows.dev_loop.nodes.feature_handoff import FeatureHandoffNode


def _run(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def incident_repo(tmp_path):
    """Reproduce the PR #1250 topology.

        main:  A
        dev:   A -- B -- C          (main is an ancestor of dev)
        feat:  A -- B -- C -- D     (cut from dev, but targeting main)

    So ``--is-ancestor origin/main feat`` is TRUE, yet feat carries B and C,
    which belong to dev. adds(main..feat) = 3, own = 1.
    """
    origin = tmp_path / "origin"
    origin.mkdir()
    _run(origin, "init", "--bare", "-b", "main")

    work = tmp_path / "work"
    work.mkdir()
    _run(work, "init", "-b", "main")
    _run(work, "remote", "add", "origin", str(origin))
    (work / "a.txt").write_text("A")
    _run(work, "add", "-A")
    _run(work, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "A")
    _run(work, "push", "origin", "main")

    _run(work, "checkout", "-b", "dev")
    for name in ("B", "C"):
        (work / f"{name}.txt").write_text(name)
        _run(work, "add", "-A")
        _run(
            work,
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-m",
            name,
        )
    _run(work, "push", "origin", "dev")

    _run(work, "checkout", "-b", "feat-465")
    (work / "D.txt").write_text("D")
    _run(work, "add", "-A")
    _run(work, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "D")
    _run(work, "push", "origin", "feat-465")
    _run(work, "fetch", "origin")
    return work


@pytest.mark.asyncio
class TestGuard:
    async def test_ancestry_alone_would_pass(self, incident_repo):
        """Documents WHY the guard is not an ancestry check."""
        rc = subprocess.run(
            [
                "git",
                "-C",
                str(incident_repo),
                "merge-base",
                "--is-ancestor",
                "origin/main",
                "feat-465",
            ]
        ).returncode
        assert rc == 0, "ancestry passes — hence the sibling-overlap guard"

    async def test_blocks_the_incident_topology(self, incident_repo):
        with pytest.raises(BaseBranchMismatch, match="own work"):
            await assert_base_is_clean("feat-465", "main", str(incident_repo), siblings=["dev"])

    async def test_passes_for_correctly_cut_branch(self, incident_repo):
        """feat-465 vs its real base (dev) is clean: adds == own."""
        await assert_base_is_clean("feat-465", "dev", str(incident_repo), siblings=["main"])

    async def test_missing_sibling_ref_is_skipped(self, incident_repo):
        await assert_base_is_clean("feat-465", "dev", str(incident_repo), siblings=["staging"])

    async def test_no_existing_siblings_passes(self, incident_repo, caplog):
        logger = MagicMock()
        await assert_base_is_clean(
            "feat-465",
            "dev",
            str(incident_repo),
            siblings=["staging"],
            logger=logger,
        )
        logger.info.assert_called_once()

    async def test_cherry_pick_does_not_false_positive(self, incident_repo):
        """Same content on a sibling under a different SHA must not count."""
        work = incident_repo
        # Cherry-pick D onto a new "backport" branch off main — new SHA,
        # not a descendant relationship with dev at all.
        _run(work, "checkout", "main")
        _run(work, "checkout", "-b", "backport")
        _run(work, "cherry-pick", "feat-465")
        _run(work, "push", "origin", "backport")
        _run(work, "fetch", "origin")

        # backport vs main, checking against dev/feat-465 as siblings: the
        # cherry-picked commit has a NEW sha, so it does not appear in
        # dev's or feat-465's history by identity -> adds == own.
        await assert_base_is_clean("backport", "main", str(work), siblings=["dev", "feat-465"])

    async def test_default_siblings_used_when_none_passed(self, incident_repo):
        """No explicit siblings -> defaults to _LONG_LIVED_BRANCHES - base,
        filtered to existing refs. 'staging' does not exist here, so only
        'dev'/'main' are candidates depending on base."""
        with pytest.raises(BaseBranchMismatch):
            await assert_base_is_clean("feat-465", "main", str(incident_repo))


def _research(**over) -> ResearchOutput:
    base = dict(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-fix",
        worktree_path="/tmp/does-not-matter",
        log_excerpts=[],
        base_branch="dev",
    )
    base.update(over)
    return ResearchOutput(**base)


def _brief(**over) -> BugBrief:
    base = dict(
        summary="customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[FlowtaskCriterion(name="run", task_path="x.yaml")],
        escalation_assignee="a",
        reporter="b",
    )
    base.update(over)
    return BugBrief(**base)


def _jira() -> MagicMock:
    j = MagicMock()
    j.jira_transition_issue = AsyncMock(return_value={"ok": True})
    j.jira_transition_to = AsyncMock(return_value={"ok": True})
    j.jira_add_comment = AsyncMock(return_value={"id": "c1"})
    return j


async def _success_push(self, branch, cwd):
    return None


@pytest.mark.asyncio
class TestDeploymentHandoffWiring:
    async def test_blocks_on_empty_base_branch(self, monkeypatch):
        monkeypatch.setattr(DeploymentHandoffNode, "_push_branch", _success_push)
        create_pr = AsyncMock(return_value="https://github.com/x/y/pull/1")
        monkeypatch.setattr(DeploymentHandoffNode, "_create_pr", create_pr)

        node = DeploymentHandoffNode(jira_toolkit=_jira())
        ctx = {
            "run_id": "r1",
            "research_output": _research(base_branch=""),
            "bug_brief": _brief(),
        }
        result = await node.execute(ctx)

        assert result["status"] == "blocked"
        assert "base_branch" in result["error"]
        create_pr.assert_not_awaited()

    async def test_bug_kind_with_recorded_dev_base_targets_dev(self, monkeypatch):
        """Proves the kind override is gone: kind='bug' + recorded
        base_branch='dev' opens the PR against dev, not main."""
        monkeypatch.setattr(DeploymentHandoffNode, "_push_branch", _success_push)
        monkeypatch.setattr(
            "parrot.flows.dev_loop.nodes.deployment_handoff.assert_base_is_clean",
            AsyncMock(return_value=None),
        )
        create_pr = AsyncMock(return_value="https://github.com/x/y/pull/1")
        monkeypatch.setattr(DeploymentHandoffNode, "_create_pr", create_pr)

        node = DeploymentHandoffNode(jira_toolkit=_jira())
        ctx = {
            "run_id": "r1",
            "research_output": _research(base_branch="dev"),
            "bug_brief": _brief(),
        }
        result = await node.execute(ctx)

        assert result["status"] == "ready_to_deploy"
        assert node._base_branch == "dev"

    async def test_guard_failure_blocks_and_skips_pr(self, monkeypatch):
        monkeypatch.setattr(DeploymentHandoffNode, "_push_branch", _success_push)
        guard = AsyncMock(side_effect=BaseBranchMismatch("branch carries sibling commits"))
        monkeypatch.setattr(
            "parrot.flows.dev_loop.nodes.deployment_handoff.assert_base_is_clean",
            guard,
        )
        create_pr = AsyncMock(return_value="https://github.com/x/y/pull/1")
        monkeypatch.setattr(DeploymentHandoffNode, "_create_pr", create_pr)

        jira = _jira()
        node = DeploymentHandoffNode(jira_toolkit=jira)
        ctx = {
            "run_id": "r1",
            "research_output": _research(base_branch="dev"),
            "bug_brief": _brief(),
        }
        result = await node.execute(ctx)

        assert result["status"] == "blocked"
        assert "sibling" in result["error"]
        create_pr.assert_not_awaited()
        # The guard fires BEFORE any PR is opened, so the ticket is never
        # moved to a "ready" state — only _mark_blocked's own "Deployment
        # Blocked" transition happens (same shape as the existing
        # push/PR-failure blocked paths in test_deployment_handoff.py).
        jira.jira_transition_to.assert_awaited_once()
        assert jira.jira_transition_to.await_args.kwargs["target_status"] == "Deployment Blocked"


def _planner(**over):
    from parrot.flows.dev_loop.models import PlannerOutput

    base = dict(
        spec_path="sdd/specs/x.spec.md",
        task_index_path="sdd/tasks/index/x.json",
        feat_id="FEAT-378",
        branch_name="feat-378-x",
        worktree_path="/tmp/does-not-matter-feature",
    )
    base.update(over)
    return PlannerOutput(**base)


@pytest.mark.asyncio
class TestFeatureHandoffWiring:
    async def test_guard_applied(self, monkeypatch, tmp_path):
        guard = AsyncMock(return_value=None)
        monkeypatch.setattr(
            "parrot.flows.dev_loop.nodes.feature_handoff.assert_base_is_clean",
            guard,
        )
        monkeypatch.setattr(FeatureHandoffNode, "_run_git", AsyncMock(return_value=""))
        monkeypatch.setattr(
            FeatureHandoffNode,
            "_create_pr",
            AsyncMock(return_value="https://github.com/x/y/pull/2"),
        )
        monkeypatch.setattr(FeatureHandoffNode, "_docs_rel_path", lambda self, planner: "docs/x.md")
        monkeypatch.setattr(FeatureHandoffNode, "_write_and_push_docs", AsyncMock(return_value=None))
        monkeypatch.setattr(FeatureHandoffNode, "_ingest_wiki_page", AsyncMock(return_value=None))

        node = FeatureHandoffNode()
        planner = _planner(worktree_path=str(tmp_path))
        ctx = {"run_id": "r1", "planner_output": planner}
        result = await node.execute(ctx)

        guard.assert_awaited_once()
        called_args = guard.await_args.args
        assert called_args[0] == planner.branch_name
        assert result["status"] == "ready_to_deploy"

    async def test_blocks_when_guard_fails(self, monkeypatch, tmp_path):
        guard = AsyncMock(side_effect=BaseBranchMismatch("branch carries sibling commits"))
        monkeypatch.setattr(
            "parrot.flows.dev_loop.nodes.feature_handoff.assert_base_is_clean",
            guard,
        )
        monkeypatch.setattr(FeatureHandoffNode, "_run_git", AsyncMock(return_value=""))
        create_pr = AsyncMock(return_value="https://github.com/x/y/pull/2")
        monkeypatch.setattr(FeatureHandoffNode, "_create_pr", create_pr)

        node = FeatureHandoffNode()
        planner = _planner(worktree_path=str(tmp_path))
        ctx = {"run_id": "r1", "planner_output": planner}
        result = await node.execute(ctx)

        assert result["status"] == "blocked"
        create_pr.assert_not_awaited()
