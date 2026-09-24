"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import pytest

from parrot.flows.dev_loop._subagent_defs import load_subagent_definition

_CHECKPOINT_HEADING = "## Neutral checkpoint handoff (FEAT-584)"
_INSPECTION_HEADING = "## Bounded inspection and delivery (FEAT-584)"


def _repo_root() -> Path:
    """Walk up from this test file to the repo root that owns `.claude/agents/`."""
    for parent in Path(__file__).resolve().parents:
        if (parent / ".claude" / "agents").is_dir():
            return parent
    raise AssertionError("repo root (containing .claude/agents/) not found relative to this test file")


def test_neutral_review_context_contract(tmp_path: Path) -> None:
    """Reviewer twins require fresh context, complete diff and checkpoint revalidation.

    `code-reviewer` (interactive, markdown verdict) and `sdd-codereview` (packaged
    dev-loop gate, JSON verdict with fix-and-commit) are NOT a literal twin pair --
    the task only asks both to bootstrap from the same durable checkpoint contract
    while keeping their own independent review process and output contract.
    """
    repo_root = _repo_root()
    code_reviewer_body = (repo_root / ".claude" / "agents" / "code-reviewer.md").read_text(encoding="utf-8")
    sdd_codereview_body = load_subagent_definition("sdd-codereview")

    for label, body in (("code-reviewer", code_reviewer_body), ("sdd-codereview", sdd_codereview_body)):
        assert _CHECKPOINT_HEADING in body, f"{label} is missing the neutral checkpoint handoff block"
        section = body.split(_CHECKPOINT_HEADING, 1)[1]
        for marker in (
            "fresh review context",
            "durable checkpoint",
            "Validate HEAD, branch, spec/index/convention hashes",
            "complete immutable diff",
            "invalidates the checkpoint and previous approval",
        ):
            assert marker in section, f"{label} handoff block is missing {marker!r}"

    # AC9/AC17: the handoff is a bootstrap, not a fork of the implementer's history --
    # it lands before each reviewer's own review process/steps, never replaces them.
    assert code_reviewer_body.index(_CHECKPOINT_HEADING) < code_reviewer_body.index("1. **Context Analysis**")
    assert sdd_codereview_body.index(_CHECKPOINT_HEADING) < sdd_codereview_body.index("1. Inspect the change")

    # Independent review coverage is preserved: adversarial cross-check + severity
    # policy for the interactive reviewer, the qualitative JSON gate for the packaged one.
    assert "Adversarial Cross-Check" in code_reviewer_body
    assert "CRITICAL" in code_reviewer_body
    assert "only when every acceptance criterion" in sdd_codereview_body

    # The two reviewer profiles stay genuinely different gates, not a literal twin pair --
    # sdd-codereview keeps its own JSON verdict contract that code-reviewer never had.
    assert '"passed"' in sdd_codereview_body
    assert "files_modified" in sdd_codereview_body
    assert '"passed"' not in code_reviewer_body
    assert code_reviewer_body != sdd_codereview_body


def test_coder_retains_delivery_scope(tmp_path: Path) -> None:
    """Coder twins retain code-only delivery, full feedback and validation coverage.

    AC13: the coder must not compact by tool/task nor alter the acceptance role --
    task closure and feature compaction stay the worker's responsibility.
    """
    repo_root = _repo_root()
    installed_body = (repo_root / ".claude" / "agents" / "sdd-coder.md").read_text(encoding="utf-8")
    packaged_body = load_subagent_definition("sdd-coder")

    for label, body in (("installed", installed_body), ("packaged", packaged_body)):
        assert _INSPECTION_HEADING in body, f"{label} sdd-coder is missing the bounded inspection block"
        section = body.split(_INSPECTION_HEADING, 1)[1]
        for marker in (
            "wiki-first discovery",
            "complete task acceptance/file contract",
            "Do not interpret compact payloads, background finished or a log as task acceptance",
            "task closure",
            "feature compaction remain the worker's responsibility",
            "never one compact per task",
        ):
            assert marker in section, f"{label} sdd-coder block is missing {marker!r}"

    # The block augments step (a) -- it must not displace the step's own bullets, nor
    # the delivery-feedback step that immediately follows.
    for _label, body in (("installed", installed_body), ("packaged", packaged_body)):
        assert body.index(_INSPECTION_HEADING) < body.index("- Read the full task file at `task_file`.")
        assert body.index("- Read the full task file at `task_file`.") < body.index(
            "### a.1) Apply Previous Delivery Feedback"
        )

    # Code-only delivery contract and the full native coder_feedback obligation stay intact.
    for _label, body in (("installed", installed_body), ("packaged", packaged_body)):
        assert "commit the code, and stop" in body
        assert "never touch SDD state" in body
        assert "Never claim a test ran" in body

    # Unlike the deliberately-distinct reviewer profiles above, the coder's installed and
    # packaged twins must stay in semantic lockstep -- byte-identical, like
    # `test_subagent_parity.py` enforces for every other dual-sourced prompt.
    pkg_copy_raw = (resources.files("parrot.flows.dev_loop") / "_subagent_data" / "sdd-coder.md").read_text(
        encoding="utf-8"
    )
    assert installed_body == pkg_copy_raw
