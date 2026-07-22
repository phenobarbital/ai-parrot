"""Recipe stores — AbstractRecipeStore + File + DB backends (Module 4, FEAT-324).

Two backends, both core ai-parrot (resolved brainstorm decision): a plain
YAML-per-file directory (:class:`FileRecipeStore`, for hand-authoring) and a
Redis-backed store (:class:`DBRecipeStore`), whose connection/config shape
mirrors :class:`parrot.skills.store.SkillRegistry` — a lazy, try/except
``redis.asyncio`` import behind a ``REDIS_AVAILABLE`` flag, an idempotent
``configure()``, and an in-memory dict fallback when Redis is absent or
unreachable. (SkillRegistry does NOT use asyncdb/a SQL table anywhere —
grep-verified — so this mirrors what actually exists, not a relational
pattern that would need to be invented.)

Versioning is simple overwrite + ``updated_at`` bump (spec G5); ``save()`` is
the single source of truth for ``updated_at`` (the TASK-1865 models do not
auto-set it). Owner scoping isolates recipes across all operations.

Core-side, dependency-free (spec G8): Redis is optional and imported lazily;
``FileRecipeStore`` works with zero DB extras installed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from parrot.outputs.a2ui.recipes.models import InfographicRecipe

try:
    from redis.asyncio import Redis

    REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when redis is absent
    REDIS_AVAILABLE = False
    Redis = None  # type: ignore[assignment,misc]

__all__ = [
    "AbstractRecipeStore",
    "DBRecipeStore",
    "FileRecipeStore",
    "RecipeNotFoundError",
    "RecipeSchemaVersionError",
    "SUPPORTED_SCHEMA_VERSION",
]

logger = logging.getLogger(__name__)

#: The only recipe `schema_version` this store generation understands. A
#: stored recipe carrying any other value fails to load with explicit
#: upgrade guidance rather than silently misinterpreting its shape.
SUPPORTED_SCHEMA_VERSION = 1

_VALID_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class RecipeNotFoundError(LookupError):
    """Raised when a requested recipe does not exist in the store.

    Attributes:
        name: The recipe name that was not found.
        available: Names of recipes actually present (same owner scope).
    """

    def __init__(self, name: str, available: list[str]) -> None:
        self.name = name
        self.available = available
        super().__init__(
            f"Recipe {name!r} not found; available recipes: {sorted(available)!r}"
        )


class RecipeSchemaVersionError(ValueError):
    """Raised when a stored recipe's `schema_version` is not supported."""

    def __init__(self, name: str, found_version: int) -> None:
        self.name = name
        self.found_version = found_version
        super().__init__(
            f"Recipe {name!r} has schema_version={found_version!r}, but this "
            f"store only supports schema_version={SUPPORTED_SCHEMA_VERSION!r}. "
            "Migrate the recipe (or the store) before loading it."
        )


def _validate_name(value: str, *, kind: str = "recipe name") -> None:
    """Reject path-traversal-shaped or otherwise unsafe names.

    Args:
        value: The candidate name (recipe name or owner scope).
        kind: Human-readable label used in the raised error.

    Raises:
        ValueError: If ``value`` is empty or contains characters outside the
            safe allowlist (letters, digits, ``.``, ``_``, ``-``) — this
            rejects path separators, ``..``, and absolute paths outright.
    """
    if not value or not _VALID_NAME_RE.match(value) or ".." in value:
        raise ValueError(
            f"Invalid {kind} {value!r}: only letters, digits, '.', '_', '-' are allowed."
        )


def _check_schema_version(recipe: InfographicRecipe) -> InfographicRecipe:
    if recipe.schema_version != SUPPORTED_SCHEMA_VERSION:
        raise RecipeSchemaVersionError(recipe.name, recipe.schema_version)
    return recipe


def _summary(recipe: InfographicRecipe) -> dict[str, Any]:
    """Build the lightweight listing dict for a recipe (spec: list() is NOT full recipes)."""
    return {
        "name": recipe.name,
        "title": recipe.title,
        "description": recipe.description,
        "owner": recipe.owner,
        "updated_at": recipe.updated_at.isoformat(),
    }


class AbstractRecipeStore(ABC):
    """Persistence contract shared by :class:`FileRecipeStore` and :class:`DBRecipeStore`.

    All operations accept an optional ``owner`` for scoping; recipes owned by
    different owners (including ``None``, the unscoped/shared owner) never
    collide even if they share a ``name``.
    """

    @abstractmethod
    async def save(self, recipe: InfographicRecipe) -> None:
        """Persist ``recipe``, overwriting any existing recipe with the same
        ``(name, owner)`` and bumping ``updated_at`` to now (UTC)."""
        raise NotImplementedError

    @abstractmethod
    async def get(self, name: str, owner: Optional[str] = None) -> InfographicRecipe:
        """Load a recipe by name (and owner scope).

        Raises:
            RecipeNotFoundError: If no such recipe exists.
            RecipeSchemaVersionError: If the stored `schema_version` is unsupported.
        """
        raise NotImplementedError

    @abstractmethod
    async def list(self, owner: Optional[str] = None) -> list[dict[str, Any]]:
        """List lightweight summaries (name/title/description/owner/updated_at)
        for every recipe in ``owner``'s scope."""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, name: str, owner: Optional[str] = None) -> None:
        """Delete a recipe by name (and owner scope).

        Raises:
            RecipeNotFoundError: If no such recipe exists.
        """
        raise NotImplementedError


class FileRecipeStore(AbstractRecipeStore):
    """One YAML file per recipe under ``directory`` (hand-authoring backend).

    Layout: ``<directory>/<name>.yaml`` for unscoped recipes, or
    ``<directory>/<owner>/<name>.yaml`` when ``owner`` is set. Writes are
    atomic (write-to-temp + ``os.replace``) so concurrent same-name saves
    never leave a partially-written file.
    """

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)

    def _scope_dir(self, owner: Optional[str]) -> Path:
        if owner is not None:
            _validate_name(owner, kind="owner")
            return self.directory / owner
        return self.directory

    def _path_for(self, name: str, owner: Optional[str]) -> Path:
        _validate_name(name)
        return self._scope_dir(owner) / f"{name}.yaml"

    @staticmethod
    def _write_atomic(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.parent / f".{path.name}.{os.getpid()}.tmp"
        tmp_path.write_text(text, encoding="utf-8")
        os.replace(tmp_path, path)

    async def save(self, recipe: InfographicRecipe) -> None:
        recipe = recipe.model_copy(update={"updated_at": datetime.now(timezone.utc)})
        path = self._path_for(recipe.name, recipe.owner)
        await asyncio.to_thread(self._write_atomic, path, recipe.to_yaml())

    async def get(self, name: str, owner: Optional[str] = None) -> InfographicRecipe:
        path = self._path_for(name, owner)
        if not await asyncio.to_thread(path.exists):
            raise RecipeNotFoundError(name, await self._available_names(owner))
        text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        recipe = InfographicRecipe.from_yaml(text)
        return _check_schema_version(recipe)

    async def list(self, owner: Optional[str] = None) -> list[dict[str, Any]]:
        scope_dir = self._scope_dir(owner)
        if not await asyncio.to_thread(scope_dir.is_dir):
            return []
        summaries = []
        for path in sorted(await asyncio.to_thread(lambda: list(scope_dir.glob("*.yaml")))):
            text = await asyncio.to_thread(path.read_text, encoding="utf-8")
            recipe = InfographicRecipe.from_yaml(text)
            summaries.append(_summary(recipe))
        return summaries

    async def delete(self, name: str, owner: Optional[str] = None) -> None:
        path = self._path_for(name, owner)
        if not await asyncio.to_thread(path.exists):
            raise RecipeNotFoundError(name, await self._available_names(owner))
        await asyncio.to_thread(path.unlink)

    async def _available_names(self, owner: Optional[str]) -> list[str]:
        scope_dir = self._scope_dir(owner)
        if not await asyncio.to_thread(scope_dir.is_dir):
            return []
        return [p.stem for p in await asyncio.to_thread(lambda: list(scope_dir.glob("*.yaml")))]


class DBRecipeStore(AbstractRecipeStore):
    """Redis-backed recipe store (falls back to in-memory when Redis is unavailable).

    Mirrors :class:`parrot.skills.store.SkillRegistry`'s connection shape: a
    lazy, try/except ``redis.asyncio`` import, an idempotent ``configure()``
    that connects (or degrades gracefully), and per-``namespace`` key
    isolation. There is no relational table here — SkillRegistry itself has
    none to copy.
    """

    def __init__(self, redis_url: Optional[str] = None, namespace: str = "default") -> None:
        self.logger = logging.getLogger(f"parrot.outputs.a2ui.recipes.{self.__class__.__name__}")
        self.namespace = namespace
        self.redis_url = redis_url
        self._redis: Optional["Redis"] = None
        self._use_redis = bool(redis_url) and REDIS_AVAILABLE
        # In-memory fallback, keyed by (owner-or-"", name).
        self._recipes: dict[tuple[str, str], InfographicRecipe] = {}
        self._configured = False
        self._lock = asyncio.Lock()

    async def configure(self) -> None:
        """Idempotently connect to Redis, falling back to in-memory on failure.

        Takes ``self._lock`` for the whole check-then-set so two concurrent
        first-callers cannot both attempt a Redis connection (the previous,
        lock-free double-checked version had exactly that race).
        """
        async with self._lock:
            if self._configured:
                return
            if self._use_redis:
                try:
                    self._redis = Redis.from_url(
                        self.redis_url, decode_responses=True, socket_connect_timeout=5
                    )
                    await self._redis.ping()
                    self.logger.info("DBRecipeStore connected to Redis")
                except Exception as exc:  # noqa: BLE001 - mirrors SkillRegistry's broad fallback
                    self.logger.warning(
                        "DBRecipeStore Redis connection failed (%s); using in-memory store", exc
                    )
                    self._use_redis = False
            self._configured = True

    def _key(self, name: str, owner: Optional[str]) -> str:
        return f"a2ui_recipe:{self.namespace}:{owner or '_'}:{name}"

    def _index_key(self, owner: Optional[str]) -> str:
        return f"a2ui_recipes:{self.namespace}:{owner or '_'}"

    async def save(self, recipe: InfographicRecipe) -> None:
        await self.configure()
        recipe = recipe.model_copy(update={"updated_at": datetime.now(timezone.utc)})
        async with self._lock:
            if self._use_redis and self._redis:
                await self._redis.set(
                    self._key(recipe.name, recipe.owner), recipe.model_dump_json()
                )
                await self._redis.sadd(self._index_key(recipe.owner), recipe.name)
            else:
                self._recipes[(recipe.owner or "", recipe.name)] = recipe

    async def get(self, name: str, owner: Optional[str] = None) -> InfographicRecipe:
        await self.configure()
        if self._use_redis and self._redis:
            payload = await self._redis.get(self._key(name, owner))
            if payload is None:
                raise RecipeNotFoundError(name, await self._available_names(owner))
            recipe = InfographicRecipe.model_validate_json(payload)
        else:
            recipe = self._recipes.get((owner or "", name))
            if recipe is None:
                raise RecipeNotFoundError(name, await self._available_names(owner))
        return _check_schema_version(recipe)

    async def list(self, owner: Optional[str] = None) -> list[dict[str, Any]]:
        await self.configure()
        names = await self._available_names(owner)
        if not names:
            return []

        if self._use_redis and self._redis:
            # Single MGET instead of N sequential GETs (one per recipe).
            keys = [self._key(name, owner) for name in names]
            payloads = await self._redis.mget(keys)
            summaries = []
            for name, payload in zip(names, payloads):
                if payload is None:
                    continue  # index/value race (deleted between smembers and mget)
                recipe = _check_schema_version(InfographicRecipe.model_validate_json(payload))
                summaries.append(_summary(recipe))
            return summaries

        summaries = []
        for name in names:
            recipe = await self.get(name, owner)
            summaries.append(_summary(recipe))
        return summaries

    async def delete(self, name: str, owner: Optional[str] = None) -> None:
        await self.configure()
        async with self._lock:
            if self._use_redis and self._redis:
                removed = await self._redis.delete(self._key(name, owner))
                if not removed:
                    raise RecipeNotFoundError(name, await self._available_names(owner))
                await self._redis.srem(self._index_key(owner), name)
            else:
                if (owner or "", name) not in self._recipes:
                    raise RecipeNotFoundError(name, await self._available_names(owner))
                del self._recipes[(owner or "", name)]

    async def _available_names(self, owner: Optional[str]) -> list[str]:
        if self._use_redis and self._redis:
            members = await self._redis.smembers(self._index_key(owner))
            return sorted(members)
        return sorted(n for (o, n) in self._recipes if o == (owner or ""))
