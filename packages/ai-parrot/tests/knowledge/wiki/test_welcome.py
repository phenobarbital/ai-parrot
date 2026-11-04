"""FEAT-799 welcome renderer tests."""

from __future__ import annotations

import json

import pytest
from rich.console import Console
from rich.prompt import Prompt

from parrot.cli import console as console_mod
from parrot.knowledge.wiki.claude_code import welcome
from parrot.self_ import doctor
from parrot.self_.doctor import DoctorCheck
from parrot.sdd.scripts.native_claude_sandbox import MODE_ENV, resolve_sandbox_mode

OK = [
    DoctorCheck(name="sdd: bwrap", ok=True),
    DoctorCheck(name="sdd: bwrap nested userns", ok=True),
]
FAIL = [
    DoctorCheck(name="sdd: bwrap", ok=True),
    DoctorCheck(name="sdd: bwrap nested userns", ok=False, detail="setgroups denied"),
]


def test_bwrap_diagnostic_non_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    """The diagnostic silently skips platforms that do not use Bubblewrap."""
    monkeypatch.setattr(doctor.sys, "platform", "darwin")

    assert welcome.run_bwrap_diagnostic() == []


def test_bwrap_diagnostic_delegates_to_doctor(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bridge returns exactly the doctor diagnostic result."""
    expected = [DoctorCheck(name="sdd: bwrap", ok=True)]
    monkeypatch.setattr(welcome, "check_bwrap_sandbox", lambda: expected)

    assert welcome.run_bwrap_diagnostic() == expected


def test_render_welcome_all_ok() -> None:
    """Successful checks render the positive sandbox status without fixes."""
    markdown = welcome.build_welcome_markdown(["Claude hook installed"], OK, "native")

    assert "## Sandbox Status" in markdown
    assert "✅ nested Bubblewrap works" in markdown
    assert welcome.APPARMOR_FIX not in markdown
    assert "- ✓ Claude hook installed" in markdown
    assert "Sandbox mode: native (Claude Code sandbox, `required`)" in markdown


def test_render_welcome_bwrap_fails() -> None:
    """Failed checks render all copyable operating-system fix commands."""
    markdown = welcome.build_welcome_markdown([], FAIL, "legacy")

    assert "sdd: bwrap nested userns: setgroups denied" in markdown
    assert welcome.SYSCTL_FIX in markdown
    assert welcome.APPARMOR_FIX in markdown
    assert welcome.VERIFY_CMD in markdown
    assert markdown.count("```bash") == 3
    assert "Sandbox mode: legacy (SDD Bubblewrap wrapper)" in markdown


def test_render_welcome_no_checks() -> None:
    """Non-Linux calls omit the sandbox section entirely."""
    markdown = welcome.build_welcome_markdown([], [], None)

    assert "## Sandbox Status" not in markdown
    assert "## Next Steps" in markdown


def test_render_welcome_prints_to_shared_console() -> None:
    """Rendering uses the shared Rich console override."""
    recording_console = Console(record=True, width=100)
    console_mod.set_console(recording_console)
    try:
        welcome.render_welcome(["Claude hook installed"], OK, None)
        output = recording_console.export_text()
    finally:
        console_mod.set_console(None)

    assert "AI-Parrot — Claude Code Integration Installed" in output
    assert "nested Bubblewrap works" in output


def test_wizard_preset_native(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A native preset writes the resolver-compatible TOML mode."""
    monkeypatch.delenv(MODE_ENV, raising=False)

    assert welcome.sandbox_mode_wizard(tmp_path, preset="native") == "native"
    assert 'sandbox = "required"' in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert resolve_sandbox_mode(tmp_path) == "required"


def test_wizard_preset_legacy(tmp_path) -> None:
    """A legacy preset writes only Claude's local environment configuration."""
    assert welcome.sandbox_mode_wizard(tmp_path, preset="legacy") == "legacy"

    settings = json.loads((tmp_path / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert settings["env"][MODE_ENV] == "legacy"
    assert not (tmp_path / "pyproject.toml").exists()


def test_wizard_non_interactive_skips(tmp_path) -> None:
    """Non-interactive execution leaves an unset configuration untouched."""
    assert welcome.sandbox_mode_wizard(tmp_path, non_interactive=True) is None
    assert not (tmp_path / "pyproject.toml").exists()
    assert not (tmp_path / ".claude" / "settings.local.json").exists()


def test_wizard_interactive_choice_1(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The first interactive choice selects native mode."""
    monkeypatch.setattr(Prompt, "ask", lambda *args, **kwargs: "1")

    assert welcome.sandbox_mode_wizard(tmp_path) == "native"
    assert 'sandbox = "required"' in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")


def test_wizard_interactive_choice_3(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The skip choice does not create configuration files."""
    monkeypatch.setattr(Prompt, "ask", lambda *args, **kwargs: "3")

    assert welcome.sandbox_mode_wizard(tmp_path) is None
    assert not (tmp_path / "pyproject.toml").exists()
    assert not (tmp_path / ".claude" / "settings.local.json").exists()


def test_wizard_creates_toml_section(tmp_path) -> None:
    """Native mode appends a missing SDD table without replacing project metadata."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "sample"\n', encoding="utf-8")

    welcome.write_sandbox_mode(tmp_path, "native")

    contents = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert '[project]\nname = "sample"' in contents
    assert '[tool.parrot.sdd]\nsandbox = "required"' in contents


def test_wizard_preserves_existing_toml(tmp_path) -> None:
    """Replacing a sandbox key leaves comments and sibling SDD values intact."""
    original = '# preserved\n[tool.parrot.sdd]\nother = "value"\nsandbox = "preferred"\n'
    (tmp_path / "pyproject.toml").write_text(original, encoding="utf-8")

    welcome.write_sandbox_mode(tmp_path, "native")

    contents = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert "# preserved" in contents
    assert 'other = "value"' in contents
    assert 'sandbox = "required"' in contents


def test_wizard_idempotent(tmp_path) -> None:
    """Writing native mode repeatedly preserves identical TOML bytes."""
    welcome.write_sandbox_mode(tmp_path, "native")
    initial = (tmp_path / "pyproject.toml").read_bytes()

    welcome.write_sandbox_mode(tmp_path, "native")

    assert (tmp_path / "pyproject.toml").read_bytes() == initial


def test_native_clears_legacy_env(tmp_path) -> None:
    """Selecting native removes the legacy override while retaining other settings."""
    welcome.write_sandbox_mode(tmp_path, "legacy")
    path = tmp_path / ".claude" / "settings.local.json"
    settings = json.loads(path.read_text(encoding="utf-8"))
    settings["other"] = "kept"
    path.write_text(json.dumps(settings), encoding="utf-8")

    welcome.write_sandbox_mode(tmp_path, "native")

    settings = json.loads(path.read_text(encoding="utf-8"))
    assert MODE_ENV not in settings.get("env", {})
    assert settings["other"] == "kept"
