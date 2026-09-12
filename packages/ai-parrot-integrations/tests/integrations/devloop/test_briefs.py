"""Tests for parrot.integrations.devloop.briefs (TASK-3201)."""

import json

from parrot.integrations.devloop.briefs import (
    brief_summary_fields,
    brief_to_file,
    build_bug_brief,
    build_feature_brief,
)
from parrot.integrations.devloop.models import DevLoopCommand, DevLoopIntegrationConfig, Requester

_CFG = DevLoopIntegrationConfig(
    name="b",
    enabled=True,
    default_acceptance_criteria=[{"kind": "shell", "name": "unit", "command": "pytest -q"}],
)
_REQ = Requester(transport="slack", tenant_id="T", user_id="U")


def test_bug_defaults_and_ac_override() -> None:
    cmd = DevLoopCommand(
        action="dispatch",
        type="bug",
        prompt="Sync drops last row\nwhen CSV ends with newline",
        acceptance_command="pytest packages -q",
    )
    brief = build_bug_brief(cmd, _REQ, _CFG, reporter="r@x", escalation_assignee="e@x")
    assert brief.summary == "Sync drops last row" and brief.affected_component == "ai-parrot"
    assert brief.acceptance_criteria[0].command == "pytest packages -q" and brief.base_branch is None


def test_bug_base_sets_flow_type() -> None:
    cmd = DevLoopCommand(action="dispatch", type="bug", prompt="A long enough bug summary", base_branch="staging")
    brief = build_bug_brief(cmd, _REQ, _CFG, reporter="r", escalation_assignee="e")
    assert brief.flow_type == "feature" and brief.base_branch == "staging"


def test_bug_default_criteria_used_without_ac() -> None:
    cmd = DevLoopCommand(action="dispatch", type="bug", prompt="A long enough bug summary")
    brief = build_bug_brief(cmd, _REQ, _CFG, reporter="r", escalation_assignee="e")
    assert brief.acceptance_criteria[0].command == "pytest -q"


def test_bug_summary_padding_when_short() -> None:
    cmd = DevLoopCommand(action="dispatch", type="bug", prompt="Bug")
    brief = build_bug_brief(cmd, _REQ, _CFG, reporter="r", escalation_assignee="e")
    assert len(brief.summary) >= 10
    assert brief.summary.startswith("bug: ")


def test_bug_component_override() -> None:
    cmd = DevLoopCommand(
        action="dispatch", type="bug", prompt="A long enough bug summary", component="ai-parrot-integrations"
    )
    brief = build_bug_brief(cmd, _REQ, _CFG, reporter="r", escalation_assignee="e")
    assert brief.affected_component == "ai-parrot-integrations"


def test_feature_title_derivation_and_base(tmp_path) -> None:
    cmd = DevLoopCommand(
        action="dispatch", type="feature", prompt="Add a token budget. Details follow", base_branch="dev"
    )
    brief = build_feature_brief(cmd, _CFG)
    assert brief.title == "Add a token budget" and brief.kind == "new_feature" and brief.base_branch == "dev"
    path = brief_to_file(brief, str(tmp_path), "run-1")
    assert json.load(open(path))["kind"] == "new_feature"
    assert (tmp_path / "run-1.brief.json").stat().st_mode & 0o777 == 0o600


def test_feature_title_flag_wins() -> None:
    cmd = DevLoopCommand(action="dispatch", type="feature", title="Explicit Title", prompt="Some request. More text.")
    brief = build_feature_brief(cmd, _CFG)
    assert brief.title == "Explicit Title"


def test_brief_summary_fields_bug() -> None:
    cmd = DevLoopCommand(action="dispatch", type="bug", prompt="A long enough bug summary", jira_issue_key="NAV-1")
    brief = build_bug_brief(cmd, _REQ, _CFG, reporter="r", escalation_assignee="e")
    fields = brief_summary_fields(brief)
    assert fields["kind"] == "bug"
    assert fields["jira"] == "NAV-1"
    assert fields["component"] == "ai-parrot"
    assert "unit" in fields["criteria"]


def test_brief_summary_fields_feature() -> None:
    cmd = DevLoopCommand(action="dispatch", type="feature", prompt="A new feature request", base_branch="staging")
    brief = build_feature_brief(cmd, _CFG)
    fields = brief_summary_fields(brief)
    assert fields["kind"] == "new_feature"
    assert fields["title"] == brief.title
    assert fields["base"] == "staging"
