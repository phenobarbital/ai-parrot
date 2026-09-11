"""Unit tests for ``scripts.sdd.sdd_meta.plan_worktree`` — FEAT-552 / TASK-3153."""

from __future__ import annotations

import pytest

from scripts.sdd.sdd_meta import WORKTREE_ROOT, FlowMeta, WorktreePlan, plan_worktree

SLUG = "worktree-creation-ownership"


def test_plan_feature_name_keeps_feat_prefix() -> None:
    """A feature keeps the doubled `feat-FEAT-` prefix — /sdd-done greps it."""
    plan = plan_worktree(
        FlowMeta(type="feature", base_branch="dev"), slug=SLUG, feature_id="FEAT-552"
    )
    assert isinstance(plan, WorktreePlan)
    assert plan.name == f"feat-FEAT-552-{SLUG}"
    assert plan.path == f"{WORKTREE_ROOT}/feat-FEAT-552-{SLUG}"


@pytest.mark.parametrize("branch", ["dev", "staging"])
def test_plan_feature_base_ref_is_remote_qualified(branch: str) -> None:
    """base_ref is always origin/<base_branch> — never a local HEAD."""
    plan = plan_worktree(
        FlowMeta(type="feature", base_branch=branch), slug=SLUG, feature_id="FEAT-552"
    )
    assert plan.base_ref == f"origin/{branch}"


def test_plan_hotfix_uses_jira_key_and_origin_main() -> None:
    """FEAT-466: a hotfix is named from its Jira key and branches from main."""
    plan = plan_worktree(
        FlowMeta(type="hotfix", base_branch="main"), slug=SLUG, jira_key="NAV-8036"
    )
    assert plan.name == f"hotfix-NAV-8036-{SLUG}"
    assert plan.base_ref == "origin/main"


def test_plan_feature_without_feature_id_raises() -> None:
    """A feature with no id is a programming error, not a default."""
    with pytest.raises(ValueError, match="feature_id"):
        plan_worktree(FlowMeta(type="feature", base_branch="dev"), slug=SLUG)


def test_plan_feature_with_bare_number_raises() -> None:
    """`552` is not `FEAT-552` — reject it rather than emit a legacy-style name."""
    with pytest.raises(ValueError, match="feature_id"):
        plan_worktree(FlowMeta(type="feature", base_branch="dev"), slug=SLUG, feature_id="552")


def test_plan_hotfix_without_jira_key_raises() -> None:
    """A hotfix has no FEAT id, so the Jira key is mandatory."""
    with pytest.raises(ValueError, match="jira_key"):
        plan_worktree(FlowMeta(type="hotfix", base_branch="main"), slug=SLUG)


@pytest.mark.parametrize("slug", ["", "   "])
def test_plan_empty_slug_raises(slug: str) -> None:
    """An empty slug would yield `feat-FEAT-552-` — refuse it."""
    with pytest.raises(ValueError, match="slug"):
        plan_worktree(FlowMeta(type="feature", base_branch="dev"), slug=slug, feature_id="FEAT-552")
