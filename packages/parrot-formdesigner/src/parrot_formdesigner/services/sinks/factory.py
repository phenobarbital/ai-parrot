"""`SinkFactory` — builds and caches sinks, and enforces coordinate immutability.

The single owner of the sink dispatch table (`services/sinks/__init__.py`)
and the single place that enforces the **coordinate-immutability** rule
(spec section 8, resolved): a form's destination coordinates
(schema/table/path/sheet id, and the connection alias itself) freeze once
the factory has first resolved a sink for that form. Only the *mapping*
(fields, delimiter, etc.) may evolve. This is what keeps a form's history
in one place forever and is why ``promote()`` needs no changes.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import TYPE_CHECKING

from parrot_formdesigner.services.sinks.base import (
    AbstractSubmissionSink,
    SinkTargetMismatchError,
)

if TYPE_CHECKING:
    from parrot_formdesigner.core.persistence import SubmissionTarget
    from parrot_formdesigner.core.schema import FormSchema
    from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry

# `_load` is defined in `services/sinks/__init__.py` (the dispatch table's
# owner). Imported lazily, inside `get()`, rather than at module level:
# `__init__.py` imports `SinkFactory` from THIS module for re-export, so a
# top-level `from parrot_formdesigner.services.sinks import _load` here
# would run while `__init__.py` is still mid-initialization. Deferring the
# import to call time avoids relying on strict definition-order in
# `__init__.py`.

# Coordinate fields per target type — the destination's PHYSICAL location.
# Deliberately excludes mapping-only fields (e.g. `delimiter`) so a form's
# fields/metadata may evolve without tripping the immutability check.
_COORDINATE_FIELDS: dict[str, tuple[str, ...]] = {
    "postgres_table": ("connection", "schema_name", "table"),
    "asyncdb": ("connection", "driver", "collection"),
    "csv_file": ("connection", "path"),
    "gsheet": ("connection", "spreadsheet_id", "worksheet"),
}


def _fingerprint(target: SubmissionTarget) -> str:
    """Return a stable hash of ``target``'s coordinate fields only.

    Args:
        target: The submission target to fingerprint.

    Returns:
        A hex-encoded SHA-256 digest of the sorted coordinate fields.
    """
    fields = _COORDINATE_FIELDS[target.type]
    coords = target.model_dump(include=set(fields))
    return hashlib.sha256(json.dumps(coords, sort_keys=True, default=str).encode()).hexdigest()


class SinkFactory:
    """Builds and caches sinks per ``(tenant, form_uid, version)``.

    Not a global singleton — instantiated once by the app (TASK-2429) with
    a single :class:`SinkAliasRegistry` and passed in explicitly. Holds no
    module-level mutable state.

    Args:
        alias_registry: Shared alias registry passed to every sink built
            by this factory.
    """

    def __init__(self, alias_registry: SinkAliasRegistry) -> None:
        self._alias_registry = alias_registry
        self._cache: dict[tuple[str, uuid.UUID, str], AbstractSubmissionSink] = {}
        # Coordinate fingerprint of the FIRST target ever seen for a given
        # (tenant, form_uid), independent of version.
        self._fingerprints: dict[tuple[str, uuid.UUID], str] = {}

    async def get(self, form: FormSchema, *, tenant: str) -> AbstractSubmissionSink:
        """Return the sink for ``form``'s declared persistence target.

        Args:
            form: The form whose ``persistence.data`` target to resolve.
            tenant: Tenant scope used both for caching and alias resolution.

        Returns:
            The cached or newly built sink for
            ``(tenant, form.form_uid, form.version)``.

        Raises:
            ValueError: If ``form.persistence`` is not set.
            SinkTargetMismatchError: If the target's coordinates differ
                from the fingerprint recorded for this ``(tenant,
                form_uid)`` on a previous call.
        """
        if form.persistence is None:
            raise ValueError(f"FormSchema {form.form_id!r} has no persistence configured")

        target = form.persistence.data
        coord_key = (tenant, form.form_uid)
        fingerprint = _fingerprint(target)

        recorded = self._fingerprints.get(coord_key)
        if recorded is None:
            self._fingerprints[coord_key] = fingerprint
        elif recorded != fingerprint:
            raise SinkTargetMismatchError(
                f"Persistence coordinates for form {form.form_id!r} "
                f"(uid={form.form_uid}) changed after they were first "
                "resolved. Destination coordinates are immutable once set."
            )

        cache_key = (tenant, form.form_uid, form.version)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # Deferred import — see the module-level comment above.
        from parrot_formdesigner.services.sinks import _load

        sink_cls = _load(target.type)
        sink: AbstractSubmissionSink = sink_cls(target, alias_registry=self._alias_registry, tenant=tenant)
        self._cache[cache_key] = sink
        return sink

    async def close_all(self) -> None:
        """Close every cached sink. Idempotent — safe to call twice."""
        sinks = list(self._cache.values())
        self._cache.clear()
        for sink in sinks:
            await sink.close()
