"""Tests for `parrot.interfaces.jira` models and `parse_issue` (FEAT-454, M1)."""

import json
import sys

import pytest
from parrot.interfaces.jira import (
    JiraAttachmentRef,
    JiraIssue,
    JiraIssueLinkKind,
    JiraPerson,
    parse_issue,
)

BASE = "https://example.atlassian.net"


@pytest.fixture
def issue(raw_issue) -> JiraIssue:
    return parse_issue(raw_issue, base_url=BASE, ac_field_id="customfield_10101")


class TestParseIssueProjection:
    def test_core_fields(self, issue):
        assert issue.key == "NAV-9372"
        assert issue.issue_id == "184220"
        assert issue.project_key == "NAV"
        assert issue.issue_type == "Bug"
        assert issue.status == "In Progress"
        assert issue.priority == "High"
        assert issue.resolution is None
        assert issue.url == f"{BASE}/browse/NAV-9372"

    def test_hierarchy(self, issue):
        assert issue.parent_key == "NAV-9000"
        assert issue.epic_key == "NAV-8000"
        assert issue.subtask_keys == ["NAV-9373", "NAV-9374"]

    def test_links_normalized_both_directions(self, issue):
        by_target = {link.target_key: link.kind for link in issue.links}
        assert by_target["NAV-9400"] is JiraIssueLinkKind.BLOCKS
        assert by_target["NAV-9111"] is JiraIssueLinkKind.DUPLICATED_BY

    def test_unknown_link_type_degrades_to_relates(self, issue):
        by_target = {link.target_key: link.kind for link in issue.links}
        assert by_target["NAV-9500"] is JiraIssueLinkKind.RELATES

    def test_attachments_are_references_only(self, issue):
        (att,) = issue.attachments
        assert isinstance(att, JiraAttachmentRef)
        assert att.filename == "trace.har"
        assert att.size_bytes == 20481
        assert att.url.endswith("trace.har")

    def test_rendered_description_and_ac_captured_as_html(self, issue):
        assert "<strong>tenant</strong>" in issue.description_html
        assert issue.acceptance_criteria_html is not None

    def test_ac_omitted_when_field_id_not_given(self, raw_issue):
        parsed = parse_issue(raw_issue, base_url=BASE, ac_field_id=None)
        assert parsed.acceptance_criteria_html is None

    def test_history_sorted_ascending(self, issue):
        assert [e.field for e in issue.history] == ["priority", "status"]
        assert issue.history[0].at < issue.history[1].at
        assert issue.history[1].from_value == "To Do"
        assert issue.history[1].to_value == "In Progress"

    def test_labels_and_components(self, issue):
        assert set(issue.labels) == {"multitenant", "forms"}
        assert set(issue.components) == {"navigator-forms", "api"}


class TestPIIBoundary:
    """G9 — no personal email ever enters the plane."""

    def test_person_model_has_no_email_field(self):
        assert "email" not in JiraPerson.model_fields
        assert not any("email" in f.lower() for f in JiraPerson.model_fields)

    def test_no_email_anywhere_in_dump(self, issue):
        dumped = issue.model_dump_json()
        assert "jlara@example.com" not in dumped
        assert "aruiz@example.com" not in dumped
        assert "emailAddress" not in dumped

    def test_changelog_author_email_dropped(self, issue):
        for event in issue.history:
            if event.author is not None:
                assert "email" not in json.dumps(event.author.model_dump()).lower()


class TestPurityAndOptionalDependency:
    def test_importable_without_jira_installed(self, monkeypatch):
        """The package must not import `jira` at module load."""
        monkeypatch.setitem(sys.modules, "jira", None)
        import importlib

        import parrot.interfaces.jira as mod

        importlib.reload(mod)
        assert mod.JiraIssue is not None

    def test_parse_is_deterministic(self, raw_issue):
        a = parse_issue(raw_issue, base_url=BASE, ac_field_id="customfield_10101")
        b = parse_issue(raw_issue, base_url=BASE, ac_field_id="customfield_10101")
        assert a.model_dump_json() == b.model_dump_json()


class TestDefensiveParsing:
    def test_missing_fields_dict_raises_valueerror(self):
        with pytest.raises(ValueError, match="fields"):
            parse_issue({"id": "1", "key": "NAV-1"}, base_url=BASE)

    def test_sparse_issue_yields_defaults_not_keyerror(self):
        raw = {
            "id": "1",
            "key": "NAV-1",
            "fields": {
                "project": {"key": "NAV"},
                "issuetype": {"name": "Task"},
                "status": {"name": "To Do"},
                "summary": "s",
            },
        }
        parsed = parse_issue(raw, base_url=BASE)
        assert parsed.labels == [] and parsed.links == []
        assert parsed.assignee is None and parsed.description_html is None
