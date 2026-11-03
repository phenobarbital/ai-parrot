"""FEAT-795 M1 — stale SDD file detection."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from parrot.sdd.installer import RECEIPT_PATH, SUPPORTED_HOSTS, install_sdd_integration
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
