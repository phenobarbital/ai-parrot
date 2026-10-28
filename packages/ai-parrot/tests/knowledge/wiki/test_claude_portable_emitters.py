"""FEAT-633 TASK-4081 — Claude Code emitters: Windows script paths + portable form."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest
from parrot.knowledge.wiki.claude_code import assets, bookstore
from parrot.mcp.toolkit_config import ToolkitSection


def _strings(value: Any) -> Iterator[str]:
    """Yield every string nested in an emitted entry (keys excluded)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _assert_no_abs_paths(entry: Any, root: Path) -> None:
    for text in _strings(entry):
        assert not os.path.isabs(text), text
        assert str(root) not in text and sys.executable not in text, text


def _section() -> ToolkitSection:
    return ToolkitSection(**{"class": "parrot_tools.fake.FakeToolkit"})


def test_portable_entries_no_abs_paths(tmp_path: Path) -> None:
    """Spec §4: portable wikitoolkit/toolkit/bookstore entries + hook carry no absolute path."""
    entries = [
        assets.mcp_json_entry(tmp_path, portable=True),
        assets.toolkit_mcp_json_entry(tmp_path, "memory", _section(), portable=True),
        bookstore.mcp_json_entry(tmp_path, portable=True),
        assets.hook_command(tmp_path, portable=True),
    ]
    for entry in entries:
        _assert_no_abs_paths(entry, tmp_path)
    assert bookstore.mcp_json_entry(tmp_path, portable=True)["command"] == "bookstore"
    assert "cwd" not in assets.toolkit_mcp_json_entry(tmp_path, "memory", _section(), portable=True)


def test_portable_entries_root_independent(tmp_path: Path) -> None:
    """Two roots produce identical portable entries (committable)."""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert assets.mcp_json_entry(a, portable=True) == assets.mcp_json_entry(b, portable=True)
    assert bookstore.mcp_json_entry(a, portable=True) == bookstore.mcp_json_entry(b, portable=True)


def test_default_emission_unchanged(tmp_path: Path) -> None:
    """Spec §4: without portable, emitters return exactly today's shapes."""
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "wikitoolkit").write_text("")
    (venv_bin / "parrot").write_text("")
    assert assets.mcp_json_entry(tmp_path) == {"command": str(venv_bin / "wikitoolkit"), "args": ["mcp"], "env": {}}
    assert bookstore.mcp_json_entry(tmp_path) == {
        "command": sys.executable,
        "args": ["-m", "parrot.knowledge.bookstore.cli", "mcp"],
        "cwd": str(tmp_path.resolve()),
        "env": {},
    }
    assert assets.toolkit_mcp_json_entry(tmp_path, "memory", _section()) == {
        "command": str(venv_bin / "parrot"),
        "args": ["mcp-local", "memory", "--config", str(tmp_path / ".parrot" / "mcp-toolkits.yaml")],
        "cwd": str(tmp_path),
        "env": {},
    }
    assert assets.permission_rules(tmp_path)[-1] == f"Bash({venv_bin / 'wikitoolkit'}:*)"
    assert assets.permission_rules(tmp_path, portable=True) == assets.PERMISSION_RULES


def test_windows_scripts_branch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A Windows venv (Scripts\\<name>.exe) is resolved through launcher.script_path."""
    monkeypatch.setattr(assets, "script_path", lambda venv, name: venv / "Scripts" / f"{name}.exe")
    exe = tmp_path / ".venv" / "Scripts" / "wikitoolkit.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert assets.resolve_wikitoolkit_bin(tmp_path) == str(exe)


def test_bookstore_managed_detection_accepts_portable() -> None:
    assert bookstore._is_managed_entry({"command": "bookstore", "args": ["mcp"], "env": {}})
    assert bookstore._is_managed_entry({"command": "/x/python", "args": ["-m", "parrot.knowledge.bookstore.cli", "mcp"]})
    assert not bookstore._is_managed_entry({"command": "my-bookstore", "args": ["mcp"]})


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs sh")
@pytest.mark.parametrize(
    "build",
    [assets.git_hook_block, lambda root: assets.ledger_hook_block(root, "post-merge")],
    ids=["git_hook_block", "ledger_hook_block"],
)
def test_hook_windows_path_survives_sh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, build: Callable[[Path], str]
) -> None:
    """Spec rev 0.5 C24: a Windows-style binary path in a hook body survives `sh` (quoted, forward slashes)."""
    monkeypatch.setattr(assets, "resolve_wikitoolkit_bin", lambda root: "C:\\r\\.venv\\Scripts\\wikitoolkit.exe")
    line = next(
        text for text in build(tmp_path).splitlines() if "wikitoolkit" in text and not text.lstrip().startswith("#")
    )
    token = line.strip().split(" ", 1)[0]  # the (quoted) binary path; the test path has no spaces
    out = subprocess.run(["sh", "-c", f'printf "%s" {token}'], capture_output=True, text=True, check=True).stdout
    assert out == "C:/r/.venv/Scripts/wikitoolkit.exe"


def test_hook_bodies_quote_and_use_forward_slashes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """[rev 0.5] D6: a Windows path is quoted and slash-normalised; a plain POSIX path is unchanged."""
    monkeypatch.setattr(assets, "resolve_wikitoolkit_bin", lambda root: r"C:\Users\A B\.venv\Scripts\wikitoolkit.exe")
    want = "'C:/Users/A B/.venv/Scripts/wikitoolkit.exe'"
    assert f"    {want} upsert --changed" in assets.git_hook_block(tmp_path)
    for event in assets.LEDGER_HOOK_EVENTS:
        if event == "pre-commit":  # FEAT-758: an intentional no-op block, it runs no binary
            assert want not in assets.ledger_hook_block(tmp_path, event)
            continue
        assert assets.ledger_hook_block(tmp_path, event).splitlines()[3].startswith(f"{want} ledger ")
    monkeypatch.setattr(assets, "resolve_wikitoolkit_bin", lambda root: "/opt/repo/.venv/bin/wikitoolkit")
    assert "    /opt/repo/.venv/bin/wikitoolkit upsert --changed" in assets.git_hook_block(tmp_path)
