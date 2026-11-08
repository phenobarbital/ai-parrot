"""Deterministic FEAT-768 native policy tests (no Claude process, no network)."""

from __future__ import annotations

import json
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


_REAL_WARM_TIKTOKEN_CACHE = native.warm_tiktoken_cache


@pytest.fixture(autouse=True)
def no_tiktoken_warmup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep launcher tests off the network; the warm-up has its own tests below."""
    monkeypatch.setattr(native, "warm_tiktoken_cache", lambda target, environ: None)


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
    feature = main / ".parrot" / "worktrees" / "feat"
    pool = main / ".parrot" / "worktrees" / "pool"
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


def test_native_allow_write_includes_coder_evidence_dir(linked: tuple[Path, Path]) -> None:
    """The native backend allows exactly what Bubblewrap binds, and nothing else under ``artifacts/``."""
    feature, main = linked
    allow = native.native_sandbox_settings(feature)["sandbox"]["filesystem"]["allowWrite"]
    assert str((main / "artifacts" / "logs" / "sdd-coder-usage").resolve()) in allow
    assert str((main / "artifacts").resolve()) not in allow


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
        worktree / "packages" / "ai-parrot" / "src" / "parrot" / "sdd" / "scripts" / "native_claude_sandbox.py",
        worktree / "packages" / "ai-parrot" / "src" / "parrot" / "sdd" / "scripts" / "worktree_environment.py",
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
        ("[tool.parrot.sdd]\nsandbox = 'legacy'\n", "may only be set through"),
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


def test_plan_native_launch_legacy_uses_bubblewrap_without_native_probe(
    linked: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Legacy mode keeps the hook's Bubblewrap boundary without native settings."""
    feature, _main = linked
    monkeypatch.setenv(native.MODE_ENV, "legacy")
    monkeypatch.setattr(native.shutil, "which", lambda name: "/usr/bin/bwrap" if name == "bwrap" else None)
    monkeypatch.setattr(native, "_bwrap_probe", lambda executable: (True, ""))
    monkeypatch.setattr(
        native,
        "native_sandbox_available",
        lambda: (_ for _ in ()).throw(AssertionError("native probe must not run in legacy mode")),
    )

    mode, degraded, reason, settings = native.plan_native_launch(feature, allowed_domains=["invalid"])

    assert (mode, degraded, reason) == ("legacy", False, "")
    assert "sandbox" not in settings
    assert settings["hooks"]["PreToolUse"]


@pytest.mark.parametrize(
    ("platform", "executable", "probe", "match"),
    [
        ("darwin", "/usr/bin/bwrap", (True, ""), "not available on macos"),
        ("linux", None, (True, ""), "missing prerequisite"),
        ("linux", "/usr/bin/bwrap", (False, "namespace denied"), "namespace denied"),
    ],
)
def test_plan_native_launch_legacy_refuses_unusable_bubblewrap(
    linked: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    executable: str | None,
    probe: tuple[bool, str],
    match: str,
) -> None:
    """Legacy mode never permits an unprotected launch."""
    feature, _main = linked
    monkeypatch.setenv(native.MODE_ENV, "legacy")
    monkeypatch.setattr(native.sys, "platform", platform)
    monkeypatch.setattr(native.shutil, "which", lambda name: executable)
    monkeypatch.setattr(native, "_bwrap_probe", lambda executable: probe)

    with pytest.raises(RuntimeError, match=match):
        native.plan_native_launch(feature)


def test_launch_backend_selects_bubblewrap_only_for_legacy() -> None:
    """Only the declared legacy posture retains the Bubblewrap hook backend."""
    assert native.launch_backend("legacy") == native.BACKEND_BUBBLEWRAP
    assert native.launch_backend("required") == native.BACKEND_NATIVE


def test_native_sandbox_available_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class _Completed:
        def __init__(self, returncode: int, stderr: str = "") -> None:
            self.returncode, self.stderr = returncode, stderr

    monkeypatch.setattr(native, "sandbox_platform", lambda: "linux")
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
    ("platform", "expected"),
    [("linux", "linux"), ("darwin", "macos"), ("win32", "windows"), ("cygwin", "windows"), ("freebsd", "unsupported")],
)
def test_sandbox_platform(monkeypatch: pytest.MonkeyPatch, platform: str, expected: str) -> None:
    """Supported host platforms have explicit native-sandbox outcomes."""
    monkeypatch.setattr(native.sys, "platform", platform)
    assert native.sandbox_platform() == expected


def test_native_sandbox_available_macos_windows_and_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-Linux probes neither require Bubblewrap nor silently permit a sandbox."""
    calls: list[list[str]] = []

    class _Completed:
        def __init__(self, returncode: int, stderr: str = "") -> None:
            self.returncode, self.stderr = returncode, stderr

    monkeypatch.setattr(native, "sandbox_platform", lambda: "macos")
    monkeypatch.setattr(native.shutil, "which", lambda name: None)
    assert native.native_sandbox_available() == (False, "missing prerequisite(s): sandbox-exec")

    monkeypatch.setattr(native, "_probe_cache", None)
    monkeypatch.setattr(native.shutil, "which", lambda name: "/usr/bin/sandbox-exec")
    monkeypatch.setattr(
        native.subprocess, "run", lambda argv, **kwargs: calls.append(argv) or _Completed(1, "Seatbelt denied\n")
    )
    assert native.native_sandbox_available() == (False, "Seatbelt denied")
    assert calls == [["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)", "/usr/bin/true"]]

    monkeypatch.setattr(native, "_probe_cache", None)
    monkeypatch.setattr(native.subprocess, "run", lambda argv, **kwargs: _Completed(0))
    assert native.native_sandbox_available() == (True, "")

    monkeypatch.setattr(native, "_probe_cache", None)
    monkeypatch.setattr(native, "sandbox_platform", lambda: "windows")
    available, reason = native.native_sandbox_available()
    assert available is False and "WSL2" in reason and "PARROT_SDD_SANDBOX_MODE=preferred" in reason

    monkeypatch.setattr(native, "_probe_cache", None)
    monkeypatch.setattr(native, "sandbox_platform", lambda: "unsupported")
    monkeypatch.setattr(native.sys, "platform", "plan9")
    assert native.native_sandbox_available() == (False, "unsupported platform 'plan9' for the native sandbox")


def test_user_tag_is_safe_without_getuid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows-style users produce stable cache directory names."""
    monkeypatch.delattr(native.os, "getuid", raising=False)
    monkeypatch.setattr(native.getpass, "getuser", lambda: "Ada Lovelace!")
    assert native._user_tag() == "AdaLovelace"


def test_launch_worker_prints_macos_seatbelt_notice(
    linked: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A strict macOS launch makes the unqualified backend visible to the operator."""
    feature, _main = linked
    monkeypatch.setattr(native.shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None)
    monkeypatch.setattr(native, "_native_roots", lambda cwd: (feature, feature / ".git", feature))
    monkeypatch.setattr(native, "plan_native_launch", lambda *args, **kwargs: ("required", False, "", {}))
    monkeypatch.setattr(native, "native_root_env", lambda cwd: {})
    monkeypatch.setattr(native, "sandbox_platform", lambda: "macos")
    monkeypatch.setattr(native.os, "execvpe", lambda *args: None)

    assert native.launch_worker([]) == 1
    assert "NOTICE macOS Seatbelt backend is implemented but not certified" in capsys.readouterr().err


def test_launch_worker_uses_requested_cwd_and_final_prompt(
    linked: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A host launcher may select the feature worktree and final worker trigger."""
    feature, _main = linked
    calls: list[object] = []
    monkeypatch.setattr(native.shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None)
    monkeypatch.setattr(native, "_native_roots", lambda cwd: (feature, feature / ".git", feature))
    monkeypatch.setattr(native, "plan_native_launch", lambda *args, **kwargs: ("required", False, "", {}))
    monkeypatch.setattr(native, "native_root_env", lambda cwd: {})
    monkeypatch.setattr(native, "_allocate_session_cache", lambda: feature / "cache")
    monkeypatch.setattr(native.os, "chdir", lambda cwd: calls.append(cwd))
    monkeypatch.setattr(native.os, "execvpe", lambda *args: calls.append(args))

    assert native.launch_worker(["--", "--verbose"], cwd=feature, initial_prompt="run FEAT-768") == 1
    assert calls[0] == feature
    command = calls[1][1]
    assert command[-1] == "run FEAT-768"
    assert command[-2] == "--verbose"


_SECRET = "ghp_SECRET_TOKEN_VALUE"


def _launch_harness(
    linked: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    *,
    primary_toml: str | None,
    worktree_toml: str | None = None,
) -> tuple[Path, dict[str, object]]:
    """Wire launch_worker to a fake claude and record the plan domains, exec command and env."""
    feature, main = linked
    if primary_toml is not None:
        (main / "pyproject.toml").write_text(primary_toml)
    if worktree_toml is not None:
        (feature / "pyproject.toml").write_text(worktree_toml)
    seen: dict[str, object] = {"gh_calls": 0, "exec": None}

    def fake_plan(cwd: Path, *, allowed_domains=()):  # noqa: ANN001, ANN202
        seen["domains"] = list(allowed_domains)
        return "required", False, "", {}

    monkeypatch.setattr(native.shutil, "which", lambda name: f"/usr/bin/{name}" if name in ("claude", "gh") else None)
    monkeypatch.setattr(native, "_native_roots", lambda cwd: (feature, feature / ".git", main))
    monkeypatch.setattr(native, "plan_native_launch", fake_plan)
    monkeypatch.setattr(native, "native_root_env", lambda cwd: {})
    monkeypatch.setattr(native, "_allocate_session_cache", lambda: feature / "cache")
    monkeypatch.setattr(native.os, "chdir", lambda cwd: None)
    monkeypatch.setattr(native.os, "execvpe", lambda *args: seen.__setitem__("exec", args))
    monkeypatch.delenv(native.MODE_ENV, raising=False)
    return feature, seen


def _fake_gh(
    monkeypatch: pytest.MonkeyPatch, seen: dict[str, object], *, code: int = 0, out: str = _SECRET + "\n"
) -> None:
    def run(cmd, **kwargs):  # noqa: ANN001, ANN003, ANN202
        seen["gh_calls"] = int(seen["gh_calls"]) + 1  # type: ignore[call-overload]
        return subprocess.CompletedProcess(cmd, code, stdout=out, stderr="")

    monkeypatch.setattr(native.subprocess, "run", run)


_CONFIG = 'tool = {parrot = {sdd = {sandbox_allowed_domains = ["api.github.com"], gh_token = true}}}\n'


def test_launch_config_domains_union_with_flags(linked: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """Primary-checkout config domains reach the plan, unioned order-stably with flags."""
    feature, seen = _launch_harness(linked, monkeypatch, primary_toml=_CONFIG)
    _fake_gh(monkeypatch, seen)
    args = ["--sandbox-allow-domain", "pypi.org", "--sandbox-allow-domain", "API.github.com"]
    assert native.launch_worker(args, cwd=feature) == 1
    assert seen["domains"] == ["api.github.com", "pypi.org"]


def test_worktree_config_is_ignored(linked: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """A worktree pyproject (session-writable) never widens egress."""
    feature, seen = _launch_harness(
        linked,
        monkeypatch,
        primary_toml=None,
        worktree_toml='tool = {parrot = {sdd = {sandbox_allowed_domains = ["evil.example.com"], gh_token = true}}}\n',
    )
    _fake_gh(monkeypatch, seen)
    native.launch_worker([], cwd=feature)
    assert seen["domains"] == []
    assert seen["gh_calls"] == 0


@pytest.mark.parametrize(
    "body",
    [
        'sandbox_allowed_domains = "api.github.com"',
        'sandbox_allowed_domains = ["https://github.com"]',
        "gh_token = 1",
        "sandbox_allowed_domains = [",
    ],
)
def test_malformed_launch_config_exits_2(
    linked: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], body: str
) -> None:
    """Bad config refuses to launch claude and names the file."""
    feature, seen = _launch_harness(linked, monkeypatch, primary_toml=f"[tool.parrot.sdd]\n{body}\n")
    assert native.launch_worker([], cwd=feature) == 2
    assert seen["exec"] is None
    assert "Invalid sandbox launch config" in capsys.readouterr().err


def test_gh_token_injected_never_leaked(
    linked: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The host-resolved token reaches only the exec env, never argv or output."""
    feature, seen = _launch_harness(linked, monkeypatch, primary_toml=_CONFIG)
    _fake_gh(monkeypatch, seen)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    native.launch_worker([], cwd=feature)
    _path, command, env = seen["exec"]  # type: ignore[misc]
    assert env["GH_TOKEN"] == _SECRET
    assert all(_SECRET not in part for part in command)
    captured = capsys.readouterr()
    assert _SECRET not in captured.out + captured.err


def test_existing_gh_token_kept_and_gh_not_called(linked: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """A GH_TOKEN already in the environment wins."""
    feature, seen = _launch_harness(linked, monkeypatch, primary_toml=_CONFIG)
    _fake_gh(monkeypatch, seen)
    monkeypatch.setenv("GH_TOKEN", "preset")
    native.launch_worker([], cwd=feature)
    assert seen["gh_calls"] == 0
    assert seen["exec"][2]["GH_TOKEN"] == "preset"  # type: ignore[index]


def test_no_gh_token_flag_skips_resolution(linked: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """--no-gh-token is launcher-owned: no token, no gh call, not forwarded to claude."""
    feature, seen = _launch_harness(linked, monkeypatch, primary_toml=_CONFIG)
    _fake_gh(monkeypatch, seen)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    native.launch_worker(["--no-gh-token"], cwd=feature)
    assert seen["gh_calls"] == 0
    assert "GH_TOKEN" not in seen["exec"][2]  # type: ignore[index]
    assert "--no-gh-token" not in seen["exec"][1]  # type: ignore[index]


@pytest.mark.parametrize("failure", ["missing", "nonzero", "timeout", "empty"])
def test_gh_token_failure_warns_and_launches(
    linked: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], failure: str
) -> None:
    """Any gh failure warns on stderr and proceeds without GH_TOKEN."""
    feature, seen = _launch_harness(linked, monkeypatch, primary_toml=_CONFIG)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    if failure == "missing":
        monkeypatch.setattr(native.shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None)
    elif failure == "nonzero":
        _fake_gh(monkeypatch, seen, code=1, out=_SECRET)
    elif failure == "empty":
        _fake_gh(monkeypatch, seen, out="  \n")
    else:

        def boom(cmd, **kwargs):  # noqa: ANN001, ANN003, ANN202
            raise subprocess.TimeoutExpired(cmd, 10)

        monkeypatch.setattr(native.subprocess, "run", boom)
    native.launch_worker([], cwd=feature)
    captured = capsys.readouterr()
    assert "WARNING gh_token is enabled but no token could be obtained" in captured.err
    assert _SECRET not in captured.out + captured.err
    assert seen["exec"] is not None
    assert "GH_TOKEN" not in seen["exec"][2]  # type: ignore[index]


@pytest.mark.parametrize(
    ("mode", "degraded"),
    [("required", False), ("preferred", True), ("off", False), ("legacy", False)],
)
def test_notification_settings_preserve_policy(
    linked: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, mode: str, degraded: bool
) -> None:
    """A marked tmux feature adds one Stop command without changing compiled policy."""
    feature, _main = linked
    captured: list[tuple[object, ...]] = []
    settings = {
        "sandbox": {"enabled": mode != "legacy", "network": {"allowAllUnixSockets": False}},
        "hooks": {
            "PreToolUse": [{"hooks": [{"type": "command", "command": "pre", "timeout": 10}]}],
            "Stop": [{"hooks": [{"type": "command", "command": "existing", "timeout": 9}]}],
        },
    }

    def configure(cache: Path, *, worktree: Path, env: dict[str, str]) -> str:
        assert cache == feature / "cache" and worktree == feature
        assert env["TMUX_PANE"] == "%4"
        return "helper --hook"

    class Loader:
        def exec_module(self, module: object) -> None:
            module.configure_notification = configure

    spec = type("Spec", (), {"loader": Loader()})()
    monkeypatch.setattr(native.shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None)
    monkeypatch.setattr(native, "_native_roots", lambda cwd: (feature, feature / ".git", feature))
    monkeypatch.setattr(native, "plan_native_launch", lambda *args, **kwargs: (mode, degraded, "", settings))
    monkeypatch.setattr(native, "native_root_env", lambda cwd: {})
    monkeypatch.setattr(native, "_allocate_session_cache", lambda: feature / "cache")
    monkeypatch.setattr(native.importlib.util, "spec_from_file_location", lambda *args: spec)
    monkeypatch.setattr(native.importlib.util, "module_from_spec", lambda spec: type("Helper", (), {})())
    monkeypatch.setattr(native.os, "chdir", lambda cwd: captured.append(("chdir", cwd)))
    monkeypatch.setattr(native.os, "execvpe", lambda *args: captured.append(args))

    native.launch_worker(
        [],
        cwd=feature,
        base_env={
            "TMUX_PANE": "%4",
            "PARROT_SDD_NOTIFY_FEATURE": "FEAT-768",
            "PARROT_SDD_NOTIFY_SLUG": "sandbox",
            "PARROT_SDD_NOTIFY_DESKTOP": "{}",
        },
    )
    command = captured[1][1]
    compiled = json.loads(command[command.index("--settings") + 1])
    environment = captured[1][2]
    assert compiled["sandbox"] == {"enabled": mode != "legacy", "network": {"allowAllUnixSockets": False}}
    assert compiled["hooks"]["PreToolUse"] == settings["hooks"]["PreToolUse"]
    assert compiled["hooks"]["Stop"] == [
        {"hooks": [{"type": "command", "command": "existing", "timeout": 9}]},
        {"hooks": [{"type": "command", "command": "helper --hook", "timeout": 5}]},
    ]
    assert environment["PARROT_SDD_NOTIFY_PYTHON"] == str(Path(native.sys.executable).absolute())
    assert environment["PARROT_SDD_NOTIFY_HELPER"] == str(
        Path(native.__file__).resolve().with_name("worker_notification.py")
    )


@pytest.mark.parametrize(
    "base_env",
    [
        {
            "PARROT_SDD_NOTIFY_FEATURE": "FEAT-768",
            "PARROT_SDD_NOTIFY_SLUG": "sandbox",
            "PARROT_SDD_NOTIFY_DESKTOP": "{}",
        },
        {
            "TMUX_PANE": "%4",
            "PARROT_SDD_NOTIFY_FEATURE": "",
            "PARROT_SDD_NOTIFY_SLUG": "sandbox",
            "PARROT_SDD_NOTIFY_DESKTOP": "{}",
        },
    ],
)
def test_notification_requires_tmux_and_complete_metadata(
    linked: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, base_env: dict[str, str]
) -> None:
    """Missing tmux state or identity cannot load a helper or retain stale exports."""
    feature, _main = linked
    captured: list[tuple[object, ...]] = []
    base_env.update({"PARROT_SDD_NOTIFY_PYTHON": "/stale/python", "PARROT_SDD_NOTIFY_HELPER": "/stale/helper"})
    monkeypatch.setattr(native.shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None)
    monkeypatch.setattr(native, "_native_roots", lambda cwd: (feature, feature / ".git", feature))
    monkeypatch.setattr(native, "plan_native_launch", lambda *args, **kwargs: ("required", False, "", {"hooks": {}}))
    monkeypatch.setattr(native, "native_root_env", lambda cwd: {})
    monkeypatch.setattr(native, "_allocate_session_cache", lambda: feature / "cache")
    monkeypatch.setattr(
        native.importlib.util, "spec_from_file_location", lambda *args: pytest.fail("metadata must gate helper loading")
    )
    monkeypatch.setattr(native.os, "chdir", lambda cwd: captured.append(("chdir", cwd)))
    monkeypatch.setattr(native.os, "execvpe", lambda *args: captured.append(args))

    native.launch_worker([], cwd=feature, base_env=base_env)
    environment = captured[1][2]
    assert "PARROT_SDD_NOTIFY_PYTHON" not in environment
    assert "PARROT_SDD_NOTIFY_HELPER" not in environment


def test_notification_setup_failure_does_not_fail_launch(
    linked: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invalid metadata and helper loading failures keep the worker executable."""
    feature, _main = linked
    captured: list[tuple[object, ...]] = []
    settings = {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "pre", "timeout": 10}]}]}}
    monkeypatch.setattr(native.shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None)
    monkeypatch.setattr(native, "_native_roots", lambda cwd: (feature, feature / ".git", feature))
    monkeypatch.setattr(native, "plan_native_launch", lambda *args, **kwargs: ("required", False, "", settings))
    monkeypatch.setattr(native, "native_root_env", lambda cwd: {})
    monkeypatch.setattr(native, "_allocate_session_cache", lambda: feature / "cache")
    monkeypatch.setattr(
        native.importlib.util, "spec_from_file_location", lambda *args: (_ for _ in ()).throw(OSError("gone"))
    )
    monkeypatch.setattr(native.os, "chdir", lambda cwd: captured.append(("chdir", cwd)))
    monkeypatch.setattr(native.os, "execvpe", lambda *args: captured.append(args))

    native.launch_worker(
        [],
        cwd=feature,
        initial_prompt="run FEAT-768",
        base_env={
            "TMUX_PANE": "%4",
            "PARROT_SDD_NOTIFY_FEATURE": "FEAT-768",
            "PARROT_SDD_NOTIFY_SLUG": "sandbox",
            "PARROT_SDD_NOTIFY_DESKTOP": "{}",
            "PARROT_SDD_NOTIFY_PYTHON": "/stale/python",
            "PARROT_SDD_NOTIFY_HELPER": "/stale/helper",
        },
    )
    command = captured[1][1]
    compiled = json.loads(command[command.index("--settings") + 1])
    environment = captured[1][2]
    assert compiled == settings
    assert "PARROT_SDD_NOTIFY_PYTHON" not in environment
    assert "PARROT_SDD_NOTIFY_HELPER" not in environment
    assert command[-1] == "run FEAT-768"


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
    native.validate_native_write_path(feature, main / ".parrot" / "worktrees" / "new" / "file")
    denied = [
        feature / ".venv" / "editable.pth",
        main / ".git" / "config",
        main / ".git" / "hooks" / "pre-commit",
        main / ".git" / "worktrees" / "feat" / "config.worktree",
        main / "data" / "rtk" / "trust.json",
        feature / ".claude" / "settings.local.json",
        feature / "packages" / "ai-parrot" / "src" / "parrot" / "flows" / "dev_loop" / "native_claude_sandbox.py",
        feature / "packages" / "ai-parrot" / "src" / "parrot" / "sdd" / "scripts" / "native_claude_sandbox.py",
        feature / "packages" / "ai-parrot" / "src" / "parrot" / "sdd" / "scripts" / "worktree_environment.py",
        Path(native.__file__).resolve().parent / "worktree_environment.py",
    ]
    for target in denied:
        with pytest.raises(ValueError):
            native.validate_native_write_path(feature, target)


def test_task_cwd_prefix_rules(linked: tuple[Path, Path]) -> None:
    """A literal absolute prefix selects a sibling linked worktree; a relative one resolves against the session."""
    feature, main = linked
    pool = main / ".parrot" / "worktrees" / "pool"
    assert native.native_task_cwd(feature, f"cd {pool} && pytest -q") == pool.resolve()
    assert native.native_task_cwd(feature, "pytest -q") == feature
    # issue:2860a2723bad — `cd packages && …` stays inside the session worktree, so the hook roots there
    # instead of denying the command with "Native task cwd must be an absolute path".
    assert native.native_task_cwd(feature, "cd packages && python3 - <<'PY'\nimport re\nPY") == feature.resolve()
    assert native.native_task_cwd(feature, "cd ./packages/x/src && pytest -q") == feature.resolve()
    assert native.native_task_cwd(feature, "cd ../pool && pytest -q") == pool.resolve()
    for command in (
        f"cd '{pool}' && pytest -q",
        "cd $HOME && pytest -q",
        "cd /tmp && pytest -q",
        "cd /tmp",
        "cd .. && pytest -q",  # the primary checkout's worktree directory
        "cd ../../.. && pytest -q",  # the primary checkout itself
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
    assert Path(environment["TIKTOKEN_CACHE_DIR"]).is_relative_to(scratch_root)
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


def test_script_mode_sibling_import_resolves_inside_sdd_scripts(tmp_path: Path) -> None:
    """Under ``python -S`` (no parrot) the shims + moved files stay co-importable as script siblings."""
    import subprocess
    import sys

    dev_loop = Path(native.__file__).resolve().parents[2] / "flows" / "dev_loop"
    code = (
        "import importlib.util, sys; sys.path.insert(0, sys.argv[1]); "
        "import native_claude_sandbox as n, worktree_environment as w; "
        "assert 'parrot' not in sys.modules, 'parrot'; "
        "assert n.__file__.endswith('sdd/scripts/native_claude_sandbox.py'), n.__file__; "
        "assert n._we is w or n._we.__file__.endswith('worktree_environment.py'); "
        "p = __import__('pathlib').Path(n.__file__).with_name('worker_notification.py'); "
        "s = importlib.util.spec_from_file_location('worker_notification', p); "
        "m = importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        "assert callable(m.configure_notification); assert 'parrot' not in sys.modules; print('ok')"
    )
    result = subprocess.run(
        [sys.executable, "-S", "-c", code, str(dev_loop)],
        capture_output=True,
        text=True,
        env={},
        cwd=tmp_path,
        check=False,
    )
    assert result.stdout.strip() == "ok", result.stderr


def test_script_mode_native_settings_for_a_linked_worktree(linked: tuple[Path, Path], tmp_path: Path) -> None:
    """The tmux child (``python -S``) builds settings for a linked worktree without importing parrot."""
    feature, main = linked
    admin_root = main / ".parrot" / "worktrees"
    admin_root.mkdir(parents=True, exist_ok=True)
    dev_loop = Path(native.__file__).resolve().parents[2] / "flows" / "dev_loop"
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); from pathlib import Path; "
        "import native_claude_sandbox as n, worktree_environment as w; "
        "s = n.native_sandbox_settings(Path(sys.argv[2])); "
        "assert 'parrot' not in sys.modules, 'parrot'; "
        "print(sys.argv[3] in s['sandbox']['filesystem']['allowWrite'])"
    )
    result = subprocess.run(
        [sys.executable, "-S", "-c", code, str(dev_loop), str(feature), str(admin_root.resolve())],
        capture_output=True,
        text=True,
        env={"HOME": str(tmp_path)},
        cwd=tmp_path,
        check=False,
    )
    assert result.stdout.strip() == "True", result.stderr


def test_tiktoken_cache_is_shared_not_per_session(
    linked: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, scratch_root: Path
) -> None:
    """The tiktoken cache survives the launcher reaping per-session caches."""
    feature, _main = linked
    session = scratch_root / "parrot-sdd-cache" / "8c1b7f0e-6a4e-4d8a-9b1e-2f6c5d4a3b21"
    monkeypatch.setenv(native.CACHE_DIR_ENV, str(session))
    environment = native.native_command_environment(feature)
    cache = Path(environment["TIKTOKEN_CACHE_DIR"])
    assert cache == native.tiktoken_cache_dir()
    assert not cache.is_relative_to(session)
    assert cache.parent.name.startswith("shared-")


def test_warm_tiktoken_cache_copies_host_cache_without_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Encodings already cached on the host are copied; nothing is downloaded."""
    host_tmp = tmp_path / "host-tmp"
    host_cache = host_tmp / "data-gym-cache"
    host_cache.mkdir(parents=True)
    encoding = "9b5ad71b2ce5302211f9c61530b329a4922fc6a4"
    (host_cache / encoding).write_bytes(b"encoding")
    (host_cache / "notes.txt").write_text("not an encoding", encoding="utf-8")
    (host_cache / ("a" * 40)).symlink_to(host_cache / "notes.txt")

    def no_download(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("must not download when the host cache is seeded")

    monkeypatch.setattr(native.subprocess, "run", no_download)
    target = tmp_path / "sandbox-cache"
    _REAL_WARM_TIKTOKEN_CACHE(target, {"TMPDIR": str(host_tmp)})
    assert sorted(entry.name for entry in target.iterdir()) == [encoding]
    assert (target / encoding).read_bytes() == b"encoding"


def test_warm_tiktoken_cache_downloads_into_target_when_host_cache_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no host cache, the host downloads straight into the sandbox cache, bounded by a timeout."""
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(native.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(native.subprocess, "run", lambda argv, **kwargs: calls.append({"argv": argv, **kwargs}))
    target = tmp_path / "sandbox-cache"
    _REAL_WARM_TIKTOKEN_CACHE(target, {"TMPDIR": str(tmp_path / "empty-tmp")})
    assert len(calls) == 1
    assert calls[0]["env"]["TIKTOKEN_CACHE_DIR"] == str(target)  # type: ignore[index]
    assert calls[0]["timeout"] == native._TIKTOKEN_WARM_TIMEOUT_S
    assert "cl100k_base" in calls[0]["argv"][-1]  # type: ignore[index]


def test_warm_tiktoken_cache_never_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A slow or failing download leaves the cache empty instead of failing the launch."""

    def timeout(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="tiktoken", timeout=1)

    monkeypatch.setattr(native.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(native.subprocess, "run", timeout)
    _REAL_WARM_TIKTOKEN_CACHE(tmp_path / "sandbox-cache", {"TMPDIR": str(tmp_path / "empty-tmp")})
