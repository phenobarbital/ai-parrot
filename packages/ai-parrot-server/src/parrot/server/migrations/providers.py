"""Fixed navigator ownership for optional server sets."""

from parrot.migrations.models import MigrationSet


def ui_surfaces_set() -> MigrationSet:
    """Own navigator.ui_surfaces and navigator.ui_surface_shares only."""
    return MigrationSet(
        name="ui_surfaces",
        package="parrot.server.migrations",
        resource_dir="sql/ui_surfaces",
        tables=("navigator.ui_surfaces", "navigator.ui_surface_shares"),
    )


def crew_definitions_set() -> MigrationSet:
    """Own navigator.crew_definitions only."""
    return MigrationSet(
        name="crew_definitions",
        package="parrot.server.migrations",
        resource_dir="sql/crew_definitions",
        tables=("navigator.crew_definitions",),
    )


def metric_definitions_set() -> MigrationSet:
    """Own navigator.metric_definitions only."""
    return MigrationSet(
        name="metric_definitions",
        package="parrot.server.migrations",
        resource_dir="sql/metric_definitions",
        tables=("navigator.metric_definitions",),
    )


def recipes_set() -> MigrationSet:
    """Own navigator.infographic_recipes only."""
    return MigrationSet(
        name="recipes",
        package="parrot.server.migrations",
        resource_dir="sql/recipes",
        tables=("navigator.infographic_recipes",),
    )


def scheduler_set() -> MigrationSet:
    """Own navigator.service_scheduler only."""
    return MigrationSet(
        name="scheduler",
        package="parrot.server.migrations",
        resource_dir="sql/scheduler",
        tables=("navigator.service_scheduler",),
    )
