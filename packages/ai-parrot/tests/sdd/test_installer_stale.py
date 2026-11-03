"""FEAT-795 M1 — stale SDD file detection."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from parrot.sdd.installer import (
    RECEIPT_PATH,
    SUPPORTED_HOSTS,
    install_sdd_integration,
    remove_stale_sdd_files,
    sdd_status,
    uninstall_sdd_integration,
)
from parrot.sdd.stale import SOURCE_CHECKOUT_MARKER, find_stale, is_source_checkout


@pytest.fixture
def gemini(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the user-global Gemini MCP file away from the real home directory."""
    path = tmp_path / "gemini_home" / "mcp_config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    monkeypatch.setattr("parrot.knowledge.wiki.google.assets.default_mcp_config_path", lambda: path)
    return path


@pytest.fixture
def stale_repo(tmp_path: Path, gemini: Path) -> Path:
    """Return a fully-installed repository augmented with representative stale files."""
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    install_sdd_integration(root, SUPPORTED_HOSTS, sdd_coder=False)
    for relative in (
        "scripts/sdd/reserve_ids.py",
        "scripts/sdd/__pycache__/x.pyc",
        "scripts/sdd/.collision_baseline.json",
        ".claude/rules/worktree-status.md",
        ".agent/agents/sdd-worker/agent.md",
        ".claude/commands/sdd-insight.md",
        ".claude/commands/sdd-dropped.md",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stale\n", encoding="utf-8")
    receipt_path = root / RECEIPT_PATH
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["files"][".claude/commands/sdd-dropped.md"] = "dropped"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return root


def _paths(entries: list) -> dict[str, str]:
    """Map stale paths to their selected reasons."""
    return {entry.path: entry.reason for entry in entries}


def test_receipt_orphan_detected(stale_repo: Path) -> None:
    """Receipt-only dropped assets are reported as receipt orphans."""
    assert _paths(find_stale(stale_repo))[".claude/commands/sdd-dropped.md"] == "receipt-orphan"


def test_retired_scripts_sdd_tree(stale_repo: Path) -> None:
    """All retired helper-tree files, including hidden and cache files, are detected."""
    paths = _paths(find_stale(stale_repo))
    assert paths["scripts/sdd/reserve_ids.py"] == "retired"
    assert paths["scripts/sdd/__pycache__/x.pyc"] == "retired"
    assert paths["scripts/sdd/.collision_baseline.json"] == "retired"


def test_legacy_agent_layout_google_only(stale_repo: Path) -> None:
    """The legacy Google agent layout is ignored for non-Google hosts."""
    assert ".agent/agents/sdd-worker/agent.md" in _paths(find_stale(stale_repo, ("google",)))
    assert ".agent/agents/sdd-worker/agent.md" not in _paths(find_stale(stale_repo, ("claude",)))


def test_sdd_prefix_orphan_file_and_dir(stale_repo: Path) -> None:
    """A prefix orphan file and every file below a prefix orphan directory are reported."""
    directory_file = stale_repo / ".agents/skills/sdd-custom/SKILL.md"
    directory_file.parent.mkdir(parents=True)
    directory_file.write_text("custom\n", encoding="utf-8")
    paths = _paths(find_stale(stale_repo))
    assert paths[".claude/commands/sdd-insight.md"] == "sdd-orphan"
    assert paths[".agents/skills/sdd-custom/SKILL.md"] == "sdd-orphan"


def test_current_targets_and_seeds_never_stale(tmp_path: Path, gemini: Path) -> None:
    """A fresh full installation contains no stale assets or state."""
    root = tmp_path / "fresh"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    install_sdd_integration(root, SUPPORTED_HOSTS, sdd_coder=False)
    assert find_stale(root) == []


def test_non_sdd_files_untouched(stale_repo: Path) -> None:
    """Normal host configuration and non-SDD files are never selected."""
    paths = _paths(find_stale(stale_repo))
    assert ".codex/config.toml" not in paths
    assert ".codex/skills/parrot-wiki/SKILL.md" not in paths
    assert ".claude/rules/python-development.md" not in paths


def test_reason_precedence(stale_repo: Path) -> None:
    """A receipt orphan wins over an overlapping retired pattern."""
    receipt_path = stale_repo / RECEIPT_PATH
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["files"]["scripts/sdd/reserve_ids.py"] = "retired"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    assert _paths(find_stale(stale_repo))["scripts/sdd/reserve_ids.py"] == "receipt-orphan"


def test_symlink_not_followed(stale_repo: Path, tmp_path: Path) -> None:
    """A retired symlink is reported once without walking its target directory."""
    scripts = stale_repo / "scripts"
    for path in sorted((scripts / "sdd").rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    (scripts / "sdd").rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "not-walked.py").write_text("outside\n", encoding="utf-8")
    os.symlink(outside, scripts / "sdd")
    entries = find_stale(stale_repo)
    assert [(entry.path, entry.symlink) for entry in entries if entry.path.startswith("scripts/sdd")] == [
        ("scripts/sdd", True)
    ]


def test_source_checkout_detected(tmp_path: Path) -> None:
    """Only a root containing the packaged-manifest marker is a source checkout."""
    assert not is_source_checkout(tmp_path)
    marker = tmp_path / SOURCE_CHECKOUT_MARKER
    marker.parent.mkdir(parents=True)
    marker.write_text("{}", encoding="utf-8")
    assert is_source_checkout(tmp_path)


def test_retired_remove_worktree_script(stale_repo: Path) -> None:
    """The previous standalone worktree remover is retired for every host."""
    path = stale_repo / "scripts/remove_worktree.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("legacy\n", encoding="utf-8")
    assert _paths(find_stale(stale_repo))["scripts/remove_worktree.py"] == "retired"


def test_unknown_host_raises(stale_repo: Path) -> None:
    """Unsupported host names are rejected before scanning the filesystem."""
    with pytest.raises(ValueError, match="unknown host"):
        find_stale(stale_repo, ("unknown",))


def test_remove_stale_removes_and_prunes(stale_repo: Path) -> None:
    """Stale files and their empty parents are removed without changing current assets."""
    current_asset = stale_repo / "sdd/WORKFLOW.md"
    current_bytes = current_asset.read_bytes()

    actions = remove_stale_sdd_files(stale_repo)

    assert not (stale_repo / "scripts/sdd").exists()
    assert not (stale_repo / ".agent/agents/sdd-worker").exists()
    assert current_asset.read_bytes() == current_bytes
    assert any("scripts/sdd/reserve_ids.py — removed (retired)" in action for action in actions)
    assert actions[-1].startswith("note: commit the deletions")


def test_remove_stale_updates_receipt(stale_repo: Path) -> None:
    """Removing a receipt orphan drops only its stale receipt key and keeps the receipt."""
    receipt_path = stale_repo / RECEIPT_PATH
    before = json.loads(receipt_path.read_text(encoding="utf-8"))

    remove_stale_sdd_files(stale_repo)

    after = json.loads(receipt_path.read_text(encoding="utf-8"))
    expected_files = dict(before["files"])
    expected_files.pop(".claude/commands/sdd-dropped.md")
    assert after["files"] == expected_files
    assert receipt_path.is_file()


def test_remove_stale_keep_glob(stale_repo: Path, tmp_path: Path) -> None:
    """Keep globs and symlink safeguards preserve matching stale entries."""
    kept = stale_repo / ".claude/commands/sdd-team-local.md"
    kept.write_text("team command\n", encoding="utf-8")
    outside = tmp_path / "outside-rule.md"
    outside.write_text("outside\n", encoding="utf-8")
    symlink = stale_repo / ".claude/rules/worktree-start-feature.md"
    os.symlink(outside, symlink)

    actions = remove_stale_sdd_files(stale_repo, keep=(".claude/commands/sdd-team-*",))

    assert kept.read_text(encoding="utf-8") == "team command\n"
    assert symlink.is_symlink()
    assert ".claude/commands/sdd-team-local.md — kept (--keep)" in actions
    assert "warning: .claude/rules/worktree-start-feature.md — symlink; kept" in actions


def test_remove_stale_dry_run_writes_nothing(stale_repo: Path) -> None:
    """A stale-removal dry run leaves every repository file byte-identical."""

    def snapshot() -> dict[str, bytes]:
        return {
            path.relative_to(stale_repo).as_posix(): path.read_bytes()
            for path in stale_repo.rglob("*")
            if path.is_file()
        }

    before = snapshot()
    actions = remove_stale_sdd_files(stale_repo, dry_run=True)

    assert snapshot() == before
    assert actions
    assert all(action.startswith("plan:") for action in actions)


def test_remove_stale_refuses_source_checkout(stale_repo: Path) -> None:
    """Source checkouts reject real deletion while retaining an inspectable dry run."""
    marker = stale_repo / SOURCE_CHECKOUT_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="refusing:.*source checkout"):
        remove_stale_sdd_files(stale_repo)

    assert remove_stale_sdd_files(stale_repo, dry_run=True)[0].startswith("note:")
    assert (stale_repo / "scripts/sdd/reserve_ids.py").is_file()


def test_install_reports_stale_note(stale_repo: Path) -> None:
    """Install reports stale files once without deleting them."""
    orphan = stale_repo / "scripts/sdd/reserve_ids.py"

    actions = install_sdd_integration(stale_repo, ("claude",), sdd_coder=False)

    notes = [action for action in actions if "stale SDD file(s)" in action]
    assert len(notes) == 1
    assert notes[0].startswith("note:")
    assert orphan.read_text(encoding="utf-8") == "stale\n"


def test_status_reports_stale(stale_repo: Path) -> None:
    """Status exposes serialized stale-file entries and the stale-MCP key."""
    report = sdd_status(stale_repo)

    assert any(entry["path"] == "scripts/sdd/reserve_ids.py" for entry in report["stale"])
    assert "stale_mcp" in report
    assert isinstance(report["stale_mcp"], list)


def test_plain_uninstall_unchanged(stale_repo: Path) -> None:
    """Plain uninstall continues to leave stale files outside its manifest plan untouched."""
    orphan = stale_repo / "scripts/sdd/reserve_ids.py"
    dropped = stale_repo / ".claude/commands/sdd-dropped.md"

    uninstall_sdd_integration(stale_repo, ("claude",))

    assert orphan.read_text(encoding="utf-8") == "stale\n"
    assert dropped.read_text(encoding="utf-8") == "stale\n"
