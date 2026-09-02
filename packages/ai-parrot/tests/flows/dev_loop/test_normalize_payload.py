"""Unit tests for normalize_payload() + summarize_tool_input() (FEAT-496 TASK-2723)."""

import pytest

from parrot.flows.dev_loop.dispatchers._shared import (
    _DISPATCH_LABELS_CTX,
    SUMMARY_MAX_CHARS,
    bind_labels,
    normalize_payload,
    summarize_tool_input,
)
from parrot.flows.dev_loop.models import DispatchLabels

KINDS = [
    "dispatch.queued",
    "dispatch.started",
    "dispatch.message",
    "dispatch.tool_use",
    "dispatch.tool_result",
    "dispatch.output_invalid",
    "dispatch.failed",
    "dispatch.completed",
]


@pytest.mark.parametrize("kind", KINDS)
def test_every_kind_gets_a_summary(kind):
    out = normalize_payload(kind, {})
    assert out["summary"]
    assert len(out["summary"]) <= SUMMARY_MAX_CHARS


def test_preserves_backend_keys():
    raw = {"codex_event": {"type": "item.started"}, "message_class": "X"}
    out = normalize_payload("dispatch.message", raw)
    assert out["codex_event"] == raw["codex_event"]
    assert out["message_class"] == "X"


def test_does_not_overwrite_backend_summary():
    out = normalize_payload("dispatch.message", {"summary": "mine"})
    assert out["summary"] == "mine"


def test_labels_are_stamped():
    token = bind_labels(DispatchLabels(task_id="TASK-1857", seat="development.w1"))
    try:
        out = normalize_payload("dispatch.tool_use", {"tool_name": "Read"})
        assert out["task_id"] == "TASK-1857"
        assert out["seat"] == "development.w1"
    finally:
        _DISPATCH_LABELS_CTX.reset(token)


def test_task_file_only_on_lifecycle_kinds():
    token = bind_labels(DispatchLabels(task_file="sdd/tasks/active/TASK-1.md"))
    try:
        assert "task_file" in normalize_payload("dispatch.started", {})
        assert "task_file" not in normalize_payload("dispatch.tool_use", {})
    finally:
        _DISPATCH_LABELS_CTX.reset(token)


@pytest.mark.parametrize("bad", [None, 42, "a string", {"k": object()}])
def test_never_raises(bad):
    out = normalize_payload("dispatch.message", bad)
    assert isinstance(out, dict) and out["summary"]


class TestSummarizeToolInput:
    def test_file_path(self):
        assert "foo.py" in summarize_tool_input("Read", {"file_path": "a/b/foo.py"})

    def test_command(self):
        assert "pytest" in summarize_tool_input("Bash", {"command": "pytest -q"})

    def test_pattern_and_path(self):
        out = summarize_tool_input("Grep", {"pattern": "def x", "path": "src/"})
        assert "def x" in out and "src/" in out

    def test_clamped(self):
        assert len(summarize_tool_input("Bash", {"command": "x" * 500})) <= 120

    def test_json_string_input(self):
        assert "foo.py" in summarize_tool_input("Read", '{"file_path": "foo.py"}')

    def test_unknown_shape_degrades(self):
        assert summarize_tool_input("Weird", object()) == ""
