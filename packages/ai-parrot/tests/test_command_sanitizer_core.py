"""Tests for the relocated CommandSanitizer engine (FEAT-252 / TASK-1611).

Verifies:
- Import resolves from parrot.security.command_sanitizer (new home)
- Re-export shim from parrot_tools.shell_tool.security yields the same objects
- Verdict parity: RESTRICTIVE / MODERATE / PERMISSIVE behaviour is unchanged
"""
from __future__ import annotations

import pytest

from parrot.security.command_sanitizer import (
    CommandSanitizer,
    CommandVerdict,
    SecurityLevel,
    SecurityPolicy,
    ValidationResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sanitizer(level: str = "restrictive", allowed=None) -> CommandSanitizer:
    if level == "restrictive":
        return CommandSanitizer(SecurityPolicy.restrictive(allowed_commands=allowed or set()))
    if level == "moderate":
        return CommandSanitizer(SecurityPolicy.moderate())
    if level == "permissive":
        return CommandSanitizer(SecurityPolicy.permissive())
    raise ValueError(level)


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------


class TestRelocatedEngine:
    """Smoke tests for the relocated core engine."""

    def test_core_import_resolves(self):
        """The relocated module is importable from its new location."""
        assert SecurityLevel.RESTRICTIVE.value == "restrictive"
        assert SecurityLevel.MODERATE.value == "moderate"
        assert SecurityLevel.PERMISSIVE.value == "permissive"

    def test_shell_tool_reexport_is_same_object(self):
        """parrot_tools.shell_tool.security re-exports the same class objects."""
        from parrot_tools.shell_tool.security import CommandSanitizer as ShimCS
        from parrot_tools.shell_tool.security import SecurityPolicy as ShimSP
        assert ShimCS is CommandSanitizer
        assert ShimSP is SecurityPolicy

    def test_shell_tool_shim_all_symbols(self):
        """All expected symbols are re-exported from the shim."""
        import parrot_tools.shell_tool.security as shim
        for name in (
            "SecurityLevel", "CommandVerdict", "ValidationResult",
            "CommandRule", "CommandSecurityError", "SecurityPolicy",
            "CommandSanitizer", "SecureShellMixin",
        ):
            assert hasattr(shim, name), f"missing {name!r} in shim"


class TestVerdictParity:
    """Verify RESTRICTIVE / MODERATE / PERMISSIVE produce identical verdicts before and after relocation."""

    def test_restrictive_denies_unlisted(self):
        """RESTRICTIVE policy denies any command not in the explicit allowlist."""
        pol = SecurityPolicy.restrictive(allowed_commands={"ls"})
        san = CommandSanitizer(pol)
        assert san.validate("rm -rf /").is_denied
        assert san.validate("ls").is_allowed

    def test_restrictive_only_allows_listed(self):
        pol = SecurityPolicy.restrictive(allowed_commands={"ls", "git"})
        san = CommandSanitizer(pol)
        assert san.validate("git status").is_allowed
        assert san.validate("curl http://example.com").is_denied

    def test_moderate_allows_safe_defaults(self):
        san = _make_sanitizer("moderate")
        assert san.validate("ls -la").is_allowed
        assert san.validate("grep foo bar.txt").is_allowed

    def test_moderate_denies_dangerous(self):
        san = _make_sanitizer("moderate")
        result = san.validate("sudo rm -rf /")
        assert result.is_denied

    def test_permissive_allows_most(self):
        san = _make_sanitizer("permissive")
        assert san.validate("cat /etc/hostname").is_allowed

    def test_permissive_still_denies_hardcoded(self):
        san = _make_sanitizer("permissive")
        # sudo is in the default denied set even for permissive
        result = san.validate("sudo bash")
        assert result.is_denied

    def test_validation_result_shape(self):
        """ValidationResult has the expected attributes."""
        pol = SecurityPolicy.restrictive(allowed_commands={"ls"})
        san = CommandSanitizer(pol)
        result = san.validate("ls")
        assert isinstance(result, ValidationResult)
        assert result.verdict == CommandVerdict.ALLOWED
        assert result.is_allowed
        assert not result.is_denied
        assert result.risk_score == 0.0

    def test_risk_score_nonzero_on_deny(self):
        pol = SecurityPolicy.restrictive(allowed_commands=set())
        san = CommandSanitizer(pol)
        result = san.validate("rm -rf /")
        assert result.is_denied
        assert result.risk_score > 0.0

    def test_validate_batch(self):
        san = _make_sanitizer("moderate")
        results = san.validate_batch(["ls", "sudo rm"])
        assert results[0].is_allowed
        assert results[1].is_denied


class TestSecureShellMixin:
    """SecureShellMixin stays in shell_tool and still works via re-export."""

    def test_mixin_validate_without_policy(self):
        from parrot_tools.shell_tool.security import SecureShellMixin, CommandVerdict

        class FakeShell(SecureShellMixin):
            pass

        shell = FakeShell()
        result = shell.validate_command("rm -rf /")
        assert result.verdict == CommandVerdict.ALLOWED  # no policy → all allowed

    def test_mixin_with_policy_denies(self):
        from parrot_tools.shell_tool.security import SecureShellMixin, CommandSecurityError

        class FakeShell(SecureShellMixin):
            pass

        shell = FakeShell()
        shell.set_security_policy(SecurityPolicy.restrictive(allowed_commands={"ls"}))
        with pytest.raises(CommandSecurityError):
            shell.assert_command_safe("rm -rf /")
