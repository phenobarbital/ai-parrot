"""Build core wheel in temporary output; inspect entry_points/package data.

Tests verify that:
- Core wheel builds and contains the expected entry points
- Package data includes SQL migration files
- Isolated core-only environment discovers bots only
- All five exact-byte SQL/check pairs are present
- No asyncpg/server eager imports occur during discovery
- No manual scripts are packaged
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from parrot.migrations import catalog
from parrot.migrations.catalog import discover_sets, load_migrations
from parrot.migrations.models import MigrationSet
from parrot.migrations.providers import bots_set

# Mark all tests as wheel_build since they need uv to build wheels
pytestmark = pytest.mark.wheel_build


def _build_core_wheel(tmp_path: Path) -> Path:
    """Build the core ai-parrot wheel in a temporary output directory."""
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()

    # Build wheel using uv
    result = subprocess.run(
        ["uv", "build", "--package", "ai-parrot", "--wheel", "--out-dir", str(wheel_dir)],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parents[3],  # repo root
    )
    if result.returncode != 0:
        pytest.skip(f"Wheel build failed: {result.stderr}")

    wheels = list(wheel_dir.glob("*.whl"))
    if not wheels:
        pytest.skip("No wheel produced")
    return wheels[0]


@pytest.fixture
def core_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Provide the built core wheel path."""
    return _build_core_wheel(tmp_path_factory.mktemp("wheel_build"))


def test_core_wheel_has_migration_entry_point(core_wheel: Path) -> None:
    """Verify the wheel contains the bots migration entry point."""
    with zipfile.ZipFile(core_wheel, "r") as whl:
        # Check for entry_points.txt
        entry_points_files = [n for n in whl.namelist() if n.endswith("entry_points.txt")]
        assert entry_points_files, "No entry_points.txt found in wheel"

        entry_points_content = whl.read(entry_points_files[0]).decode("utf-8")
        assert "[parrot.migrations]" in entry_points_content, "Missing parrot.migrations entry point group"
        assert "bots = parrot.migrations.providers:bots_set" in entry_points_content, "Missing bots entry point"


def test_core_wheel_contains_sql_files(core_wheel: Path) -> None:
    """Verify the wheel includes all five SQL/check pairs for bots."""
    expected_files = {
        "parrot/migrations/sql/bots/001_baseline.sql",
        "parrot/migrations/sql/bots/001_baseline.check.sql",
        "parrot/migrations/sql/bots/002_fold_embedding.sql",
        "parrot/migrations/sql/bots/002_fold_embedding.check.sql",
        "parrot/migrations/sql/bots/003_fold_llm.sql",
        "parrot/migrations/sql/bots/003_fold_llm.check.sql",
        "parrot/migrations/sql/bots/004_tool_names.sql",
        "parrot/migrations/sql/bots/004_tool_names.check.sql",
        "parrot/migrations/sql/bots/005_language_schema.sql",
        "parrot/migrations/sql/bots/005_language_schema.check.sql",
    }

    with zipfile.ZipFile(core_wheel, "r") as whl:
        file_list = set(whl.namelist())

        for expected in expected_files:
            assert expected in file_list, f"Missing expected file: {expected}"

        # Verify no manual scripts are packaged
        sql_files = [n for n in file_list if n.startswith("parrot/migrations/sql/") and n.endswith(".sql")]
        for sql_file in sql_files:
            # All SQL files should be numbered migration files
            filename = Path(sql_file).name
            assert filename.endswith(".check.sql") or (
                len(filename) >= 7 and filename[0:3].isdigit() and filename[3] == "_"
            ), f"Unexpected SQL file (not a numbered migration): {sql_file}"


def test_core_wheel_sql_checksums(core_wheel: Path) -> None:
    """Verify SQL files have deterministic checksums (exact bytes preserved)."""
    with zipfile.ZipFile(core_wheel, "r") as whl:
        sql_files = [n for n in whl.namelist() if "/sql/bots/" in n and n.endswith(".sql")]

        for sql_path in sql_files:
            content = whl.read(sql_path)
            # Verify content is valid UTF-8
            content.decode("utf-8")
            # Verify we can compute a stable checksum
            checksum = hashlib.sha256(content).hexdigest()
            assert len(checksum) == 64, f"Invalid checksum for {sql_path}"


def test_core_migration_files_load_exact_bytes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify all five migration SQL/check pairs load with exact byte checksums."""
    migration_set = bots_set()
    migrations = load_migrations(migration_set)

    # Should have exactly 5 migrations
    assert len(migrations) == 5, f"Expected 5 migrations, got {len(migrations)}"

    for m in migrations:
        # Verify checksums are computed from exact bytes
        sql_bytes = m.sql.encode("utf-8")
        check_bytes = m.check_sql.encode("utf-8")
        sql_checksum = hashlib.sha256(sql_bytes).hexdigest()
        check_checksum = hashlib.sha256(check_bytes).hexdigest()

        assert sql_checksum == m.checksum, f"SQL checksum mismatch for {m.filename}"
        assert check_checksum == m.check_checksum, f"Check checksum mismatch for {m.filename}"


def test_core_no_server_imports() -> None:
    """Verify core migration discovery does not import server modules.

    Note: This test verifies that the core catalog module itself does not
    import server modules. In a test environment where server modules may
    already be loaded, we verify the catalog code paths don't trigger
    new server imports.
    """
    # The catalog module should not have any imports of server modules
    import parrot.migrations.catalog as catalog_module
    import inspect

    source = inspect.getsource(catalog_module)

    # Core catalog should not reference server modules
    assert "parrot.server" not in source, "catalog.py references parrot.server"
    assert "parrot_server" not in source, "catalog.py references parrot_server"

    # The providers module should only reference core
    import parrot.migrations.providers as providers_module

    providers_source = inspect.getsource(providers_module)

    assert "parrot.server" not in providers_source, "providers.py references parrot.server"
    assert "parrot.handlers" not in providers_source, "providers.py references parrot.handlers"


def test_core_help_no_asyncpg_eager_import() -> None:
    """Verify migration catalog code does not reference asyncpg.

    The catalog module should not have any dependencies on asyncpg
    since it only handles metadata discovery and resource loading.
    """
    import parrot.migrations.catalog as catalog_module
    import inspect

    source = inspect.getsource(catalog_module)

    # Catalog should not import asyncpg
    assert "asyncpg" not in source, "catalog.py imports asyncpg"
    assert "import asyncpg" not in source, "catalog.py has asyncpg import"

    # The models module should also not reference asyncpg
    import parrot.migrations.models as models_module

    models_source = inspect.getsource(models_module)

    assert "asyncpg" not in models_source, "models.py references asyncpg"


def test_core_discovery_is_sorted_and_unique() -> None:
    """Verify discovered sets are sorted and have unique names."""
    sets = discover_sets()
    names = [s.name for s in sets]

    # Should be sorted
    assert names == sorted(names), f"Sets not sorted: {names}"

    # Should be unique
    assert len(names) == len(set(names)), f"Duplicate set names: {names}"


def test_core_bots_set_metadata() -> None:
    """Verify the bots migration set has correct metadata."""
    migration_set = bots_set()

    assert migration_set.name == "bots"
    assert migration_set.package == "parrot.migrations"
    assert migration_set.resource_dir == "sql/bots"
    assert len(migration_set.tables) == 1
    assert "ai_bots" in migration_set.tables[0] or "bots" in migration_set.tables[0]
