"""Unit tests for ``scripts.sdd.sdd_meta.resolve_flow`` — FEAT-466 / TASK-2502."""

from __future__ import annotations

import pytest

from scripts.sdd.sdd_meta import WORK_KIND_FLOW, resolve_flow


class TestResolveFlowKindMapping:
    def test_bug_is_a_hotfix_on_main(self):
        meta = resolve_flow(kind="bug")
        assert (meta.type, meta.base_branch) == ("hotfix", "main")

    @pytest.mark.parametrize("kind", ["enhancement", "new_feature"])
    def test_non_bug_kinds_are_features_on_dev(self, kind):
        meta = resolve_flow(kind=kind)
        assert (meta.type, meta.base_branch) == ("feature", "dev")

    def test_no_arguments_returns_default(self):
        meta = resolve_flow()
        assert (meta.type, meta.base_branch) == ("feature", "dev")

    def test_unknown_kind_falls_through_to_default(self):
        meta = resolve_flow(kind="not-a-kind")
        assert (meta.type, meta.base_branch) == ("feature", "dev")

    def test_mapping_constant_is_exhaustive(self):
        assert set(WORK_KIND_FLOW) == {"bug", "enhancement", "new_feature"}


class TestResolveFlowMissingDocument:
    def test_missing_doc_path_is_not_an_error(self, tmp_path):
        """THE regression this task exists for: parse() raises
        FileNotFoundError on a missing path, which is exactly the dev-loop
        bug path's situation."""
        meta = resolve_flow(kind="bug", doc_path=tmp_path / "nope.brainstorm.md")
        assert (meta.type, meta.base_branch) == ("hotfix", "main")

    def test_none_doc_path_is_not_an_error(self):
        assert resolve_flow(kind="bug", doc_path=None).type == "hotfix"


class TestResolveFlowPrecedence:
    def test_existing_doc_frontmatter_beats_kind(self, tmp_path):
        doc = tmp_path / "x.brainstorm.md"
        doc.write_text("---\ntype: feature\nbase_branch: dev\n---\n# body\n")
        meta = resolve_flow(kind="bug", doc_path=doc)
        assert (meta.type, meta.base_branch) == ("feature", "dev")

    def test_overrides_beat_document(self, tmp_path):
        doc = tmp_path / "x.brainstorm.md"
        doc.write_text("---\ntype: feature\nbase_branch: dev\n---\n")
        meta = resolve_flow(
            doc_path=doc, type_override="hotfix", base_branch_override="main"
        )
        assert (meta.type, meta.base_branch) == ("hotfix", "main")

    def test_overrides_compose_field_wise(self):
        """Only base_branch overridden -> the kind-derived type survives.
        This is what lets the console override just the base branch."""
        meta = resolve_flow(kind="enhancement", base_branch_override="staging")
        assert (meta.type, meta.base_branch) == ("feature", "staging")


class TestResolveFlowValidation:
    def test_hotfix_off_main_is_rejected(self):
        with pytest.raises(ValueError, match="hotfix"):
            resolve_flow(type_override="hotfix", base_branch_override="dev")

    def test_unknown_branch_warns_but_succeeds(self, caplog):
        meta = resolve_flow(base_branch_override="feat/parent-branch")
        assert meta.base_branch == "feat/parent-branch"
