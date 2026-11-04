"""FEAT-799 welcome renderer tests."""

from __future__ import annotations

import pytest
from rich.console import Console

from parrot.cli import console as console_mod
from parrot.knowledge.wiki.claude_code import welcome
from parrot.self_ import doctor
from parrot.self_.doctor import DoctorCheck

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
