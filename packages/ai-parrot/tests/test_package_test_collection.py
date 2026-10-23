"""Guard the one-importable-identity-per-test-tree invariant (FEAT-720, Amendment B).

Every ``packages/<dist>/tests`` is literally named ``tests``. With pytest's default import mode two of them in one session
collide with ``ImportPathMismatchError`` before any test runs. The fix is configuration in the live ``pytest.ini`` (not
``pyproject.toml``, which pytest ignores while ``pytest.ini`` exists): importlib mode plus ``consider_namespace_packages``.
"""
from __future__ import annotations

import configparser
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
_COLLECT_TIMEOUT_S = 300
_TESTS_IMPORT = re.compile(r"^\s*(?:from|import)\s+tests(?:\.|\s|$)", re.MULTILINE)


def test_pytest_ini_enables_path_derived_test_identities() -> None:
    """``pytest.ini`` must carry both settings; either one alone leaves the collision."""
    ini = REPO_ROOT / "pytest.ini"
    assert ini.is_file(), "pytest.ini is the live pytest config and must exist"
    parser = configparser.ConfigParser()
    parser.read(ini)
    section = parser["pytest"]
    assert "--import-mode=importlib" in section.get("addopts", "").split()
    assert section.get("consider_namespace_packages", "").strip().lower() == "true"


def test_two_package_test_trees_collect_together() -> None:
    """``pytest <embeddings> <formdesigner> --collect-only`` must exit 0."""
    assert (REPO_ROOT / "packages").is_dir(), "repo root misderived"
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "packages/ai-parrot-embeddings/tests",
            "packages/parrot-formdesigner/tests",
            "--collect-only", "-q", "-p", "no:randomly",
        ],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=_COLLECT_TIMEOUT_S,
    )
    combined = result.stdout + result.stderr
    for needle in ("ImportPathMismatchError", "already registered", "import file mismatch"):
        assert needle not in combined, f"{needle!r} in collect output:\n{combined[-3000:]}"
    assert result.returncode == 0, f"collect exited {result.returncode}:\n{combined[-3000:]}"


def test_no_test_imports_the_ambiguous_tests_package() -> None:
    """``tests`` names 25 different trees, so ``from tests.<x>`` resolves to whichever was imported first."""
    assert (REPO_ROOT / "packages").is_dir(), "repo root misderived"
    offenders = sorted(
        str(path.relative_to(REPO_ROOT))
        for path in REPO_ROOT.glob("packages/*/tests/**/*.py")
        if path.resolve() != Path(__file__).resolve() and _TESTS_IMPORT.search(path.read_text(errors="ignore"))
    )
    assert offenders == [], f"files still import the ambiguous `tests` package: {offenders}"
