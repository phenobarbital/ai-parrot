"""FormVersionService — immutable semver publishing for FormSchema objects.

Implements the form publishing lifecycle described in FEAT-300 §2 (RF-06):
- Publishing promotes the current live version to published, IN PLACE
  (FEAT-433 §8 Q5, closed 2026-08-19) — it does not bump to a new tag.
- Published snapshots are immutable — re-promoting raises ``ValueError``.
- In-flight responses resolve against the version they started with.
- Deletion of a form/version with associated responses is blocked (caller
  provides a ``has_responses`` hook).

FEAT-300 — Module 4. FEAT-433 — Modules 3, 5, 6.
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


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class VersionMeta(BaseModel):
    """Metadata record for one stored form version (FEAT-433 D1/Module 3).

    Attributes:
        form_id: The form's human-readable slug (FEAT-389 — display /
            search only; NOT the canonical identifier). The canonical,
            immutable identifier is ``FormSchema.form_uid``, used as the
            lookup key everywhere in this service; ``VersionMeta`` keeps
            ``form_id`` purely as a friendlier label for callers.
        version: The semver-style ``major.minor`` tag (e.g. ``"1.0"``).
        published_at: UTC timestamp. For a published row, when it was
            published; for a draft row, its own ``created_at`` (never the
            wall-clock "now" of the request — see :meth:`_published_at_from_row`).
        tenant: Tenant slug.
        is_published: Whether this row IS the published snapshot for its own
            version — derived, never stored (D1/D2):
            ``published_version == version``. The draft/published
            distinction is a per-row LABEL (D3), not a visibility gate —
            every stored row is listed regardless of this value.
        is_frozen: Equal to ``is_published`` — only a published snapshot is
            immutable; a draft row is rewritable in place by the next editor
            save.
    """

    model_config = ConfigDict(extra="forbid")

    form_id: str
    version: str
    published_at: datetime
    tenant: str
    is_published: bool
    is_frozen: bool


# ---------------------------------------------------------------------------
# Semver helpers
# ---------------------------------------------------------------------------

#: FEAT-433 TASK-2267 — the one grammar both former bumpers now share.
#: ``major.minor`` (spec S1's canonical, unchanged format) is required; an
#: optional third ``.patch`` component is accepted (matching the pre-merge
#: ``api/_utils._bump_version`` behavior) but never participates in
#: ordering — the stored format is ``major.minor`` (D2/S1), so a
#: patch-shaped input shares its parent's ``(major, minor)`` bucket.
_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?$")

#: Sentinel returned by :func:`_parse_major_minor` for a version string that
#: does not even match ``major.minor`` — sorts LAST, deterministically,
#: matching the SQL ordering guard's ``NULLS LAST`` (Module 2). Replaces the
#: previous ``(1, 0)`` fallback, which silently misordered an unparseable
#: row as if it were the OLDEST version in the history — the opposite of
#: harmless.
_UNPARSEABLE_SORT_KEY = (2**63 - 1, 2**63 - 1)


def _parse_major_minor(version: str) -> tuple[int, int]:
    """Parse a version string's ``(major, minor)`` for ordering purposes.

    Args:
        version: Version string, e.g. ``"1.0"``, ``"2.3"``, or ``"1.2.3"``
            (a trailing patch component is accepted but ignored here).

    Returns:
        ``(major, minor)`` ints. Falls back to :data:`_UNPARSEABLE_SORT_KEY`
        — NOT ``(1, 0)`` — when ``version`` doesn't match ``major.minor``
        at all, so an unparseable row sorts last instead of being mistaken
        for the oldest version.
    """
    m = _SEMVER_RE.match(version or "")
    if m:
        return int(m.group(1)), int(m.group(2))
    logger.warning("Could not parse version %r as major.minor — sorting it last", version)
    return _UNPARSEABLE_SORT_KEY


def _is_published_label(published_version: str | None, version: str) -> bool:
    """Whether a stored row is the published snapshot for its own version.

    FEAT-433 D1/D2/D3: this is the one comparison the whole feature turns
    on. Before Module 3 it *gated* ``list_versions`` — a row was dropped
    unless this held. It now *labels* the row instead — every stored row is
    listed, and this decides how it is presented, not whether it appears.
    Kept next to :func:`_parse_major_minor` since the two derivation rules
    (ordering, labelling) live together by design.

    Args:
        published_version: The row's stamped ``published_version`` (``None``
            for a row no ``publish()`` call has ever touched).
        version: The row's own ``version``.

    Returns:
        ``True`` if this row IS the published snapshot for its version.
    """
    return published_version == version


def _bump(current: str, bump: str = "minor") -> str:
    """Bump a version string — the single grammar for both former bumpers.

    FEAT-433 TASK-2267: collapses the pre-existing ``api/_utils._bump_version``
    (incremented the last component, accepted a three-part version) and this
    module's own ``_bump`` (matched only ``major.minor``, silently degraded
    anything else) into one implementation. ``api/_utils._bump_version`` now
    delegates here.

    Grammar:
        - ``"major.minor"`` (the canonical, documented format — spec S1,
          unchanged) or ``"major.minor.patch"``: ``bump="minor"`` (default)
          increments the LAST present component, preserving a three-part
          shape (``"1.2.3"`` → ``"1.2.4"``); ``bump="major"`` increments the
          major component and resets the rest, dropping any patch
          (``"1.2.3"`` → ``"2.0"``, same rule as the two-part case).
        - Anything that doesn't even parse as a leading ``N.N`` is NOT
          rejected: this runs on the editor's hot path (every save, via
          ``api/_utils._bump_version``) and must be cheap and total — a
          bump that raises on a legacy/malformed value already in storage
          would break saving. It is passed through as ``"<current>.1"``,
          the same total fallback the pre-merge ``_bump_version`` used for
          a bare major-only input (e.g. ``"1"`` → ``"1.1"``).

    Args:
        current: Current version string, e.g. ``"1.0"`` or ``"1.2.3"``.
        bump: ``"minor"`` (default) or ``"major"``.

    Returns:
        The bumped version string.
    """
    parts = (current or "").split(".")
    if len(parts) >= 2 and all(p.isdigit() for p in parts[:2]) and all(
        p.isdigit() for p in parts[2:]
    ):
        if bump == "major":
            return f"{int(parts[0]) + 1}.0"
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    logger.warning(
        "Could not parse version %r as major.minor[.patch] — appending '.1'", current
    )
    return f"{current}.1"


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class FormVersionService:
    """Immutable semver publishing service for ``FormSchema`` objects.

    Each call to :meth:`publish` promotes the CURRENT live version to
    published, IN PLACE (FEAT-433 §8 Q5, closed 2026-08-19) — it no longer
    bumps to a new tag. The next editor SAVE is what bumps to a new draft
    (``_bump`` / ``api/_utils._bump_version``). The snapshot is stored via
    ``storage.promote()`` when available; an in-memory fallback (dict) is
    used otherwise (suitable for tests and development).

    Deletion is guarded by the optional ``has_responses`` async hook: if
    supplied, the service calls it before any delete to confirm no response
    data exists.  If the hook returns ``True``, deletion raises ``ValueError``
    and the form is only deactivated (not deleted).

    Example::

        svc = FormVersionService(registry, storage)
        # form.version == "1.5" (the editor's current draft)
        tag = await svc.publish(form.form_uid, tenant="navigator")  # → "1.5"
        snap = await svc.get_published(form.form_uid, version="1.5", tenant="navigator")

    Args:
        registry: ``FormRegistry`` used to look up the live form state and
            register snapshots when a ``storage`` backend is not available.
        storage: ``FormStorage`` used to persist snapshots. When ``None``,
            the service stores snapshots in an in-memory dict.
        has_responses: Optional async callback ``(form_uid, tenant) -> bool``
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

        # In-memory fallback stores (keyed by form_uid, the immutable
        # identity — FEAT-389):
        # _snapshots[tenant][form_uid][version] = FormSchema
        self._snapshots: dict[str, dict[str, dict[str, FormSchema]]] = {}
        # _meta[tenant][form_uid] = list[VersionMeta]
        self._meta: dict[str, dict[str, list[VersionMeta]]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def publish(
        self,
        form_uid: str,
        *,
        tenant: str,
        bump: str = "minor",
    ) -> str:
        """Promote the current live version to published, in place.

        FEAT-433 Module 6 (spec §8 Q5, closed 2026-08-19): no longer bumps
        to a new tag. Publishing draft ``"1.5"`` produces published
        ``"1.5"`` (not ``"1.6"``) — the version the user is looking at is
        the version that gets published. The next editor SAVE is what
        bumps to a new draft. This produces one row per actual change,
        instead of a content-identical draft/published twin pair for every
        publish.

        Steps:
        1. Load the live form from the registry.
        2. Raise ``ValueError`` if the live version is already published
           (immutability).
        3. Set ``published_version`` (= the unchanged ``version``) on a
           deep copy.
        4. Promote the existing row in place (storage) or record it
           (in-memory).

        Args:
            form_uid: The form's immutable UUID (FEAT-389).
            tenant: Tenant slug.
            bump: Accepted for backward API compatibility. UNUSED —
                ``publish()`` no longer bumps (see above); version bumping
                now happens only on the editor's save path (``_bump`` /
                ``api/_utils._bump_version``).

        Returns:
            The published version string — the SAME tag the live form was
            already at.

        Raises:
            KeyError: If the form is not found in the registry.
            ValueError: If the live version is already published (immutable).
        """
        form = await self._registry.get(form_uid, tenant=tenant)
        if form is None:
            raise KeyError(f"Form '{form_uid}' not found under tenant '{tenant}'")

        target_version = form.version

        # Immutability guard (fast path — not the authoritative guard, see
        # the promote() call below). FEAT-433 Module 5: get_published() no
        # longer filters by published_version, so it returns the row at
        # target_version regardless of its label — check its OWN
        # published_version against target_version to ask the Q5 question
        # ("is the version I am looking at already published?"), not
        # "does a row exist here" (a live draft row almost always does).
        existing = await self.get_published(form_uid, version=target_version, tenant=tenant)
        if existing is not None and existing.published_version == target_version:
            raise ValueError(
                f"Version '{target_version}' of form '{form.form_id}' already exists and is frozen."
            )

        published_at = datetime.now(timezone.utc)

        # Build the promoted snapshot — SAME version, now stamped
        # published. ``published_at`` is stamped into ``meta`` so version
        # history can be reconstructed from storage after a restart.
        snapshot = form.model_copy(deep=True, update={
            "published_version": target_version,
            "meta": {**(form.meta or {}), "published_at": published_at.isoformat()},
        })

        # Persist via the promote path (Module 6): an UPDATE guarded by
        # `published_version IS DISTINCT FROM version`, which IS the
        # authoritative immutability guard (the pre-check above is a fast
        # path, not the guard).
        try:
            await self._save_snapshot(snapshot, tenant=tenant)
        except Exception as exc:
            if is_unique_violation(exc):
                raise ValueError(
                    f"Version '{target_version}' of form '{form.form_id}' already exists and is frozen."
                ) from exc
            raise

        # Update the live form's published_version in the registry.
        # version itself is unchanged — promote in place.
        updated_live = form.model_copy(deep=True, update={
            "published_version": target_version,
        })
        await self._registry.register(updated_live, persist=False, overwrite=True, tenant=tenant)

        # Record VersionMeta (form_id kept as the human-readable slug label).
        # A _meta entry only ever exists because THIS method just published
        # it — always the published row, never a draft.
        meta = VersionMeta(
            form_id=form.form_id,
            version=target_version,
            published_at=published_at,
            tenant=tenant,
            is_published=True,
            is_frozen=True,
        )
        self._meta.setdefault(tenant, {}).setdefault(form_uid, []).append(meta)

        self.logger.info(
            "Published form '%s' as version '%s' for tenant '%s'",
            form.form_id, target_version, tenant,
        )
        return target_version

    async def get_published(
        self,
        form_uid: str,
        *,
        version: str,
        tenant: str,
    ) -> FormSchema | None:
        """Retrieve the stored snapshot for a version — draft or published.

        FEAT-433 Module 5: despite the name (kept for API compatibility —
        renaming is optional per the spec, and this is public API), this no
        longer requires ``version`` to be the published tag. Before this
        change the ``snap.published_version == version`` filter meant
        ``GET .../versions/{version}`` 404d for every version the editor
        ever saved directly (i.e. every draft) — the exact rows Module 1-3
        now lists. Every listed version must resolve here, or the history
        list is a list of dead links (the anti-regression this task exists
        for). The returned ``FormSchema`` still carries its own
        ``published_version``, so a caller can tell draft from published
        without a second call. Immutability for an actually-published
        snapshot (RF-06 — untouched by subsequent publishes) is unaffected:
        dropping the filter changes what is *returned*, not whether a
        published row can be *overwritten* (that guarantee is Module 6 /
        TASK-2269's job).

        Args:
            form_uid: The form's immutable UUID (FEAT-389).
            version: The semver tag to retrieve (e.g. ``"1.1"``).
            tenant: Tenant slug.

        Returns:
            The stored ``FormSchema`` snapshot at ``version``, or ``None``
            if no such version was ever stored.
        """
        if self._storage is not None:
            snap = await self._storage.load(form_uid, version=version, tenant=tenant)
            if snap is not None:
                return snap
        # In-memory fallback. Only ever populated by publish()/
        # backfill_published() (FEAT-433: those are the only writers to
        # _snapshots), so every entry here is already a published row —
        # dropping the filter above doesn't change this branch's behavior.
        return (
            self._snapshots
            .get(tenant, {})
            .get(form_uid, {})
            .get(version)
        )

    async def list_versions(
        self,
        form_uid: str,
        *,
        tenant: str,
    ) -> list[VersionMeta]:
        """List every stored version of a form, draft and published (D1/D3).

        Merges the in-process ``VersionMeta`` cache with a single ordered
        query against storage (:meth:`FormStorage.list_versions`, FEAT-433
        Module 2), so history survives a process restart (the snapshots
        live in Postgres under ``UNIQUE(form_uid, version)``; ``published_at``
        is recovered from the stamp written into ``snapshot.meta`` by
        :meth:`publish`). Replaces the old per-candidate-version probing
        loop, which cost one round-trip per version and silently truncated
        history across any two-version gap.

        FEAT-433 Module 3 (D1/D3): ``published_version == version`` no
        longer decides whether a row is *listed* — every stored row is,
        including rows the editor saved directly via ``storage.save()``
        (no ``publish()`` call). It decides how the row is *labelled*
        (:func:`_is_published_label`): ``is_published`` (and ``is_frozen``,
        which mirrors it).

        On conflict between the in-process cache and a storage row for the
        same version, the storage row wins — a ``_meta`` entry is only an
        in-process echo of a publish that already wrote a row, so a restart
        never changes the answer.

        Args:
            form_uid: The form's immutable UUID (FEAT-389).
            tenant: Tenant slug.

        Returns:
            List of ``VersionMeta`` objects ordered by (major, minor).
        """
        by_version: dict[str, VersionMeta] = {
            m.version: m for m in self._meta.get(tenant, {}).get(form_uid, [])
        }

        if self._storage is not None:
            for row in await self._storage.list_versions(form_uid, tenant=tenant):
                version = row["version"]
                published = _is_published_label(row.get("published_version"), version)
                by_version[version] = VersionMeta(
                    form_id=row.get("form_id") or "",
                    version=version,
                    published_at=self._published_at_from_row(row),
                    tenant=tenant,
                    is_published=published,
                    is_frozen=published,
                )

        return sorted(by_version.values(), key=lambda m: _parse_major_minor(m.version))

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

    @staticmethod
    def _published_at_from_row(row: dict) -> datetime:
        """Recover a version's timestamp from a projected storage row.

        Same precedence as :meth:`_published_at_from_snapshot`, adapted to
        the projected dict shape returned by
        :meth:`FormStorage.list_versions` (FEAT-433 Module 2) instead of a
        whole ``FormSchema`` snapshot: the ``meta.published_at`` stamp when
        present, otherwise the row's own ``created_at``.

        FEAT-433 Module 3 (D1): deliberately does NOT fall back to
        ``datetime.now()`` — the previous fallback made every draft in a
        mixed history report "published just now", which the history UI
        would render as a wall of identical timestamps. ``created_at`` is
        NOT NULL at the storage layer (``PostgresFormStorage``'s
        ``schema_json``-backed row always carries it), so this is total in
        practice.
        """
        stamp = row.get("published_at")
        if isinstance(stamp, str):
            try:
                return datetime.fromisoformat(stamp)
            except ValueError:
                pass
        return row["created_at"]

    async def can_delete(self, form_uid: str, *, tenant: str) -> bool:
        """Return ``True`` if deletion is safe (no responses associated).

        If no ``has_responses`` hook was provided, deletion is always
        considered safe (returns ``True``).

        Args:
            form_uid: The form's immutable UUID (FEAT-389).
            tenant: Tenant slug.

        Returns:
            ``True`` if deletion is permitted.
        """
        if self._has_responses is None:
            return True
        has = await self._has_responses(form_uid, tenant)
        return not has

    async def safe_delete(self, form_uid: str, *, tenant: str) -> None:
        """Delete a form only if it has no responses.

        Raises:
            ValueError: If ``has_responses`` returns ``True`` for this form.
        """
        if not await self.can_delete(form_uid, tenant=tenant):
            raise ValueError(
                f"Form '{form_uid}' has responses and cannot be deleted. "
                "Deactivate it instead."
            )
        if self._storage is not None:
            await self._storage.delete(form_uid, tenant=tenant)
        # Also remove from the registry (public API — never touch _forms)
        await self._registry.unregister(form_uid, tenant=tenant)

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
                seen_ids = {f.form_uid for f in forms_to_backfill}
                for row in rows:
                    fid = row.get("form_uid")
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

                # Backfill marks the form as published at its current
                # version — same "always the published row" reasoning as
                # publish()'s own _meta entry above.
                meta = VersionMeta(
                    form_id=form.form_id,
                    version=target_version,
                    published_at=published_at,
                    tenant=tenant,
                    is_published=True,
                    is_frozen=True,
                )
                self._meta.setdefault(tenant, {}).setdefault(form.form_uid, []).append(meta)

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
        """Persist a snapshot that :meth:`publish`/:meth:`backfill_published`
        just stamped as published.

        FEAT-433 Module 6: routes through the storage's PROMOTE path
        (``FormStorage.promote()``) — a guarded ``UPDATE``, never the
        editor's UPSERT. Every snapshot this method ever receives already
        has ``published_version == version`` stamped by its caller (the
        editor's own save path never calls this method — it writes directly
        via ``storage.save()``), so "promote" is always the correct write.
        No row affected means the version is ALREADY published — the
        authoritative immutability guard (the fast-path pre-check in
        :meth:`publish` is not the guard). The in-memory fallback (no
        backend configured) has no separate guard of its own; that same
        fast-path pre-check already catches a re-publish of the same
        version before this is ever reached.

        Args:
            snapshot: Snapshot to persist. ``published_version`` MUST
                already equal ``version`` — the promote path relies on
                that invariant.
            tenant: Tenant slug.

        Raises:
            ValueError: The version is already published (the storage-level
                promote guard tripped).
            Exception: Whatever the storage call raised otherwise.
        """
        if self._storage is not None:
            try:
                promoted = await self._storage.promote(
                    snapshot.form_uid,
                    snapshot.version,
                    snapshot.model_dump_json(),
                    tenant=tenant,
                )
            except Exception as exc:
                self.logger.error(
                    "storage.promote() failed for snapshot %s (form_id=%s) v%s: %s",
                    snapshot.form_uid, snapshot.form_id, snapshot.version, exc,
                )
                raise
            if not promoted:
                raise ValueError(
                    f"Version '{snapshot.version}' of form '{snapshot.form_id}' "
                    "already exists and is frozen."
                )
            return
        # In-memory store (no backend configured — tests/development).
        # Keyed by form_uid (FEAT-389) — must match get_published()'s lookup
        # key, NOT the mutable form_id slug.
        (
            self._snapshots
            .setdefault(tenant, {})
            .setdefault(snapshot.form_uid, {})
        )[snapshot.version] = snapshot
