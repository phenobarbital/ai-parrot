"""Brief agy-permission-hook, task 2 — ``parrot sdd install --host google`` registers the agy hook and rules.

agy auto-approves only through ``permissions.allow`` rules in the user's settings, so the google host install
writes the named hook into ``.agents/hooks.json`` and merges the managed rules into every agy ``settings.json``
(additive, recorded in the receipt, removed exactly on uninstall). Every test runs against a fake ``HOME``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.sdd.installer import (
    AGY_HOOK_LINE,
    AGY_HOOK_NAME,
    agy_hook_command,
    agy_settings_paths,
    install_sdd_integration,
    load_receipt,
    sdd_status,
    uninstall_sdd_integration,
)
from parrot.sdd.scripts.agy_permissions import SDD_ALLOW_RULES

HOOKS = ".agents/hooks.json"
SETTINGS = ".gemini/antigravity-cli/settings.json"
SNAP_SETTINGS = "snap/antigravity-cli/common/.gemini/antigravity-cli/settings.json"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    return path


def _install(repo: Path, **kwargs: object) -> list[str]:
    kwargs.setdefault("sdd_coder", False)
    kwargs.setdefault("portable", True)
    return install_sdd_integration(repo, ("google",), **kwargs)  # type: ignore[arg-type]


def _allow(path: Path) -> list[str]:
    return json.loads(path.read_text(encoding="utf-8"))["permissions"]["allow"]


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def test_install_registers_hook_and_rules(repo: Path, home: Path) -> None:
    actions = _install(repo)
    hooks = json.loads((repo / HOOKS).read_text(encoding="utf-8"))
    (entry,) = hooks[AGY_HOOK_NAME]["PreToolUse"]
    assert entry["matcher"] == "run_command"
    assert entry["hooks"] == [{"type": "command", "command": AGY_HOOK_LINE, "timeout": 10}]
    assert _allow(home / SETTINGS) == list(SDD_ALLOW_RULES)
    assert load_receipt(repo)["agy_rules"] == sorted(SDD_ALLOW_RULES)
    assert "agy-permissions" in load_receipt(repo)["settings_hooks"]
    assert any("agy permission hook registered (bare)" in a for a in actions)
    assert any(f"{len(SDD_ALLOW_RULES)} agy rule(s) added" in a for a in actions)


def test_install_is_idempotent(repo: Path, home: Path) -> None:
    _install(repo)
    before = ((repo / HOOKS).read_bytes(), (home / SETTINGS).read_bytes())
    actions = _install(repo)
    assert ((repo / HOOKS).read_bytes(), (home / SETTINGS).read_bytes()) == before
    assert any("agy permission hook already registered" in a for a in actions)
    assert any("agy rules present" in a for a in actions)


def test_foreign_hooks_and_user_rules_survive(repo: Path, home: Path) -> None:
    _write(repo / HOOKS, {"lint": {"PostToolUse": [{"matcher": "run_command", "hooks": [{"command": "x"}]}]}})
    _write(home / SETTINGS, {"model": "m", "permissions": {"allow": ["command(npm test)", "command(find)"]}})
    _install(repo)
    hooks = json.loads((repo / HOOKS).read_text(encoding="utf-8"))
    assert set(hooks) == {"lint", AGY_HOOK_NAME}
    settings = json.loads((home / SETTINGS).read_text(encoding="utf-8"))
    assert settings["model"] == "m"
    assert settings["permissions"]["allow"][:2] == ["command(npm test)", "command(find)"]
    assert settings["permissions"]["allow"].count("command(find)") == 1
    assert "command(find)" not in load_receipt(repo)["agy_rules"]

    uninstall_sdd_integration(repo, ("google",))
    hooks = json.loads((repo / HOOKS).read_text(encoding="utf-8"))
    assert set(hooks) == {"lint"}
    settings = json.loads((home / SETTINGS).read_text(encoding="utf-8"))
    assert settings == {"model": "m", "permissions": {"allow": ["command(npm test)", "command(find)"]}}


def test_uninstall_removes_a_hooks_file_it_alone_used(repo: Path, home: Path) -> None:
    _install(repo)
    uninstall_sdd_integration(repo, ("google",))
    assert not (repo / HOOKS).exists()
    assert json.loads((home / SETTINGS).read_text(encoding="utf-8")) == {}
    assert "agy_rules" not in load_receipt(repo)


def test_malformed_files_are_never_rewritten(repo: Path, home: Path) -> None:
    (repo / ".agents").mkdir()
    (repo / HOOKS).write_text("{not json", encoding="utf-8")
    (home / SETTINGS).parent.mkdir(parents=True)
    (home / SETTINGS).write_text("[1, 2]", encoding="utf-8")
    actions = _install(repo)
    assert (repo / HOOKS).read_text(encoding="utf-8") == "{not json"
    assert (home / SETTINGS).read_text(encoding="utf-8") == "[1, 2]"
    assert any(a.startswith("warning: .agents/hooks.json") for a in actions)
    assert any(a.startswith("warning: ~/.gemini/antigravity-cli/settings.json") for a in actions)


def test_symlinked_hooks_file_outside_the_repo_is_refused(repo: Path, home: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    (repo / ".agents").mkdir()
    (repo / HOOKS).symlink_to(outside)
    actions = _install(repo)
    assert outside.read_text(encoding="utf-8") == "{}"
    assert any("resolves outside the repository" in a for a in actions)


def test_both_settings_files_are_updated(repo: Path, home: Path) -> None:
    _write(home / SETTINGS, {})
    _write(home / SNAP_SETTINGS, {"permissions": {"allow": ["command(ls)"]}})
    assert agy_settings_paths() == [home / SETTINGS, home / SNAP_SETTINGS]
    _install(repo)
    assert _allow(home / SETTINGS) == list(SDD_ALLOW_RULES)
    assert _allow(home / SNAP_SETTINGS)[0] == "command(ls)"
    assert set(SDD_ALLOW_RULES) <= set(_allow(home / SNAP_SETTINGS))


def test_snap_only_settings_is_used_alone(home: Path) -> None:
    _write(home / SNAP_SETTINGS, {})
    assert agy_settings_paths() == [home / SNAP_SETTINGS]


def test_opt_out_and_other_hosts_plan_nothing(repo: Path, home: Path) -> None:
    _install(repo, agy_permissions=False)
    assert not (repo / HOOKS).exists()
    install_sdd_integration(repo, ("claude",), sdd_coder=False, portable=True)
    assert not (repo / HOOKS).exists()
    assert not (home / ".gemini").exists()


def test_dry_run_writes_nothing(repo: Path, home: Path) -> None:
    plan = _install(repo, dry_run=True)
    assert "plan: agy-permissions .agents/hooks.json (+ rules in ~/.gemini/antigravity-cli/settings.json)" in plan
    assert not (repo / HOOKS).exists()
    assert not any(home.iterdir())


def test_baked_form(repo: Path, home: Path) -> None:
    command, form = agy_hook_command(portable=False)
    assert form == "baked"
    assert command.endswith(" sdd hooks agy-permissions --hook") and command != AGY_HOOK_LINE
    _install(repo, portable=False)
    assert sdd_status(repo)["agy_permissions"]["form"] == "baked"


def test_status_reports_hook_and_missing_rules(repo: Path, home: Path) -> None:
    before = sdd_status(repo)["agy_permissions"]
    assert before["form"] is None
    assert before["missing_rules"] == len(SDD_ALLOW_RULES)
    _install(repo)
    after = sdd_status(repo)["agy_permissions"]
    assert after["form"] == "bare"
    assert after["command"] == AGY_HOOK_LINE
    assert after["missing_rules"] == 0
    assert after["settings"] == [str(home / SETTINGS)]


def test_cli_flag_skips_agy_permissions(repo: Path, home: Path) -> None:
    from parrot.cli import cli

    args = ["sdd", "install", "--path", str(repo), "--host", "google", "--no-sdd-coder", "--portable"]
    result = CliRunner().invoke(cli, [*args, "--no-agy-permissions"])
    assert result.exit_code == 0, result.output
    assert not (repo / HOOKS).exists()
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 0, result.output
    assert (repo / HOOKS).is_file()
