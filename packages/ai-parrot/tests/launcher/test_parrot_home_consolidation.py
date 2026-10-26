"""All three PARROT_HOME readers agree with parrot.launcher.parrot_home (FEAT-633, TASK-4073)."""
from __future__ import annotations

import subprocess
import sys

import pytest

from parrot.cli.modes import cli_state_dir
from parrot.knowledge.bookstore.config import _parrot_home
from parrot.knowledge.wiki.project import parrot_home
from parrot.launcher import parrot_home as launcher_parrot_home  # created by TASK-4071


@pytest.mark.parametrize("value", [None, "", "~/custom-home", "ABS"])
def test_three_readers_identical(value, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    if value is None:
        monkeypatch.delenv("PARROT_HOME", raising=False)
    else:
        monkeypatch.setenv("PARROT_HOME", str(tmp_path / "abs-home") if value == "ABS" else value)
    expected = launcher_parrot_home()
    assert parrot_home() == expected
    assert _parrot_home() == expected
    assert cli_state_dir() == expected / "cli"


def test_default_and_tilde_semantics(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PARROT_HOME", "")
    assert parrot_home() == tmp_path / ".parrot"             # empty ⇒ default (``or`` semantics)
    monkeypatch.setenv("PARROT_HOME", "~/x")
    assert _parrot_home() == tmp_path / "x"                  # ``~`` expanded
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "link"))
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    assert parrot_home() == tmp_path / "link"                # NOT resolved


def test_bookstore_config_does_not_import_wiki_chain():
    code = (
        "import sys, parrot.knowledge.bookstore.config; "
        "print(any(m.startswith('parrot.knowledge.wiki') for m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=120).stdout
    assert out.strip() == "False"
