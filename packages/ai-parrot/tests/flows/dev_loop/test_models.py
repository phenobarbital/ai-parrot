"""Unit tests for parrot.flows.dev_loop.models (TASK-874)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot.flows.dev_loop import (
    BugBrief,
    ClaudeCodeDispatchProfile,
    DispatchEvent,
    FlowtaskCriterion,
    LogSource,
    ShellCriterion,
)


class TestBugBrief:
    def test_bug_brief_rejects_empty_criteria(self):
        with pytest.raises(ValidationError):
            BugBrief(
                summary="x" * 20,
                affected_component="etl/customers/sync.yaml",
                log_sources=[],
                acceptance_criteria=[],
                escalation_assignee="557058:abc",
                reporter="557058:def",
            )

    def test_bug_brief_accepts_valid_payload(self):
        brief = BugBrief(
            summary="customer sync drops the last row",
            affected_component="etl/customers/sync.yaml",
            log_sources=[LogSource(kind="cloudwatch", locator="/etl/x")],
            acceptance_criteria=[
                FlowtaskCriterion(name="run", task_path="etl/customers/sync.yaml"),
            ],
            escalation_assignee="557058:abc",
            reporter="557058:def",
        )
        assert brief.acceptance_criteria[0].kind == "flowtask"


class TestDiscriminatedUnion:
    def test_round_trip_flowtask(self):
        brief = BugBrief.model_validate(
            {
                "summary": "x" * 20,
                "affected_component": "etl/customers/sync.yaml",
                "log_sources": [],
                "acceptance_criteria": [
                    {
                        "kind": "flowtask",
                        "name": "x",
                        "task_path": "etl/customers/sync.yaml",
                    },
                ],
                "escalation_assignee": "a",
                "reporter": "b",
            }
        )
        criterion = brief.acceptance_criteria[0]
        assert isinstance(criterion, FlowtaskCriterion)
        assert criterion.task_path == "etl/customers/sync.yaml"

    def test_round_trip_shell(self):
        brief = BugBrief.model_validate(
            {
                "summary": "x" * 20,
                "affected_component": "etl/customers/sync.yaml",
                "log_sources": [],
                "acceptance_criteria": [
                    {"kind": "shell", "name": "lint", "command": "ruff check ."},
                ],
                "escalation_assignee": "a",
                "reporter": "b",
            }
        )
        assert isinstance(brief.acceptance_criteria[0], ShellCriterion)


class TestDispatchProfile:
    def test_defaults(self):
        profile = ClaudeCodeDispatchProfile()
        assert profile.subagent == "sdd-worker"
        assert profile.permission_mode == "default"
        assert profile.setting_sources == ["project"]
        assert profile.model == "claude-sonnet-4-6"
        assert profile.timeout_seconds == 1800

    def test_generic_session_when_subagent_none(self):
        profile = ClaudeCodeDispatchProfile(
            subagent=None, system_prompt_override="be terse"
        )
        assert profile.subagent is None
        assert profile.system_prompt_override == "be terse"


class TestDispatchEvent:
    @pytest.mark.parametrize(
        "kind",
        [
            "dispatch.queued",
            "dispatch.started",
            "dispatch.message",
            "dispatch.tool_use",
            "dispatch.tool_result",
            "dispatch.output_invalid",
            "dispatch.failed",
            "dispatch.completed",
        ],
    )
    def test_kind_literal_round_trip(self, kind):
        ev = DispatchEvent(
            kind=kind, ts=0.0, run_id="r", node_id="n", payload={}
        )
        assert ev.kind == kind

    def test_invalid_kind_rejected(self):
        with pytest.raises(ValidationError):
            DispatchEvent(
                kind="dispatch.bogus",
                ts=0.0,
                run_id="r",
                node_id="n",
                payload={},
            )
