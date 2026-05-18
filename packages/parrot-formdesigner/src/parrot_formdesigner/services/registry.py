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
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..core.schema import FormSchema
from ..core.style import StyleSchema
from .validators import FormValidator

logger = logging.getLogger(__name__)


class FormAlreadyExistsError(ValueError):
    """Raised when attempting to register a form with an ID that already exists."""
    pass


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
    """Thread-safe registry for FormSchema objects.

    Supports in-memory registration, optional persistence via FormStorage,
    async event callbacks, and YAML directory loading via YamlExtractor.

    Example:
        registry = FormRegistry()
        await registry.register(form_schema)
        form = await registry.get("my-form")

        # With persistence
        registry = FormRegistry(storage=PostgreSQLFormStorage(...))
        await registry.register(form_schema, persist=True)
        await registry.load_from_storage()
    """

    def __init__(self, storage: FormStorage | None = None) -> None:
        """Initialize FormRegistry.

        Args:
            storage: Optional FormStorage backend for persistence.
        """
        self._forms: dict[str, FormSchema] = {}
        self._lock = asyncio.Lock()
        self._storage = storage
        self._on_register: list[Callable[[FormSchema], Awaitable[None]]] = []
        self._on_unregister: list[Callable[[str], Awaitable[None]]] = []
        self.logger = logging.getLogger(__name__)

    async def register(
        self,
        form: FormSchema,
        *,
        persist: bool = False,
        overwrite: bool = True,
    ) -> None:
        """Register a form schema.

        Args:
            form: FormSchema to register.
            persist: If True, also save to storage backend.
                Logs a warning (does not raise) if no storage is configured.
            overwrite: If True, overwrite existing registration (default True).
        """
        async with self._lock:
            if form.form_id in self._forms and not overwrite:
                self.logger.debug("Form %s already registered, skipping", form.form_id)
                return

            self._forms[form.form_id] = form

        # Persist to backend if requested
        if persist:
            if self._storage is not None:
                try:
                    await self._storage.save(form, tenant=form.tenant)
                except Exception as exc:
                    self.logger.warning(
                        "Failed to persist form %s: %s", form.form_id, exc
                    )
            else:
                self.logger.warning(
                    "persist=True but no FormStorage configured — "
                    "form %s saved in-memory only",
                    form.form_id,
                )

        # Fire callbacks
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

    async def unregister(self, form_id: str) -> bool:
        """Unregister a form schema.

        Args:
            form_id: ID of the form to remove.

        Returns:
            True if removed, False if not found.
        """
        async with self._lock:
            form = self._forms.pop(form_id, None)
            if form is None:
                return False

        # Fire callbacks
        for callback in self._on_unregister:
            try:
                await callback(form_id)
            except Exception as exc:
                self.logger.warning("Unregister callback failed: %s", exc)

        return True

    async def get(self, form_id: str) -> FormSchema | None:
        """Get a form schema by ID.

        Args:
            form_id: Form identifier.

        Returns:
            FormSchema if found, None otherwise.
        """
        async with self._lock:
            return self._forms.get(form_id)

    async def list_forms(self) -> list[FormSchema]:
        """List all registered form schemas.

        Returns:
            List of all registered FormSchema objects.
        """
        async with self._lock:
            return list(self._forms.values())

    async def list_form_ids(self) -> list[str]:
        """List all registered form IDs.

        Returns:
            List of form_id strings.
        """
        async with self._lock:
            return list(self._forms.keys())

    async def contains(self, form_id: str) -> bool:
        """Check if a form is registered.

        Args:
            form_id: Form identifier to check.

        Returns:
            True if registered.
        """
        async with self._lock:
            return form_id in self._forms

    async def clear(self) -> None:
        """Clear all registered forms."""
        async with self._lock:
            self._forms.clear()

    async def load_from_directory(
        self,
        path: str | Path,
        *,
        recursive: bool = True,
        overwrite: bool = False,
    ) -> int:
        """Load YAML form definitions from a directory using YamlExtractor.

        If YamlExtractor is not available, logs a warning and returns 0.

        Args:
            path: Directory path containing .yaml/.yml form files.
            recursive: If True, search subdirectories.
            overwrite: If True, overwrite existing registrations.

        Returns:
            Number of forms successfully loaded.
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

        for yaml_file in list(dir_path.glob(pattern)) + list(dir_path.glob(yml_pattern)):
            try:
                form = extractor.extract_from_file(str(yaml_file))
                await self.register(form, overwrite=overwrite)
                count += 1
                self.logger.debug("Loaded form %s from %s", form.form_id, yaml_file)
            except Exception as exc:
                self.logger.warning(
                    "Failed to load form from %s: %s", yaml_file, exc
                )

        self.logger.info("Loaded %d forms from %s", count, dir_path)
        return count

    async def load_from_storage(self, *, tenant: str | None = None) -> int:
        """Load all persisted forms from storage into memory.

        Args:
            tenant: Optional tenant slug forwarded to the storage backend
                so per-tenant schemas (``epson.form_schemas``) hydrate
                correctly. ``None`` uses the storage's default schema.

        Returns:
            Number of forms loaded from storage.
        """
        if self._storage is None:
            self.logger.warning("load_from_storage() called but no storage configured")
            return 0

        try:
            form_list = await self._storage.list_forms(tenant=tenant)
        except Exception as exc:
            self.logger.error("Failed to list forms from storage: %s", exc)
            return 0

        count = 0
        for item in form_list:
            form_id = item.get("form_id")
            if not form_id:
                continue
            try:
                form = await self._storage.load(form_id, tenant=tenant)
                if form is not None:
                    await self.register(form, overwrite=True)
                    count += 1
            except Exception as exc:
                self.logger.warning(
                    "Failed to load form %s from storage: %s", form_id, exc
                )

        self.logger.info("Loaded %d forms from storage", count)
        return count

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

    def on_register(
        self, callback: Callable[[FormSchema], Awaitable[None]]
    ) -> None:
        """Register a callback invoked when a form is registered.

        Args:
            callback: Async callable receiving the registered FormSchema.
        """
        self._on_register.append(callback)

    def on_unregister(
        self, callback: Callable[[str], Awaitable[None]]
    ) -> None:
        """Register a callback invoked when a form is unregistered.

        Args:
            callback: Async callable receiving the unregistered form_id.
        """
        self._on_unregister.append(callback)

    async def __aiter__(self):
        """Async iterate over registered forms."""
        async with self._lock:
            forms = list(self._forms.values())
        for form in forms:
            yield form

    def __len__(self) -> int:
        """Return number of registered forms (non-async snapshot)."""
        return len(self._forms)

    def __contains__(self, form_id: str) -> bool:
        """Check if form_id is registered (non-async snapshot)."""
        return form_id in self._forms

    async def clone_form(
        self,
        source_form_id: str,
        new_form_id: str,
        patch: "dict[str, Any] | None" = None,
        *,
        persist: bool = True,
        tenant: str | None = None,
    ) -> "FormSchema":
        """Clone an existing form under a new form_id.

        Creates a deep copy of the source form, assigns ``new_form_id``,
        resets ``version`` to ``"1.0"`` and ``created_at`` to ``None``,
        records ``meta["cloned_from"]`` for provenance, optionally applies an
        RFC 7396 merge-patch, validates the result, and registers it.

        Args:
            source_form_id: ``form_id`` of the form to clone.
            new_form_id: ``form_id`` to assign to the cloned form.
            patch: Optional RFC 7396 merge-patch dict to apply on top of the
                cloned form before validation.  ``form_id`` and ``created_at``
                in the patch are ignored.
            persist: If ``True`` (default), persist the cloned form via the
                configured storage backend.
            tenant: Optional tenant slug applied to the cloned form.  When
                provided it overrides whatever the source form carried.

        Returns:
            The newly cloned and registered ``FormSchema``.

        Raises:
            KeyError: When ``source_form_id`` is not found in the registry.
            FormAlreadyExistsError: When ``new_form_id`` already exists in the
                registry.
            ValueError: When ``FormValidator.check_schema`` reports structural
                errors on the cloned (and optionally patched) form.
        """
        source = await self.get(source_form_id)
        if source is None:
            raise KeyError(f"Form '{source_form_id}' not found")

        if await self.contains(new_form_id):
            raise FormAlreadyExistsError(f"Form '{new_form_id}' already exists")

        # Deep-clone via Pydantic v2
        clone = source.model_copy(deep=True)

        # Apply mandatory field resets
        clone.form_id = new_form_id
        clone.version = "1.0"
        clone.created_at = None

        # Apply tenant override when provided
        if tenant is not None:
            clone.tenant = tenant

        # Record provenance in meta
        if clone.meta is None:
            clone.meta = {}
        clone.meta["cloned_from"] = source_form_id

        # Apply optional RFC 7396 merge-patch
        if patch:
            from ..api._utils import _deep_merge  # deferred to avoid circular import
            clone_dict = clone.model_dump()
            merged = _deep_merge(clone_dict, patch)
            # Patch cannot override form_id or created_at
            merged["form_id"] = new_form_id
            merged.pop("created_at", None)
            # Ensure provenance survives the patch (RFC 7396 null removal)
            meta = merged.get("meta") or {}
            meta["cloned_from"] = source_form_id
            merged["meta"] = meta
            clone = FormSchema.model_validate(merged)
            # Ensure created_at remains None after re-validation
            clone.created_at = None

        # Structural validation
        errors = FormValidator().check_schema(clone)
        if errors:
            raise ValueError(f"Cloned form failed validation: {errors}")

        await self.register(clone, persist=persist, overwrite=False)

        # TOCTOU race condition guard
        if not await self.contains(new_form_id):
            raise ValueError(
                f"Form '{new_form_id}' could not be registered — concurrent conflict"
            )

        self.logger.info(
            "Cloned form '%s' -> '%s' (persist=%s)",
            source_form_id,
            new_form_id,
            persist,
        )
        return clone
