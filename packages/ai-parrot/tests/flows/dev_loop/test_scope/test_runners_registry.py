"""Unit tests for the stdlib-only test runner registry (FEAT-709 M1)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope.runners import RunnerRegistry, load_registry, normalize_launcher_argv


class FakeAdapter:
    """Minimal protocol-compliant adapter for registry tests."""

    kind = "fake"
    binaries = ("fake-test",)
    default_tiers = frozenset({"task", "merge"})
    report_format = "exit-code"

    def matches(self, argv):
        return bool(argv) and argv[0] == "fake-test"

    def operands(self, argv):
        return list(argv[1:])

    def is_broad(self, argv, *, worktree):
        return False

    def mirror_targets(self, changed, *, worktree, settings):
        return []

    def distribution_of(self, target, *, settings):
        return "root"

    def invocation(self, targets, *, distribution, worktree, settings, policy, report_path):
        raise AssertionError("not exercised")

    def parse_report(self, *, report_path, exit_code, stdout, stderr, duration_s, timed_out, suite):
        raise AssertionError("not exercised")

    def validate_settings(self, settings, *, worktree):
        return []


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["PYTHONPATH=x", "uv", "run", "--no-sync", "pytest", "a.py"], ["pytest", "a.py"]),
        (["python", "-m", "pytest", "a.py"], ["pytest", "a.py"]),
        (["pnpm", "exec", "vitest", "run"], ["vitest", "run"]),
        (["pnpm", "test"], ["vitest", "run"]),
        (["npx", "vitest"], ["vitest"]),
    ],
)
def test_normalize_launcher_argv(argv, expected):
    """Known launcher chains normalize to the runner command."""
    assert normalize_launcher_argv(argv) == expected


def test_normalize_launcher_argv_respects_disabled_pnpm_test_mapping():
    """A configured non-vitest test script remains unchanged."""
    assert normalize_launcher_argv(["pnpm", "test"], pnpm_test_is_vitest=False) == ["pnpm", "test"]


def test_registry_uses_injected_adapter_and_validates_configured_tiers():
    """Injected adapters support argv lookup, settings copies, and tier narrowing."""
    registry = RunnerRegistry({"fake": FakeAdapter()}, {"fake": {"tiers": "task", "timeout_s": "7"}})
    assert registry.adapter_for_argv(["fake-test", "test_a"]).kind == "fake"
    assert registry.settings_for("fake") == {"tiers": "task", "timeout_s": "7"}
    assert registry.tiers_for("fake") == frozenset({"task"})
    assert registry.timeout_for("fake") == 7
    assert registry.binaries == ("fake-test",)


def test_registry_rejects_tier_outside_adapter_support():
    """Configured tiers cannot expand an adapter's supported tiers."""
    registry = RunnerRegistry({"fake": FakeAdapter()}, {"fake": {"tiers": "feature"}})
    with pytest.raises(ValueError, match="feature"):
        registry.tiers_for("fake")


def test_load_registry_reads_toml_settings_and_extension(tmp_path, monkeypatch):
    """TOML settings and protocol-compliant extension classes are loaded fail-closed."""
    module = tmp_path / "fake_runner_extension.py"
    module.write_text(
        "from test_runners_registry import FakeAdapter\nclass Adapter(FakeAdapter):\n    kind = 'extension'\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setitem(sys.modules, "test_runners_registry", sys.modules[__name__])
    config = tmp_path / ".parrot" / "test_runners.toml"
    config.parent.mkdir()
    config.write_text(
        "[runners.vitest]\ntest_script = false\ntimeout_s = 45\ntiers = ['task', 'merge']\n"
        "[runners.extension]\ntiers = ['task']\n[extensions]\nextension = 'fake_runner_extension:Adapter'\n"
    )

    registry = load_registry(tmp_path)
    assert registry.settings_for("vitest")["test_script"] == "False"
    assert registry.timeout_for("vitest") == 45
    assert registry.adapter_for_kind("extension").kind == "extension"
    assert registry.tiers_for("extension") == frozenset({"task"})
    assert registry.adapter_for_argv(["pnpm", "test"]) is None


@pytest.mark.parametrize(
    "config",
    [
        "[runners.pytest\n",
        "[unknown]\nvalue = 1\n",
        "[runners.pytest]\ntiers = ['invalid']\n",
        "[extensions]\nmissing = 'missing_runner_module:Adapter'\n",
        "[extensions]\nwrong = 'test_runners_registry:object'\n",
    ],
)
def test_load_registry_fails_closed_for_invalid_configuration(tmp_path, config):
    """Malformed TOML, invalid sections, tiers, and extensions name the config path."""
    path = tmp_path / ".parrot" / "test_runners.toml"
    path.parent.mkdir()
    path.write_text(config)
    with pytest.raises(ValueError, match=r"\.parrot/test_runners\.toml"):
        load_registry(tmp_path)
