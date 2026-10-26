"""Dev-loop nodes use the single branch-policy definition in sdd_meta (FEAT-633 TASK-4298)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from parrot.flows.dev_loop.nodes import base as base_mod
from parrot.flows.dev_loop.nodes import feature_handoff as handoff_mod
from parrot.flows.dev_loop.nodes import research as research_mod
from parrot.knowledge.wiki.ledger import sdd_meta


def test_no_local_copies() -> None:
    assert not hasattr(base_mod, "_LONG_LIVED_BRANCHES")
    assert not hasattr(research_mod, "_WORK_KIND_BASE_BRANCH")
    assert not hasattr(research_mod, "_parse_flow_frontmatter")
    assert not hasattr(handoff_mod, "_parse_flow_frontmatter")


def test_base_uses_known_branches() -> None:
    assert base_mod.KNOWN_BRANCHES is sdd_meta.KNOWN_BRANCHES


def _planner(tmp_path: Path, frontmatter: str | None) -> SimpleNamespace:
    (tmp_path / "sdd" / "specs" / "x.spec.md").unlink(missing_ok=True) if (tmp_path / "sdd" / "specs").exists() else None
    spec = tmp_path / "sdd" / "specs"
    spec.mkdir(parents=True, exist_ok=True)
    if frontmatter is not None:
        (spec / "x.spec.md").write_text(frontmatter, encoding="utf-8")
    return SimpleNamespace(spec_path="sdd/specs/x.spec.md", worktree_path=str(tmp_path))


def test_feature_handoff_fallback(tmp_path: Path) -> None:
    resolve = handoff_mod.FeatureHandoffNode._resolve_base_branch
    assert resolve(_planner(tmp_path, "# no frontmatter\n")) == sdd_meta.DEFAULT_FEATURE_BASE
    assert resolve(_planner(tmp_path, "---\nbase_branch: staging\n---\n")) == "staging"


@pytest.mark.parametrize(("kind", "expected"), [("bug", "main"), ("enhancement", "dev"), ("unknown-kind", "dev")])
def test_research_kind_mapping_fallback(tmp_path: Path, kind: str, expected: str) -> None:
    node = research_mod.ResearchNode(dispatcher=MagicMock(), jira_toolkit=MagicMock(), log_toolkits={})
    out = SimpleNamespace(spec_path="missing.spec.md", worktree_path=str(tmp_path), base_branch="")
    brief = SimpleNamespace(base_branch=None, kind=kind)
    assert node._resolve_base_branch(out, brief) == expected
