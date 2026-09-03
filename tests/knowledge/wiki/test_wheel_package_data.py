"""FEAT-498 TASK-2752 — AC17: the ast-grep rule YAMLs ship inside the wheel.

Slow (builds a real wheel with `uv build`, including the Cython
extensions) — skipped when `uv` is not on PATH rather than failing, and
not gated behind a custom pytest marker (this task's own Files table does
not include the root `pyproject.toml`, where `[tool.pytest.ini_options]
markers` lives, and `--strict-markers` there rejects an unregistered
one).
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PACKAGE_DIR = _REPO_ROOT / "packages" / "ai-parrot"

pytestmark = pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed")


def test_wheel_contains_ast_grep_rule_yamls(tmp_path: Path) -> None:
    """`uv build --wheel` output includes every language's RuleSet YAML."""
    out_dir = tmp_path / "dist"
    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out_dir), str(_PACKAGE_DIR)],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    wheels = list(out_dir.glob("*.whl"))
    assert wheels, "uv build produced no wheel"

    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())

    for language in ("typescript", "php", "rust", "perl", "python"):
        expected = f"parrot/knowledge/wiki/languages/rules/{language}.yaml"
        assert expected in names, f"{expected} missing from wheel; names sample: {sorted(names)[:20]}"
