"""Security tests for PythonREPLTool."""

from __future__ import annotations

import pytest

from parrot.tools.pythonrepl import PythonREPLTool


@pytest.fixture
def repl(tmp_path):
    return PythonREPLTool(report_dir=tmp_path)


@pytest.mark.parametrize(
    "code, blocked",
    [
        ("import os\nos.environ.keys()", "import 'os' is blocked"),
        ('__import__("os").environ', "blocked in python_repl"),
        ('open("/etc/passwd").read()', "use of 'open' is blocked"),
        ('import subprocess\nsubprocess.run(["echo", "x"])', "import 'subprocess' is blocked"),
        ('import pathlib\npathlib.Path("/etc/passwd").read_text()', "import 'pathlib' is blocked"),
        ("import sys\nsys.modules", "import 'sys' is blocked"),
    ],
)
def test_python_repl_blocks_sensitive_runtime_access(repl, code, blocked):
    result = repl.execute_sync(code)

    assert result.startswith("BlockedOperationError:")
    assert blocked in result


def test_python_repl_redacts_secret_like_output(repl):
    result = repl.execute_sync('{"JIRA_API_TOKEN": "super-secret-value", "NORMAL": "ok"}')

    assert "super-secret-value" not in result
    assert "[REDACTED]" in result
    assert "NORMAL" in result
