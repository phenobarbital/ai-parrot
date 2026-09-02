"""`scripts/sdd/lint_new.py` — ruff findings the branch introduced (FEAT-497 Module 2).

Drives ``main()`` against a real ``tmp_path`` git repo so ``git diff``/``git
ls-files`` behave exactly as they would in a feature worktree.
"""

from __future__ import annotations

import subprocess

import pytest

from scripts.sdd import lint_new
from scripts.sdd.lint_new import main


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A real git repo on a branch forked from `dev`-shaped history."""

    def run(*args):
        subprocess.run(args, cwd=tmp_path, check=True, capture_output=True)

    run("git", "init", "-q", "-b", "dev")
    run("git", "config", "user.email", "t@t.t")
    run("git", "config", "user.name", "t")
    # Deterministic baseline violation regardless of ambient ruff config.
    (tmp_path / "ruff.toml").write_text('[lint]\nselect = ["E", "F", "I", "UP"]\n')
    (tmp_path / "mod.py").write_text("from typing import Dict\n\nX: Dict = {}\n")
    run("git", "add", "-A")
    run("git", "commit", "-qm", "baseline")
    run("git", "checkout", "-qb", "feature")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_no_paths_exits_zero(capsys):
    assert main([]) == 0


def test_pre_existing_finding_on_unchanged_line_is_ignored(repo, capsys):
    """Baseline mod.py carries UP035; the branch appends a clean line → exit 0."""
    (repo / "mod.py").write_text("from typing import Dict\n\nX: Dict = {}\nY = 1\n")
    assert main(["--base", "dev", "mod.py"]) == 0
    assert "pre-existing finding(s)" in capsys.readouterr().out


def test_new_finding_on_added_line_fails(repo, capsys):
    """Branch adds a line with an F401-style violation → exit 1, finding printed."""
    (repo / "mod.py").write_text("from typing import Dict\nimport os\n\nX: Dict = {}\n")  # os unused → F401
    assert main(["--base", "dev", "mod.py"]) == 1
    assert "F401" in capsys.readouterr().out


def test_i001_import_block_is_attributed_to_the_added_import(repo, capsys):
    """Adding an out-of-order import → I001 reported even though its row (1) is unchanged (G4)."""
    (repo / "mod.py").write_text("from typing import Dict\nimport aaa\n\nX: Dict = {}\n")
    assert main(["--base", "dev", "mod.py"]) == 1
    assert "I001" in capsys.readouterr().out


def test_untracked_file_counts_as_fully_added(repo, capsys):
    (repo / "new.py").write_text("import os\n")  # F401
    assert main(["--base", "dev", "new.py"]) == 1


def test_ruff_failure_exits_two(repo, monkeypatch, capsys):
    monkeypatch.setattr(lint_new, "_ruff_findings", lambda paths: None)
    assert main(["--base", "dev", "mod.py"]) == 2
