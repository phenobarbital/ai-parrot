"""Unit tests for the stdlib-only test runner registry (FEAT-709 M1)."""

from __future__ import annotations

import subprocess
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
        (["npm", "test"], ["vitest", "run"]),
        (["npm", "run", "test", "tests/a.test.ts"], ["vitest", "run", "tests/a.test.ts"]),
        (["npm", "exec", "vitest", "run"], ["vitest", "run"]),
        (["yarn", "test"], ["vitest", "run"]),
        (["yarn", "run", "test"], ["vitest", "run"]),
    ],
)
def test_normalize_launcher_argv(argv, expected):
    """Known launcher chains normalize to the runner command."""
    assert normalize_launcher_argv(argv) == expected


def test_registry_normalize_matches_adapter_resolution():
    """`normalize()` yields the argv the resolved adapter actually parses (operands/is_broad)."""
    registry = RunnerRegistry({}, {})
    normalized = registry.normalize(["npm", "test", "--", "tests/a.test.ts"])
    adapter = registry.adapter_for_argv(normalized)
    assert adapter is not None and adapter.kind == "vitest"
    assert adapter.operands(normalized) is not None
    assert registry.normalize(normalized) == normalized


def test_normalize_launcher_argv_respects_disabled_pnpm_test_mapping():
    """A configured non-vitest test script remains unchanged."""
    assert normalize_launcher_argv(["pnpm", "test"], pnpm_test_is_vitest=False) == ["pnpm", "test"]
    assert normalize_launcher_argv(["npm", "test"], pnpm_test_is_vitest=False) == ["npm", "test"]
    assert normalize_launcher_argv(["yarn", "run", "test"], pnpm_test_is_vitest=False) == ["yarn", "run", "test"]


def test_registry_uses_injected_adapter_and_validates_configured_tiers():
    """Injected adapters support argv lookup, settings copies, and tier narrowing."""
    registry = RunnerRegistry({"fake": FakeAdapter()}, {"fake": {"tiers": "task", "timeout_s": "7"}})
    assert registry.adapter_for_argv(["fake-test", "test_a"]).kind == "fake"
    assert registry.settings_for("fake") == {"tiers": "task", "timeout_s": "7"}
    assert registry.tiers_for("fake") == frozenset({"task"})
    assert registry.timeout_for("fake") == 7
    assert "fake-test" in registry.binaries


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


def _git(repo: Path, *args: str) -> None:
    """Run git in ``repo`` with a fixed identity so commits work on any CI host."""
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _repo_with_commit(tmp_path: Path, config: str | None) -> Path:
    """Create a git repo whose single commit holds ``config`` as the runners TOML (or no TOML)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "README").write_text("x\n")
    if config is not None:
        (repo / ".parrot").mkdir()
        (repo / ".parrot" / "test_runners.toml").write_text(config)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _plant_extension(tmp_path: Path, monkeypatch, repo: Path) -> Path:
    """Write a working-tree-only TOML naming an extension whose import leaves a marker file."""
    marker = tmp_path / "imported.marker"
    module_dir = tmp_path / "planted"
    module_dir.mkdir()
    (module_dir / "planted_runner_ext.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\nclass Adapter:\n    pass\n"
    )
    monkeypatch.syspath_prepend(str(module_dir))
    monkeypatch.delitem(sys.modules, "planted_runner_ext", raising=False)
    (repo / ".parrot").mkdir(exist_ok=True)
    (repo / ".parrot" / "test_runners.toml").write_text("[extensions]\nplanted = 'planted_runner_ext:Adapter'\n")
    return marker


def test_load_registry_from_ref_ignores_working_tree_toml(tmp_path, monkeypatch):
    """With ``ref``, the committed TOML is used and a working-tree-only extension is never imported."""
    repo = _repo_with_commit(tmp_path, "[runners.pytest]\ntimeout_s = 7\n")
    marker = _plant_extension(tmp_path, monkeypatch, repo)

    registry = load_registry(repo, ref="HEAD")

    assert registry.timeout_for("pytest") == 7
    assert not marker.exists()
    assert "planted_runner_ext" not in sys.modules


def test_load_registry_from_ref_without_config_is_empty(tmp_path, monkeypatch):
    """A ref without the TOML yields built-ins only, even when the working tree has one."""
    repo = _repo_with_commit(tmp_path, None)
    marker = _plant_extension(tmp_path, monkeypatch, repo)

    registry = load_registry(repo, ref="HEAD")

    assert registry.settings_for("pytest") == {}
    assert registry.adapter_for_argv(["pytest", "a.py"]) is not None
    assert not marker.exists()


@pytest.mark.parametrize("ref", ["nope", "--output=x", ""])
def test_load_registry_rejects_bad_ref(tmp_path, ref):
    """An unresolvable, empty or option-looking ref fails closed instead of reading the working tree."""
    repo = _repo_with_commit(tmp_path, None)
    with pytest.raises(ValueError):
        load_registry(repo, ref=ref)


@pytest.mark.parametrize("cwd", ["/etc", "../x", "a/../../x", ".."])
def test_load_registry_rejects_escaping_cwd(tmp_path, cwd):
    """A runner cwd that is absolute or leaves the worktree is rejected at load time."""
    config = tmp_path / ".parrot" / "test_runners.toml"
    config.parent.mkdir()
    config.write_text(f"[runners.vitest]\ncwd = {cwd!r}\n")
    with pytest.raises(ValueError, match="cwd must stay inside the worktree"):
        load_registry(tmp_path)


def test_load_registry_accepts_nested_cwd(tmp_path):
    """A relative cwd inside the worktree (even with a harmless ``..``) still loads."""
    config = tmp_path / ".parrot" / "test_runners.toml"
    config.parent.mkdir()
    config.write_text("[runners.vitest]\ncwd = 'packages/x/../ui'\n")
    assert load_registry(tmp_path).settings_for("vitest")["cwd"] == "packages/x/../ui"
