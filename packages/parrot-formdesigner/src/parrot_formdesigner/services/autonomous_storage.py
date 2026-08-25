"""`AutonomousFormStorage` — pointer-indexed form definitions.

The second half of "autonomous": a form's *definition body* lives in its
own store (a :class:`~parrot_formdesigner.core.persistence.
FileDefinitionTarget`, for v1), while the registry still indexes a
lightweight pointer row so listing, RBAC and multi-tenancy keep working
unchanged (spec section 8, resolved).

Implemented as a **decorator** over an existing ``FormStorage`` — not a
new registry — because satisfying the same interface means
:meth:`~parrot_formdesigner.services.registry.FormRegistry._read_through`
needs NO changes at all. ``FormRegistry`` itself is never modified by
this feature.

WARNING (the single biggest trap in this feature): ``FormStorage.
load_by_slug`` is **not declared on the ABC**
(``services/registry.py:63-238``) yet ``FormRegistry`` calls it
(``services/registry.py:418`` and ``:1075``). This class MUST implement
it — its absence is an ``AttributeError`` at runtime, not a type error
at build time.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.core.style import StyleSchema
from parrot_formdesigner.services.registry import FormStorage
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry

# Package-wide default tenant, matching the convention used elsewhere
# (e.g. `FormRegistry.default_tenant`, `services/submissions.py:31`).
_DEFAULT_TENANT = "navigator"

# Nested key under `FormSchema.meta` (a free-form bag) holding the
# resolved definition-body location — the "source_ref" referenced by the
# spec. Never a new FormSchema field: `meta` is exactly the extension
# point this package already offers for opaque, storage-owned data.
_META_KEY = "_autonomous_source_ref"


def _is_pointer(form: FormSchema) -> bool:
    """Return whether ``form`` declares an externalized definition body."""
    return form.persistence is not None and form.persistence.definition is not None


class AutonomousFormStorage(FormStorage):
    """Decorates a `FormStorage`, externalizing the definition body.

    Forms WITHOUT a ``persistence.definition`` block pass straight
    through to the inner storage, unchanged — this class introduces no
    behaviour difference for ordinary forms.

    Args:
        inner: The wrapped storage (e.g. ``PostgresFormStorage``) — the
            pointer row's home. MUST implement ``load_by_slug`` (not on
            the ABC, but required by ``FormRegistry``).
        aliases: Resolves a ``FileDefinitionTarget.connection`` to a base
            directory and contains ``path`` within it.
    """

    def __init__(self, inner: FormStorage, aliases: SinkAliasRegistry) -> None:
        self._inner = inner
        self._aliases = aliases
        self.logger = logging.getLogger(__name__)

    def _resolve_path(self, target: Any, *, tenant: str):
        return self._aliases.contain(target.connection, tenant=tenant, relative_path=target.path)

    def _write_body_sync(self, path, body: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)

    def _read_body_sync(self, path) -> str:
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def _delete_body_sync(self, path) -> None:
        path.unlink(missing_ok=True)

    async def _hydrate(self, pointer: FormSchema, *, tenant: str) -> FormSchema:
        """Read the full form body from the definition target.

        Args:
            pointer: The pointer row loaded from the inner storage.
            tenant: Tenant used to resolve the definition target's alias.

        Returns:
            The full, hydrated `FormSchema`.

        Raises:
            Exception: Any read failure propagates uncaught — the
                registry's ``_read_through`` already fail-softs broadly
                (``services/registry.py:1070-1082``), so the form 404s
                rather than 500s.
        """
        target = pointer.persistence.definition  # type: ignore[union-attr]
        path = await asyncio.to_thread(self._resolve_path, target, tenant=tenant)
        body = await asyncio.to_thread(self._read_body_sync, path)
        return FormSchema.model_validate(json.loads(body))

    async def save(
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        tenant: str | None = None,
    ) -> str:
        """Persist ``form``, externalizing the body when declared.

        Args:
            form: The form to persist.
            style: Optional associated style.
            tenant: Optional per-call tenant override.

        Returns:
            The ``form_id`` of the saved form (per the inner storage).
        """
        if not _is_pointer(form):
            return await self._inner.save(form, style, tenant=tenant)

        effective_tenant = tenant if tenant is not None else (form.tenant or _DEFAULT_TENANT)
        target = form.persistence.definition  # type: ignore[union-attr]
        path = await asyncio.to_thread(self._resolve_path, target, tenant=effective_tenant)
        body = form.model_dump_json()
        await asyncio.to_thread(self._write_body_sync, path, body)

        pointer = form.model_copy(
            update={
                "sections": [],
                "meta": {**(form.meta or {}), _META_KEY: str(path)},
            }
        )
        self.logger.info(
            "AutonomousFormStorage: wrote definition body for form %s " "(uid=%s) to %s",
            form.form_id,
            form.form_uid,
            path,
        )
        return await self._inner.save(pointer, style, tenant=tenant)

    async def load(
        self,
        form_uid: uuid.UUID,
        version: str | None = None,
        *,
        tenant: str | None = None,
    ) -> FormSchema | None:
        """Load a form by its immutable ``form_uid``, hydrating if pointed.

        Args:
            form_uid: The form's immutable UUID (matches the concrete/
                caller contract used by ``FormRegistry`` — NOT the ABC's
                ``form_id: str`` docstring).
            version: Optional specific version.
            tenant: Optional per-call tenant override.

        Returns:
            The full `FormSchema` (hydrated if pointer-indexed), or
            ``None`` if not found.
        """
        pointer = await self._inner.load(form_uid, version, tenant=tenant)
        if pointer is None or not _is_pointer(pointer):
            return pointer
        effective_tenant = tenant if tenant is not None else (pointer.tenant or _DEFAULT_TENANT)
        return await self._hydrate(pointer, tenant=effective_tenant)

    async def load_by_slug(
        self,
        form_id: str,
        tenant: str,
        version: str | None = None,
    ) -> FormSchema | None:
        """Load a form by its mutable slug, hydrating if pointer-indexed.

        REQUIRED even though ``FormStorage`` (the ABC) omits it —
        ``FormRegistry._read_through`` calls it directly
        (``services/registry.py:1075``).

        Args:
            form_id: The form's human-readable slug.
            tenant: Tenant to query (required, matching the concrete
                ``PostgresFormStorage.load_by_slug`` contract).
            version: Optional specific version.

        Returns:
            The full `FormSchema` (hydrated if pointer-indexed), or
            ``None`` if not found.
        """
        pointer = await self._inner.load_by_slug(form_id, tenant, version)
        if pointer is None or not _is_pointer(pointer):
            return pointer
        return await self._hydrate(pointer, tenant=tenant)

    async def delete(self, form_uid: uuid.UUID, *, tenant: str | None = None) -> bool:
        """Delete both the pointer row and (if any) the externalized body.

        Args:
            form_uid: The form's immutable UUID.
            tenant: Optional per-call tenant override.

        Returns:
            Whatever the inner storage's ``delete()`` returns.
        """
        pointer = await self._inner.load(form_uid, tenant=tenant)
        if pointer is not None and _is_pointer(pointer):
            effective_tenant = tenant if tenant is not None else (pointer.tenant or _DEFAULT_TENANT)
            target = pointer.persistence.definition  # type: ignore[union-attr]
            path = await asyncio.to_thread(self._resolve_path, target, tenant=effective_tenant)
            await asyncio.to_thread(self._delete_body_sync, path)
        return await self._inner.delete(form_uid, tenant=tenant)

    async def list_forms(self, *, tenant: str | None = None) -> list[dict[str, Any]]:
        """Delegate to the inner storage — pointer rows list identically."""
        return await self._inner.list_forms(tenant=tenant)

    async def list_versions(self, form_uid: uuid.UUID, *, tenant: str | None = None) -> list[dict[str, Any]]:
        """Delegate to the inner storage."""
        return await self._inner.list_versions(form_uid, tenant=tenant)

    async def promote(
        self,
        form_uid: uuid.UUID,
        version: str,
        schema_json: str,
        *,
        tenant: str | None = None,
    ) -> bool:
        """Delegate to the inner storage.

        Coordinate/definition immutability means ``promote()`` needs no
        special handling here: the destination never changes across
        versions (spec section 2, "Destination immutability").
        """
        return await self._inner.promote(form_uid, version, schema_json, tenant=tenant)

    async def close(self) -> None:
        """Delegate to the inner storage."""
        await self._inner.close()
