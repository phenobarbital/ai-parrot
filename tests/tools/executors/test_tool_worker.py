"""Tests for the worker-side entrypoint at ``parrot.cli.tool_worker``."""
from __future__ import annotations

import io
import json
import sys

import pytest

from parrot.cli import tool_worker


def _envelope_text(import_path: str, method_name: str | None, arguments: dict) -> str:
    return json.dumps(
        {
            "tool_import_path": import_path,
            "tool_init_kwargs": {},
            "method_name": method_name,
            "arguments": arguments,
            "permission_context": None,
            "trace_context": None,
            "timeout_seconds": 30,
            "webhook_callback_url": None,
            "envelope_version": 1,
        }
    )


def _extract_result_block(captured: str) -> dict:
    begin = "__PARROT_TOOL_RESULT_BEGIN__"
    end = "__PARROT_TOOL_RESULT_END__"
    assert begin in captured and end in captured, captured
    payload = captured.split(begin, 1)[1].split(end, 1)[0].strip()
    return json.loads(payload)


def test_main_executes_abstract_tool_envelope(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(_envelope_text(
            "tests.tools.executors._fixtures:EchoTool",
            None,
            {"msg": "from-worker"},
        )),
    )
    rc = tool_worker.main(["--envelope", "-"])
    captured = capsys.readouterr().out
    assert rc == 0
    payload = _extract_result_block(captured)
    assert payload["status"] == "success"
    assert payload["result"] == "echo:from-worker"


def test_main_executes_toolkit_method_envelope(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(_envelope_text(
            "tests.tools.executors._fixtures:GreetingToolkit",
            "add",
            {"a": 2, "b": 3},
        )),
    )
    rc = tool_worker.main(["--envelope", "-"])
    captured = capsys.readouterr().out
    assert rc == 0
    payload = _extract_result_block(captured)
    assert payload["status"] == "success"
    assert payload["result"] == 5


def test_main_emits_error_when_tool_class_missing(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(_envelope_text(
            "tests.tools.executors._fixtures:DoesNotExist",
            None,
            {},
        )),
    )
    rc = tool_worker.main(["--envelope", "-"])
    captured = capsys.readouterr().out
    payload = _extract_result_block(captured)
    # Worker handled the exception gracefully — return code stays 0 so
    # the executor reads a structured ToolResult instead of having to
    # interpret an exit code.
    assert rc == 0
    assert payload["status"] == "error"
    assert "DoesNotExist" in (payload.get("error") or "")


def test_main_handles_missing_envelope_file(capsys):
    rc = tool_worker.main(["--envelope", "/no/such/file.json"])
    captured = capsys.readouterr().out
    payload = _extract_result_block(captured)
    assert rc == 2
    assert payload["status"] == "error"
    assert "Could not read envelope" in (payload.get("error") or "")
