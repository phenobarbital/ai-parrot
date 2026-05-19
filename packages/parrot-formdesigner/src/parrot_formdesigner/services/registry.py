"""Form Registry for the forms abstraction layer.

Provides FormStorage (abstract persistence backend) and FormRegistry
(in-memory registry with optional persistence and async callbacks).

Migrated from parrot/integrations/dialogs/registry.py with:
- FormSchema instead of FormDefinition
- async-first API (asyncio.Lock instead of threading.Lock)
- FormStorage ABC for pluggable persistence backends
- persist= parameter on register()
- load_from_storage() for startup hydration
- Async register/unregister callbacks

Multi-tenancy support (FEAT-183):
- Internal state is dict[tenant, dict[form_id, FormSchema]] (nested dict).
- Every public method accepts kwarg-only ``tenant: str | None = None``.
- ``tenant=None`` resolves strictly to ``default_tenant`` — never aggregates.
- ``on_unregister`` callbacks receive ``(form_id, tenant)`` — BREAKING change.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..core.schema import FormSchema
from ..core.style import StyleSchema

logger = logging.getLogger(__name__)


class FormStorage(ABC):
    """Abstract base class for form persistence backends.

    Implementations provide save/load/delete/list operations on persisted
    FormSchema objects. Used by FormRegistry when persist=True.

    Example implementation: PostgreSQLFormStorage (TASK-529).
    """

    @abstractmethod
    async def save(
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        tenant: str | None = None,
    ) -> str:
        """Persist a form schema.

        Args:
            form: FormSchema to persist.
            style: Optional associated StyleSchema.
            tenant: Optional tenant slug used by Postgres-backed storages
                to resolve the target schema. Implementations that don't
                segregate by tenant may ignore it.

        Returns:
            The form_id of the saved form.
        """
        ...

    @abstractmethod
    async def load(
        self,
        form_id: str,
        version: str | None = None,
        *,
        tenant: str | None = None,
    ) -> FormSchema | None:
        """Load a form schema by ID.

        Args:
            form_id: Identifier of the form to load.
            version: Optional version string. If None, loads the latest.
            tenant: Optional tenant slug used by Postgres-backed storages
                to resolve the target schema.

        Returns:
            FormSchema if found, None otherwise.
        """
        ...

    @abstractmethod
    async def delete(self, form_id: str, *, tenant: str | None = None) -> bool:
        """Delete a persisted form.

        Args:
            form_id: Identifier of the form to delete.
            tenant: Optional tenant slug used by Postgres-backed storages
                to resolve the target schema.

        Returns:
            True if deleted, False if not found.
        """
        ...

    @abstractmethod
    async def list_forms(self, *, tenant: str | None = None) -> list[dict[str, Any]]:
        """List all persisted forms.

        Each dict in the returned list MUST include ``form_id`` and
        ``version`` (required keys). Implementations SHOULD also include
        ``title``, ``description``, and ``created_at`` when the backend
        has them available.

        ``description`` may be ``None`` when the form has no description.
        ``created_at`` is an ISO-8601 string produced via
        ``datetime.isoformat()`` (e.g. ``"2026-04-12T10:31:00+00:00"``)
        or ``None`` when not available.

        Returns:
            List of dicts with at minimum ``form_id`` and ``version``.
            Optional keys: ``title``, ``description``, ``created_at``.
        """
        ...


class FormRegistry:
    """Thread-safe, multi-tenant registry for FormSchema objects.

    Supports in-memory registration scoped by tenant, optional persistence
    via FormStorage, async event callbacks, and YAML directory loading via
    YamlExtractor.

    Internal state is ``dict[tenant, dict[form_id, FormSchema]]``.
    Every public read/write method accepts a kwarg-only ``tenant=`` parameter
    that resolves via: explicit kwarg > form.tenant (register paths) >
    ``default_tenant``.

    Example::

        registry = FormRegistry()
        await registry.register(form_schema)                     # requires form.tenant
        form = await registry.get("my-form", tenant="navigator")

        # With persistence
        registry = FormRegistry(storage=PostgreSQLFormStorage(...))
        await registry.register(form_schema, persist=True)
        await registry.load_from_storage(tenant="navigator")

        # Cross-tenant admin pattern (explicit loop — no aggregation via tenant=None):
        all_forms: list[FormSchema] = []
        for t in await registry.list_tenants():
            all_forms.extend(await registry.list_forms(tenant=t))
    """

    def __init__(
        self,
        storage: FormStorage | None = None,
        *,
        default_tenant: str = "navigator",
        require_tenant: bool = True,
    ) -> None:
        """Initialize FormRegistry.

        Args:
            storage: Optional FormStorage backend for persistence.
            default_tenant: Tenant name used when callers pass ``tenant=None``.
                Defaults to ``"navigator"`` to match
                ``PostgresFormStorage.DEFAULT_SCHEMA``.
            require_tenant: When ``True`` (default), :meth:`register` raises
                ``ValueError`` if the form's effective tenant would fall all
                the way through to ``default_tenant`` because BOTH the
                explicit ``tenant=`` kwarg AND ``form.tenant`` are ``None``.
                When ``False``, such forms are silently sealed to
                ``default_tenant``.
        """
        self._forms: dict[str, dict[str, FormSchema]] = {}
        self._lock = asyncio.Lock()
        self._storage = storage
        self._default_tenant = default_tenant
        self._require_tenant = require_tenant
        self._on_register: list[Callable[[FormSchema], Awaitable[None]]] = []
        self._on_unregister: list[Callable[[str, str], Awaitable[None]]] = []
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_tenant(
        self,
        tenant: str | None,
        form: FormSchema | None = None,
    ) -> str:
        """Resolve effective tenant.

        Precedence: explicit kwarg > form.tenant (register paths only) >
        ``default_tenant``.

        This mirrors ``PostgresFormStorage._resolve_schema`` in
        ``services/storage.py:97-107``.

        Args:
            tenant: Caller-supplied tenant kwarg (may be ``None``).
            form: Optional FormSchema whose ``.tenant`` field provides a
                fallback. Pass only in ``register()`` paths.

        Returns:
            Resolved tenant string — never ``None``.
        """
        if tenant is not None:
            return tenant
        if form is not None and form.tenant is not None:
            return form.tenant
        return self._default_tenant

    # ------------------------------------------------------------------
    # Public API — write paths
    # ------------------------------------------------------------------

    async def register(
        self,
        form: FormSchema,
        *,
        persist: bool = False,
        overwrite: bool = True,
        tenant: str | None = None,
    ) -> None:
        """Register a form schema under a specific tenant.

        Resolution order for the effective tenant:

        1. Explicit ``tenant=`` kwarg (if not ``None``).
        2. ``form.tenant`` (if not ``None``).
        3. ``self._default_tenant``.

        When ``require_tenant=True`` (the default), step 3 is only reached
        if BOTH the kwarg AND ``form.tenant`` are ``None`` — in that case a
        ``ValueError`` is raised to prevent accidental un-scoped registration.

        If the explicit kwarg differs from ``form.tenant``, a ``WARNING`` is
        logged and the kwarg wins.  ``form.tenant`` is never mutated.

        Args:
            form: FormSchema to register.
            persist: If True, also save to storage backend.
                Logs a warning (does not raise) if no storage is configured.
            overwrite: If True, overwrite existing registration (default True).
            tenant: Explicit tenant override.  ``None`` means "use
                form.tenant or default_tenant".

        Raises:
            ValueError: When ``require_tenant=True`` and both ``tenant=``
                kwarg and ``form.tenant`` are ``None``.
        """
        # Determine whether resolution would fall all the way to default_tenant
        # because no explicit information was provided.
        both_missing = tenant is None and form.tenant is None
        if both_missing and self._require_tenant:
            raise ValueError(
                f"FormRegistry: form.tenant is required (form_id={form.form_id!r}). "
                "Set form.tenant or pass tenant= explicitly, or use "
                "require_tenant=False to seal to default_tenant."
            )

        resolved = self._resolve_tenant(tenant, form=form)

        # Warn when explicit kwarg overrides form.tenant.
        if (
            tenant is not None
            and form.tenant is not None
            and tenant != form.tenant
        ):
            self.logger.warning(
                "FormRegistry.register: explicit tenant=%r overrides "
                "form.tenant=%r for form_id=%r. The form is indexed under %r.",
                tenant,
                form.tenant,
                form.form_id,
                resolved,
            )

        async with self._lock:
            tenant_bucket = self._forms.setdefault(resolved, {})
            if form.form_id in tenant_bucket and not overwrite:
                self.logger.debug(
                    "Form %s already registered under tenant=%s, skipping",
                    form.form_id,
                    resolved,
                )
                return

            tenant_bucket[form.form_id] = form

        # Persist to backend if requested.
        if persist:
            if self._storage is not None:
                try:
                    await self._storage.save(form, tenant=resolved)
                except Exception as exc:
                    self.logger.warning(
                        "Failed to persist form %s (tenant=%s): %s",
                        form.form_id,
                        resolved,
                        exc,
                    )
            else:
                self.logger.warning(
                    "persist=True but no FormStorage configured — "
                    "form %s (tenant=%s) saved in-memory only",
                    form.form_id,
                    resolved,
                )

        # Fire on_register callbacks (unchanged signature: form carries .tenant).
        for callback in self._on_register:
            try:
                await callback(form)
            except Exception as exc:
                self.logger.warning("Register callback failed: %s", exc)

    def set_storage(self, storage: FormStorage) -> None:
        """Set the FormStorage backend for this registry.

        Args:
            storage: FormStorage instance to use for persistence.
        """
        self._storage = storage

    async def unregister(self, form_id: str, *, tenant: str | None = None) -> bool:
        """Unregister a form schema from a specific tenant.

        If removing the form leaves the tenant bucket empty, the outer key
        is deleted so :meth:`list_tenants` never reports empty tenants.

        Args:
            form_id: ID of the form to remove.
            tenant: Tenant scope.  ``None`` resolves to ``default_tenant``.

        Returns:
            True if removed, False if not found.
        """
        resolved = self._resolve_tenant(tenant)

        async with self._lock:
            bucket = self._forms.get(resolved)
            if bucket is None or form_id not in bucket:
                return False

            bucket.pop(form_id)
            # Clean up empty outer key so list_tenants() stays accurate.
            if not bucket:
                del self._forms[resolved]

        # Fire on_unregister callbacks with new (form_id, tenant) signature.
        for callback in self._on_unregister:
            try:
                await callback(form_id, resolved)
            except Exception as exc:
                self.logger.warning("Unregister callback failed: %s", exc)

        return True

    # ------------------------------------------------------------------
    # Public API — read paths
    # ------------------------------------------------------------------

    async def get(self, form_id: str, *, tenant: str | None = None) -> FormSchema | None:
        """Get a form schema by ID within a specific tenant.

        Args:
            form_id: Form identifier.
            tenant: Tenant scope.  ``None`` resolves to ``default_tenant``.

        Returns:
            FormSchema if found under the resolved tenant, ``None`` otherwise.
            A form registered under ``"epson"`` is invisible to
            ``get(form_id, tenant="pokemon")``.
        """
        resolved = self._resolve_tenant(tenant)
        async with self._lock:
            return self._forms.get(resolved, {}).get(form_id)

    async def list_forms(self, *, tenant: str | None = None) -> list[FormSchema]:
        """List all registered form schemas for a specific tenant.

        Never aggregates across tenants.  To iterate all tenants, loop over
        :meth:`list_tenants` and call ``list_forms(tenant=t)`` for each.

        Args:
            tenant: Tenant scope.  ``None`` resolves to ``default_tenant``.

        Returns:
            List of FormSchema objects registered under the resolved tenant.
        """
        resolved = self._resolve_tenant(tenant)
        async with self._lock:
            return list(self._forms.get(resolved, {}).values())

    async def list_form_ids(self, *, tenant: str | None = None) -> list[str]:
        """List all registered form IDs for a specific tenant.

        Args:
            tenant: Tenant scope.  ``None`` resolves to ``default_tenant``.

        Returns:
            List of form_id strings under the resolved tenant.
        """
        resolved = self._resolve_tenant(tenant)
        async with self._lock:
            return list(self._forms.get(resolved, {}).keys())

    async def contains(self, form_id: str, *, tenant: str | None = None) -> bool:
        """Check if a form is registered under a specific tenant.

        Args:
            form_id: Form identifier to check.
            tenant: Tenant scope.  ``None`` resolves to ``default_tenant``.

        Returns:
            True if the form is registered under the resolved tenant.
        """
        resolved = self._resolve_tenant(tenant)
        async with self._lock:
            return form_id in self._forms.get(resolved, {})

    async def clear(self, *, tenant: str | None = None) -> None:
        """Clear all registered forms for a specific tenant only.

        Never aggregates.  Drops only ``resolved_tenant``'s forms and removes
        the outer key so :meth:`list_tenants` stays accurate.

        Args:
            tenant: Tenant scope.  ``None`` resolves to ``default_tenant``.
        """
        resolved = self._resolve_tenant(tenant)
        async with self._lock:
            self._forms.pop(resolved, None)

    async def clear_all(self) -> None:
        """Drop every tenant's forms.

        Use for test teardown and maintenance only — not for single-tenant
        operations (use :meth:`clear` for those).
        """
        async with self._lock:
            self._forms.clear()

    async def list_tenants(self) -> list[str]:
        """Return a sorted list of tenants that have at least one registered form.

        Returns:
            Alphabetically sorted list of tenant strings.  Empty when the
            registry has no forms.
        """
        async with self._lock:
            return sorted(self._forms.keys())

    # ------------------------------------------------------------------
    # Directory and storage loaders
    # ------------------------------------------------------------------

    async def load_from_directory(
        self,
        path: str | Path,
        *,
        recursive: bool = True,
        overwrite: bool = False,
        tenant: str | None = None,
    ) -> int:
        """Load YAML form definitions from a directory using YamlExtractor.

        If YamlExtractor is not available, logs a warning and returns 0.

        Tenant resolution per file:

        1. YAML's own ``tenant:`` field wins (carried on
           ``FormSchema.tenant`` after extraction).
        2. Otherwise the ``tenant=`` kwarg passed to this method supplies
           a default.
        3. Otherwise, if ``require_tenant=True``, the file is skipped with
           a ``WARNING`` log.  If ``require_tenant=False``, the form is
           sealed to ``default_tenant`` by the :meth:`register` call.

        Args:
            path: Directory path containing .yaml/.yml form files.
            recursive: If True, search subdirectories.
            overwrite: If True, overwrite existing registrations.
            tenant: Default tenant for YAML files that don't declare
                ``tenant:`` at the top level.

        Returns:
            Number of forms successfully loaded (skipped files are NOT
            counted).
        """
        try:
            from ..extractors.yaml import YamlExtractor
            extractor = YamlExtractor()
        except ImportError:
            self.logger.warning(
                "YamlExtractor not available — cannot load forms from directory"
            )
            return 0

        dir_path = Path(path)
        if not dir_path.exists():
            self.logger.warning("Form directory does not exist: %s", dir_path)
            return 0

        count = 0
        pattern = "**/*.yaml" if recursive else "*.yaml"
        yml_pattern = "**/*.yml" if recursive else "*.yml"

        # Import YAML parser for raw tenant extraction.
        # The YamlExtractor does not currently pass `tenant:` through to
        # FormSchema.tenant. As a workaround, we read the raw YAML dict
        # ourselves to extract the top-level `tenant:` field before calling
        # the extractor. See Completion Note in TASK-1240 for the gap details.
        try:
            import yaml as _yaml  # type: ignore[import-not-found]
        except ImportError:
            _yaml = None  # type: ignore[assignment]

        for yaml_file in list(dir_path.glob(pattern)) + list(dir_path.glob(yml_pattern)):
            try:
                form = extractor.extract_from_file(str(yaml_file))

                # Tenant resolution per spec §2 Overview:
                # 1. YAML's own tenant: field wins — read it directly from
                #    the raw YAML since YamlExtractor doesn't surface it.
                yaml_tenant: str | None = None
                if _yaml is not None:
                    try:
                        raw = _yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
                        if isinstance(raw, dict):
                            yaml_tenant = raw.get("tenant") or None
                    except Exception:
                        pass

                if yaml_tenant is not None:
                    # YAML wins — override whatever extractor produced.
                    form = form.model_copy(update={"tenant": yaml_tenant})
                elif form.tenant is None and tenant is not None:
                    # 2. Apply kwarg default.
                    form = form.model_copy(update={"tenant": tenant})

                # 3. If still no tenant and require_tenant=True, skip with warning.
                if form.tenant is None and self._require_tenant:
                    self.logger.warning(
                        "Skipping %s: no tenant declared in YAML and no "
                        "fallback tenant= kwarg supplied (require_tenant=True)",
                        yaml_file,
                    )
                    continue

                await self.register(form, overwrite=overwrite)
                count += 1
                self.logger.debug(
                    "Loaded form %s (tenant=%s) from %s",
                    form.form_id,
                    form.tenant,
                    yaml_file,
                )
            except Exception as exc:
                self.logger.warning(
                    "Failed to load form from %s: %s", yaml_file, exc
                )

        self.logger.info("Loaded %d forms from %s", count, dir_path)
        return count

    async def load_from_storage(self, *, tenant: str | None = None) -> int:
        """Load all persisted forms from storage into memory for a tenant.

        Consecutive calls for different tenants do not overwrite each other —
        each call lands results in ``_forms[resolved_tenant]``.

        Args:
            tenant: Tenant slug forwarded to the storage backend so per-tenant
                schemas (``epson.form_schemas``) hydrate correctly.  ``None``
                resolves to ``default_tenant``.

        Returns:
            Number of forms loaded from storage.
        """
        if self._storage is None:
            self.logger.warning("load_from_storage() called but no storage configured")
            return 0

        resolved = self._resolve_tenant(tenant)

        try:
            form_list = await self._storage.list_forms(tenant=resolved)
        except Exception as exc:
            self.logger.error("Failed to list forms from storage: %s", exc)
            return 0

        count = 0
        for item in form_list:
            form_id = item.get("form_id")
            if not form_id:
                continue
            try:
                form = await self._storage.load(form_id, tenant=resolved)
                if form is not None:
                    await self.register(form, overwrite=True, tenant=resolved)
                    count += 1
            except Exception as exc:
                self.logger.warning(
                    "Failed to load form %s from storage (tenant=%s): %s",
                    form_id,
                    resolved,
                    exc,
                )

        self.logger.info(
            "Loaded %d forms from storage (tenant=%s)", count, resolved
        )
        return count

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def has_storage(self) -> bool:
        """Return True if a FormStorage backend is configured.

        Use this instead of accessing ``_storage`` directly from external code.

        Returns:
            True when a storage backend is configured, False otherwise.
        """
        return self._storage is not None

    @property
    def storage(self) -> "FormStorage | None":
        """Return the configured FormStorage backend, or None.

        Prefer :attr:`has_storage` for boolean checks and this property
        when you actually need to call the backend.

        Returns:
            The configured FormStorage instance, or None.
        """
        return self._storage

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def on_register(
        self, callback: Callable[[FormSchema], Awaitable[None]]
    ) -> None:
        """Register a callback invoked when a form is registered.

        Args:
            callback: Async callable receiving the registered FormSchema.
                The form's ``.tenant`` attribute is populated with the
                resolved tenant at registration time (may still be ``None``
                if ``require_tenant=False`` and no tenant was resolved yet).
        """
        self._on_register.append(callback)

    def on_unregister(
        self, callback: Callable[[str, str], Awaitable[None]]
    ) -> None:
        """Register a callback invoked when a form is unregistered.

        BREAKING change from the pre-FEAT-183 signature: callbacks now
        receive ``(form_id, tenant)`` rather than just ``form_id``.

        Args:
            callback: Async callable receiving ``(form_id: str,
                tenant: str)`` — the tenant is the resolved tenant captured
                at :meth:`unregister` call time (never ``None``).
        """
        self._on_unregister.append(callback)

    # ------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------

    async def __aiter__(self):
        """Async iterate over all registered forms in deterministic order.

        Yields forms sorted by ``(tenant, form_id)`` — stable across runs,
        required for reproducible tests and admin UIs.
        """
        async with self._lock:
            # Snapshot under lock to avoid modification during iteration.
            snapshot = [
                form
                for t in sorted(self._forms.keys())
                for fid in sorted(self._forms[t].keys())
                for form in (self._forms[t].get(fid),)
                if form is not None
            ]
        for form in snapshot:
            yield form

    def __len__(self) -> int:
        """Return total number of registered forms across all tenants."""
        return sum(len(inner) for inner in self._forms.values())

    def __contains__(self, item: tuple[str, str]) -> bool:  # type: ignore[override]
        """Check registration using a ``(tenant, form_id)`` tuple.

        BREAKING change from the pre-FEAT-183 ``__contains__(form_id: str)``
        signature.  Passing a plain ``str`` raises ``TypeError`` to catch
        callers that have not been updated.

        Args:
            item: A ``(tenant, form_id)`` tuple.

        Returns:
            True if the form is registered under the given tenant.

        Raises:
            TypeError: If ``item`` is not a tuple.
        """
        if not isinstance(item, tuple):
            raise TypeError(
                "FormRegistry.__contains__ requires a (tenant, form_id) tuple; "
                f"got {type(item).__name__!r}. "
                "Use: (tenant, form_id) in registry"
            )
        tenant, form_id = item
        return form_id in self._forms.get(tenant, {})
