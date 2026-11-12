"""Deterministic migration discovery, loading, rendering and local authoring.

Migration SQL may use only ``{schema}`` and ``{bots_table}`` replacement
tokens.  Both are identifier contexts: callers replace them with PostgreSQL
quoted identifiers, while JSON braces and all other SQL text remain literal.
"""
from __future__ import annotations

from hashlib import sha256
from importlib import metadata, resources
from pathlib import Path
import re

from .models import MigrationConfigurationError, MigrationFile, MigrationSet


_IDENTIFIER_RE = re.compile(r"[a-z_][a-z0-9_]{0,62}\Z")
_MIGRATION_RE = re.compile(r"(?P<sequence>[0-9]{3})_(?P<name>[a-z][a-z0-9_]*)\.sql\Z")
_CHECK_RE = re.compile(r"(?P<sequence>[0-9]{3})_(?P<name>[a-z][a-z0-9_]*)\.check\.sql\Z")


def _configuration_error(message: str) -> MigrationConfigurationError:
    """Construct a configuration error without exposing source contents."""
    return MigrationConfigurationError(message)


def _entry_points() -> tuple[metadata.EntryPoint, ...]:
    """Read migration entry points across supported importlib.metadata APIs."""
    discovered = metadata.entry_points()
    if hasattr(discovered, "select"):
        return tuple(discovered.select(group="parrot.migrations"))
    return tuple(discovered.get("parrot.migrations", ()))


def discover_sets() -> tuple[MigrationSet, ...]:
    """Load sorted parrot.migrations entry points; reject ambiguous providers."""
    discovered = sorted(_entry_points(), key=lambda entry_point: entry_point.name)
    names: set[str] = set()
    migration_sets: list[MigrationSet] = []

    for entry_point in discovered:
        if entry_point.name in names:
            raise _configuration_error(f"Duplicate migration provider name: {entry_point.name}")
        names.add(entry_point.name)

        try:
            factory = entry_point.load()
            migration_set = factory()
        except Exception as error:
            raise _configuration_error(f"Unable to load migration provider: {entry_point.name}") from error

        if not isinstance(migration_set, MigrationSet):
            raise _configuration_error(f"Migration provider did not return MigrationSet: {entry_point.name}")
        if migration_set.name != entry_point.name:
            raise _configuration_error(f"Migration provider name mismatch: {entry_point.name}")
        migration_sets.append(migration_set)

    return tuple(migration_sets)


def _resource_files(migration_set: MigrationSet) -> dict[str, object]:
    """Return named packaged resources for one migration set."""
    try:
        directory = resources.files(migration_set.package).joinpath(migration_set.resource_dir)
        if not directory.is_dir():
            raise _configuration_error(f"Migration resource directory is missing: {migration_set.name}")
        return {entry.name: entry for entry in directory.iterdir() if entry.is_file()}
    except MigrationConfigurationError:
        raise
    except Exception as error:
        raise _configuration_error(f"Migration resources are unavailable: {migration_set.name}") from error


def _read_resource(resource: object, migration_set: MigrationSet, filename: str) -> tuple[bytes, str]:
    """Read a resource as exact bytes and validate its UTF-8 encoding."""
    try:
        contents = resource.read_bytes()  # type: ignore[attr-defined]
        return contents, contents.decode("utf-8")
    except UnicodeDecodeError as error:
        raise _configuration_error(f"Migration resource is not UTF-8: {migration_set.name}/{filename}") from error
    except Exception as error:
        raise _configuration_error(f"Migration resource is unavailable: {migration_set.name}/{filename}") from error


def load_migrations(migration_set: MigrationSet) -> tuple[MigrationFile, ...]:
    """Validate contiguous body/check pairs and checksum their exact UTF-8 bytes."""
    entries = _resource_files(migration_set)
    bodies: dict[int, tuple[str, str]] = {}
    checks: dict[tuple[int, str], str] = {}

    for filename in entries:
        check_match = _CHECK_RE.fullmatch(filename)
        if check_match:
            key = (int(check_match["sequence"]), check_match["name"])
            checks[key] = filename
            continue

        body_match = _MIGRATION_RE.fullmatch(filename)
        if body_match:
            sequence = int(body_match["sequence"])
            if sequence == 0:
                raise _configuration_error(f"Migration sequence must start at 001: {migration_set.name}/{filename}")
            if sequence in bodies:
                raise _configuration_error(f"Duplicate migration sequence: {migration_set.name}/{filename}")
            bodies[sequence] = (body_match["name"], filename)
            continue

        if filename.endswith(".sql"):
            raise _configuration_error(f"Invalid migration filename: {migration_set.name}/{filename}")

    if not bodies:
        raise _configuration_error(f"Migration set has no SQL bodies: {migration_set.name}")

    sequences = sorted(bodies)
    expected = list(range(1, len(sequences) + 1))
    if sequences != expected:
        raise _configuration_error(f"Migration sequence has a gap: {migration_set.name}")

    expected_checks = {(sequence, name) for sequence, (name, _) in bodies.items()}
    if checks.keys() != expected_checks:
        raise _configuration_error(f"Migration body/check pairs are incomplete: {migration_set.name}")

    migrations: list[MigrationFile] = []
    for sequence in sequences:
        name, filename = bodies[sequence]
        check_filename = checks[(sequence, name)]
        sql_bytes, sql = _read_resource(entries[filename], migration_set, filename)
        check_bytes, check_sql = _read_resource(entries[check_filename], migration_set, check_filename)
        migrations.append(
            MigrationFile(
                migration_set=migration_set.name,
                filename=filename,
                sequence=sequence,
                sql=sql,
                check_sql=check_sql,
                checksum=sha256(sql_bytes).hexdigest(),
                check_checksum=sha256(check_bytes).hexdigest(),
            )
        )
    return tuple(migrations)


def _quoted_identifier(value: str, label: str) -> str:
    """Validate and quote an identifier used by packaged migration SQL."""
    if not _IDENTIFIER_RE.fullmatch(value):
        raise _configuration_error(f"Invalid {label} identifier")
    return f'"{value}"'


def render_sql(sql: str, *, schema: str, bots_table: str) -> str:
    """Replace exact configured identifier tokens while preserving JSON braces."""
    return sql.replace("{schema}", _quoted_identifier(schema, "schema")).replace(
        "{bots_table}", _quoted_identifier(bots_table, "bots table")
    )


def _next_sequence(directory: Path) -> int:
    """Return the next body sequence from an explicit source directory."""
    sequences = [
        int(match["sequence"])
        for entry in directory.iterdir()
        if entry.is_file() and (match := _MIGRATION_RE.fullmatch(entry.name))
    ]
    return max(sequences, default=0) + 1


def scaffold(set_name: str, name: str, *, directory: Path) -> tuple[Path, Path]:
    """Exclusively create the next body/check pair in an explicit source directory."""
    if not _IDENTIFIER_RE.fullmatch(set_name) or not _IDENTIFIER_RE.fullmatch(name):
        raise _configuration_error("Migration set and name must be lowercase identifiers")
    if not directory.is_dir() or directory.name != set_name:
        raise _configuration_error("Migration source directory must exist and match the migration set")

    sequence = _next_sequence(directory)
    if sequence > 999:
        raise _configuration_error("Migration sequence exceeds 999")
    stem = f"{sequence:03d}_{name}"
    body_path = directory / f"{stem}.sql"
    check_path = directory / f"{stem}.check.sql"

    try:
        with body_path.open("x", encoding="utf-8") as body_file:
            body_file.write(f"-- {set_name} migration: {name}\n")
    except FileExistsError as error:
        raise _configuration_error(f"Migration scaffold already exists: {body_path}") from error

    try:
        with check_path.open("x", encoding="utf-8") as check_file:
            check_file.write("-- Replace with a query that verifies this migration's postcondition.\nSELECT FALSE;\n")
    except OSError as error:
        raise _configuration_error(f"Partial migration scaffold created: {body_path}; check not created: {check_path}") from error

    return body_path, check_path
