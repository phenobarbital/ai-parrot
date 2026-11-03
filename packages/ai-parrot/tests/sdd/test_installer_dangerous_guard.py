"""C32 — ``parrot sdd install`` registers the dangerous-actions guard in ``.claude/settings.json`` (TASK-5110)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from parrot.sdd.installer import (
    DANGEROUS_HOOK_LINE,
    dangerous_hook_command,
    install_sdd_integration,
    sdd_status,
    uninstall_sdd_integration,
)

SETTINGS = ".claude/settings.json"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    return tmp_path


def _entries(repo: Path) -> list[dict]:
    data = json.loads((repo / SETTINGS).read_text())
    return data.get("hooks", {}).get("PreToolUse", [])


def _ours(repo: Path) -> list[dict]:
    return [e for e in _entries(repo) if any("dangerous-actions --hook" in h["command"] for h in e["hooks"])]


def test_install_adds_exactly_one_entry(repo: Path) -> None:
    install_sdd_integration(repo)
    (entry,) = _ours(repo)
    assert entry["matcher"] == "Bash|Edit|Write|MultiEdit"
    assert entry["hooks"][0]["type"] == "command" and entry["hooks"][0]["timeout"] == 10
    assert "||" not in entry["hooks"][0]["command"]


def test_reinstall_does_not_duplicate(repo: Path) -> None:
    install_sdd_integration(repo)
    install_sdd_integration(repo)
    assert len(_ours(repo)) == 1


def test_portable_writes_bare_form(repo: Path) -> None:
    install_sdd_integration(repo, portable=True)
    assert _ours(repo)[0]["hooks"][0]["command"] == DANGEROUS_HOOK_LINE
    assert sdd_status(repo)["dangerous_guard"] == {"form": "bare", "command": DANGEROUS_HOOK_LINE}


def test_reinstall_upgrades_form_in_place(repo: Path) -> None:
    install_sdd_integration(repo, portable=True)
    expected, _ = dangerous_hook_command(portable=False)
    install_sdd_integration(repo)
    assert len(_ours(repo)) == 1
    assert _ours(repo)[0]["hooks"][0]["command"] == expected


def test_foreign_entries_are_kept_byte_identical(repo: Path) -> None:
    foreign = {"matcher": "Bash", "hooks": [{"type": "command", "command": "my-linter --check"}]}
    (repo / ".claude").mkdir()
    (repo / SETTINGS).write_text(json.dumps({"theme": "dark", "hooks": {"PreToolUse": [foreign]}}, indent=2) + "\n")
    install_sdd_integration(repo)
    data = json.loads((repo / SETTINGS).read_text())
    assert data["theme"] == "dark"
    assert data["hooks"]["PreToolUse"][0] == foreign
    assert len(data["hooks"]["PreToolUse"]) == 2


def test_existing_blocker_makes_it_skip_with_note(repo: Path) -> None:
    entry = {"matcher": "Bash", "hooks": [{"type": "command", "command": ".claude/hooks/dangerous-actions-blocker.sh"}]}
    (repo / ".claude").mkdir()
    (repo / SETTINGS).write_text(json.dumps({"hooks": {"PreToolUse": [entry]}}))
    before = (repo / SETTINGS).read_bytes()
    out = install_sdd_integration(repo)
    assert any(a.startswith("note:") and "dangerous-actions-blocker" in a for a in out)
    assert (repo / SETTINGS).read_bytes() == before


def test_opt_out_adds_nothing(repo: Path) -> None:
    install_sdd_integration(repo, dangerous_guard=False)
    assert not (repo / SETTINGS).exists() or _ours(repo) == []
    assert sdd_status(repo)["dangerous_guard"]["form"] is None


def test_dry_run_writes_nothing(repo: Path) -> None:
    out = install_sdd_integration(repo, dry_run=True)
    assert any(a.startswith("plan: dangerous-guard") for a in out)
    assert not (repo / SETTINGS).exists()


def test_non_claude_host_gets_no_guard(repo: Path) -> None:
    out = install_sdd_integration(repo, ["codex"], dry_run=True)
    assert not any("dangerous-guard" in a for a in out)


def test_uninstall_removes_only_our_entry(repo: Path) -> None:
    foreign = {"matcher": "Bash", "hooks": [{"type": "command", "command": "my-linter --check"}]}
    (repo / ".claude").mkdir()
    (repo / SETTINGS).write_text(json.dumps({"hooks": {"PreToolUse": [foreign]}}))
    install_sdd_integration(repo)
    uninstall_sdd_integration(repo)
    assert _entries(repo) == [foreign]


def test_uninstall_ignores_entry_not_recorded_in_receipt(repo: Path) -> None:
    (repo / ".claude").mkdir()
    mine = {"matcher": "Bash", "hooks": [{"type": "command", "command": DANGEROUS_HOOK_LINE}]}
    (repo / SETTINGS).write_text(json.dumps({"hooks": {"PreToolUse": [mine]}}))
    install_sdd_integration(repo, dangerous_guard=False)
    uninstall_sdd_integration(repo)
    assert _ours(repo) == [mine]
