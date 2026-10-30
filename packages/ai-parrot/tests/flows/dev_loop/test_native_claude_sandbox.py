"""Deterministic FEAT-768 native policy tests (no Claude process, no network)."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from parrot.flows.dev_loop import native_claude_sandbox as native
from parrot.flows.dev_loop import worktree_environment as policy


@pytest.fixture(autouse=True)
def scratch_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep the scratch root inside tmp_path."""
    root = tmp_path / "claude-scratch"
    monkeypatch.setattr(policy, "CLAUDE_SCRATCH_ROOT", root)
    return root


@pytest.fixture
def linked(tmp_path: Path) -> tuple[Path, Path]:
    """Return a linked feature worktree and its primary checkout."""
    main = tmp_path / "main"
    git_dir = main / ".git"
    feature_admin = git_dir / "worktrees" / "feat"
    pool_admin = git_dir / "worktrees" / "pool"
    for admin in (feature_admin, pool_admin):
        admin.mkdir(parents=True)
        (admin / "commondir").write_text("../..\n")
    feature = main / ".claude" / "worktrees" / "feat"
    pool = main / ".claude" / "worktrees" / "pool"
    for worktree, admin in ((feature, feature_admin), (pool, pool_admin)):
        worktree.mkdir(parents=True)
        (worktree / ".git").write_text(f"gitdir: {admin}\n")
    environment = main / ".venv"
    environment.mkdir()
    (environment / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (feature / ".venv").symlink_to(environment, target_is_directory=True)
    (main / ".parrot" / "ledger").mkdir(parents=True)
    (feature / "packages" / "x" / "src").mkdir(parents=True)
    return feature, main


def test_native_settings_reject_widening_inputs(tmp_path: Path) -> None:
    """Malformed roots and invalid domains cannot produce a permissive launch."""
    with pytest.raises(ValueError):
        native.native_sandbox_settings(tmp_path)
    with pytest.raises(ValueError):
        native.validate_allowed_domains(["https://github.com"])


def test_settings_are_strict_and_explicit(linked: tuple[Path, Path]) -> None:
    """All security keys are present with strict values."""
    feature, main = linked
    settings = native.native_sandbox_settings(feature, allowed_domains=["GitHub.COM.", "github.com"])
    sandbox = settings["sandbox"]
    assert sandbox["enabled"] is True
    assert sandbox["failIfUnavailable"] is True
    assert sandbox["allowUnsandboxedCommands"] is False
    assert sandbox["excludedCommands"] == []
    assert sandbox["allowNestedUserNamespaces"] is False
    assert sandbox["network"] == {
        "allowAllUnixSockets": False,
        "strictAllowlist": True,
        "allowedDomains": ["github.com"],
    }
    assert str(main) not in sandbox["filesystem"]["allowWrite"]
    deny = sandbox["filesystem"]["denyWrite"]
    worktree = feature
    controls = worktree / "packages" / "ai-parrot" / "src" / "parrot" / "flows" / "dev_loop"
    for control in (
        controls / "native_claude_sandbox.py",
        controls / "worktree_environment.py",
        worktree / ".claude" / "settings.json",
        worktree / ".claude" / "settings.local.json",
        worktree / ".claude" / "agents",
    ):
        assert str(control.resolve()) in deny, control
    assert settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"].endswith(" || exit 2")


@pytest.fixture(autouse=True)
def _clean_sandbox_mode_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never inherit a developer's mode/marker or a cached probe result into a test."""
    monkeypatch.delenv(native.MODE_ENV, raising=False)
    monkeypatch.delenv(native.DEGRADED_ENV, raising=False)
    monkeypatch.setattr(native, "_probe_cache", None)


def test_sandbox_mode_resolution_prefers_environment_then_pyproject(
    linked: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    feature, _main = linked
    assert native.resolve_sandbox_mode(feature) == "required"  # no pyproject, no env

    (feature / "pyproject.toml").write_text("[tool.parrot.sdd]\nsandbox = 'preferred'\n", encoding="utf-8")
    assert native.resolve_sandbox_mode(feature) == "preferred"
    monkeypatch.setenv(native.MODE_ENV, "   ")  # empty/whitespace is "unset"
    assert native.resolve_sandbox_mode(feature) == "preferred"
    monkeypatch.setenv(native.MODE_ENV, " OFF ")
    assert native.resolve_sandbox_mode(feature) == "off"
    monkeypatch.setenv(native.MODE_ENV, "invalid")
    with pytest.raises(ValueError, match=native.MODE_ENV):
        native.resolve_sandbox_mode(feature)


@pytest.mark.parametrize(
    ("content", "match"),
    [
        ("[tool.parrot.sdd]\nsandbox = 'off'\n", "may only be set through"),
        ("[tool.parrot.sdd]\nsandbox = 'unsafe'\n", "pyproject.toml"),
        ("[tool.parrot.sdd]\nsandbox = 3\n", "pyproject.toml"),
        ("[tool.parrot]\nsdd = 'x'\n[tool.parrot.sdd]\n", "malformed"),
        ("[tool]\nparrot = 1\n", r"\[tool\.parrot\] is not a table"),
    ],
)
def test_sandbox_mode_pyproject_errors(linked: tuple[Path, Path], content: str, match: str) -> None:
    """A repository may choose required/preferred only; anything else is an error naming the source."""
    feature, _main = linked
    (feature / "pyproject.toml").write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        native.resolve_sandbox_mode(feature)


def test_settings_can_omit_native_sandbox(linked: tuple[Path, Path]) -> None:
    feature, _main = linked

    settings = native.native_sandbox_settings(feature, include_sandbox=False)

    assert "sandbox" not in settings
    assert settings["hooks"]["PreToolUse"]


def test_plan_native_launch_degrades_or_refuses(linked: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    feature, _main = linked
    monkeypatch.setattr(native, "native_sandbox_available", lambda: (False, "probe failed"))

    (feature / "pyproject.toml").write_text("[tool.parrot.sdd]\nsandbox = 'preferred'\n", encoding="utf-8")
    mode, degraded, reason, settings = native.plan_native_launch(feature)
    assert (mode, degraded, reason) == ("preferred", True, "probe failed")
    assert "sandbox" not in settings

    (feature / "pyproject.toml").write_text("[tool.parrot.sdd]\nsandbox = 'required'\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="probe failed"):
        native.plan_native_launch(feature)


def test_plan_native_launch_strict_when_available_and_off_skips_probe(
    linked: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    feature, _main = linked
    (feature / "pyproject.toml").write_text("[tool.parrot.sdd]\nsandbox = 'preferred'\n", encoding="utf-8")
    monkeypatch.setattr(native, "native_sandbox_available", lambda: (True, ""))
    mode, degraded, reason, settings = native.plan_native_launch(feature)
    assert (mode, degraded, reason) == ("preferred", False, "")
    assert settings["sandbox"]["failIfUnavailable"] is True  # preferred + available == required + available

    def _never() -> tuple[bool, str]:
        raise AssertionError("probe must not run in off mode")

    monkeypatch.setattr(native, "native_sandbox_available", _never)
    monkeypatch.setenv(native.MODE_ENV, "off")
    mode, degraded, reason, settings = native.plan_native_launch(feature)
    assert (mode, degraded, reason) == ("off", True, "sandbox mode off")
    assert "sandbox" not in settings


def test_native_sandbox_available_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class _Completed:
        def __init__(self, returncode: int, stderr: str = "") -> None:
            self.returncode, self.stderr = returncode, stderr

    monkeypatch.setattr(native.shutil, "which", lambda name: None if name == "socat" else f"/usr/bin/{name}")
    assert native.native_sandbox_available() == (False, "missing prerequisite(s): socat")

    monkeypatch.setattr(native, "_probe_cache", None)
    monkeypatch.setattr(native.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        native.subprocess, "run", lambda argv, **kw: calls.append(argv) or _Completed(1, "\nbwrap: denied\n")
    )
    assert native.native_sandbox_available() == (False, "bwrap: denied")
    assert calls[0][:3] == ["/usr/bin/bwrap", "--unshare-user", "--unshare-pid"]
    assert native.native_sandbox_available() == (False, "bwrap: denied") and len(calls) == 1  # cached

    monkeypatch.setattr(native, "_probe_cache", None)

    def _timeout(argv: list[str], **kw: object) -> _Completed:
        raise native.subprocess.TimeoutExpired(argv, 10)

    monkeypatch.setattr(native.subprocess, "run", _timeout)
    assert native.native_sandbox_available() == (False, "bwrap probe timed out")

    monkeypatch.setattr(native, "_probe_cache", None)
    monkeypatch.setattr(native.subprocess, "run", lambda argv, **kw: _Completed(0))
    assert native.native_sandbox_available() == (True, "")


@pytest.mark.parametrize(
    "bad",
    [
        "https://github.com",
        "*.github.com",
        "github.com:443",
        "10.0.0.1",
        "::1",
        "",
        "127.1",
        "2130706433",
        "0x7f.1",
        "1.2.3",
        "localhost",
        "metadata",
    ],
)
def test_domain_rejected(linked: tuple[Path, Path], bad: str) -> None:
    """Only exact DNS hostnames are valid egress grants."""
    assert linked
    with pytest.raises(ValueError):
        native.validate_allowed_domains([bad])


def test_write_matrix_positive_and_negative(linked: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """Task paths are writable while environments and control paths are protected."""
    feature, main = linked
    monkeypatch.setenv("XDG_DATA_HOME", str(main / "data"))
    task_file = feature / "task.py"
    native.validate_native_write_path(feature, task_file)
    native.validate_native_write_path(feature, policy.claude_scratch_root() / "scratch.txt")
    native.validate_native_write_path(feature, main / ".claude" / "worktrees" / "new" / "file")
    denied = [
        feature / ".venv" / "editable.pth",
        main / ".git" / "config",
        main / ".git" / "hooks" / "pre-commit",
        main / ".git" / "worktrees" / "feat" / "config.worktree",
        main / "data" / "rtk" / "trust.json",
        feature / ".claude" / "settings.local.json",
        feature / "packages" / "ai-parrot" / "src" / "parrot" / "flows" / "dev_loop" / "native_claude_sandbox.py",
    ]
    for target in denied:
        with pytest.raises(ValueError):
            native.validate_native_write_path(feature, target)


def test_task_cwd_prefix_rules(linked: tuple[Path, Path]) -> None:
    """Only a literal absolute prefix selects a sibling linked worktree."""
    feature, main = linked
    pool = main / ".claude" / "worktrees" / "pool"
    assert native.native_task_cwd(feature, f"cd {pool} && pytest -q") == pool.resolve()
    assert native.native_task_cwd(feature, "pytest -q") == feature
    for command in (
        "cd relative && pytest -q",
        f"cd '{pool}' && pytest -q",
        "cd /tmp && pytest -q",
        "cd /tmp",
    ):
        with pytest.raises(ValueError):
            native.native_task_cwd(feature, command)


def test_environment_does_not_mutate_os_environ(
    linked: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, scratch_root: Path
) -> None:
    """Native environment values are task-local and leave process state unchanged."""
    feature, _main = linked
    before = dict(os.environ)
    monkeypatch.setenv(native.CACHE_DIR_ENV, str(scratch_root / "configured"))
    environment = native.native_command_environment(feature)
    assert environment["UV_NO_SYNC"] == "1"
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert environment["PYTHONPATH"].split(os.pathsep)[0] == str(feature / "packages" / "x" / "src")
    assert Path(environment["XDG_CACHE_HOME"]).is_relative_to(scratch_root)
    assert Path(environment["UV_CACHE_DIR"]).is_relative_to(scratch_root)
    assert os.environ[native.CACHE_DIR_ENV] == str(scratch_root / "configured")
    assert {key: value for key, value in os.environ.items() if key != native.CACHE_DIR_ENV} == {
        key: value for key, value in before.items() if key != native.CACHE_DIR_ENV
    }


def test_module_imports_as_script_sibling() -> None:
    """The module has no package-import dependency when loaded as a script sibling."""
    module_dir = str(Path(native.__file__).parent)
    code = f"import sys; sys.path.insert(0, {module_dir!r}); import native_claude_sandbox"
    result = subprocess.run([sys.executable, "-S", "-c", code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_hook_command_uses_the_launching_interpreter(linked: tuple[Path, Path]) -> None:
    feature, _main = linked
    command = native.native_sandbox_settings(feature)["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert command.startswith((native.shlex.quote(sys.executable), sys.executable))


def test_sibling_worktree_admin_dirs_are_denied(linked: tuple[Path, Path]) -> None:
    feature, main = linked
    sibling = main / ".git" / "worktrees" / "other"
    sibling.mkdir()
    deny = native.native_sandbox_settings(feature)["sandbox"]["filesystem"]["denyWrite"]
    assert str(sibling.resolve()) in deny
    assert str((main / ".git" / "worktrees" / "feat").resolve()) not in deny  # our own admin dir stays usable


def test_frozen_roots_win_over_a_forged_git_marker(linked: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    feature, main = linked
    root_env = native.native_root_env(feature)
    frozen = root_env[native.ROOTS_ENV].split(native.os.pathsep)
    assert [Path(p) for p in frozen] == list(native._native_roots(feature))

    monkeypatch.setenv(native.ROOTS_ENV, root_env[native.ROOTS_ENV])
    (feature / ".git").write_text("gitdir: /nonexistent/forged\n", encoding="utf-8")  # session-writable marker
    assert native._native_roots(feature / "sub") == tuple(Path(p) for p in frozen)
    with pytest.raises(ValueError):  # a cwd outside the frozen root still derives (and here fails) on its own
        native._native_roots(main / "elsewhere")
