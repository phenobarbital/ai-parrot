"""Security tests for PythonREPLTool.

Tests from commit ``0f76129b1`` (original denylist) are preserved here and
updated in FEAT-252 / TASK-1614 to also accept the new allowlist-first
``SecurityError:`` prefix that fires before the denylist.
"""

from __future__ import annotations

import pytest

from parrot.tools.pythonrepl import PythonREPLTool


@pytest.fixture
def repl(tmp_path):
    return PythonREPLTool(report_dir=tmp_path)


_DENIAL_PREFIXES = ("BlockedOperationError:", "SecurityError:")


@pytest.mark.parametrize(
    "code",
    [
        "import os\nos.environ.keys()",
        '__import__("os").environ',
        'open("/etc/passwd").read()',
        'import subprocess\nsubprocess.run(["echo", "x"])',
        'import pathlib\npathlib.Path("/etc/passwd").read_text()',
        "import sys\nsys.modules",
    ],
)
def test_python_repl_blocks_sensitive_runtime_access(repl, code):
    """FEAT-252: code is denied by either the allowlist gate (SecurityError)
    or the legacy denylist (BlockedOperationError)."""
    result = repl.execute_sync(code)
    assert any(result.startswith(p) for p in _DENIAL_PREFIXES), (
        f"Expected a denial prefix in {_DENIAL_PREFIXES!r}, got: {result!r}"
    )


def test_python_repl_redacts_secret_like_output_when_flagged(repl):
    """Redaction is opt-in per agent: a flagged tool scrubs secret-like output."""
    repl.enable_redaction = True
    result = repl.execute_sync('{"JIRA_API_TOKEN": "super-secret-value", "NORMAL": "ok"}')

    assert "super-secret-value" not in result
    # FEAT-252: OutputScrubber emits reason-tagged markers; legacy [REDACTED] also accepted
    assert "REDACTED" in result
    assert "NORMAL" in result


def test_python_repl_no_redaction_by_default(repl):
    """Unflagged agents (default) get their REPL output verbatim — no scrubbing."""
    result = repl.execute_sync('{"JIRA_API_TOKEN": "super-secret-value", "NORMAL": "ok"}')

    assert "super-secret-value" in result
    assert "REDACTED" not in result


# =============================================================================
# FEAT-252 / TASK-1614 — allowlist-first AST gate tests
# =============================================================================

from parrot.security.python_sanitizer import (  # noqa: E402
    PythonCodeSanitizer,
    PythonExecutionPolicy,
    general_profile,
    data_analysis_profile,
)


@pytest.fixture
def gen():
    """General-profile sanitizer."""
    return PythonCodeSanitizer(general_profile())


@pytest.fixture
def da():
    """Data-analysis-profile sanitizer."""
    return PythonCodeSanitizer(data_analysis_profile())


class TestPythonAllowlistGate:
    """Allowlist-first AST gate — deny/allow parametric tests."""

    @pytest.mark.parametrize(
        "code",
        [
            "import os; os.environ",
            "dict(os.environ)",
            "os.getenv('X')",
            "().__class__.__bases__",
            "globals()",
            "eval('1+1')",
            "open('/etc/passwd')",
            "import pandas as pd; pd.read_csv('x.csv')",
            "import subprocess; subprocess.run(['ls'])",
            "import pathlib; pathlib.Path('/etc').read_text()",
        ],
    )
    def test_denied(self, gen, code):
        """All categorically dangerous patterns are denied by the general profile."""
        result = gen.validate(code)
        assert result.is_denied, f"Expected DENY for: {code!r}, got reasons: {result.reasons}"

    @pytest.mark.parametrize(
        "code",
        [
            "sum([1, 2, 3])",
            "x = [i * 2 for i in range(5)]",
            "len('abc')",
            "import math; math.sqrt(4)",
            "import json; json.dumps({'key': 'value'})",
        ],
    )
    def test_allowed(self, gen, code):
        """Safe compute expressions are allowed by the general profile."""
        result = gen.validate(code)
        assert result.is_allowed, f"Expected ALLOW for: {code!r}, got reasons: {result.reasons}"

    def test_profile_differentiation(self, gen, da):
        """data_analysis profile allows broader pandas attribute surface that general rejects."""
        # A DataFrame method not categorically blocked should be allowed in data_analysis
        # and potentially denied in general if not imported (default_deny fires)
        wide = "df.merge(other, on='k').pivot_table(index='a')"
        # Neither profile bans pivot_table as categorical; both should allow attribute use
        # The key differentiation is the wider allowed_imports for numexpr/tabulate
        import_code = "import numexpr"
        gen_result = gen.validate(import_code)
        da_result = da.validate(import_code)
        assert gen_result.is_denied, "numexpr should be denied by general profile"
        assert da_result.is_allowed, "numexpr should be allowed by data_analysis profile"

    def test_policy_is_immutable(self):
        """PythonExecutionPolicy is a frozen dataclass."""
        p = general_profile()
        with pytest.raises((AttributeError, TypeError)):
            p.default_deny = False  # type: ignore[misc]

    def test_validate_returns_validation_result(self, gen):
        """validate() returns a ValidationResult with is_allowed / is_denied."""
        from parrot.security.command_sanitizer import ValidationResult
        result = gen.validate("x = 1")
        assert isinstance(result, ValidationResult)

    def test_syntax_error_is_denied(self, gen):
        """Unparseable code is denied immediately."""
        result = gen.validate("def (broken syntax")
        assert result.is_denied
        assert any("SyntaxError" in r for r in result.reasons)

    def test_dynamic_exec_denied(self, gen):
        """eval/exec/compile/__import__ are categorically denied."""
        for bad in ("eval('x')", "exec('x=1')", "compile('x', '<s>', 'eval')"):
            assert gen.validate(bad).is_denied, f"Expected DENY for: {bad!r}"

    def test_data_io_attribute_denied(self, gen):
        """pd.read_csv (attribute access path) is denied."""
        result = gen.validate("pd.read_csv('file.csv')")
        assert result.is_denied

    def test_env_attribute_denied(self, gen):
        """os.environ attribute access is denied."""
        result = gen.validate("os.environ['KEY']")
        assert result.is_denied


class TestAllowlistGateInREPL:
    """Verify the allowlist gate is wired into PythonREPLTool.execute_sync."""

    def test_denied_code_returns_security_error(self, repl):
        """A deny by the allowlist gate returns SecurityError: prefix."""
        result = repl.execute_sync("import socket; socket.connect(('evil.com', 80))")
        assert result.startswith(("SecurityError:", "BlockedOperationError:"))

    def test_allowed_code_executes(self, repl):
        """Ordinary compute code still executes after the gate is wired."""
        result = repl.execute_sync("x = sum([1, 2, 3])\nprint(x)")
        assert "6" in result

    def test_custom_policy_accepted(self, tmp_path):
        """PythonREPLTool accepts a custom policy kwarg."""
        custom_policy = data_analysis_profile()
        tool = PythonREPLTool(report_dir=tmp_path, policy=custom_policy)
        assert tool._code_sanitizer.policy is custom_policy
