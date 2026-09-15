"""Loader contract for parrot.flows.conventions (FEAT-553, spec AC-4/AC-14)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from parrot.flows.conventions import CODER_RULE_NAMES, load_project_conventions

# packages/ai-parrot/tests/flows/test_conventions.py -> packages/ai-parrot/src
_AI_PARROT_SRC = Path(__file__).resolve().parents[2] / "src"


@pytest.fixture
def rules_worktree(tmp_path: Path) -> Path:
    d = tmp_path / ".agent" / "rules"
    d.mkdir(parents=True)
    (d / "codebase-conventions.md").write_text("---\nname: x\n---\nSENTINEL-WORKTREE-RULE\n")
    return tmp_path


def test_conventions_prefer_worktree_copy(rules_worktree):
    out = load_project_conventions(rules_worktree, names=("codebase-conventions",))
    assert "SENTINEL-WORKTREE-RULE" in out and "name: x" not in out


def test_conventions_fall_back_to_package_copy(tmp_path):
    # Both None and a tmp_path without rules should return the same package content
    out_none = load_project_conventions(None)
    out_tmp = load_project_conventions(tmp_path)
    assert out_none == out_tmp
    assert "## Project rule: python-development" in out_none


def test_conventions_strip_frontmatter_and_join():
    # Every name in CODER_RULE_NAMES yields a "## Project rule: <name>" heading
    out = load_project_conventions()
    for name in CODER_RULE_NAMES:
        assert f"## Project rule: {name}" in out
    # Blocks are separated by the separator
    assert "\n\n---\n\n" in out
    # Frontmatter is stripped - "trigger: always_on" should not survive
    assert "trigger: always_on" not in out


def test_conventions_reject_unknown_name():
    with pytest.raises(ValueError):
        load_project_conventions(names=("nope",))


def test_conventions_module_is_import_light():
    """`import parrot.flows.conventions` must never pull in `parrot.flows.dev_loop`.

    The subprocess is spawned with a bare environment (no ambient `sys.path`
    manipulation this repo's root `conftest.py` applies in-process for pytest
    runs), so its own `PYTHONPATH` must point at THIS worktree's package
    source explicitly — otherwise, in a multi-worktree shared-venv setup, the
    subprocess can resolve `parrot` via whichever checkout the shared venv's
    editable install happens to point at (which may not have this module at
    all), turning a false ModuleNotFoundError into a spurious test failure
    unrelated to the import-lightness property under test.
    """
    code = "import sys, parrot.flows.conventions; assert 'parrot.flows.dev_loop' not in sys.modules"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(_AI_PARROT_SRC), env.get("PYTHONPATH", "")]))
    result = subprocess.run([sys.executable, "-c", code], check=False, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
