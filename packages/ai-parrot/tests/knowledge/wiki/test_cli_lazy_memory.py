"""Regression tests for lazy wikitoolkit memory command registration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from parrot.knowledge.wiki.cli import wiki

REPOSITORY_ROOT = Path(__file__).parents[5]


def _run_cli(arguments: list[str]) -> dict[str, Any]:
    """Run a fresh CLI process and return its one-line JSON result."""
    code = f"""
import json
import sys

from click.testing import CliRunner
from parrot.knowledge.wiki.cli import wiki

result = CliRunner().invoke(wiki, {arguments!r})
memory_loaded = any(
    module == \"parrot.memory\" or module.startswith(\"parrot.memory.\")
    for module in sys.modules
)
print(json.dumps({{
    \"exit_code\": result.exit_code,
    \"memory_loaded\": memory_loaded,
    \"has_storage_path\": \"--storage-path\" in result.output,
}}))
"""
    # The child must import the same ``parrot`` tree as this process: in a git
    # worktree the shared venv's editable install points at the main checkout.
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(entry for entry in sys.path if entry)}
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_wikitoolkit_commands_do_not_import_parrot_memory() -> None:
    """Verify a non-memory command leaves the memory package unloaded."""
    result = _run_cli(["status", "--help"])

    assert result["exit_code"] == 0
    assert result["memory_loaded"] is False


def test_memory_group_resolves_lazily() -> None:
    """Verify the static group resolves its real options only when selected."""
    assert "memory" in wiki.commands

    result = _run_cli(["memory", "--help"])

    assert result["exit_code"] == 0
    assert result["has_storage_path"] is True
    assert result["memory_loaded"] is True
