"""Shared fixtures for ShellTool security tests (TASK-261)."""
import pytest

from parrot.tools.shell_tool.security import (
    CommandSanitizer,
    SecurityPolicy,
)


@pytest.fixture
def restrictive_policy():
    return SecurityPolicy.restrictive(allowed_commands={"ls", "cat", "grep", "echo", "git"})


@pytest.fixture
def moderate_policy():
    return SecurityPolicy.moderate()


@pytest.fixture
def permissive_policy():
    return SecurityPolicy.permissive()


@pytest.fixture
def restrictive_sanitizer(restrictive_policy):
    return CommandSanitizer(restrictive_policy)


@pytest.fixture
def moderate_sanitizer(moderate_policy):
    return CommandSanitizer(moderate_policy)


@pytest.fixture
def permissive_sanitizer(permissive_policy):
    return CommandSanitizer(permissive_policy)


@pytest.fixture
def sandbox_policy(tmp_path):
    return SecurityPolicy.moderate(sandbox_dir=str(tmp_path))


@pytest.fixture
def sandbox_sanitizer(sandbox_policy):
    return CommandSanitizer(sandbox_policy)


@pytest.fixture
def safe_commands():
    return [
        "echo hello",
        "ls -la",
        "git status",
        "cat README.md",
        "grep -r pattern .",
    ]


@pytest.fixture
def dangerous_commands():
    return [
        "rm -rf /",
        "sudo bash",
        "dd if=/dev/zero of=/dev/sda",
        "$(cat /etc/passwd)",
        "echo hi; rm -rf /",
    ]
