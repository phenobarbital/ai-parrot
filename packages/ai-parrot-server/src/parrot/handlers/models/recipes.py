"""PgRecipeStore — relational AbstractRecipeStore beside PgUISurfaceStore (FEAT-528).

Mirrors :class:`parrot.handlers.models.ui_surfaces.PgUISurfaceStore`'s shape
line for line: same ``AsyncDB("pg", dsn=...)`` per-call idiom, same lazy
``_ensure_ready()`` / ``ensure_schema()`` pattern, same ``navigator`` schema
default. One row per recipe, keyed by ``(name, owner)`` (``owner = ''`` means
unscoped/shared), so a recipe becomes editable, backed-up, queryable data
alongside the surfaces it produces.

``title``/``description`` are denormalised columns written on every ``save``
so ``list()`` never has to deserialise the full ``recipe`` JSONB payload.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from asyncdb import AsyncDB
from parrot.conf import default_dsn
from parrot.outputs.a2ui.recipes.models import InfographicRecipe
from parrot.outputs.a2ui.recipes.store import (
    AbstractRecipeStore,
    RecipeNotFoundError,
    _check_schema_version,
    _load_and_migrate,
)

logger = logging.getLogger(__name__)

#: Only a valid, unquoted SQL identifier is accepted for ``schema=`` — this
#: value is interpolated directly into DDL/DML (asyncpg has no identifier
#: bind-parameter support), so anything else is rejected before any SQL runs.
_VALID_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _ddl_statements(schema: str) -> list[str]:
    """Build the idempotent DDL for ``<schema>.infographic_recipes``.

    Args:
        schema: Already-validated schema name (see :func:`_validate_schema`).

    Returns:
        Ordered list of ``CREATE ... IF NOT EXISTS`` statements.
    """
    return [
        f"CREATE SCHEMA IF NOT EXISTS {schema}",
        f"""
        CREATE TABLE IF NOT EXISTS {schema}.infographic_recipes (
            name            VARCHAR      NOT NULL,
            owner           VARCHAR      NOT NULL DEFAULT '',
            schema_version  INTEGER      NOT NULL,
            title           TEXT,
            description     TEXT,
            recipe          JSONB        NOT NULL,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            PRIMARY KEY (name, owner)
        )
        """,
        f"CREATE INDEX IF NOT EXISTS ix_infographic_recipes_owner " f"ON {schema}.infographic_recipes (owner)",
    ]


def _validate_schema(schema: str) -> None:
    """Reject a schema name that is not a safe, unquoted SQL identifier.

    Args:
        schema: Candidate schema name.

    Raises:
        ValueError: If ``schema`` does not match ``^[A-Za-z_][A-Za-z0-9_]*$``.
    """
    if not _VALID_SCHEMA_RE.match(schema):
        raise ValueError(f"Invalid schema name {schema!r}: must match {_VALID_SCHEMA_RE.pattern!r}.")


def _insert_sql(schema: str) -> str:
    return f"""
    INSERT INTO {schema}.infographic_recipes
        (name, owner, schema_version, title, description, recipe, created_at, updated_at)
    VALUES ($1, $2, $3, $4, $5, $6::jsonb, NOW(), NOW())
    ON CONFLICT (name, owner) DO UPDATE SET
        schema_version = EXCLUDED.schema_version,
        title = EXCLUDED.title,
        description = EXCLUDED.description,
        recipe = EXCLUDED.recipe,
        updated_at = NOW()
    """


def _get_sql(schema: str) -> str:
    return f"""
    SELECT name, owner, schema_version, title, description, recipe, created_at, updated_at
    FROM {schema}.infographic_recipes
    WHERE name = $1 AND owner = $2
    """


def _list_sql(schema: str) -> str:
    return f"""
    SELECT name, title, description, owner, updated_at
    FROM {schema}.infographic_recipes
    WHERE owner = $1
    ORDER BY name
    """


def _delete_sql(schema: str) -> str:
    return f"""
    DELETE FROM {schema}.infographic_recipes
    WHERE name = $1 AND owner = $2
    RETURNING name
    """


def _raw_schema_version_sql(schema: str) -> str:
    return f"""
    SELECT schema_version
    FROM {schema}.infographic_recipes
    WHERE name = $1 AND owner = $2
    """


class PgRecipeStore(AbstractRecipeStore):
    """Postgres store for :class:`InfographicRecipe` rows.

    Args:
        dsn: Optional connection string; defaults to
            :data:`parrot.conf.default_dsn`, same as :class:`PgUISurfaceStore`.
        schema: Target schema (default ``"navigator"``). Validated eagerly
            against a safe-identifier allowlist — unlike
            :class:`PgUISurfaceStore`, which hardcodes ``navigator``, this
            store takes an explicit ``schema=`` keyword (spec §6).
    """

    def __init__(self, dsn: str | None = None, *, schema: str = "navigator") -> None:
        _validate_schema(schema)
        self.dsn = dsn or default_dsn
        self.schema = schema
        self.logger = logger
        self._schema_ensured = False

    def _get_db(self) -> AsyncDB:
        """Construct a fresh ``pg`` :class:`AsyncDB` wrapper for this store."""
        return AsyncDB("pg", dsn=self.dsn)

    async def _ensure_ready(self) -> None:
        """Lazily run :meth:`ensure_schema` on first store use."""
        if not self._schema_ensured:
            await self.ensure_schema()

    async def ensure_schema(self) -> None:
        """Create ``<schema>.infographic_recipes`` if missing.

        Idempotent — ``CREATE ... IF NOT EXISTS`` everywhere. Tolerates
        duplicate-object races under concurrent first-callers, mirroring
        :meth:`PgUISurfaceStore.ensure_schema`.
        """
        db = self._get_db()
        async with await db.connection() as conn:
            for stmt in _ddl_statements(self.schema):
                try:
                    await conn.execute(stmt)
                except Exception as exc:
                    if "already exists" in str(exc).lower():
                        self.logger.debug("infographic_recipes DDL race tolerated: %s", exc)
                        continue
                    raise
        self._schema_ensured = True
        self.logger.info("infographic_recipes schema ensured")

    async def save(self, recipe: InfographicRecipe) -> None:
        """Upsert ``recipe`` on ``(name, owner)``, bumping ``updated_at``."""
        await self._ensure_ready()
        owner = recipe.owner or ""
        db = self._get_db()
        async with await db.connection() as conn:
            # NOTE (deviation from the PgUISurfaceStore template): pass the raw
            # dict, NOT `json.dumps(...)`, for the `::jsonb`-cast parameter.
            # asyncdb's pg driver registers a custom jsonb codec that itself
            # calls its encoder's `dumps()` on whatever value it is given —
            # pre-serializing here double-encodes the payload into a jsonb
            # *string scalar* (verified live: a subsequent `jsonb_set` on such
            # a row fails with "cannot set path in scalar").
            await conn.execute(
                _insert_sql(self.schema),
                recipe.name,
                owner,
                recipe.schema_version,
                recipe.title,
                recipe.description,
                recipe.model_dump(mode="json"),
            )

    async def get(self, name: str, owner: Optional[str] = None) -> InfographicRecipe:
        """Load a recipe by name (and owner scope).

        Raises:
            RecipeNotFoundError: If no such recipe exists.
            RecipeSchemaVersionError: If the stored `schema_version` is unsupported.
        """
        await self._ensure_ready()
        scoped_owner = owner or ""
        db = self._get_db()
        async with await db.connection() as conn:
            # NOTE (deviation from the PgUISurfaceStore template): the installed
            # asyncdb driver's `pg.fetchrow()` is a no-argument CURSOR method,
            # not a `(sentence, *args)` single-row query — verified live against
            # asyncdb 2.15.10. `fetch_one(sentence, *args)` is the query-with-
            # params single-row call that actually exists on this driver.
            row = await conn.fetch_one(_get_sql(self.schema), name, scoped_owner)
        if row is None:
            raise RecipeNotFoundError(name, await self._available_names(owner))
        raw = _decode_jsonb(dict(row)["recipe"])
        recipe = _load_and_migrate(raw, name_for_error=name)
        return _check_schema_version(recipe)

    async def list(self, owner: Optional[str] = None) -> list[dict[str, Any]]:
        """List lightweight summaries from the denormalised columns only."""
        await self._ensure_ready()
        scoped_owner = owner or ""
        db = self._get_db()
        async with await db.connection() as conn:
            rows = await conn.fetchall(_list_sql(self.schema), scoped_owner)
        summaries = []
        for row in rows or []:
            data = dict(row)
            summaries.append(
                {
                    "name": data["name"],
                    "title": data["title"],
                    "description": data["description"],
                    "owner": data["owner"],
                    "updated_at": (
                        data["updated_at"].isoformat()
                        if hasattr(data["updated_at"], "isoformat")
                        else data["updated_at"]
                    ),
                }
            )
        return summaries

    async def delete(self, name: str, owner: Optional[str] = None) -> None:
        """Delete a recipe by name (and owner scope).

        Raises:
            RecipeNotFoundError: If no such recipe exists.
        """
        await self._ensure_ready()
        scoped_owner = owner or ""
        db = self._get_db()
        async with await db.connection() as conn:
            result = await conn.fetchval(_delete_sql(self.schema), name, scoped_owner)
        if result is None:
            raise RecipeNotFoundError(name, await self._available_names(owner))

    async def _raw_schema_version(self, name: str, owner: Optional[str] = None) -> int:
        """Return the ON-DISK ``schema_version`` column, without migrating it.

        Raises:
            RecipeNotFoundError: If no such recipe exists.
        """
        await self._ensure_ready()
        scoped_owner = owner or ""
        db = self._get_db()
        async with await db.connection() as conn:
            row = await conn.fetch_one(_raw_schema_version_sql(self.schema), name, scoped_owner)
        if row is None:
            raise RecipeNotFoundError(name, await self._available_names(owner))
        return int(dict(row)["schema_version"])

    async def _available_names(self, owner: Optional[str]) -> list[str]:
        """Return recipe names visible in ``owner``'s scope (for error messages)."""
        scoped_owner = owner or ""
        db = self._get_db()
        async with await db.connection() as conn:
            rows = await conn.fetchall(
                f"SELECT name FROM {self.schema}.infographic_recipes WHERE owner = $1",
                scoped_owner,
            )
        # `fetchall` (asyncdb's `fetch_all`) returns `None`, not `[]`, when no
        # rows match — normalize before iterating.
        return sorted(dict(row)["name"] for row in rows or [])


def _decode_jsonb(raw: Any) -> dict[str, Any]:
    """Normalize a JSONB column value into a plain ``dict``.

    Depending on the driver's codec configuration, the value may already be
    a ``dict`` (asyncpg with the jsonb codec registered) or a JSON-encoded
    string/bytes.
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        return json.loads(raw)
    return {}
