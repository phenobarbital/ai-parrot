"""FEAT-252 end-to-end containment + non-regression test suite.

Verifies that the original incident scenario (``os.environ.keys()`` leaking
``ODOO_EPSON_PRODUCTION_PASSWORD``) is stopped at every defence layer:

  Layer 1 (WS1)  — ``PythonCodeSanitizer`` allowlist-first AST gate
  Layer 2 (WS3)  — ``OutputScrubber`` single-seam hook at ``AbstractTool.execute()``
  Layer 3 (WS2)  — ``GoogleGenAIClient._resolve_final_response`` chokepoint

Also verifies:
  - No redaction gap after TASK-1613 removed the scattered redact_* calls.
  - In-process REPL state (``_inject_context_to_repl`` pattern) still works
    under the allowlist gate.
  - The original ``0f76129b1`` security tests still pass (see
    ``test_pythonrepl_security.py``).
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from parrot.security.python_sanitizer import PythonCodeSanitizer, general_profile
from parrot.security.redaction import OutputScrubber, ScrubPolicy
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.pythonrepl import PythonREPLTool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SECRET_VALUE = "ODOO_EPSON_PRODUCTION_PASSWORD_s3cr3t"
_ENVIRON_DUMP = (
    f"KeysView(environ({{'{_SECRET_VALUE}': 'hunter2', 'NORMAL': 'visible'}}))"
)


@pytest.fixture
def tmp_repl(tmp_path):
    """PythonREPLTool with the general profile (default) and a tmp report dir."""
    return PythonREPLTool(report_dir=tmp_path)


@pytest.fixture
def sanitizer():
    """PythonCodeSanitizer with the general profile."""
    return PythonCodeSanitizer(general_profile())


@pytest.fixture
def scrubber():
    """Default OutputScrubber."""
    return OutputScrubber(ScrubPolicy())


# ---------------------------------------------------------------------------
# Layer 1 (WS1) — AST gate
# ---------------------------------------------------------------------------

class TestLayer1ASTGate:
    """The allowlist-first AST gate denies the incident scenario at source."""

    def test_os_environ_keys_denied(self, sanitizer):
        """``import os; os.environ.keys()`` is denied by the general profile."""
        result = sanitizer.validate("import os; os.environ.keys()")
        assert result.is_denied, f"Expected DENY, got: {result.reasons}"

    def test_dict_os_environ_denied(self, sanitizer):
        """``dict(os.environ)`` is denied (os.environ attribute access)."""
        result = sanitizer.validate("dict(os.environ)")
        assert result.is_denied

    def test_getenv_denied(self, sanitizer):
        """``os.getenv('SECRET')`` is denied."""
        result = sanitizer.validate("os.getenv('SECRET')")
        assert result.is_denied

    def test_denial_produces_no_secret_echo(self, sanitizer):
        """The denial reasons do NOT echo the secret value."""
        code = f"import os; x = os.environ['{_SECRET_VALUE}']"
        result = sanitizer.validate(code)
        assert result.is_denied
        reasons_text = " ".join(result.reasons)
        assert _SECRET_VALUE not in reasons_text


# ---------------------------------------------------------------------------
# Layer 2 (WS3) — OutputScrubber seam
# ---------------------------------------------------------------------------

class TestLayer2OutputScrubber:
    """The OutputScrubber seam scrubs any environ dump that surfaces."""

    def test_environ_dump_scrubbed(self, scrubber):
        """An environ dump string is scrubbed of the secret value."""
        out = scrubber.scrub(_ENVIRON_DUMP)
        assert "hunter2" not in out
        assert "REDACTED" in out

    def test_scrubber_seam_in_execute(self):
        """AbstractTool.execute() runs the scrubber on the result."""

        class EnvDumpTool(AbstractTool):
            name = "env_dump_tool"
            description = "test"

            async def _execute(self, **kwargs):
                return _ENVIRON_DUMP

        import asyncio
        tool = EnvDumpTool()
        tool.enable_redaction = True  # redaction is opt-in per agent
        result = asyncio.run(tool.execute())
        assert isinstance(result, ToolResult)
        assert "hunter2" not in str(result.result)
        assert "REDACTED" in str(result.result)

    def test_repl_denies_then_scrubs_if_surfaced(self, tmp_repl):
        """REPL execution of the incident scenario is denied; if the denial message
        itself surfaces a secret it is also scrubbed (defence in depth)."""
        result = tmp_repl.execute_sync("import os; os.environ.keys()")
        # The denial prefix from gate or legacy denylist
        assert result.startswith(("SecurityError:", "BlockedOperationError:"))
        # The actual secret value must not appear in the refusal message
        assert "hunter2" not in result
        assert _SECRET_VALUE not in result


# ---------------------------------------------------------------------------
# Layer 3 (WS2) — _resolve_final_response chokepoint
# ---------------------------------------------------------------------------

class TestLayer3Chokepoint:
    """The Gemini client chokepoint scrubs secrets from synthesised responses."""

    def _make_client(self):
        """Build a minimal GoogleGenAIClient stub (no real credentials)."""
        from parrot.clients.google.client import GoogleGenAIClient
        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        client.model = "gemini-2.5-flash"
        client.temperature = 0.0
        client.max_tokens = None
        client.logger = MagicMock()
        client.logger.notice = MagicMock()
        client.logger.info = MagicMock()
        client.logger.warning = MagicMock()
        client._scrubber = OutputScrubber(ScrubPolicy())
        client._echo_threshold = 0.85
        client.enable_redaction = True  # redaction is opt-in per agent
        return client

    def test_secret_in_synthesis_is_scrubbed(self):
        """A synthesised answer containing the secret value is scrubbed."""
        client = self._make_client()
        candidate = f"The password is {_SECRET_VALUE}=hunter2"
        out = client._resolve_final_response(candidate, [], None)
        assert "hunter2" not in out
        assert "REDACTED" in out

    def test_environ_dump_in_candidate_scrubbed(self):
        """An environ-dump candidate is scrubbed before delivery."""
        client = self._make_client()
        out = client._resolve_final_response(_ENVIRON_DUMP, [], None)
        assert "hunter2" not in out

    def test_no_scattered_redact_calls(self):
        """Verify google/client.py has zero scattered redact_text/redact_secrets calls
        (non-regression for TASK-1613 cleanup)."""
        import inspect
        import parrot.clients.google.client as m
        src = inspect.getsource(m)
        count = src.count("redact_text(") + src.count("redact_secrets(")
        assert count == 0, (
            f"Found {count} scattered redact_text/redact_secrets call(s) in client.py — "
            "all scrubbing must go through _resolve_final_response / OutputScrubber."
        )


# ---------------------------------------------------------------------------
# REPL in-process state preservation
# ---------------------------------------------------------------------------

class TestReplStatePreservation:
    """Verify _inject_context_to_repl pattern still works under the allowlist gate."""

    def test_locals_injection_survives_gate(self, tmp_path):
        """Data injected into REPL locals is accessible to allowed code."""
        import pandas as pd
        repl = PythonREPLTool(report_dir=tmp_path)

        # Simulate _inject_context_to_repl injecting a DataFrame
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        repl.locals["df"] = df

        # Verify a safe compute expression on the injected df works
        result = repl.execute_sync("print(df.shape)")
        assert "(3, 2)" in result

    def test_read_csv_still_denied_even_with_df_in_locals(self, tmp_path):
        """Even when a DataFrame is in locals, pd.read_csv() is denied."""
        import pandas as pd
        repl = PythonREPLTool(report_dir=tmp_path)
        repl.locals["df"] = pd.DataFrame({"x": [1, 2]})

        result = repl.execute_sync("import pandas as pd; pd.read_csv('file.csv')")
        assert result.startswith(("SecurityError:", "BlockedOperationError:"))

    def test_custom_locals_key_accessible(self, tmp_path):
        """A plain Python dict injected into locals is accessible."""
        repl = PythonREPLTool(report_dir=tmp_path)
        repl.locals["my_data"] = {"value": 42}

        result = repl.execute_sync("print(my_data['value'])")
        assert "42" in result


# ---------------------------------------------------------------------------
# Cross-layer: defense in depth
# ---------------------------------------------------------------------------

class TestDefenseInDepth:
    """End-to-end: the incident scenario is blocked at EVERY layer."""

    def test_incident_denied_at_gate(self, sanitizer):
        """Layer 1 (AST gate) denies the incident code."""
        assert sanitizer.validate("import os; os.environ.keys()").is_denied

    def test_incident_scrubbed_if_surfaced(self, scrubber):
        """Layer 2 (OutputScrubber) scrubs even if the value somehow surfaces."""
        out = scrubber.scrub(_ENVIRON_DUMP)
        assert "hunter2" not in out

    def test_incident_not_echoed_in_repl(self, tmp_repl):
        """Layer 1 denies REPL execution; the refusal message leaks no secret."""
        result = tmp_repl.execute_sync("import os; os.environ.keys()")
        assert result.startswith(("SecurityError:", "BlockedOperationError:"))
        assert "hunter2" not in result

    def test_allowlist_gate_wired_into_repl(self, tmp_repl):
        """The REPL's _code_sanitizer attribute exists and uses general_profile."""
        assert hasattr(tmp_repl, "_code_sanitizer")
        assert isinstance(tmp_repl._code_sanitizer, PythonCodeSanitizer)

    def test_scrubber_seam_wired_into_abstract_tool(self):
        """The AbstractTool._default_scrubber() returns an OutputScrubber."""
        import parrot.tools.abstract as m
        scrubber_instance = m._default_scrubber()
        assert isinstance(scrubber_instance, OutputScrubber)
