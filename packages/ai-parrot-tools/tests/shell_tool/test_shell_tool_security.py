"""Integration tests for ShellTool security (TASK-261).

Tests ShellTool's security integration: default policy, policy injection,
command validation before execution, plan mode validation, and backward
compatibility with security_policy=None.
"""
import pytest

from parrot.tools.shell_tool import (
    ShellTool,
    CommandSecurityError,
    SecurityPolicy,
    SecurityLevel,
    SecureShellMixin,
)
from parrot.tools.shell_tool.security import CommandSanitizer


class TestShellToolDefaultPolicy:
    def test_default_policy_is_moderate(self):
        tool = ShellTool()
        assert tool._sanitizer is not None
        assert tool._sanitizer.policy.level == SecurityLevel.MODERATE

    def test_inherits_secure_shell_mixin(self):
        tool = ShellTool()
        assert isinstance(tool, SecureShellMixin)

    def test_has_sanitizer_attribute(self):
        tool = ShellTool()
        assert isinstance(tool._sanitizer, CommandSanitizer)

    def test_set_security_policy_updates_sanitizer(self):
        tool = ShellTool()
        new_policy = SecurityPolicy.restrictive(allowed_commands={"ls"})
        tool.set_security_policy(new_policy)
        assert tool._sanitizer.policy.level == SecurityLevel.RESTRICTIVE


class TestShellToolPolicyInjection:
    def test_custom_moderate_policy_accepted(self):
        policy = SecurityPolicy.moderate(allowed_commands={"my_tool"})
        tool = ShellTool(security_policy=policy)
        assert tool._sanitizer.policy is policy

    def test_restrictive_policy_accepted(self):
        policy = SecurityPolicy.restrictive(allowed_commands={"ls"})
        tool = ShellTool(security_policy=policy)
        assert tool._sanitizer.policy.level == SecurityLevel.RESTRICTIVE

    def test_permissive_policy_accepted(self):
        policy = SecurityPolicy.permissive()
        tool = ShellTool(security_policy=policy)
        assert tool._sanitizer.policy.level == SecurityLevel.PERMISSIVE

    def test_none_policy_disables_security(self):
        tool = ShellTool(security_policy=None)
        assert tool._sanitizer is None


class TestShellToolCommandValidation:
    def test_assert_command_safe_passes_for_allowed(self):
        tool = ShellTool()
        # echo is in moderate's safe defaults — should not raise
        tool.assert_command_safe("echo hello")

    def test_assert_command_safe_raises_for_denied(self):
        tool = ShellTool()
        with pytest.raises(CommandSecurityError) as exc_info:
            tool.assert_command_safe("rm -rf /")
        assert exc_info.value.result.is_denied

    def test_error_includes_result(self):
        tool = ShellTool()
        with pytest.raises(CommandSecurityError) as exc_info:
            tool.assert_command_safe("sudo bash")
        assert exc_info.value.result is not None
        assert exc_info.value.result.is_denied

    def test_validate_command_returns_result(self):
        tool = ShellTool()
        result = tool.validate_command("echo hello")
        assert result is not None

    def test_validate_command_no_policy_returns_allowed(self):
        tool = ShellTool(security_policy=None)
        result = tool.validate_command("rm -rf /")
        assert result.is_allowed


class TestShellToolBackwardCompatibility:
    def test_no_policy_allows_all_commands(self):
        tool = ShellTool(security_policy=None)
        # Must not raise even for "dangerous" commands
        tool.assert_command_safe("rm -rf /")
        tool.assert_command_safe("sudo bash")
        tool.assert_command_safe("dd if=/dev/zero of=/dev/sda")

    def test_no_policy_sanitizer_is_none(self):
        tool = ShellTool(security_policy=None)
        assert tool._sanitizer is None


class TestShellToolExecuteValidation:
    """Tests that ShellTool._execute() validates commands before dispatch."""

    @pytest.mark.asyncio
    async def test_execute_raises_for_rm_rf(self):
        """Denied commands raise CommandSecurityError before subprocess is invoked."""
        tool = ShellTool()
        with pytest.raises(CommandSecurityError) as exc_info:
            await tool._execute(command="rm -rf /")
        assert exc_info.value.result.is_denied

    @pytest.mark.asyncio
    async def test_execute_plan_raises_for_dangerous_step(self):
        """Dangerous plan steps raise CommandSecurityError."""
        tool = ShellTool()
        plan = [{"type": "run_command", "command": "sudo bash"}]
        with pytest.raises(CommandSecurityError) as exc_info:
            await tool._execute(plan=plan)
        assert exc_info.value.result.is_denied

    def test_allowed_command_does_not_raise(self):
        """echo is in moderate allowlist — assert_command_safe must not raise."""
        tool = ShellTool()
        # Must not raise
        tool.assert_command_safe("echo hello")

    def test_plan_safe_command_does_not_raise(self):
        """git status passes validation before any subprocess is launched."""
        tool = ShellTool()
        tool.assert_command_safe("git status")

    def test_no_policy_allows_any_command(self):
        """With security_policy=None, assert_command_safe never raises."""
        tool = ShellTool(security_policy=None)
        tool.assert_command_safe("rm -rf /")
        tool.assert_command_safe("sudo bash")
        tool.assert_command_safe("dd if=/dev/zero of=/dev/sda")

    @pytest.mark.asyncio
    async def test_execute_empty_command_returns_ok(self):
        """Empty command list returns ok=True with no results."""
        tool = ShellTool()
        result = await tool._execute()
        assert result["ok"] is True
        assert result["results"] == []


class TestShellToolOutputTruncation:
    """Tests that output truncation configuration is wired correctly."""

    def test_policy_max_output_bytes_accessible(self):
        """Policy output limits are reachable from the sanitizer."""
        policy = SecurityPolicy.moderate()
        tool = ShellTool(security_policy=policy)
        assert tool._sanitizer.policy.max_output_bytes == 1_048_576

    def test_policy_max_stderr_bytes_accessible(self):
        policy = SecurityPolicy.moderate()
        tool = ShellTool(security_policy=policy)
        assert tool._sanitizer.policy.max_stderr_bytes == 262_144

    def test_custom_output_limit_stored(self):
        policy = SecurityPolicy.moderate()
        policy.max_output_bytes = 512
        tool = ShellTool(security_policy=policy)
        assert tool._sanitizer.policy.max_output_bytes == 512

    def test_no_policy_no_sanitizer(self):
        """When security is disabled, _sanitizer is None (no truncation logic)."""
        tool = ShellTool(security_policy=None)
        assert tool._sanitizer is None
