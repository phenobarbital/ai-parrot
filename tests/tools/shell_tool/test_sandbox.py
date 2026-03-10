"""Tests for path sandbox enforcement (TASK-261).

Tests CommandSanitizer Layer 5: path token validation against sandbox_dir.
"""
import pytest

from parrot.tools.shell_tool.security import (
    CommandSanitizer,
    SecurityPolicy,
)


@pytest.fixture
def sandbox_dir(tmp_path):
    return tmp_path


@pytest.fixture
def sandbox_sanitizer(sandbox_dir):
    policy = SecurityPolicy.moderate(sandbox_dir=str(sandbox_dir))
    return CommandSanitizer(policy)


class TestSandboxEnforcement:
    def test_path_inside_sandbox_allowed(self, sandbox_sanitizer, sandbox_dir):
        target = str(sandbox_dir / "data.txt")
        result = sandbox_sanitizer.validate(f"cat {target}")
        assert not any("resolves outside sandbox" in r for r in result.reasons)

    def test_path_outside_sandbox_denied(self, sandbox_sanitizer):
        result = sandbox_sanitizer.validate("cat /etc/passwd")
        assert result.is_denied

    def test_path_traversal_outside_denied(self, sandbox_sanitizer, sandbox_dir):
        result = sandbox_sanitizer.validate(f"cat {sandbox_dir}/../../../etc/shadow")
        assert result.is_denied

    def test_relative_traversal_outside_denied(self, sandbox_sanitizer):
        result = sandbox_sanitizer.validate("cat ../../../etc/shadow")
        assert result.is_denied

    def test_url_ignored_by_sandbox(self, sandbox_sanitizer):
        # URLs (containing ://) must not be treated as filesystem paths
        result = sandbox_sanitizer.validate("curl https://example.com/data")
        assert not any("resolves outside sandbox" in r for r in result.reasons)

    def test_flags_not_treated_as_paths(self, sandbox_sanitizer):
        # Flags like -la must not trigger path sandbox check
        result = sandbox_sanitizer.validate("ls -la")
        assert not any("resolves outside sandbox" in r for r in result.reasons)

    def test_no_sandbox_does_not_restrict(self):
        policy = SecurityPolicy.moderate()  # No sandbox_dir
        sanitizer = CommandSanitizer(policy)
        result = sanitizer.validate("cat /etc/hosts")
        # No sandbox → no sandbox-related reasons
        assert not any("resolves outside sandbox" in r for r in result.reasons)

    def test_sandbox_dir_set_in_policy(self, sandbox_dir):
        policy = SecurityPolicy.moderate(sandbox_dir=str(sandbox_dir))
        assert policy.sandbox_dir == str(sandbox_dir)

    def test_sandbox_resolved_at_init(self, sandbox_dir):
        policy = SecurityPolicy.moderate(sandbox_dir=str(sandbox_dir))
        sanitizer = CommandSanitizer(policy)
        assert sanitizer._sandbox_resolved is not None
        assert sanitizer._sandbox_resolved == sandbox_dir.resolve()

    def test_restrictive_sandbox(self, sandbox_dir):
        policy = SecurityPolicy.restrictive(
            allowed_commands={"cat"},
            sandbox_dir=str(sandbox_dir),
        )
        sanitizer = CommandSanitizer(policy)
        outside = "/etc/passwd"
        result = sanitizer.validate(f"cat {outside}")
        assert result.is_denied


class TestValidatePath:
    """Tests for CommandSanitizer.validate_path() used by file actions."""

    def test_safe_path_allowed(self, sandbox_dir):
        policy = SecurityPolicy.moderate(sandbox_dir=str(sandbox_dir))
        sanitizer = CommandSanitizer(policy)
        safe = str(sandbox_dir / "safe.txt")
        result = sanitizer.validate_path(safe)
        assert result.is_allowed

    def test_outside_sandbox_denied(self, sandbox_dir):
        policy = SecurityPolicy.moderate(sandbox_dir=str(sandbox_dir))
        sanitizer = CommandSanitizer(policy)
        result = sanitizer.validate_path("/etc/passwd")
        assert result.is_denied

    def test_sensitive_path_detected(self):
        policy = SecurityPolicy.moderate()
        sanitizer = CommandSanitizer(policy)
        result = sanitizer.validate_path("/etc/passwd")
        assert not result.is_allowed

    def test_kernel_fs_denied(self):
        policy = SecurityPolicy.moderate()
        sanitizer = CommandSanitizer(policy)
        result = sanitizer.validate_path("/proc/1/maps")
        assert not result.is_allowed

    def test_normal_path_no_sandbox_allowed(self):
        policy = SecurityPolicy.moderate()  # No sandbox
        sanitizer = CommandSanitizer(policy)
        result = sanitizer.validate_path("/tmp/workdir/output.txt")
        assert result.is_allowed
