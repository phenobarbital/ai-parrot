"""Unit tests for parrot.launcher resolution (FEAT-633 M1, TASK-4071)."""
from __future__ import annotations

from pathlib import Path

import pytest

from parrot import launcher  # created by this task


def make_venv(path: Path, *scripts: str) -> Path:
    """Fake venv: pyvenv.cfg + empty POSIX script stubs."""
    (path / "bin").mkdir(parents=True)
    (path / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    for name in scripts:
        (path / "bin" / name).write_text("#!/bin/sh\n", encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _reset_warnings(monkeypatch):
    monkeypatch.setattr(launcher, "_WARNED", set())


@pytest.fixture
def linked_worktree_repo(tmp_path: Path) -> tuple[Path, Path]:
    """main checkout (real .git dir) + linked worktree (.git FILE with gitdir:, admin dir with commondir)."""
    main = tmp_path / "main"
    admin = main / ".git" / "worktrees" / "wt"
    admin.mkdir(parents=True)
    (admin / "commondir").write_text("../..\n", encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {admin}\n", encoding="utf-8")
    return main, wt


def test_parrot_home_env_default_and_tilde(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert launcher.parrot_home({}) == tmp_path / ".parrot"
    assert launcher.parrot_home({"PARROT_HOME": ""}) == tmp_path / ".parrot"
    assert launcher.parrot_home({"PARROT_HOME": "~/x"}) == tmp_path / "x"


def test_launcher_not_managed(tmp_path):
    env = {"PARROT_HOME": str(tmp_path / "home")}
    assert launcher.is_managed(str(tmp_path / "other"), env=env) is False
    assert launcher.is_managed(str(tmp_path / "home" / "venv"), env=env) is True


def test_resolve_order_and_validity(tmp_path):
    home, proj = tmp_path / "home", tmp_path / "proj"
    make_venv(home / "venv", "wikitoolkit")
    (proj / ".git").mkdir(parents=True)
    make_venv(proj / ".venv", "wikitoolkit")
    explicit = make_venv(tmp_path / "explicit", "wikitoolkit")
    ve = make_venv(tmp_path / "ve", "wikitoolkit")
    env = {"PARROT_HOME": str(home), "PARROT_VENV": str(explicit), "VIRTUAL_ENV": str(ve)}
    assert launcher.resolve_venv("wikitoolkit", argv=[], env=env, cwd=proj)[1] == "PARROT_VENV"
    env.pop("PARROT_VENV")
    assert launcher.resolve_venv("wikitoolkit", argv=[], env=env, cwd=proj) == (proj / ".venv", "project")
    (proj / ".venv" / "bin" / "wikitoolkit").unlink()
    assert launcher.resolve_venv("wikitoolkit", argv=[], env=env, cwd=proj) == (ve, "VIRTUAL_ENV")
    env.pop("VIRTUAL_ENV")
    assert launcher.resolve_venv("wikitoolkit", argv=[], env=env, cwd=proj) == (home / "venv", "managed")


def test_worktree_prefers_local_then_main(linked_worktree_repo, tmp_path):
    main, wt = linked_worktree_repo
    make_venv(main / ".venv", "parrot")
    env = {"PARROT_HOME": str(tmp_path / "home")}
    assert launcher.resolve_venv("parrot", argv=[], env=env, cwd=wt)[0].resolve() == (main / ".venv").resolve()
    make_venv(wt / ".venv", "parrot")
    assert launcher.resolve_venv("parrot", argv=[], env=env, cwd=wt)[0] == wt / ".venv"


def test_script_path_windows(tmp_path):
    assert launcher.script_path(tmp_path, "bookstore", os_name="nt").parts[-2:] == ("Scripts", "bookstore.exe")
    assert launcher.script_path(tmp_path, "bookstore", os_name="posix") == tmp_path / "bin" / "bookstore"


def test_warn_once_per_session(tmp_path, capsys):
    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    make_venv(proj / ".venv")                      # venv WITHOUT the script
    env = {"PARROT_HOME": str(tmp_path / "home")}
    for _ in range(3):
        launcher.resolve_venv("wikitoolkit", argv=[], env=env, cwd=proj)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("\n") == 1


def test_walk_up_stops_at_temp_root(tmp_path, monkeypatch):
    """rev 0.5 C24: a stray `.git` in the system temp dir never becomes the project (mirrors wiki.project)."""
    fake_tmp = tmp_path / "systmp"
    (fake_tmp / ".git").mkdir(parents=True)
    cwd = fake_tmp / "a" / "b"
    cwd.mkdir(parents=True)
    monkeypatch.setattr(launcher.tempfile, "gettempdir", lambda: str(fake_tmp))
    assert launcher.find_project_root([], {}, cwd) is None
    assert launcher.repository_paths(cwd) == (cwd.resolve(), None)


def test_find_project_root_precedence(tmp_path):
    a, b, c, d = (tmp_path / n for n in "abcd")
    for p in (a, b, c):
        p.mkdir()
    (d / ".git").mkdir(parents=True)
    env = {"PARROT_PROJECT": str(b), "CLAUDE_PROJECT_DIR": str(c)}
    assert launcher.find_project_root(["--project", str(a)], env, d) == a.resolve()
    assert launcher.find_project_root([f"--project={a}"], env, d) == a.resolve()
    assert launcher.find_project_root([], env, d) == b.resolve()
    assert launcher.find_project_root([], {"CLAUDE_PROJECT_DIR": str(c)}, d) == c.resolve()
    assert launcher.find_project_root([], {}, d) == d
    # non-leading --project belongs to a wikitoolkit subcommand
    assert launcher.find_project_root(["build", "--project", str(a)], {}, d) == d
    # a pinned root that does not exist falls through
    assert launcher.find_project_root([], {"PARROT_PROJECT": str(tmp_path / "nope")}, d) == d


def test_malformed_git_file_does_not_crash(tmp_path):
    (tmp_path / ".git").write_text("garbage\n", encoding="utf-8")
    assert launcher.repository_paths(tmp_path) == (tmp_path.resolve(), None)
    assert launcher.find_project_root([], {}, tmp_path) == tmp_path
    env = {"PARROT_HOME": str(tmp_path / "home")}
    assert launcher.resolve_venv("parrot", argv=[], env=env, cwd=tmp_path)[1] == "managed"


def test_managed_venv_never_returned_as_virtual_env(tmp_path):
    home = tmp_path / "home"
    make_venv(home / "venv", "parrot")
    env = {"PARROT_HOME": str(home), "VIRTUAL_ENV": str(home / "venv")}
    assert launcher.resolve_venv("parrot", argv=[], env=env, cwd=tmp_path) == (home / "venv", "managed")
