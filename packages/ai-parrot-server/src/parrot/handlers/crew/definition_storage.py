"""Authoritative crew definition routing and migration results."""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from .models import CrewDefinition
from .postgres_persistence import CrewPostgres
from .redis_persistence import CrewRedis, CrewRedisCleanupResult


class CrewStorageUnavailable(RuntimeError):
    """A required storage operation failed without a trustworthy answer."""


class CrewStorageConflict(ValueError):
    """An authoritative identity conflicts with the requested mutation."""


class CrewDeletionResolution(BaseModel):
    """Tombstone-aware result used for idempotent manager removal."""

    state: Literal["active", "deleted", "absent"]
    definition: CrewDefinition | None = None
    tenant: str | None = None
    name: str | None = None
    crew_id: str | None = None


class CrewMigrationReport(BaseModel):
    """Per-sweep outcomes; tenant:name keys and predicted outcomes in dry runs."""

    dry_run: bool = False
    lock_acquired: bool = True
    skipped_reason: str | None = None
    migrated: list[str] = Field(default_factory=list)
    already_present: list[str] = Field(default_factory=list)
    deleted_sources: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    failed: dict[str, str] = Field(default_factory=dict)
    redis_cleanup_failed: list[str] = Field(default_factory=list)


class CrewDefinitionStorage:
    """Route crews to an immutable configured primary store."""

    def __init__(self, redis: CrewRedis, postgres: CrewPostgres | None = None, *, migration: bool = False) -> None:
        """Initialize storage routing.

        Args:
            redis: Legacy Redis definition store.
            postgres: Configured authoritative store, when PostgreSQL mode is enabled.
            migration: Reserved migration feature flag.
        """
        self.redis = redis
        self.postgres = postgres
        self.migration = migration
        self._postgres_active = False
        self.logger = logging.getLogger(__name__)

    @property
    def postgres_active(self) -> bool:
        """Return last observed Postgres health, not a routing decision."""
        return self._postgres_active

    @property
    def _uses_postgres(self) -> bool:
        """Return whether Postgres was explicitly configured as the primary."""
        return self.postgres is not None

    def _translate_exception(self, operation: str, error: Exception) -> Exception:
        """Map backend failures without exposing backend connection details.

        Args:
            operation: Public operation which failed.
            error: Backend error to classify.

        Returns:
            A typed public storage exception.
        """
        if isinstance(error, (CrewStorageUnavailable, CrewStorageConflict)):
            return error
        message = str(error).lower()
        if isinstance(error, ValueError) or any(
            marker in message for marker in ("unique", "duplicate", "integrity", "constraint", "identity")
        ):
            return CrewStorageConflict(f"Crew definition {operation} conflicts with authoritative storage")
        return CrewStorageUnavailable(f"Crew definition {operation} is unavailable")

    def _decode_row(self, row: object) -> CrewDefinition | None:
        """Decode an authoritative row while retaining malformed-row authority."""
        if row is None:
            return None
        try:
            return self.postgres._decode_row(row)  # type: ignore[union-attr]
        except (TypeError, ValueError) as error:
            self.logger.warning("Skipping malformed authoritative crew definition: %s", error)
            return None

    @staticmethod
    def _is_deleted(row: object) -> bool:
        """Return whether a stored row is a durable tombstone."""
        return row.deleted_at is not None

    async def initialize(self) -> CrewMigrationReport | None:
        """Probe configured stores and log startup failures without changing routing."""
        redis_active = False
        try:
            redis_active = bool(await self.redis.ping())
            if not redis_active:
                self.logger.warning("Redis crew definition storage health probe failed")
        except Exception:
            self.logger.warning("Redis crew definition storage health probe failed")

        if self.postgres is None:
            return None

        try:
            self._postgres_active = bool(await self.postgres.ping())
            if not self._postgres_active:
                self.logger.warning("Postgres crew definition storage health probe failed")
        except Exception:
            self._postgres_active = False
            self.logger.warning("Postgres crew definition storage health probe failed")

        if not self.migration:
            return None
        if not redis_active:
            return CrewMigrationReport(skipped_reason="Redis health check failed")
        if not self._postgres_active:
            return CrewMigrationReport(skipped_reason="Postgres health check failed")
        return await self.migrate_from_redis()

    @staticmethod
    def _documents_match(left: CrewDefinition, right: CrewDefinition) -> bool:
        """Compare complete normalized definitions except storage timestamps."""
        excluded = {"created_at", "updated_at"}
        return left.model_dump(mode="json", exclude=excluded) == right.model_dump(mode="json", exclude=excluded)

    async def migrate_from_redis(self, *, dry_run: bool = False) -> CrewMigrationReport:
        """Copy, verify and conditionally clean sources under one session advisory lock."""
        report = CrewMigrationReport(dry_run=dry_run)
        if self.postgres is None:
            report.lock_acquired = False
            report.skipped_reason = "Postgres storage is not configured"
            return report
        if dry_run and not getattr(self.postgres, "_schema_ensured", True):
            report.skipped_reason = "Postgres schema is not available for dry run"
            return report

        try:
            async with self.postgres.migration_lock() as acquired:
                report.lock_acquired = acquired
                if not acquired:
                    report.skipped_reason = "Migration advisory lock not acquired"
                    return report
                try:
                    inventory = await self.redis.list_all_crews_strict()
                except Exception as error:
                    report.skipped_reason = f"Redis inventory failed: {error}"
                    return report

                snapshots = []
                for entry in inventory:
                    key = f"{entry['tenant']}:{entry['name']}"
                    try:
                        snapshot = await self.redis.snapshot_crew(entry["name"], entry["tenant"])
                        if snapshot is None:
                            raise CrewStorageUnavailable("Redis snapshot disappeared during migration")
                        snapshots.append(snapshot)
                    except Exception as error:
                        if "conflicting namespaced and legacy" in str(error).lower():
                            report.conflicts.append(key)
                        report.failed[key] = str(error)

                for snapshot in snapshots:
                    key = f"{snapshot.tenant}:{snapshot.name}"
                    try:
                        existing = await self._load_authoritative_row(snapshot.name, snapshot.tenant)
                        inserted = False
                        if dry_run:
                            if existing is None:
                                outcome = "migrated"
                                row = None
                            else:
                                row = existing
                        else:
                            inserted = await self.postgres.insert_if_absent(snapshot.definition)
                            row = await self._load_authoritative_row(snapshot.name, snapshot.tenant)
                        if row is None and not (dry_run and outcome == "migrated"):
                            report.failed[key] = "Postgres row missing after migration insert"
                            continue
                        if row is not None and self._is_deleted(row):
                            outcome = "deleted"
                        elif row is not None:
                            stored = self._decode_row(row)
                            if stored is None:
                                report.failed[key] = "Postgres definition is malformed"
                                continue
                            if not self._documents_match(stored, snapshot.definition):
                                report.conflicts.append(key)
                                report.failed[key] = "definition conflict"
                                continue
                            outcome = "migrated" if inserted or existing is None else "already_present"

                        if dry_run:
                            if outcome == "migrated":
                                report.migrated.append(key)
                            elif outcome == "already_present":
                                report.already_present.append(key)
                            else:
                                report.deleted_sources.append(key)
                            continue

                        try:
                            cleanup = await self.redis.delete_snapshot(snapshot)
                        except Exception as error:
                            self.logger.warning("Redis migration cleanup failed for %s: %s", key, error)
                            report.redis_cleanup_failed.append(key)
                            continue
                        if cleanup is not CrewRedisCleanupResult.deleted:
                            report.failed[key] = "source changed"
                            continue
                        if outcome == "migrated":
                            report.migrated.append(key)
                        elif outcome == "already_present":
                            report.already_present.append(key)
                        else:
                            report.deleted_sources.append(key)
                    except Exception as error:
                        report.failed[key] = str(error)
        except Exception as error:
            report.skipped_reason = f"Migration lock failed: {error}"
        return report

    async def _load_authoritative_row(self, name: str, tenant: str | None = None) -> object | None:
        """Load a Postgres row by name, translating backend failures."""
        try:
            return await self.postgres._load_row(name, tenant)  # type: ignore[union-attr]
        except Exception as error:
            raise self._translate_exception("read", error) from error

    async def _load_authoritative_id_row(self, crew_id: str, tenant: str | None = None) -> object | None:
        """Load a Postgres row by ID, translating backend failures."""
        try:
            return await self.postgres._load_row_by_id(crew_id, tenant)  # type: ignore[union-attr]
        except Exception as error:
            raise self._translate_exception("read", error) from error

    async def _redis_candidate_is_unreserved(self, crew: CrewDefinition, tenant: str | None) -> bool:
        """Check both authoritative identities before returning a Redis fallback."""
        row_by_name = await self._load_authoritative_row(crew.name, tenant)
        row_by_id = await self._load_authoritative_id_row(crew.crew_id, tenant)
        return row_by_name is None and row_by_id is None

    async def resolve_for_delete(self, identifier: str, tenant: str | None = None) -> CrewDeletionResolution:
        """Resolve active, deleted, or absent crews by name then ID.

        Args:
            identifier: Crew name or ID.
            tenant: Optional tenant identifier.

        Returns:
            Typed deletion state and the stored definition when decodable.
        """
        if not self._uses_postgres:
            crew = await self.redis.load_crew(identifier, tenant)
            if crew is None:
                crew = await self.redis.load_crew_by_id(identifier, tenant)
            return (
                CrewDeletionResolution(state="active", definition=crew)
                if crew
                else CrewDeletionResolution(state="absent")
            )

        row = await self._load_authoritative_row(identifier, tenant)
        if row is None:
            row = await self._load_authoritative_id_row(identifier, tenant)
        if row is None:
            crew = await self.redis.load_crew(identifier, tenant)
            if crew is None:
                crew = await self.redis.load_crew_by_id(identifier, tenant)
                if crew is not None and crew.crew_id != identifier:
                    crew = None
            if crew is not None and await self._redis_candidate_is_unreserved(crew, tenant):
                return CrewDeletionResolution(state="active", definition=crew)
            return CrewDeletionResolution(state="absent")
        state: Literal["active", "deleted"] = "deleted" if self._is_deleted(row) else "active"
        return CrewDeletionResolution(
            state=state,
            definition=self._decode_row(row),
            tenant=row.tenant,
            name=row.name,
            crew_id=row.crew_id,
        )

    async def tombstone_resolution(self, resolution: CrewDeletionResolution) -> bool:
        """Tombstone a resolved row whose definition cannot be decoded.

        Args:
            resolution: Active resolution carrying the stored identity but no definition.

        Returns:
            ``True`` once the tombstone is committed.

        Raises:
            CrewStorageUnavailable: If storage is unavailable or the resolution has no identity.
            CrewStorageConflict: If the row no longer has the resolved identity.
        """
        if not self._uses_postgres or resolution.name is None or resolution.crew_id is None:
            raise CrewStorageUnavailable("Crew definition delete is unavailable")
        try:
            return bool(await self.postgres.tombstone_identity(resolution.tenant, resolution.name, resolution.crew_id))
        except Exception as error:
            raise self._translate_exception("delete", error) from error

    async def create_crew(self, crew: CrewDefinition) -> bool:
        """Create a crew without replacing an existing live definition.

        Args:
            crew: Definition to create.

        Returns:
            ``True`` when created.

        Raises:
            CrewStorageConflict: If a live crew already holds the name or the ID collides.
            CrewStorageUnavailable: If the configured store cannot persist it.
        """
        if not self._uses_postgres:
            return await self.redis.save_crew(crew)
        try:
            created = await self.postgres.create_crew(crew)  # type: ignore[union-attr]
        except Exception as error:
            raise self._translate_exception("create", error) from error
        if not created:
            raise CrewStorageConflict("Crew definition create conflicts with an existing crew name")
        return True

    async def delete_crew(self, crew: CrewDefinition) -> bool:
        """Commit an authoritative tombstone before best-effort Redis cleanup."""
        if not self._uses_postgres:
            return await self.redis.delete_crew(crew.name, crew.tenant)

        try:
            result = await self.postgres.delete_crew(crew)  # type: ignore[union-attr]
        except Exception as error:
            raise self._translate_exception("delete", error) from error
        if not result:
            raise CrewStorageUnavailable("Crew definition delete is unavailable")

        try:
            if not await self.redis.delete_crew(crew.name, crew.tenant):
                self.logger.warning("Redis cleanup did not remove crew %s:%s", crew.tenant or "global", crew.name)
        except Exception:
            self.logger.warning("Redis cleanup failed for crew %s:%s", crew.tenant or "global", crew.name)
        return True

    async def ping(self) -> bool:
        """Return configured primary health without substituting another backend."""
        if not self._uses_postgres:
            return await self.redis.ping()
        try:
            self._postgres_active = bool(await self.postgres.ping())  # type: ignore[union-attr]
        except Exception:
            self._postgres_active = False
        return self._postgres_active

    async def close(self) -> None:
        """Close both configured stores without leaking resources."""
        errors: list[Exception] = []
        for store in (self.redis, self.postgres):
            if store is None:
                continue
            try:
                await store.close()
            except Exception as error:
                errors.append(error)
        if errors:
            raise self._translate_exception("close", errors[0]) from errors[0]

    async def save_crew(self, crew: CrewDefinition) -> bool:
        """Write only the configured primary store."""
        if not self._uses_postgres:
            return await self.redis.save_crew(crew)
        try:
            result = await self.postgres.save_crew(crew)  # type: ignore[union-attr]
        except Exception as error:
            raise self._translate_exception("save", error) from error
        if not result:
            raise CrewStorageUnavailable("Crew definition save is unavailable")
        return True

    async def load_crew(self, name: str, tenant: str | None = None) -> CrewDefinition | None:
        """Load by name with both authoritative identities guarding fallback."""
        if not self._uses_postgres:
            return await self.redis.load_crew(name, tenant)

        row = await self._load_authoritative_row(name, tenant)
        if row is not None:
            return None if self._is_deleted(row) else self._decode_row(row)

        crew = await self.redis.load_crew(name, tenant)
        if crew is None or not await self._redis_candidate_is_unreserved(crew, tenant):
            return None
        return crew

    async def load_crew_by_id(self, crew_id: str, tenant: str | None = None) -> CrewDefinition | None:
        """Load by ID while rejecting stale aliases and tombstones."""
        if not self._uses_postgres:
            return await self.redis.load_crew_by_id(crew_id, tenant)

        row = await self._load_authoritative_id_row(crew_id, tenant)
        if row is not None:
            return None if self._is_deleted(row) else self._decode_row(row)

        crew = await self.redis.load_crew_by_id(crew_id, tenant)
        if crew is None or crew.crew_id != crew_id or not await self._redis_candidate_is_unreserved(crew, tenant):
            return None
        return crew

    async def _union(self, tenant: str | None = None) -> tuple[list[dict[str, str]], list[CrewDefinition]]:
        """Build one complete Redis-first snapshot union for both list APIs."""
        if not self._uses_postgres:
            entries = await self.redis.list_all_crews()
            crews = await self.redis.get_all_crews(tenant)
            return entries, crews

        try:
            inventory = await self.redis.list_all_crews_strict()
            if tenant is not None:
                inventory = [entry for entry in inventory if entry["tenant"] == (tenant or "global")]
            snapshots = []
            vanished: list[tuple[str, str]] = []
            for entry in inventory:
                try:
                    snapshot = await self.redis.snapshot_crew(entry["name"], entry["tenant"])
                except ValueError as error:
                    # A malformed or conflicting Redis source is retained for reconciliation; it must not hide
                    # the authoritative Postgres definitions. Backend failures (not ValueError) still propagate.
                    self.logger.warning(
                        "Skipping unreadable Redis crew %s:%s in listing: %s", entry["tenant"], entry["name"], error
                    )
                    continue
                if snapshot is None:
                    vanished.append((entry["tenant"], entry["name"]))
                    continue
                snapshots.append(snapshot)
            rows = await self.postgres._list_rows(tenant)  # type: ignore[union-attr]
        except CrewStorageUnavailable:
            raise
        except Exception as error:
            raise self._translate_exception("list", error) from error

        identities = {(row.tenant, row.name): row for row in rows}
        ids = {(row.tenant, row.crew_id): row for row in rows}
        for identity in vanished:
            # An entry that disappeared after the inventory was captured is explained only by a Postgres row
            # (for example a concurrent migration); otherwise the view is incomplete and must not be used.
            if identity not in identities:
                raise CrewStorageUnavailable("Crew definition inventory snapshot is incomplete")
        crews: list[CrewDefinition] = []
        entries: list[dict[str, str]] = []
        included = set()
        for row in rows:
            if self._is_deleted(row):
                continue
            crew = self._decode_row(row)
            if crew is not None:
                crews.append(crew)
                entries.append({"tenant": row.tenant, "name": row.name})
                included.add((row.tenant, row.name))
        for snapshot in snapshots:
            crew = snapshot.definition
            identity = (snapshot.tenant, snapshot.name)
            if identity in identities or (snapshot.tenant, crew.crew_id) in ids:
                continue
            if identity not in included:
                crews.append(crew)
                entries.append({"tenant": snapshot.tenant, "name": snapshot.name})
                included.add(identity)
        entries.sort(key=lambda entry: (entry["tenant"], entry["name"]))
        crews.sort(key=lambda crew: (crew.tenant or "global", crew.name))
        return entries, crews

    async def list_all_crews(self) -> list[dict[str, str]]:
        """List a complete union of active Postgres and unreserved Redis crews."""
        if not self._uses_postgres:
            return await self.redis.list_all_crews()
        entries, _ = await self._union()
        return entries

    async def get_all_crews(self, tenant: str | None = None) -> list[CrewDefinition]:
        """Return a complete union of validated crew definitions."""
        if not self._uses_postgres:
            return await self.redis.get_all_crews(tenant)
        _, crews = await self._union(tenant)
        return crews
