"""FEAT-609 M1: the missing structural tier is loud, in build and in status."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki import cli
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.languages import astgrep
from parrot.knowledge.wiki.languages.render import set_structural_enabled
from parrot.knowledge.wiki.repo_scan import scan_repository

from .languages.conftest import requires_astgrep


def _scan(tmp_path: Path, files: dict[str, str]):
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return scan_repository(tmp_path, use_git=False)


@pytest.fixture
def no_astgrep(monkeypatch):
    monkeypatch.setattr(astgrep, "is_available", lambda: False)
    astgrep.RuleSet.load.cache_clear()
    yield
    astgrep.RuleSet.load.cache_clear()


def test_structural_gap_warning_text(tmp_path, no_astgrep) -> None:
    warning = cli._structural_gap_warning(_scan(tmp_path, {"a.ts": "export function f() {}\n"}))
    assert warning is not None
    assert "javascript" in warning and "wiki-languages" in warning
    assert warning.startswith("1 javascript file(s)")


def test_no_warning_for_python_only(tmp_path, no_astgrep) -> None:
    assert cli._structural_gap_warning(_scan(tmp_path, {"a.py": "def f():\n    pass\n"})) is None


def test_no_warning_when_kill_switch_off(tmp_path, no_astgrep) -> None:
    set_structural_enabled(False)
    try:
        assert cli._structural_gap_warning(_scan(tmp_path, {"a.ts": "const x = 1\n"})) is None
    finally:
        set_structural_enabled(True)


@requires_astgrep
def test_no_warning_when_astgrep_available(tmp_path) -> None:
    assert cli._structural_gap_warning(_scan(tmp_path, {"a.ts": "const x = 1\n"})) is None


def test_build_warns_exactly_once(tmp_path, no_astgrep) -> None:
    (tmp_path / "a.ts").write_text("export function f() {}\n", encoding="utf-8")
    (tmp_path / "b.ts").write_text("export function g() {}\n", encoding="utf-8")
    result = CliRunner().invoke(wiki, ["build", "--path", str(tmp_path), "--no-git"])
    assert result.exit_code == 0, result.output
    assert result.stderr.count("wiki-languages") == 1
    assert "2 javascript file(s)" in result.stderr


def test_status_symbols_line(tmp_path, no_astgrep) -> None:
    (tmp_path / "a.ts").write_text("export function f() {}\n", encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(wiki, ["build", "--path", str(tmp_path), "--no-git"]).exit_code == 0
    result = runner.invoke(wiki, ["status", "--path", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Symbols   : disabled for" in result.output
    assert "wiki-languages" in result.output
    payload = json.loads(runner.invoke(wiki, ["status", "--path", str(tmp_path), "--json"]).output)
    assert payload["symbols"]["enabled"] is False
    assert "javascript" in payload["symbols"]["disabled_for"]


@requires_astgrep
def test_status_symbols_enabled_and_predictive(tmp_path) -> None:
    (tmp_path / "a.ts").write_text("export function f() {}\n", encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(wiki, ["build", "--path", str(tmp_path), "--no-git"]).exit_code == 0
    result = runner.invoke(wiki, ["status", "--path", str(tmp_path)])
    assert "Symbols   : enabled" in result.output
    assert "'javascript': 'ast-grep'" in result.output


@requires_astgrep
def test_status_kill_switch_line(tmp_path) -> None:
    (tmp_path / "a.ts").write_text("export function f() {}\n", encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(wiki, ["build", "--path", str(tmp_path), "--no-git"]).exit_code == 0
    set_structural_enabled(False)
    try:
        result = runner.invoke(wiki, ["status", "--path", str(tmp_path)])
    finally:
        set_structural_enabled(True)
    assert "disabled by configuration" in result.output
