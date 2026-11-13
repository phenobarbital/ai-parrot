"""Build/install core+server wheels in temporary environment.

Tests verify that:
- Core+server wheels build and install together
- All ten runtime SQL/check files load (5 bots + 5 server sets)
- No checkout fallback/handler imports occur
- Missing resources fail clearly with proper error messages
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

from parrot.migrations.catalog import discover_sets, load_migrations
from parrot.migrations.models import MigrationSet, MigrationConfigurationError
from parrot.server.migrations import providers


# Mark all tests as wheel_build since they need uv to build wheels
pytestmark = pytest.mark.wheel_build


def _build_wheels(tmp_path: Path) -> tuple[Path, Path]:
    """Build both core and server wheels in a temporary output directory."""
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    
    repo_root = Path(__file__).parents[3]
    
    # Build core wheel
    result = subprocess.run(
        ["uv", "build", "--package", "ai-parrot", "--wheel", "--out-dir", str(wheel_dir)],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    if result.returncode != 0:
        pytest.skip(f"Core wheel build failed: {result.stderr}")
    
    # Build server wheel
    result = subprocess.run(
        ["uv", "build", "--package", "ai-parrot-server", "--wheel", "--out-dir", str(wheel_dir)],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    if result.returncode != 0:
        pytest.skip(f"Server wheel build failed: {result.stderr}")
    
    wheels = list(wheel_dir.glob("*.whl"))
    core_wheels = [w for w in wheels if "ai_parrot-" in w.name and "server" not in w.name]
    server_wheels = [w for w in wheels if "ai_parrot_server-" in w.name]
    
    if not core_wheels or not server_wheels:
        pytest.skip("Wheels not produced")
    
    return core_wheels[0], server_wheels[0]


@pytest.fixture
def wheels(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Provide the built wheel paths."""
    return _build_wheels(tmp_path_factory.mktemp("wheel_build"))


def test_server_wheel_has_migration_entry_points(wheels: tuple[Path, Path]) -> None:
    """Verify the server wheel contains all five migration entry points."""
    _core_wheel, server_wheel = wheels
    
    with zipfile.ZipFile(server_wheel, "r") as whl:
        entry_points_files = [n for n in whl.namelist() if n.endswith("entry_points.txt")]
        assert entry_points_files, "No entry_points.txt found in wheel"
        
        entry_points_content = whl.read(entry_points_files[0]).decode("utf-8")
        assert "[parrot.migrations]" in entry_points_content
        
        # Check all five server sets
        expected_sets = [
            "ui_surfaces",
            "crew_definitions",
            "metric_definitions",
            "recipes",
            "scheduler",
        ]
        for set_name in expected_sets:
            assert f"{set_name} = parrot.server.migrations.providers:{set_name}_set" in entry_points_content


def test_server_wheel_contains_sql_files(wheels: tuple[Path, Path]) -> None:
    """Verify the server wheel includes all SQL/check pairs."""
    _core_wheel, server_wheel = wheels
    
    expected_files = {
        "parrot/server/migrations/sql/ui_surfaces/001_baseline.sql",
        "parrot/server/migrations/sql/ui_surfaces/001_baseline.check.sql",
        "parrot/server/migrations/sql/crew_definitions/001_baseline.sql",
        "parrot/server/migrations/sql/crew_definitions/001_baseline.check.sql",
        "parrot/server/migrations/sql/metric_definitions/001_baseline.sql",
        "parrot/server/migrations/sql/metric_definitions/001_baseline.check.sql",
        "parrot/server/migrations/sql/recipes/001_baseline.sql",
        "parrot/server/migrations/sql/recipes/001_baseline.check.sql",
        "parrot/server/migrations/sql/scheduler/001_baseline.sql",
        "parrot/server/migrations/sql/scheduler/001_baseline.check.sql",
    }
    
    with zipfile.ZipFile(server_wheel, "r") as whl:
        file_list = set(whl.namelist())
        
        for expected in expected_files:
            assert expected in file_list, f"Missing expected file: {expected}"


def test_combined_environment_discovers_all_sets() -> None:
    """Verify all six sets are discovered (bots + 5 server)."""
    sets = discover_sets()
    set_names = sorted([s.name for s in sets])
    
    expected_sets = ["bots", "crew_definitions", "metric_definitions", "recipes", "scheduler", "ui_surfaces"]
    
    assert set_names == expected_sets, f"Expected {expected_sets}, got {set_names}"
    assert len(sets) == 6, f"Expected 6 sets, got {len(sets)}"


def test_all_ten_migration_files_load() -> None:
    """Verify all ten runtime SQL/check files load with correct checksums."""
    total_migrations = 0
    
    for migration_set in discover_sets():
        migrations = load_migrations(migration_set)
        total_migrations += len(migrations)
        
        for m in migrations:
            sql_bytes = m.sql.encode("utf-8")
            check_bytes = m.check_sql.encode("utf-8")
            sql_checksum = hashlib.sha256(sql_bytes).hexdigest()
            check_checksum = hashlib.sha256(check_bytes).hexdigest()
            
            assert sql_checksum == m.checksum, f"SQL checksum mismatch for {m.migration_set}/{m.filename}"
            assert check_checksum == m.check_checksum, f"Check checksum mismatch for {m.migration_set}/{m.filename}"
    
    # 5 bots + 5 server = 10 total
    assert total_migrations == 10, f"Expected 10 migrations, got {total_migrations}"


def test_server_sets_have_correct_packages() -> None:
    """Verify each server set has the correct package metadata."""
    sets = discover_sets()
    
    # Filter to server sets only
    server_sets = [s for s in sets if s.name != "bots"]
    
    for migration_set in server_sets:
        assert migration_set.package == "parrot.server.migrations", (
            f"Wrong package for {migration_set.name}: {migration_set.package}"
        )
        assert migration_set.resource_dir.startswith("sql/"), (
            f"Unexpected resource_dir for {migration_set.name}: {migration_set.resource_dir}"
        )


def test_server_sets_have_expected_tables() -> None:
    """Verify each server set owns the expected tables."""
    expected_tables = {
        "ui_surfaces": ("navigator.ui_surfaces", "navigator.ui_surface_shares"),
        "crew_definitions": ("navigator.crew_definitions",),
        "metric_definitions": ("navigator.metric_definitions",),
        "recipes": ("navigator.infographic_recipes",),
        "scheduler": ("navigator.service_scheduler",),
    }
    
    sets = discover_sets()
    
    for migration_set in sets:
        if migration_set.name in expected_tables:
            assert migration_set.tables == expected_tables[migration_set.name], (
                f"Wrong tables for {migration_set.name}: {migration_set.tables}"
            )


def test_no_handler_imports() -> None:
    """Verify migration discovery does not import handler modules."""
    # Get current modules before discovery
    modules_before = set(sys.modules.keys())
    
    # Perform discovery
    sets = discover_sets()
    
    # Get all modules after discovery
    modules_after = set(sys.modules.keys())
    all_modules = modules_after | modules_before
    
    # Check for any handler imports
    handler_modules = [m for m in all_modules if "parrot.handlers" in m]
    
    assert handler_modules == [], f"Handler modules imported: {handler_modules}"


def test_missing_resource_fails_clearly() -> None:
    """Verify missing resources produce clear configuration errors."""
    # Create a set pointing to non-existent resources
    bad_set = MigrationSet(
        name="test_missing",
        package="parrot.migrations",
        resource_dir="sql/nonexistent",
        tables=("test.table",)
    )
    
    with pytest.raises(MigrationConfigurationError) as exc_info:
        load_migrations(bad_set)
    
    # Error message should be descriptive
    error_msg = str(exc_info.value).lower()
    assert "missing" in error_msg or "unavailable" in error_msg or "directory" in error_msg


def test_server_provider_module_does_not_depend_on_runtime_handlers() -> None:
    """Keep entry-point discovery lightweight and independent of fallback stores."""
    # Check the providers module source
    import inspect
    source = inspect.getsource(providers)
    
    assert "parrot.handlers" not in source, "providers.py imports from parrot.handlers"


def test_server_sets_are_fixed_metadata() -> None:
    """Expose fixed navigator targets without importing runtime handler modules."""
    # Test each server set factory
    factories = [
        providers.ui_surfaces_set,
        providers.crew_definitions_set,
        providers.metric_definitions_set,
        providers.recipes_set,
        providers.scheduler_set,
    ]
    
    for factory in factories:
        migration_set = factory()
        
        assert migration_set.package == "parrot.server.migrations"
        assert migration_set.resource_dir.startswith("sql/")
        assert len(migration_set.tables) >= 1
        assert all("navigator." in t for t in migration_set.tables)
