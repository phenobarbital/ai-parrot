"""Immutable migration metadata and safe reports."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class MigrationConfigurationError(ValueError):
    """Invalid migration configuration; CLI exit code 3."""


class MigrationSet(BaseModel):
    """Resource owner: name, package, resource_dir, and tuple of qualified target tables."""

    model_config = ConfigDict(frozen=True)

    name: str
    package: str
    resource_dir: str
    tables: tuple[str, ...]


class MigrationFile(BaseModel):
    """Loaded immutable body/check pair with SHA256 values and sequence."""

    model_config = ConfigDict(frozen=True)

    migration_set: str
    filename: str
    sequence: int
    sql: str
    check_sql: str
    checksum: str
    check_checksum: str


class MigrationItem(BaseModel):
    """One file's APPLIED/PENDING/CHANGED state, postcondition result and safe diagnostic."""

    model_config = ConfigDict(frozen=True)

    migration_set: str
    filename: str
    state: Literal["APPLIED", "PENDING", "CHANGED"]
    postcondition_ok: bool | None
    diagnostic: str | None


class MigrationReport(BaseModel):
    """Safe structured result; never stores credentials or raw driver errors."""

    model_config = ConfigDict(frozen=True)

    items: list[MigrationItem]
    applied: list[str]
    failed: list[str]
    skipped: list[str]
    diagnostics: list[str]
    exit_code: Literal[0, 1, 2, 3]
