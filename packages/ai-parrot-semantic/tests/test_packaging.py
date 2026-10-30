"""Regression contract: MIT satellite packaging, workspace and CI (M1)."""

from pathlib import Path
import re
import tomllib

import pytest

from parrot.semantic import __version__

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = REPOSITORY_ROOT / "packages" / "ai-parrot-semantic"


def _isolated_copy(path: Path, tmp_path: Path) -> Path:
    """Copy a text configuration file into a deterministic test-local path."""
    copy = tmp_path / path.name
    copy.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return copy


def test_namespace_version_and_package_data(tmp_path: Path) -> None:
    """Verify namespace version and package data metadata."""
    package_config = tomllib.loads(_isolated_copy(PACKAGE_ROOT / "pyproject.toml", tmp_path).read_text())

    # Shape only: scripts/release.py bumps version.py on every release, so a pinned
    # literal here breaks CI after each release.
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)
    assert package_config["project"]["license"] == "MIT"
    assert package_config["project"]["dependencies"] == [
        "ai-parrot",
        "sqlglot>=30.1,<31",
        "jsonschema>=4.20",
        "pyyaml>=6",
    ]
    assert package_config["project"]["optional-dependencies"] == {
        "duckdb": ["duckdb>=1.0"],
        "bigquery": ["google-cloud-bigquery>=3.30"],
    }
    assert package_config["tool"]["setuptools"]["package-data"]["parrot.semantic"] == [
        "schemas/*.json",
        "sql/*.sql",
    ]


def test_no_removed_dependency_or_import_exemption(tmp_path: Path) -> None:
    """Verify the removed dependency is absent and its import ban has no exemption."""
    removed_module = "side" + "mantic"
    package_config = tomllib.loads(_isolated_copy(PACKAGE_ROOT / "pyproject.toml", tmp_path).read_text())
    root_config = tomllib.loads(_isolated_copy(REPOSITORY_ROOT / "pyproject.toml", tmp_path).read_text())
    ruff_config = _isolated_copy(REPOSITORY_ROOT / "ruff.toml", tmp_path).read_text(encoding="utf-8")

    assert removed_module not in str(package_config)
    assert removed_module not in str(root_config)
    assert f'"{removed_module}".msg' in ruff_config
    assert removed_module not in ruff_config.split("[lint.per-file-ignores]", maxsplit=1)[1]


def test_workspace_ci_duckdb_extra(tmp_path: Path) -> None:
    """Verify workspace registration and CI installation of the DuckDB extra."""
    root_config = tomllib.loads(_isolated_copy(REPOSITORY_ROOT / "pyproject.toml", tmp_path).read_text())
    release_script = _isolated_copy(REPOSITORY_ROOT / "scripts" / "release.py", tmp_path).read_text(encoding="utf-8")
    ci_workflow = _isolated_copy(REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml", tmp_path).read_text(
        encoding="utf-8"
    )

    assert root_config["tool"]["uv"]["sources"]["ai-parrot-semantic"] == {"workspace": True}
    assert 'Package(\n        "ai-parrot-semantic",' in release_script
    assert "packages/ai-parrot-semantic/src/parrot/semantic/version.py" in release_script
    assert "uv sync --all-packages --extra duckdb\n" in ci_workflow
    # `--all-packages` and `--package` are mutually exclusive (uv exits 2).
    assert "--all-packages --extra duckdb --package" not in ci_workflow
    assert "uv run pytest packages/ai-parrot-semantic/tests -q --tb=short" in ci_workflow
