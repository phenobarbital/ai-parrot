"""The spec's ``Status`` reaches ``approved`` without a human editing it.

``/sdd-spec`` writes every spec at ``Status: draft`` and instructs a human
to "Mark status: approved when ready". In a dev-loop/dev-flow run nobody
ever opens the file, so specs stayed ``draft`` forever — including after
the feature was developed, reviewed and merged.

DevelopmentNode stamps it at the one point where the plan is settled and
code is about to be written, which is also the only point that can tell
approval from rejection.
"""

from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop.models import DevelopmentOutput, ResearchOutput
from parrot.flows.dev_loop.nodes.development import DevelopmentNode

_SPEC = """---
type: feature
base_branch: dev
---

# Feature Specification: my-feature

**Feature ID**: FEAT-494
**Date**: 2026-09-02
**Author**: jesuslarag@gmail.com
**Status**: draft
**Target version**: next
"""


@pytest.fixture
def worktree(tmp_path):
    spec = tmp_path / "sdd" / "specs" / "my-feature.spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(_SPEC, encoding="utf-8")
    return tmp_path


def _research(worktree, spec_path: str = "sdd/specs/my-feature.spec.md") -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path=spec_path,
        feat_id="FEAT-494",
        branch_name="feat-494-x",
        worktree_path=str(worktree),
        log_excerpts=[],
    )


def _node(**kwargs) -> DevelopmentNode:
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(
        return_value=DevelopmentOutput(files_changed=[], commit_shas=[], summary="s")
    )
    return DevelopmentNode(dispatcher=dispatcher, **kwargs)


def _status(worktree) -> str:
    text = (worktree / "sdd" / "specs" / "my-feature.spec.md").read_text(encoding="utf-8")
    return next(line for line in text.splitlines() if line.startswith("**Status**"))


@pytest.mark.asyncio
async def test_status_is_approved_implicitly_when_no_gate_is_required(worktree):
    """Nobody was going to be asked, so reaching development IS approval."""
    node = _node()

    await node.execute({"run_id": "r1", "research_output": _research(worktree)})

    assert _status(worktree) == "**Status**: approved"


@pytest.mark.asyncio
async def test_status_is_approved_after_a_human_resolves_the_gate(worktree):
    gate = MagicMock(status="approved", resolved_by="jesuslarag@gmail.com")
    host = MagicMock()
    host.open_gate = MagicMock(return_value=("g1", None))
    host.wait_gate = AsyncMock(return_value=gate)
    node = _node(require_plan_approval=True)

    await node.execute(
        {"run_id": "r1", "research_output": _research(worktree), "session_host": host}
    )

    assert _status(worktree) == "**Status**: approved"


@pytest.mark.asyncio
async def test_a_rejected_plan_leaves_the_spec_at_draft(worktree):
    """The whole point of stamping after the gate, not before it."""
    gate = MagicMock(status="rejected", resolved_by="jesuslarag@gmail.com")
    host = MagicMock()
    host.open_gate = MagicMock(return_value=("g1", None))
    host.wait_gate = AsyncMock(return_value=gate)
    node = _node(require_plan_approval=True)

    with pytest.raises(RuntimeError, match="plan_approval rejected"):
        await node.execute(
            {"run_id": "r1", "research_output": _research(worktree), "session_host": host}
        )

    assert _status(worktree) == "**Status**: draft"


@pytest.mark.asyncio
async def test_review_also_advances_to_approved(worktree):
    spec = worktree / "sdd" / "specs" / "my-feature.spec.md"
    spec.write_text(_SPEC.replace("draft", "review"), encoding="utf-8")

    await _node().execute({"run_id": "r1", "research_output": _research(worktree)})

    assert _status(worktree) == "**Status**: approved"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["obsolete", "superseded"])
async def test_a_deliberate_status_is_never_overwritten(worktree, status):
    spec = worktree / "sdd" / "specs" / "my-feature.spec.md"
    spec.write_text(_SPEC.replace("draft", status), encoding="utf-8")

    await _node().execute({"run_id": "r1", "research_output": _research(worktree)})

    assert _status(worktree) == f"**Status**: {status}"


@pytest.mark.asyncio
async def test_stamping_is_idempotent_across_a_qa_repair_re_entry(worktree):
    node = _node()
    ctx = {"run_id": "r1", "research_output": _research(worktree)}

    await node.execute(ctx)
    before = (worktree / "sdd" / "specs" / "my-feature.spec.md").read_text(encoding="utf-8")
    await node.execute(ctx)

    assert (worktree / "sdd" / "specs" / "my-feature.spec.md").read_text(encoding="utf-8") == before


@pytest.mark.asyncio
async def test_only_the_header_status_is_rewritten(worktree):
    """A spec body that discusses statuses must survive untouched."""
    spec = worktree / "sdd" / "specs" / "my-feature.spec.md"
    spec.write_text(_SPEC + "\n## Notes\n\n**Status**: draft is the default.\n", encoding="utf-8")

    await _node().execute({"run_id": "r1", "research_output": _research(worktree)})

    text = spec.read_text(encoding="utf-8")
    assert "**Status**: approved" in text
    assert "**Status**: draft is the default." in text


@pytest.mark.asyncio
async def test_a_missing_spec_never_fails_the_run(worktree):
    node = _node()

    result = await node.execute(
        {"run_id": "r1", "research_output": _research(worktree, "sdd/specs/gone.spec.md")}
    )

    assert result.summary == "s"


@pytest.mark.asyncio
async def test_the_stamp_is_committed_when_the_worktree_is_a_repo(worktree):
    subprocess.run(["git", "init", "-q", "-b", "dev", str(worktree)], check=True)
    for k, v in (("user.email", "t@t.t"), ("user.name", "t")):
        subprocess.run(["git", "config", k, v], cwd=worktree, check=True)
    subprocess.run(["git", "add", "-A"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=worktree, check=True)

    await _node().execute({"run_id": "r1", "research_output": _research(worktree)})

    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s%n%b"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "sdd: approve spec for FEAT-494" in log
    assert "Approved by: implicit (no plan_approval gate)" in log
    assert subprocess.run(
        ["git", "status", "--porcelain"], cwd=worktree, capture_output=True, text=True, check=True
    ).stdout.strip() == ""
