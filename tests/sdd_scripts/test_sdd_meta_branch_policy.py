"""Single-source branch policy in sdd_meta (FEAT-633 TASK-4298)."""
from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.wiki.ledger.sdd_meta import (
    DEFAULT_FEATURE_BASE,
    DEFAULT_HOTFIX_BASE,
    KNOWN_BRANCHES,
    WORK_KIND_FLOW,
    FlowMeta,
    read_declared_base_branch,
    resolve_flow,
)


def test_constants_match_known_branches() -> None:
    assert DEFAULT_FEATURE_BASE in KNOWN_BRANCHES
    assert DEFAULT_HOTFIX_BASE in KNOWN_BRANCHES
    assert WORK_KIND_FLOW["bug"] == ("hotfix", DEFAULT_HOTFIX_BASE)
    assert WORK_KIND_FLOW["new_feature"] == ("feature", DEFAULT_FEATURE_BASE)


def test_read_declared_returns_value(tmp_path: Path) -> None:
    doc = tmp_path / "d.md"
    doc.write_text("---\nbase_branch: staging\n---\n# x\n", encoding="utf-8")
    assert read_declared_base_branch(doc) == "staging"


@pytest.mark.parametrize(
    "content",
    [
        None,  # missing file
        "# no frontmatter\n",
        "---\nbase_branch: dev\n",  # unterminated
        "---\nbase_branch: [\n---\n",  # malformed YAML
        "---\n- a\n- b\n---\n",  # non-mapping block
        "---\ntype: feature\n---\n",  # no key
        "---\nbase_branch: 3\n---\n",  # non-string
        '---\nbase_branch: "  "\n---\n',  # blank
    ],
)
def test_read_declared_returns_none_for(tmp_path: Path, content: str | None) -> None:
    doc = tmp_path / "d.md"
    if content is not None:
        doc.write_text(content, encoding="utf-8")
    assert read_declared_base_branch(doc) is None


def test_resolve_flow_default_uses_constant() -> None:
    assert resolve_flow() == FlowMeta(type="feature", base_branch=DEFAULT_FEATURE_BASE)


def test_shim_reexports_new_names() -> None:
    from scripts.sdd.sdd_meta import (  # noqa: F401
        DEFAULT_FEATURE_BASE as feature_base,
        DEFAULT_HOTFIX_BASE as hotfix_base,
        read_declared_base_branch as reader,
    )

    assert feature_base == DEFAULT_FEATURE_BASE and hotfix_base == DEFAULT_HOTFIX_BASE and reader is read_declared_base_branch
