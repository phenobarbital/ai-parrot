"""Tests for the bookstore CLI (scope resolution and guards)."""

from __future__ import annotations

from click.testing import CliRunner

from parrot.knowledge.bookstore import cli as bookstore_cli
from parrot.knowledge.bookstore.config import ENV_LIBRARY_DIR


def _make_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    return repo


def test_locations_resolves_from_invocation_cwd(tmp_path, monkeypatch):
    """The CLI must resolve the project scope from the directory the
    user invoked it in — captured before any heavy import can chdir()
    the process (the navconfig import side effect)."""
    repo = _make_repo(tmp_path)
    monkeypatch.delenv(ENV_LIBRARY_DIR, raising=False)
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(bookstore_cli, "_INVOCATION_CWD", str(repo))
    # Simulate the post-import chdir: the process CWD is somewhere else
    # entirely; resolution must NOT look at it.
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(bookstore_cli.bookstore, ["locations"])
    assert result.exit_code == 0, result.output
    assert str(repo / ".parrot" / "library") in result.output
    assert str(tmp_path / "home" / "library") in result.output


def test_add_outside_repo_gives_clear_error(tmp_path, monkeypatch):
    lone = tmp_path / "nowhere"
    lone.mkdir()
    book = lone / "b.md"
    book.write_text("# B\n\ncontent\n", encoding="utf-8")
    monkeypatch.delenv(ENV_LIBRARY_DIR, raising=False)
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(bookstore_cli, "_INVOCATION_CWD", str(lone))
    result = CliRunner().invoke(
        bookstore_cli.bookstore, ["add", str(book), "--no-llm"]
    )
    assert result.exit_code != 0
    assert "--global" in result.output


def test_add_anchors_relative_path_to_invocation_cwd(tmp_path, monkeypatch):
    """A relative FILE must resolve against the invocation directory,
    not whatever CWD the heavy imports later chdir() the process into
    (the navconfig import side effect). The chdir is simulated inside
    _open_bookstore — after click parsing, before add_book — which is
    exactly where it happens in real life."""
    import os

    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "b.md").write_text(
        "# B\n\nEnough content to clear the markdown thinning threshold "
        "for this synthetic single-chapter book fixture.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(ENV_LIBRARY_DIR, str(tmp_path / "lib"))
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(bookstore_cli, "_INVOCATION_CWD", str(workdir))
    monkeypatch.chdir(workdir)

    real_open = bookstore_cli._open_bookstore

    def _chdir_then_open(*args, **kwargs):
        os.chdir(tmp_path)  # what the navconfig import chain does
        return real_open(*args, **kwargs)

    monkeypatch.setattr(bookstore_cli, "_open_bookstore", _chdir_then_open)
    result = CliRunner().invoke(
        bookstore_cli.bookstore, ["add", "b.md", "--no-llm"]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "lib" / "trees" / "b.json").is_file()


SAMPLE_BOOK = (
    "# Sample\n\nEnough content to clear the markdown thinning threshold "
    "for this synthetic single-chapter book fixture used by the CLI tests.\n"
)


def _books_folder(tmp_path):
    root = tmp_path / "books"
    root.mkdir()
    (root / "one.md").write_text(SAMPLE_BOOK, encoding="utf-8")
    (root / "two.md").write_text(SAMPLE_BOOK + "\nDifferent sha.\n", encoding="utf-8")
    (root / "cover.png").write_bytes(b"x")
    return root


def test_add_folder_dry_run_changes_nothing(tmp_path, monkeypatch):
    root = _books_folder(tmp_path)
    monkeypatch.setenv(ENV_LIBRARY_DIR, str(tmp_path / "lib"))
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(bookstore_cli, "_INVOCATION_CWD", str(tmp_path))
    result = CliRunner().invoke(
        bookstore_cli.bookstore, ["add-folder", str(root), "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert "Would index 2 file(s)" in result.output
    assert "cover.png" in result.output
    assert not (tmp_path / "lib").exists()


def test_add_folder_ingests_all_supported_files(tmp_path, monkeypatch):
    root = _books_folder(tmp_path)
    monkeypatch.setenv(ENV_LIBRARY_DIR, str(tmp_path / "lib"))
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(bookstore_cli, "_INVOCATION_CWD", str(tmp_path))
    result = CliRunner().invoke(
        bookstore_cli.bookstore, ["add-folder", str(root), "--no-llm"]
    )
    assert result.exit_code == 0, result.output
    assert "added: 2" in result.output
    assert (tmp_path / "lib" / "trees" / "one.json").is_file()
    assert (tmp_path / "lib" / "trees" / "two.json").is_file()
    # Re-run: sha dedupe skips everything.
    rerun = CliRunner().invoke(
        bookstore_cli.bookstore, ["add-folder", str(root), "--no-llm"]
    )
    assert rerun.exit_code == 0, rerun.output
    assert "skipped: 2" in rerun.output


def test_add_folder_relative_path_anchors_to_invocation_cwd(
    tmp_path, monkeypatch
):
    root = _books_folder(tmp_path)
    monkeypatch.setenv(ENV_LIBRARY_DIR, str(tmp_path / "lib"))
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(bookstore_cli, "_INVOCATION_CWD", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        bookstore_cli.bookstore, ["add-folder", "books", "--no-llm"]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "lib" / "trees" / "one.json").is_file()


def test_list_requires_existing_library(tmp_path, monkeypatch):
    lone = tmp_path / "nowhere"
    lone.mkdir()
    monkeypatch.delenv(ENV_LIBRARY_DIR, raising=False)
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(bookstore_cli, "_INVOCATION_CWD", str(lone))
    result = CliRunner().invoke(bookstore_cli.bookstore, ["list"])
    assert result.exit_code != 0
    assert "No library found" in result.output
