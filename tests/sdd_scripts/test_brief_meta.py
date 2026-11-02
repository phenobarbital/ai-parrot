"""Tests for ``scripts.sdd.brief_meta`` — FEAT-698 / TASK-4425."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from parrot.sdd.config import SddConfig
from scripts.sdd.brief_meta import (
    BRIEF_BASE_BRANCHES,
    BriefMeta,
    brief_task_id,
    brief_worktree_plan,
    emit_brief_frontmatter,
    parse_brief,
    plan_brief_worktree,
    write_brief_index,
)


def _meta(**overrides: object) -> BriefMeta:
    data = {
        "kind": "brief",
        "slug": "fix-path-injection",
        "key": "cs-224",
        "base_branch": "main",
        "source": {"type": "code-scanning", "ref": "224"},
        "created": "2026-10-17T00:00:00+00:00",
    }
    data.update(overrides)
    return BriefMeta(**data)


def test_round_trip(tmp_path: Path) -> None:
    """A rendered frontmatter block parses back into the same metadata."""
    meta = _meta()
    document = tmp_path / "brief.md"
    document.write_text(emit_brief_frontmatter(meta) + "# Brief\n", encoding="utf-8")

    assert parse_brief(document) == meta


def test_missing_frontmatter_raises(tmp_path: Path) -> None:
    """A brief document requires YAML frontmatter at byte zero."""
    document = tmp_path / "brief.md"
    document.write_text("# Brief\n", encoding="utf-8")

    with pytest.raises(ValueError, match="frontmatter"):
        parse_brief(document)


@pytest.mark.parametrize("bad", ["a/b", "a b", "-x"])
def test_unsafe_slug_or_key_rejected(bad: str) -> None:
    """Unsafe worktree identity values fail metadata validation."""
    with pytest.raises(ValidationError):
        _meta(slug=bad)
    with pytest.raises(ValidationError):
        _meta(key=bad)


@pytest.mark.parametrize("bad", ["a..b", "x.", "x.lock", "a..b.lock"])
def test_invalid_git_ref_components_rejected(bad: str) -> None:
    """``..``, a trailing ``.`` and the ``.lock`` suffix fail at parse time.

    These pass a bare character-class check but ``git check-ref-format``
    rejects them, so without this they would only fail inside
    ``git worktree add``.
    """
    with pytest.raises(ValidationError):
        _meta(slug=bad)
    with pytest.raises(ValidationError):
        _meta(key=bad)
    with pytest.raises(ValueError, match="safe for a git branch"):
        brief_worktree_plan(slug=bad, key="cs-224", base_branch="main")
    with pytest.raises(ValueError, match="safe for a git branch"):
        brief_worktree_plan(slug="fix-path-injection", key=bad, base_branch="main")


def test_base_branch_must_be_long_lived() -> None:
    """Only ``main``/``dev``/``staging`` are accepted, in the model and the planner."""
    assert BRIEF_BASE_BRANCHES == {"main", "dev", "staging"}

    with pytest.raises(ValidationError, match="base_branch"):
        _meta(base_branch="feature/x")
    with pytest.raises(ValueError, match="base_branch"):
        brief_worktree_plan(slug="fix-path-injection", key="cs-224", base_branch="feature/x")

    # Pin the config: the default (no sdd/config.json, e.g. pytest run from a checkout without one) has no staging.
    config = SddConfig(base_branch="dev", staging_branch="staging", hotfix_base="main")
    for branch in sorted(BRIEF_BASE_BRANCHES):
        plan = brief_worktree_plan(slug="s", key="k", base_branch=branch, config=config)
        assert plan.base_ref == f"origin/{branch}"


def test_ledger_requires_dev() -> None:
    """Ledger briefs are valid only when based on ``dev``."""
    with pytest.raises(ValidationError, match="base_branch"):
        _meta(source={"type": "ledger", "ref": "ISSUE-1"})

    assert _meta(base_branch="dev", source={"type": "ledger", "ref": "ISSUE-1"}).base_branch == "dev"


def test_worktree_naming_main_and_dev() -> None:
    """Brief worktrees use branch-sensitive names and origin base refs."""
    main_plan = plan_brief_worktree(_meta())
    dev_plan = brief_worktree_plan(slug="fix-path-injection", key="cs-224", base_branch="dev")

    assert main_plan.name == "hotfix-cs-224-fix-path-injection"
    assert main_plan.path == ".claude/worktrees/hotfix-cs-224-fix-path-injection"
    assert main_plan.base_ref == "origin/main"
    assert dev_plan.name == "fix-cs-224-fix-path-injection"
    assert dev_plan.path == ".claude/worktrees/fix-cs-224-fix-path-injection"
    assert dev_plan.base_ref == "origin/dev"


def test_index_header_and_task_defaults(tmp_path: Path) -> None:
    """Written indexes supply the brief identity and complete task defaults."""
    meta = _meta()
    path = write_brief_index(
        meta,
        [
            {
                "id": "HOTFIX-cs-224-1",
                "slug": "correct-path-validation",
                "title": "Correct path validation",
                "file": "sdd/briefs/fix-path-injection/tasks/HOTFIX-cs-224-1-correct-path-validation.md",
            }
        ],
        tmp_path,
    )
    index = json.loads(path.read_text(encoding="utf-8"))
    task = index["tasks"][0]

    assert path == tmp_path / "sdd/briefs/fix-path-injection.index.json"
    assert index["feature_id"] == "BRIEF-cs-224"
    assert index["type"] == "brief"
    assert index["parallel_semantics"] == "exclusive"
    assert task["feature_id"] == "BRIEF-cs-224"
    assert task["feature"] == "fix-path-injection"
    assert task["spec"] == "sdd/briefs/fix-path-injection.brief.md"
    assert task["status"] == "pending"
    assert task["depends_on"] == []
    assert task["file"].endswith("HOTFIX-cs-224-1-correct-path-validation.md")


def test_brief_task_id() -> None:
    """Brief task identifiers are local to the key and start at one."""
    meta = _meta()

    assert brief_task_id(meta, 1) == "HOTFIX-cs-224-1"
    with pytest.raises(ValueError, match=">= 1"):
        brief_task_id(meta, 0)
