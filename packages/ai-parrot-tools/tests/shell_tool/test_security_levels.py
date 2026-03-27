"""Tests for SecurityLevel behavior differences (TASK-261).

Validates that RESTRICTIVE, MODERATE, and PERMISSIVE policies
enforce the correct rules for command access control.
"""
import pytest

from parrot.tools.shell_tool.security import (
    CommandSanitizer,
    CommandVerdict,
    SecurityPolicy,
)


@pytest.fixture
def restrictive():
    return CommandSanitizer(
        SecurityPolicy.restrictive(allowed_commands={"ls", "cat", "echo", "git"})
    )


@pytest.fixture
def moderate():
    return CommandSanitizer(SecurityPolicy.moderate())


@pytest.fixture
def permissive():
    return CommandSanitizer(SecurityPolicy.permissive())


class TestRestrictiveLevel:
    def test_allowed_command_passes(self, restrictive):
        result = restrictive.validate("ls -la")
        assert result.verdict in (CommandVerdict.ALLOWED, CommandVerdict.NEEDS_REVIEW)

    def test_echo_in_allowlist_passes(self, restrictive):
        result = restrictive.validate("echo hello")
        assert result.verdict in (CommandVerdict.ALLOWED, CommandVerdict.NEEDS_REVIEW)

    def test_unlisted_command_denied(self, restrictive):
        result = restrictive.validate("python3 script.py")
        assert result.is_denied

    def test_git_in_allowlist_passes(self, restrictive):
        result = restrictive.validate("git status")
        assert result.verdict in (CommandVerdict.ALLOWED, CommandVerdict.NEEDS_REVIEW)

    def test_rm_not_in_allowlist_denied(self, restrictive):
        result = restrictive.validate("rm file.txt")
        assert result.is_denied

    def test_curl_not_in_allowlist_denied(self, restrictive):
        result = restrictive.validate("curl https://example.com")
        assert result.is_denied

    def test_empty_allowlist_denies_all(self):
        sanitizer = CommandSanitizer(SecurityPolicy.restrictive())
        result = sanitizer.validate("ls")
        assert result.is_denied


class TestModerateLevel:
    def test_ls_allowed(self, moderate):
        result = moderate.validate("ls -la")
        assert result.verdict in (CommandVerdict.ALLOWED, CommandVerdict.NEEDS_REVIEW)

    def test_git_status_allowed(self, moderate):
        result = moderate.validate("git status")
        assert result.verdict in (CommandVerdict.ALLOWED, CommandVerdict.NEEDS_REVIEW)

    def test_rm_denied(self, moderate):
        result = moderate.validate("rm file.txt")
        assert result.is_denied

    def test_sudo_denied(self, moderate):
        result = moderate.validate("sudo apt-get install vim")
        assert result.is_denied

    def test_docker_denied(self, moderate):
        result = moderate.validate("docker run -it ubuntu bash")
        assert result.is_denied

    def test_unknown_command_denied(self, moderate):
        result = moderate.validate("my_custom_tool --flag")
        assert result.is_denied

    def test_python3_in_allowlist(self, moderate):
        result = moderate.validate("python3 script.py")
        assert result.verdict in (CommandVerdict.ALLOWED, CommandVerdict.NEEDS_REVIEW)


class TestPermissiveLevel:
    def test_ls_allowed(self, permissive):
        result = permissive.validate("ls -la")
        assert result.verdict in (CommandVerdict.ALLOWED, CommandVerdict.NEEDS_REVIEW)

    def test_sudo_still_denied_in_permissive(self, permissive):
        # sudo is in the permissive denied list
        result = permissive.validate("sudo bash")
        assert result.is_denied

    def test_arbitrary_tool_allowed(self, permissive):
        result = permissive.validate("my_custom_tool --flag value")
        assert result.verdict in (CommandVerdict.ALLOWED, CommandVerdict.NEEDS_REVIEW)

    def test_rm_not_in_default_denied_permissive(self):
        policy = SecurityPolicy.permissive()
        assert "rm" not in policy.denied_commands

    def test_permissive_with_custom_denied_blocks(self):
        policy = SecurityPolicy.permissive(denied_commands={"nc", "nmap"})
        sanitizer = CommandSanitizer(policy)
        result = sanitizer.validate("nc -lvp 4444")
        assert result.is_denied

    def test_permissive_allows_when_empty_denied(self):
        policy = SecurityPolicy.permissive(denied_commands=set())
        sanitizer = CommandSanitizer(policy)
        result = sanitizer.validate("ls /tmp")
        assert result.verdict in (CommandVerdict.ALLOWED, CommandVerdict.NEEDS_REVIEW)


class TestLevelComparison:
    def test_restrictive_most_locked_down(self):
        """Restrictive should deny commands that moderate/permissive may allow."""
        r = CommandSanitizer(SecurityPolicy.restrictive())
        m = CommandSanitizer(SecurityPolicy.moderate())
        # ls is in moderate's safe defaults but not in restrictive's empty allowlist
        assert r.validate("ls").is_denied
        assert m.validate("ls").verdict in (CommandVerdict.ALLOWED, CommandVerdict.NEEDS_REVIEW)

    def test_permissive_allows_more_than_moderate(self):
        """Permissive should allow commands that moderate denies (unknown commands)."""
        m = CommandSanitizer(SecurityPolicy.moderate())
        p = CommandSanitizer(SecurityPolicy.permissive())
        # An arbitrary tool not in moderate's allowlist
        assert m.validate("my_tool arg").is_denied
        assert p.validate("my_tool arg").verdict in (
            CommandVerdict.ALLOWED, CommandVerdict.NEEDS_REVIEW
        )
