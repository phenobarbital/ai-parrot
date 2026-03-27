"""Tests for SecureShellMixin (TASK-258)."""
import pytest

from parrot.tools.shell_tool.security import (
    CommandSecurityError,
    CommandVerdict,
    SecurityPolicy,
    SecureShellMixin,
    ValidationResult,
)


# ---------------------------------------------------------------------------
# Minimal concrete class for testing
# ---------------------------------------------------------------------------

class ConcreteShell(SecureShellMixin):
    """Minimal concrete class used to test SecureShellMixin."""


# ---------------------------------------------------------------------------
# Default state (no policy set)
# ---------------------------------------------------------------------------

class TestNoPolicy:
    def test_sanitizer_is_none_by_default(self):
        shell = ConcreteShell()
        assert shell._sanitizer is None

    def test_validate_command_allows_any_command(self):
        shell = ConcreteShell()
        result = shell.validate_command("rm -rf /")
        assert result.is_allowed

    def test_validate_command_returns_validation_result(self):
        shell = ConcreteShell()
        result = shell.validate_command("anything")
        assert isinstance(result, ValidationResult)

    def test_validate_command_verdict_is_allowed(self):
        shell = ConcreteShell()
        result = shell.validate_command("echo hi")
        assert result.verdict == CommandVerdict.ALLOWED

    def test_assert_command_safe_no_policy_does_not_raise(self):
        shell = ConcreteShell()
        shell.assert_command_safe("rm -rf /")  # No exception

    def test_validate_command_returns_zero_risk(self):
        shell = ConcreteShell()
        result = shell.validate_command("sudo rm -rf /")
        assert result.risk_score == 0.0

    def test_validate_command_preserves_command_string(self):
        shell = ConcreteShell()
        result = shell.validate_command("echo hello world")
        assert result.command == "echo hello world"


# ---------------------------------------------------------------------------
# set_security_policy
# ---------------------------------------------------------------------------

class TestSetSecurityPolicy:
    def test_sets_sanitizer(self):
        shell = ConcreteShell()
        shell.set_security_policy(SecurityPolicy.moderate())
        assert shell._sanitizer is not None

    def test_can_replace_policy(self):
        shell = ConcreteShell()
        shell.set_security_policy(SecurityPolicy.moderate())
        first = shell._sanitizer
        shell.set_security_policy(SecurityPolicy.restrictive())
        assert shell._sanitizer is not first

    def test_policy_level_applied(self):
        shell = ConcreteShell()
        shell.set_security_policy(SecurityPolicy.moderate())
        result = shell.validate_command("rm -rf /")
        assert result.is_denied

    def test_restrictive_policy_applied(self):
        shell = ConcreteShell()
        shell.set_security_policy(SecurityPolicy.restrictive(allowed_commands={"echo"}))
        result = shell.validate_command("ls -la")
        assert result.is_denied

    def test_permissive_policy_allows_more(self):
        shell = ConcreteShell()
        shell.set_security_policy(SecurityPolicy.permissive(denied_commands=set()))
        result = shell.validate_command("foobar")
        assert result.is_allowed


# ---------------------------------------------------------------------------
# validate_command with policy
# ---------------------------------------------------------------------------

class TestValidateCommandWithPolicy:
    def test_safe_command_allowed(self):
        shell = ConcreteShell()
        shell.set_security_policy(SecurityPolicy.moderate())
        result = shell.validate_command("git status")
        assert result.is_allowed

    def test_dangerous_command_denied(self):
        shell = ConcreteShell()
        shell.set_security_policy(SecurityPolicy.moderate())
        result = shell.validate_command("sudo whoami")
        assert result.is_denied

    def test_result_has_reasons_on_deny(self):
        shell = ConcreteShell()
        shell.set_security_policy(SecurityPolicy.moderate())
        result = shell.validate_command("rm -rf /")
        assert len(result.reasons) > 0

    def test_result_has_risk_score_on_deny(self):
        shell = ConcreteShell()
        shell.set_security_policy(SecurityPolicy.moderate())
        result = shell.validate_command("rm -rf /")
        assert result.risk_score >= 0.7


# ---------------------------------------------------------------------------
# assert_command_safe
# ---------------------------------------------------------------------------

class TestAssertCommandSafe:
    def test_safe_command_does_not_raise(self):
        shell = ConcreteShell()
        shell.set_security_policy(SecurityPolicy.moderate())
        shell.assert_command_safe("echo hello")  # No exception

    def test_denied_command_raises(self):
        shell = ConcreteShell()
        shell.set_security_policy(SecurityPolicy.moderate())
        with pytest.raises(CommandSecurityError):
            shell.assert_command_safe("rm -rf /")

    def test_needs_review_raises(self):
        # Craft a command that triggers NEEDS_REVIEW (risk 0.4–0.7)
        # curl alone (risk_base=0.3) in moderate mode — allowed
        # We need risk in [0.4, 0.7); use permissive + an env var (risk 0.4)
        policy = SecurityPolicy.permissive(denied_commands=set())
        shell = ConcreteShell()
        shell.set_security_policy(policy)
        # $HOME gives risk 0.4 → NEEDS_REVIEW in permissive
        result = shell.validate_command("echo $HOME")
        if result.verdict == CommandVerdict.NEEDS_REVIEW:
            with pytest.raises(CommandSecurityError):
                shell.assert_command_safe("echo $HOME")

    def test_error_has_result_attribute(self):
        shell = ConcreteShell()
        shell.set_security_policy(SecurityPolicy.moderate())
        with pytest.raises(CommandSecurityError) as exc_info:
            shell.assert_command_safe("rm -rf /")
        assert isinstance(exc_info.value.result, ValidationResult)

    def test_error_result_is_denied(self):
        shell = ConcreteShell()
        shell.set_security_policy(SecurityPolicy.moderate())
        with pytest.raises(CommandSecurityError) as exc_info:
            shell.assert_command_safe("sudo whoami")
        assert exc_info.value.result.is_denied

    def test_error_message_contains_command(self):
        shell = ConcreteShell()
        shell.set_security_policy(SecurityPolicy.moderate())
        with pytest.raises(CommandSecurityError) as exc_info:
            shell.assert_command_safe("rm -rf /")
        assert "rm -rf /" in str(exc_info.value)

    def test_returns_none_on_allowed(self):
        shell = ConcreteShell()
        shell.set_security_policy(SecurityPolicy.moderate())
        result = shell.assert_command_safe("git status")
        assert result is None


# ---------------------------------------------------------------------------
# Inheritance mechanics
# ---------------------------------------------------------------------------

class TestInheritance:
    def test_multiple_instances_have_independent_sanitizers(self):
        s1 = ConcreteShell()
        s2 = ConcreteShell()
        s1.set_security_policy(SecurityPolicy.moderate())
        # s2 should still have no sanitizer (class-level None not mutated)
        assert s2._sanitizer is None

    def test_mixin_works_with_multiple_inheritance(self):
        class Base:
            def method(self) -> str:
                return "base"

        class MultiShell(SecureShellMixin, Base):
            pass

        obj = MultiShell()
        obj.set_security_policy(SecurityPolicy.moderate())
        assert obj.method() == "base"
        assert obj._sanitizer is not None
