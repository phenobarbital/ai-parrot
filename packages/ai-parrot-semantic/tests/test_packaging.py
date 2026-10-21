"""Packaging tests for ai-parrot-semantic: PEP 420 namespace and the AGPL import ban."""

import subprocess
from pathlib import Path

import parrot.semantic

REPO = Path(__file__).resolve().parents[3]


def test_packaging_namespace():
    """parrot.semantic imports alongside core; src/parrot has no __init__.py; version matches."""
    assert parrot.semantic.__version__ == "1.3.0"
    assert not (REPO / "packages/ai-parrot-semantic/src/parrot/__init__.py").exists()


def _ruff_tid251(path: Path) -> int:
    proc = subprocess.run(
        ["ruff", "check", "--no-cache", "--config", str(REPO / "ruff.toml"), "--select", "TID251", str(path)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode


def test_sidemantic_import_ban():
    """TID251 flags `import sidemantic` outside the satellite only."""
    outside = REPO / "packages/ai-parrot/src/parrot/_tid251_sidemantic_probe.py"
    inside = REPO / "packages/ai-parrot-semantic/src/parrot/semantic/_tid251_sidemantic_probe.py"
    try:
        outside.write_text("import sidemantic\n")
        inside.write_text("import sidemantic\n")
        assert _ruff_tid251(outside) != 0
        assert _ruff_tid251(inside) == 0
    finally:
        outside.unlink(missing_ok=True)
        inside.unlink(missing_ok=True)
