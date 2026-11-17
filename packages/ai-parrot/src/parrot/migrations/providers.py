"""Core distribution migration metadata."""

from .models import MigrationSet


def bots_set() -> MigrationSet:
    """Resolve configured bots ownership without importing application models."""
    from parrot.conf import PARROT_BOTS_TABLE, PARROT_SCHEMA

    return MigrationSet(
        name="bots",
        package="parrot.migrations",
        resource_dir="sql/bots",
        tables=(f"{PARROT_SCHEMA}.{PARROT_BOTS_TABLE}",),
    )
