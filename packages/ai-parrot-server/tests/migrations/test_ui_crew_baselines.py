"""Contract tests for the server-owned migration metadata and baselines."""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path

import pytest

from parrot.server.migrations import providers

_ROOT = Path(__file__).parents[2]
_MIGRATIONS = _ROOT / "src" / "parrot" / "server" / "migrations"


@pytest.mark.parametrize(
    ("factory", "name", "resource_dir", "tables"),
    [
        (
            providers.ui_surfaces_set,
            "ui_surfaces",
            "sql/ui_surfaces",
            ("navigator.ui_surfaces", "navigator.ui_surface_shares"),
        ),
        (providers.crew_definitions_set, "crew_definitions", "sql/crew_definitions", ("navigator.crew_definitions",)),
        (
            providers.metric_definitions_set,
            "metric_definitions",
            "sql/metric_definitions",
            ("navigator.metric_definitions",),
        ),
        (providers.recipes_set, "recipes", "sql/recipes", ("navigator.infographic_recipes",)),
        (providers.scheduler_set, "scheduler", "sql/scheduler", ("navigator.service_scheduler",)),
    ],
)
def test_server_sets_are_fixed_metadata(factory: object, name: str, resource_dir: str, tables: tuple[str, ...]) -> None:
    """Expose fixed navigator targets without importing runtime handler modules."""
    migration_set = factory()  # type: ignore[operator]

    assert migration_set.name == name
    assert migration_set.package == "parrot.server.migrations"
    assert migration_set.resource_dir == resource_dir
    assert migration_set.tables == tables
    assert find_spec("parrot.server.migrations.providers") is not None


@pytest.mark.parametrize("resource", ["ui_surfaces", "crew_definitions"])
def test_runtime_baselines_are_complete_and_transaction_free(resource: str) -> None:
    """Keep packaged SQL aligned with runtime ownership and migration authoring rules."""
    sql = (_MIGRATIONS / "sql" / resource / "001_baseline.sql").read_text(encoding="utf-8")
    check_sql = (_MIGRATIONS / "sql" / resource / "001_baseline.check.sql").read_text(encoding="utf-8")

    assert "BEGIN;" not in sql.upper()
    assert "COMMIT;" not in sql.upper()
    assert "SELECT" in check_sql.upper()
    assert "CREATE TABLE IF NOT EXISTS" in sql
    assert "ALTER TABLE" in sql
    assert "DO $$" in sql


def test_ui_catch_up_precedes_tenant_index_and_keeps_runtime_shape() -> None:
    """Add FEAT-535 columns before indexing them and retain runtime UI objects."""
    sql = (_MIGRATIONS / "sql" / "ui_surfaces" / "001_baseline.sql").read_text(encoding="utf-8")

    assert sql.index("ADD COLUMN IF NOT EXISTS tenant") < sql.index("ix_ui_surfaces_tenant_visibility")
    assert "navigator.ui_surface_shares" in sql
    assert "ON DELETE CASCADE" in sql
    assert "studio" not in sql.lower()
    assert "task_memory" not in sql.lower()


def test_provider_module_does_not_depend_on_runtime_handlers() -> None:
    """Keep entry-point discovery lightweight and independent of fallback stores."""
    source = (_MIGRATIONS / "providers.py").read_text(encoding="utf-8")

    assert "parrot.handlers" not in source
