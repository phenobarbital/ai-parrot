"""Tests for ShellTool security data models (TASK-255)."""
import pytest
from dataclasses import FrozenInstanceError

from parrot.tools.shell_tool.security import (
    CommandRule,
    CommandSecurityError,
    CommandVerdict,
    SecurityLevel,
    ValidationResult,
)


class TestSecurityLevel:
    def test_has_restrictive(self):
        assert SecurityLevel.RESTRICTIVE == "restrictive"

    def test_has_moderate(self):
        assert SecurityLevel.MODERATE == "moderate"

    def test_has_permissive(self):
        assert SecurityLevel.PERMISSIVE == "permissive"

    def test_is_str_enum(self):
        assert isinstance(SecurityLevel.MODERATE, str)

    def test_three_members(self):
        assert len(list(SecurityLevel)) == 3


class TestCommandVerdict:
    def test_has_allowed(self):
        assert CommandVerdict.ALLOWED == "allowed"

    def test_has_denied(self):
        assert CommandVerdict.DENIED == "denied"

    def test_has_needs_review(self):
        assert CommandVerdict.NEEDS_REVIEW == "needs_review"

    def test_is_str_enum(self):
        assert isinstance(CommandVerdict.ALLOWED, str)

    def test_three_members(self):
        assert len(list(CommandVerdict)) == 3


class TestValidationResult:
    def test_is_allowed_true(self):
        r = ValidationResult(verdict=CommandVerdict.ALLOWED, command="echo hi")
        assert r.is_allowed is True
        assert r.is_denied is False

    def test_is_denied_true(self):
        r = ValidationResult(verdict=CommandVerdict.DENIED, command="rm -rf /")
        assert r.is_denied is True
        assert r.is_allowed is False

    def test_needs_review_not_allowed_not_denied(self):
        r = ValidationResult(verdict=CommandVerdict.NEEDS_REVIEW, command="curl url")
        assert r.is_allowed is False
        assert r.is_denied is False

    def test_default_fields(self):
        r = ValidationResult(verdict=CommandVerdict.ALLOWED, command="ls")
        assert r.reasons == ()
        assert r.sanitized_command is None
        assert r.risk_score == 0.0

    def test_reasons_tuple(self):
        r = ValidationResult(
            verdict=CommandVerdict.DENIED,
            command="rm",
            reasons=("reason1", "reason2"),
        )
        assert r.reasons == ("reason1", "reason2")

    def test_risk_score_stored(self):
        r = ValidationResult(verdict=CommandVerdict.DENIED, command="rm", risk_score=0.9)
        assert r.risk_score == 0.9

    def test_str_allowed(self):
        r = ValidationResult(verdict=CommandVerdict.ALLOWED, command="git status")
        text = str(r)
        assert "✅" in text
        assert "allowed" in text
        assert "git status" in text
        assert "OK" in text

    def test_str_denied_with_reasons(self):
        r = ValidationResult(
            verdict=CommandVerdict.DENIED,
            command="rm -rf /",
            reasons=("command 'rm' is denied",),
            risk_score=0.9,
        )
        text = str(r)
        assert "❌" in text
        assert "denied" in text
        assert "rm -rf /" in text
        assert "command 'rm' is denied" in text

    def test_str_multiple_reasons_semicolon(self):
        r = ValidationResult(
            verdict=CommandVerdict.DENIED,
            command="x",
            reasons=("reason A", "reason B"),
        )
        assert "; " in str(r)

    def test_is_frozen(self):
        r = ValidationResult(verdict=CommandVerdict.ALLOWED, command="ls")
        with pytest.raises((FrozenInstanceError, AttributeError)):
            r.risk_score = 0.5  # type: ignore[misc]


class TestCommandRule:
    def test_required_name(self):
        rule = CommandRule(name="curl")
        assert rule.name == "curl"

    def test_default_allowed_args_none(self):
        rule = CommandRule(name="git")
        assert rule.allowed_args is None

    def test_default_denied_args_empty_set(self):
        rule = CommandRule(name="git")
        assert rule.denied_args == set()

    def test_default_denied_patterns_empty_list(self):
        rule = CommandRule(name="git")
        assert rule.denied_patterns == []

    def test_default_max_args_none(self):
        rule = CommandRule(name="git")
        assert rule.max_args is None

    def test_default_require_absolute_path_false(self):
        rule = CommandRule(name="git")
        assert rule.require_absolute_path is False

    def test_default_sandbox_paths_none(self):
        rule = CommandRule(name="git")
        assert rule.sandbox_paths is None

    def test_default_allow_pipe_false(self):
        rule = CommandRule(name="git")
        assert rule.allow_pipe is False

    def test_default_allow_redirect_false(self):
        rule = CommandRule(name="git")
        assert rule.allow_redirect is False

    def test_default_risk_base_zero(self):
        rule = CommandRule(name="git")
        assert rule.risk_base == 0.0

    def test_custom_values(self):
        rule = CommandRule(
            name="find",
            denied_args={"-exec", "-delete"},
            risk_base=0.2,
            max_args=10,
        )
        assert rule.denied_args == {"-exec", "-delete"}
        assert rule.risk_base == 0.2
        assert rule.max_args == 10

    def test_mutable_defaults_not_shared(self):
        r1 = CommandRule(name="a")
        r2 = CommandRule(name="b")
        r1.denied_args.add("--foo")
        assert "--foo" not in r2.denied_args


class TestCommandSecurityError:
    def test_is_exception(self):
        result = ValidationResult(verdict=CommandVerdict.DENIED, command="rm")
        exc = CommandSecurityError("denied", result=result)
        assert isinstance(exc, Exception)

    def test_result_attribute(self):
        result = ValidationResult(verdict=CommandVerdict.DENIED, command="rm", risk_score=0.9)
        exc = CommandSecurityError("Command denied: 'rm'", result=result)
        assert exc.result is result

    def test_message(self):
        result = ValidationResult(verdict=CommandVerdict.DENIED, command="rm")
        exc = CommandSecurityError("blocked", result=result)
        assert str(exc) == "blocked"

    def test_result_accessible_after_raise(self):
        result = ValidationResult(
            verdict=CommandVerdict.DENIED,
            command="rm -rf /",
            reasons=("denied",),
            risk_score=0.9,
        )
        with pytest.raises(CommandSecurityError) as exc_info:
            raise CommandSecurityError("denied", result=result)
        assert exc_info.value.result.risk_score == 0.9
        assert exc_info.value.result.command == "rm -rf /"
