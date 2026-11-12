"""Contract tests for the complete server migration inventory and runtime baselines."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.migrations.catalog import load_migrations
from parrot.server.migrations import providers

_ROOT = Path(__file__).parents[2]
_MIGRATIONS = _ROOT / "src" / "parrot" / "server" / "migrations"


@pytest.mark.parametrize(
    "factory",
    [
        providers.ui_surfaces_set,
        providers.crew_definitions_set,
        providers.metric_definitions_set,
        providers.recipes_set,
        providers.scheduler_set,
    ],
)
def test_complete_server_inventory_loads_body_check_pairs(factory: object) -> None:
    """Load exactly one complete baseline pair for every server-owned set."""
    migration_set = factory()  # type: ignore[operator]
    migrations = load_migrations(migration_set)

    assert len(migrations) == 1
    assert migrations[0].filename == "001_baseline.sql"
    assert migrations[0].sequence == 1
    assert migrations[0].sql
    assert migrations[0].check_sql


@pytest.mark.parametrize("resource", ["metric_definitions", "recipes", "scheduler"])
def test_runtime_baselines_are_safe_complete_resources(resource: str) -> None:
    """Keep baseline bodies non-destructive and checks read-only."""
    sql = (_MIGRATIONS / "sql" / resource / "001_baseline.sql").read_text(encoding="utf-8")
    check_sql = (_MIGRATIONS / "sql" / resource / "001_baseline.check.sql").read_text(encoding="utf-8")

    assert "BEGIN;" not in sql.upper()
    assert "COMMIT;" not in sql.upper()
    assert "DROP COLUMN" not in sql.upper()
    assert "DROP CONSTRAINT" not in sql.upper()
    assert "ALTER TABLE" in sql
    assert "DO $$" in sql
    assert check_sql.lstrip().startswith("-- FEAT-884 postcondition:")
    assert "SELECT\n" in check_sql
    assert "CREATE " not in check_sql.upper()
    assert "ALTER " not in check_sql.upper()
    assert "DROP " not in check_sql.upper()


def test_metric_baseline_preserves_nullable_tenant_identity() -> None:
    """Retain both tenant-scoped uniqueness and the global partial unique index."""
    sql = (_MIGRATIONS / "sql" / "metric_definitions" / "001_baseline.sql").read_text(encoding="utf-8")
    check_sql = (_MIGRATIONS / "sql" / "metric_definitions" / "001_baseline.check.sql").read_text(
        encoding="utf-8"
    )

    assert "UNIQUE (tenant, metric_id)" in sql
    assert "WHERE tenant IS NULL" in sql
    assert sql.index("ADD COLUMN IF NOT EXISTS tenant") < sql.index("metric_definitions_tenant_vis_idx")
    assert "visibility <> 'tenant'" in sql
    assert "metric_definitions_global_uq" in check_sql
    assert "WHERE (tenant IS NULL)" in check_sql


def test_recipe_baseline_owns_only_default_schema_composite_key() -> None:
    """Package only navigator recipes with the runtime composite primary key."""
    sql = (_MIGRATIONS / "sql" / "recipes" / "001_baseline.sql").read_text(encoding="utf-8")

    assert "navigator.infographic_recipes" in sql
    assert "PRIMARY KEY (name, owner)" in sql
    assert "DEFAULT ''" in sql
    assert "{schema}" not in sql


def test_scheduler_baseline_has_all_model_fields_defaults_and_indexes() -> None:
    """Match every ServiceSchedule field and use the extension-free fresh UUID default."""
    sql = (_MIGRATIONS / "sql" / "scheduler" / "001_baseline.sql").read_text(encoding="utf-8")
    model_fields = {
        "schedule_id",
        "target_kind",
        "target_name",
        "target_id",
        "tenant",
        "prompt",
        "method_name",
        "schedule_type",
        "schedule_config",
        "enabled",
        "created_by",
        "created_email",
        "created_at",
        "updated_at",
        "last_run",
        "next_run",
        "run_count",
        "last_status",
        "last_error",
        "last_error_at",
        "last_result",
        "last_result_at",
        "consecutive_failures",
        "last_delivery_status",
        "last_delivery_at",
        "last_callbacks",
        "metadata",
        "send_result",
        "callbacks",
    }

    assert all(field in sql for field in model_fields)
    assert "DEFAULT gen_random_uuid()" in sql
    assert "CREATE EXTENSION" not in sql.upper()
    assert "idx_service_scheduler_enabled" in sql
    assert "idx_service_scheduler_target" in sql


def test_runtime_fallback_sources_remain_outside_migration_delivery() -> None:
    """Limit this task to packaged resources rather than runtime fallback edits."""
    expected_resources = {
        "metric_definitions/001_baseline.sql",
        "metric_definitions/001_baseline.check.sql",
        "recipes/001_baseline.sql",
        "recipes/001_baseline.check.sql",
        "scheduler/001_baseline.sql",
        "scheduler/001_baseline.check.sql",
    }
    actual_resources = {
        str(path.relative_to(_MIGRATIONS / "sql"))
        for resource in ("metric_definitions", "recipes", "scheduler")
        for path in (_MIGRATIONS / "sql" / resource).glob("*.sql")
    }

    assert actual_resources == expected_resources
