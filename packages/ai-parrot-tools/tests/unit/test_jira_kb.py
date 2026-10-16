"""Tests for JiraKnowledgeBase (FEAT-696 M6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot_tools.jira_kb import JiraKnowledgeBase

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURE_DIR / "jira_kb_sample.yaml"


def _kb() -> JiraKnowledgeBase:
    return JiraKnowledgeBase.load(SAMPLE)


class TestJiraKBLoad:
    def test_load_sample(self):
        kb = _kb()
        assert kb.site == "https://acme.atlassian.net"
        assert "NAV" in kb.projects
        assert kb.projects["NAV"].issue_types["Story"].id == "10001"

    def test_load_preserves_extra_keys(self, tmp_path):
        p = tmp_path / "kb.yaml"
        p.write_text("site: https://x.atlassian.net\ncustom_note: hello\n", encoding="utf-8")
        kb = JiraKnowledgeBase.load(p)
        assert kb.model_extra["custom_note"] == "hello"
        out = tmp_path / "out.yaml"
        kb.save(out)
        assert JiraKnowledgeBase.load(out).model_extra["custom_note"] == "hello"

    def test_load_non_mapping_raises(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text("- a\n- b\n", encoding="utf-8")
        with pytest.raises(ValueError):
            JiraKnowledgeBase.load(p)


class TestResolve:
    def test_resolve_issue_type_by_name(self):
        entry = _kb().resolve_issue_type("NAV", "Story")
        assert entry is not None and entry.id == "10001"

    def test_resolve_issue_type_by_id(self):
        assert _kb().resolve_issue_type("NAV", "10004") is not None

    def test_resolve_field_alias(self):
        kb = _kb()
        assert kb.resolve_field("team") == "customfield_10001"
        assert kb.resolve_field("unknown_field") == "unknown_field"

    def test_resolve_issue_type_missing(self):
        kb = _kb()
        assert kb.resolve_issue_type("NAV", "NonExistent") is None
        assert kb.resolve_issue_type("MISSING_PROJECT", "Story") is None


class TestStatusCategory:
    def test_status_category_found(self):
        kb = _kb()
        assert kb.status_category("Open") == "to_do"
        assert kb.status_category("in progress") == "in_progress"

    def test_status_category_missing(self):
        assert _kb().status_category("Unknown") is None


class TestLimits:
    def test_summary_over_limit_raises(self):
        with pytest.raises(ValueError):
            _kb().validate_limits(summary="x" * 256)

    def test_description_over_limit_raises(self):
        with pytest.raises(ValueError):
            _kb().validate_limits(description="x" * 32768)

    def test_within_limits_ok(self):
        _kb().validate_limits(summary="x" * 255, description="y" * 100)


class TestMergeGenerated:
    def _generated(self) -> JiraKnowledgeBase:
        return JiraKnowledgeBase.model_validate(
            {
                "site": "https://new.atlassian.net",
                "cloud_id": "new-id",
                "verified": "2026-11-01",
                "projects": {"OPS": {"name": "Ops", "issue_types": {"Task": {"id": "1"}}}},
                "priorities": {"scale": ["High", "Low"], "default": "High"},
                "fields": {"team": "customfield_10001", "epic": "customfield_10014"},
                "components": ["API"],
            }
        )

    def test_merge_keeps_curated(self):
        merged = _kb().merge_generated(self._generated())
        assert merged.status_map["to_do"] == ["Open", "Reopened"]
        assert "bug_report" in merged.templates
        assert merged.limits.summary_max_chars == 255
        assert merged.priorities.legacy == ["Critical", "Blocker"]
        assert merged.priorities.default == "Medium"

    def test_merge_updates_structural(self):
        merged = _kb().merge_generated(self._generated())
        assert merged.site == "https://new.atlassian.net"
        assert set(merged.projects) == {"OPS"}
        assert merged.priorities.scale == ["High", "Low"]
        assert merged.components == ["API"]
        assert merged.fields["epic"] == "customfield_10014"
        # hand-edited alias with unknown id is dropped
        assert "sprint" not in merged.fields

    def test_merge_keeps_extra_keys(self):
        kb = _kb()
        kb.__pydantic_extra__["note"] = "keep"
        assert kb.merge_generated(self._generated()).model_extra["note"] == "keep"


class TestSave:
    def test_save_roundtrip(self, tmp_path):
        kb = _kb()
        out = tmp_path / "out.yaml"
        kb.save(out)
        kb2 = JiraKnowledgeBase.load(out)
        assert kb2.site == kb.site
        assert kb2.projects == kb.projects
        assert kb2 == kb
