"""Release-matrix contract for the core wheel (FEAT-633, TASK-4094)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
RELEASE = REPO_ROOT / ".github" / "workflows" / "release.yml"
INSTALL_MATRIX = REPO_ROOT / ".github" / "workflows" / "install-matrix.yml"   # created by TASK-4068
PYPROJECT = REPO_ROOT / "packages" / "ai-parrot" / "pyproject.toml"


def _jobs() -> dict[str, Any]:
    """Return release.yml's `jobs` mapping (the `on:` key parses as True — never read it)."""
    return yaml.safe_load(RELEASE.read_text(encoding="utf-8"))["jobs"]


def _core_legs() -> list[dict[str, Any]]:
    """Return build-core's matrix include entries."""
    return _jobs()["build-core"]["strategy"]["matrix"]["include"]


def _cibw() -> dict[str, Any]:
    """Return the [tool.cibuildwheel] table."""
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["cibuildwheel"]


def test_core_matrix_covers_all_platforms() -> None:
    """linux x86_64 + aarch64, windows AMD64 and macOS arm64 — one leg each."""
    pairs = {(leg["platform"], leg["archs"]) for leg in _core_legs()}
    assert pairs == {("linux", "x86_64"), ("linux", "aarch64"), ("windows", "AMD64"), ("macos", "arm64")}
    assert len(_core_legs()) == 4, "redundant build-core legs are back"


def test_no_cp314_while_requires_python_excludes_it() -> None:
    """Neither pyproject nor release.yml builds cp314 while requires-python is <3.14."""
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    if "<3.14" in project["requires-python"]:
        assert "14" not in _cibw()["build"]
        assert not re.search(r"CIBW_BUILD:.*14", RELEASE.read_text(encoding="utf-8"))


def test_aarch64_not_skipped_and_macos_declared() -> None:
    """manylinux aarch64 is no longer skipped; the macOS table targets arm64."""
    cibw = _cibw()
    assert "manylinux_aarch64" not in cibw["skip"]
    assert cibw["macos"]["archs"] == ["arm64"]


def test_deploy_needs_smoke_gate() -> None:
    """deploy waits for the clean-install smoke job, which waits for build-core (codex S11)."""
    jobs = _jobs()
    assert "smoke-core" in jobs["deploy"]["needs"]
    assert jobs["smoke-core"]["uses"].endswith("install-matrix.yml")
    assert "build-core" in jobs["smoke-core"]["needs"]
    assert "build-tools" in jobs["smoke-core"]["needs"]   # rev 0.5 C20: ai-parrot-tools wheel installed alongside core


def test_install_matrix_has_linux_aarch64_leg() -> None:
    """rev 0.5 C24: install-matrix smoke-tests the aarch64 core wheel on a linux ARM runner."""
    oses = yaml.safe_load(INSTALL_MATRIX.read_text(encoding="utf-8"))["jobs"]["smoke"]["strategy"]["matrix"]["os"]
    assert any(os_.startswith("ubuntu") and "arm" in os_ for os_ in oses), oses


def test_deploy_needs_sdd_foreign_smoke() -> None:
    """C3: the wheel-only foreign-repo SDD job gates deploy, installs from the wheel (never -e) and never skips."""
    jobs = _jobs()
    job = jobs["smoke-sdd-foreign"]
    assert "smoke-sdd-foreign" in jobs["deploy"]["needs"] and "build-core" in job["needs"]
    runs = "\n".join(step.get("run", "") for step in job["steps"])
    assert "pip install dist/" in runs and " -e " not in runs and "pip install ." not in runs
    assert "test_wheel_only_foreign_repo.py" in runs and "-u PYTHONPATH" in runs and "-u CLAUDE_PROJECT_DIR" in runs
    # `parrot sdd` ships: a failing probe must fail the job, never downgrade it to a skipped `::notice::`.
    assert not any("if" in step for step in job["steps"]) and "::notice::" not in runs
