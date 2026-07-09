"""FormVersionService — immutable semver publishing for FormSchema objects.

Implements the form publishing lifecycle described in FEAT-300 §2 (RF-06):
- Publishing freezes the current form as a semver-tagged snapshot.
- Published snapshots are immutable — overwriting raises ``ValueError``.
- In-flight responses resolve against the version they started with.
- Deletion of a form/version with associated responses is blocked (caller
  provides a ``has_responses`` hook).

FEAT-300 — Module 4.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict

from ..core.schema import FormSchema
from ._db_utils import is_unique_violation
from .registry import FormRegistry, FormStorage

logger = logging.getLogger(__name__)

#: Upper bound for storage probing when reconstructing version history
#: (defensive cap — real forms have far fewer published versions).
_MAX_VERSION_PROBES = 200


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class VersionMeta(BaseModel):
    """Metadata record for a published form version.

    Attributes:
        form_id: The form's canonical identifier.
        version: The semver-style ``major.minor`` tag (e.g. ``"1.0"``).
        published_at: UTC timestamp when this version was published.
        tenant: Tenant slug.
        is_frozen: Always ``True`` — published versions are immutable.
    """

    model_config = ConfigDict(extra="forbid")

    form_id: str
    version: str
    published_at: datetime
    tenant: str
    is_frozen: bool = True


# ---------------------------------------------------------------------------
# Semver helpers
# ---------------------------------------------------------------------------

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)$")


def _parse_major_minor(version: str) -> tuple[int, int]:
    """Parse a ``major.minor`` version string.

    Args:
        version: Version string, e.g. ``"1.0"`` or ``"2.3"``.

    Returns:
        ``(major, minor)`` ints. Falls back to ``(1, 0)`` on parse failure.
    """
    m = _SEMVER_RE.match(version or "")
    if m:
        return int(m.group(1)), int(m.group(2))
    logger.warning("Could not parse version %r as major.minor — defaulting to (1, 0)", version)
    return 1, 0


def _bump(current: str, bump: str = "minor") -> str:
    """Bump a ``major.minor`` version string.

    Args:
        current: Current version (e.g. ``"1.0"``).
        bump: ``"minor"`` (default) or ``"major"``.

    Returns:
        New version string. ``"1.0"`` + minor → ``"1.1"``; + major → ``"2.0"``.
    """
    major, minor = _parse_major_minor(current)
    if bump == "major":
        return f"{major + 1}.0"
    return f"{major}.{minor + 1}"


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class FormVersionService:
    """Immutable semver publishing service for ``FormSchema`` objects.

    Each call to :meth:`publish` creates a frozen snapshot identified by a
    bumped semver tag.  The snapshot is stored via ``storage.save()`` when
    available; an in-memory fallback (dict) is used otherwise (suitable for
    tests and development).

    Deletion is guarded by the optional ``has_responses`` async hook: if
    supplied, the service calls it before any delete to confirm no response
    data exists.  If the hook returns ``True``, deletion raises ``ValueError``
    and the form is only deactivated (not deleted).

    Example::

        svc = FormVersionService(registry, storage)
        tag = await svc.publish("my-form", tenant="navigator")  # → "1.1"
        snap = await svc.get_published("my-form", version="1.1", tenant="navigator")

    Args:
        registry: ``FormRegistry`` used to look up the live form state and
            register snapshots when a ``storage`` backend is not available.
        storage: ``FormStorage`` used to persist snapshots. When ``None``,
            the service stores snapshots in an in-memory dict.
        has_responses: Optional async callback ``(form_id, tenant) -> bool``
            that returns ``True`` when the form/version has associated
            responses. When ``True`` is returned, deletion is blocked.
    """

    def __init__(
        self,
        registry: FormRegistry,
        storage: FormStorage | None = None,
        *,
        has_responses: Callable[[str, str], Awaitable[bool]] | None = None,
    ) -> None:
        self._registry = registry
        self._storage = storage
        self._has_responses = has_responses
        self.logger = logging.getLogger(__name__)

        # In-memory fallback stores:
        # _snapshots[tenant][form_id][version] = FormSchema
        self._snapshots: dict[str, dict[str, dict[str, FormSchema]]] = {}
        # _meta[tenant][form_id] = list[VersionMeta]
        self._meta: dict[str, dict[str, list[VersionMeta]]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def publish(
        self,
        form_id: str,
        *,
        tenant: str,
        bump: str = "minor",
    ) -> str:
        """Publish the current form as an immutable semver snapshot.

        Steps:
        1. Load the live form from the registry.
        2. Compute the next semver tag.
        3. Raise ``ValueError`` if that tag already exists (immutability).
        4. Set ``published_version`` on a deep copy.
        5. Persist the snapshot (storage or in-memory).

        Args:
            form_id: The form's canonical ID.
            tenant: Tenant slug.
            bump: ``"minor"`` (default) or ``"major"``.

        Returns:
            The new version string (e.g. ``"1.1"``).

        Raises:
            KeyError: If the form is not found in the registry.
            ValueError: If the computed version tag already exists (immutable).
        """
        form = await self._registry.get(form_id, tenant=tenant)
        if form is None:
            raise KeyError(f"Form '{form_id}' not found under tenant '{tenant}'")

        new_version = _bump(form.version, bump=bump)

        # Immutability guard
        existing = await self.get_published(form_id, version=new_version, tenant=tenant)
        if existing is not None:
            raise ValueError(
                f"Version '{new_version}' of form '{form_id}' already exists and is frozen."
            )

        published_at = datetime.now(timezone.utc)

        # Build frozen snapshot. ``published_at`` is stamped into ``meta`` so
        # version history can be reconstructed from storage after a restart.
        snapshot = form.model_copy(deep=True, update={
            "version": new_version,
            "published_version": new_version,
            "meta": {**(form.meta or {}), "published_at": published_at.isoformat()},
        })

        # Persist. The database UNIQUE(form_id, version) constraint is the
        # authoritative immutability guard — two concurrent publishes cannot
        # both succeed (the pre-check above is a fast path, not the guard).
        try:
            await self._save_snapshot(snapshot, tenant=tenant)
        except Exception as exc:
            if _is_unique_violation(exc):
                raise ValueError(
                    f"Version '{new_version}' of form '{form_id}' already exists and is frozen."
                ) from exc
            raise

        # Update the live form's published_version in the registry
        updated_live = form.model_copy(deep=True, update={
            "version": new_version,
            "published_version": new_version,
        })
        await self._registry.register(updated_live, persist=False, overwrite=True, tenant=tenant)

        # Record VersionMeta
        meta = VersionMeta(
            form_id=form_id,
            version=new_version,
            published_at=published_at,
            tenant=tenant,
        )
        self._meta.setdefault(tenant, {}).setdefault(form_id, []).append(meta)

        self.logger.info(
            "Published form '%s' as version '%s' for tenant '%s'",
            form_id, new_version, tenant,
        )
        return new_version

    async def get_published(
        self,
        form_id: str,
        *,
        version: str,
        tenant: str,
    ) -> FormSchema | None:
        """Retrieve an immutable published snapshot.

        Always returns the untouched snapshot at ``version`` — subsequent
        publishes do not affect it (RF-06).

        Args:
            form_id: The form's canonical ID.
            version: The semver tag to retrieve (e.g. ``"1.1"``).
            tenant: Tenant slug.

        Returns:
            Frozen ``FormSchema`` snapshot, or ``None`` if not found.
        """
        if self._storage is not None:
            snap = await self._storage.load(form_id, version=version, tenant=tenant)
            if snap is not None and snap.published_version == version:
                return snap
        # In-memory fallback
        return (
            self._snapshots
            .get(tenant, {})
            .get(form_id, {})
            .get(version)
        )

    async def list_versions(
        self,
        form_id: str,
        *,
        tenant: str,
    ) -> list[VersionMeta]:
        """List all published version metadata for a form.

        Merges the in-process ``VersionMeta`` cache with a reconstruction
        from storage, so history survives a process restart (the snapshots
        live in Postgres under ``UNIQUE(form_id, version)``; ``published_at``
        is recovered from the stamp written into ``snapshot.meta`` by
        :meth:`publish`).

        Args:
            form_id: The form's canonical ID.
            tenant: Tenant slug.

        Returns:
            List of ``VersionMeta`` objects ordered by (major, minor).
        """
        by_version: dict[str, VersionMeta] = {
            m.version: m for m in self._meta.get(tenant, {}).get(form_id, [])
        }

        if self._storage is not None:
            for version in await self._probe_storage_versions(form_id, tenant=tenant):
                if version in by_version:
                    continue
                snap = await self._storage.load(form_id, version=version, tenant=tenant)
                if snap is None or snap.published_version != version:
                    continue
                by_version[version] = VersionMeta(
                    form_id=form_id,
                    version=version,
                    published_at=self._published_at_from_snapshot(snap),
                    tenant=tenant,
                )

        return sorted(by_version.values(), key=lambda m: _parse_major_minor(m.version))

    async def _probe_storage_versions(self, form_id: str, *, tenant: str) -> list[str]:
        """Enumerate published version tags persisted in storage.

        ``FormStorage`` has no version-listing API, but publish tags form a
        contiguous semver chain (each publish bumps from the live version),
        so the history is recoverable by probing minors per major up to the
        latest stored version. A single leading miss per major is tolerated
        (the first publish of a form is usually ``X.1``, not ``X.0``).
        """
        latest = await self._storage.load(form_id, tenant=tenant)
        if latest is None:
            return []
        latest_major, _ = _parse_major_minor(latest.version)

        found: list[str] = []
        probes = 0
        for major in range(1, latest_major + 1):
            minor = 0
            misses = 0
            while misses < 2 and probes < _MAX_VERSION_PROBES:
                version = f"{major}.{minor}"
                snap = await self._storage.load(form_id, version=version, tenant=tenant)
                probes += 1
                if snap is not None and snap.published_version == version:
                    found.append(version)
                    misses = 0
                else:
                    misses += 1
                minor += 1
        return found

    @staticmethod
    def _published_at_from_snapshot(snap: FormSchema) -> datetime:
        """Recover the publish timestamp stamped into ``snapshot.meta``."""
        stamp = (snap.meta or {}).get("published_at")
        if isinstance(stamp, str):
            try:
                return datetime.fromisoformat(stamp)
            except ValueError:
                pass
        return snap.created_at or datetime.now(timezone.utc)

    async def can_delete(self, form_id: str, *, tenant: str) -> bool:
        """Return ``True`` if deletion is safe (no responses associated).

        If no ``has_responses`` hook was provided, deletion is always
        considered safe (returns ``True``).

        Args:
            form_id: The form's canonical ID.
            tenant: Tenant slug.

        Returns:
            ``True`` if deletion is permitted.
        """
        if self._has_responses is None:
            return True
        has = await self._has_responses(form_id, tenant)
        return not has

    async def safe_delete(self, form_id: str, *, tenant: str) -> None:
        """Delete a form only if it has no responses.

        Raises:
            ValueError: If ``has_responses`` returns ``True`` for this form.
        """
        if not await self.can_delete(form_id, tenant=tenant):
            raise ValueError(
                f"Form '{form_id}' has responses and cannot be deleted. "
                "Deactivate it instead."
            )
        if self._storage is not None:
            await self._storage.delete(form_id, tenant=tenant)
        # Also remove from the registry (public API — never touch _forms)
        await self._registry.unregister(form_id, tenant=tenant)

    # ------------------------------------------------------------------
    # Backfill (TASK-005)
    # ------------------------------------------------------------------

    async def backfill_published(
        self,
        *,
        tenant: str,
        dry_run: bool = False,
    ) -> int:
        """Backfill pre-existing forms as published v1.0 snapshots.

        For every form whose ``published_version`` is ``None``, marks it as
        published at its current ``version`` value (default ``"1.0"``).
        Already-backfilled forms (``published_version is not None``) are
        skipped — the operation is idempotent.

        This resolves decision C3 (spec §8): forms created before FEAT-300 had
        no version history.  Running this migration once enables
        ``FormVersionService`` on tenants with pre-existing forms.

        Args:
            tenant: Tenant slug to backfill.
            dry_run: If ``True``, logs what would change but persists nothing.

        Returns:
            Number of forms that were (or would be) backfilled.
        """
        changed = 0

        # --- Collect forms needing backfill ---
        # Strategy: iterate registry forms for this tenant (public API),
        # then also check storage-persisted forms if a backend is available.
        forms_to_backfill: list[FormSchema] = []

        # Registry entries (public API — never touch _forms)
        for form in await self._registry.list_forms(tenant=tenant):
            if form.published_version is None:
                forms_to_backfill.append(form)

        # Storage-persisted forms (may not overlap with in-memory).
        # Storage failures are fatal: silently returning changed=0 would make
        # operators believe nothing needed backfilling (review M5).
        if self._storage is not None:
            try:
                rows = await self._storage.list_forms(tenant=tenant)
                seen_ids = {f.form_id for f in forms_to_backfill}
                for row in rows:
                    fid = row.get("form_id")
                    if not fid or fid in seen_ids:
                        continue
                    loaded = await self._storage.load(fid, tenant=tenant)
                    if loaded is not None and loaded.published_version is None:
                        forms_to_backfill.append(loaded)
            except Exception:
                self.logger.error(
                    "backfill_published: storage unreachable for tenant '%s' — aborting",
                    tenant,
                )
                raise

        # --- Backfill each form ---
        for form in forms_to_backfill:
            target_version = form.version or "1.0"
            self.logger.info(
                "backfill: %s form '%s' v%s for tenant '%s'",
                "[dry-run]" if dry_run else "publishing",
                form.form_id, target_version, tenant,
            )
            if not dry_run:
                published_at = datetime.now(timezone.utc)

                # Build frozen snapshot at the existing version (stamped for
                # post-restart history reconstruction, same as publish())
                snapshot = form.model_copy(deep=True, update={
                    "published_version": target_version,
                    "meta": {**(form.meta or {}), "published_at": published_at.isoformat()},
                })
                await self._save_snapshot(snapshot, tenant=tenant)

                # Update live form in registry
                updated = form.model_copy(deep=True, update={"published_version": target_version})
                await self._registry.register(updated, persist=False, overwrite=True, tenant=tenant)

                meta = VersionMeta(
                    form_id=form.form_id,
                    version=target_version,
                    published_at=published_at,
                    tenant=tenant,
                )
                self._meta.setdefault(tenant, {}).setdefault(form.form_id, []).append(meta)

            changed += 1

        self.logger.info(
            "backfill_published: %s%d form(s) for tenant '%s'",
            "[dry-run] would change " if dry_run else "changed ",
            changed, tenant,
        )
        return changed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _save_snapshot(self, snapshot: FormSchema, *, tenant: str) -> None:
        """Persist a frozen snapshot.

        Uses ``storage.save()`` when a backend is available; the in-memory
        ``_snapshots`` dict is used ONLY when no backend is configured.
        Storage failures propagate to the caller — silently falling back to
        memory would return success for a publish that vanishes on restart
        (review H3).

        Args:
            snapshot: Frozen ``FormSchema`` (``published_version`` must be set).
            tenant: Tenant slug.

        Raises:
            Exception: Whatever ``storage.save()`` raised (including unique
                violations, surfaced by :meth:`publish` as ``ValueError``).
        """
        if self._storage is not None:
            try:
                await self._storage.save(snapshot, tenant=tenant)
            except Exception as exc:
                self.logger.error(
                    "storage.save() failed for snapshot %s v%s: %s",
                    snapshot.form_id, snapshot.version, exc,
                )
                raise
            return
        # In-memory store (no backend configured — tests/development)
        (
            self._snapshots
            .setdefault(tenant, {})
            .setdefault(snapshot.form_id, {})
        )[snapshot.version] = snapshot
