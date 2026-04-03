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
    ) -> str:
        """Persist a form schema.

        Args:
            form: FormSchema to persist.
            style: Optional associated StyleSchema.

        Returns:
            The form_id of the saved form.
        """
        ...

    @abstractmethod
    async def load(
        self,
        form_id: str,
        version: str | None = None,
    ) -> FormSchema | None:
        """Load a form schema by ID.

        Args:
            form_id: Identifier of the form to load.
            version: Optional version string. If None, loads the latest.

        Returns:
            FormSchema if found, None otherwise.
        """
        ...

    @abstractmethod
    async def delete(self, form_id: str) -> bool:
        """Delete a persisted form.

        Args:
            form_id: Identifier of the form to delete.

        Returns:
            True if deleted, False if not found.
        """
        ...

    @abstractmethod
    async def list_forms(self) -> list[dict[str, str]]:
        """List all persisted forms.

        Returns:
            List of dicts with at minimum {"form_id": ..., "title": ...}.
        """
        ...


class FormRegistry:
    """Thread-safe registry for FormSchema objects.

    Supports in-memory registration, trigger-phrase lookup, optional
    persistence via FormStorage, async event callbacks, and YAML directory
    loading via YamlExtractor.

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
        self._trigger_index: dict[str, str] = {}  # phrase_lower -> form_id
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

            # Index trigger phrases if the form has them
            trigger_phrases: list[str] = getattr(form, "trigger_phrases", []) or []
            for phrase in trigger_phrases:
                self._trigger_index[phrase.lower()] = form.form_id

        # Persist to backend if requested
        if persist:
            if self._storage is not None:
                try:
                    await self._storage.save(form)
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

            # Remove trigger phrases
            trigger_phrases: list[str] = getattr(form, "trigger_phrases", []) or []
            for phrase in trigger_phrases:
                phrase_lower = phrase.lower()
                if self._trigger_index.get(phrase_lower) == form_id:
                    del self._trigger_index[phrase_lower]

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

    async def get_by_trigger(self, phrase: str) -> FormSchema | None:
        """Get a form by exact trigger phrase (case-insensitive).

        Args:
            phrase: Trigger phrase to look up.

        Returns:
            FormSchema if found, None otherwise.
        """
        phrase_lower = phrase.lower()
        async with self._lock:
            form_id = self._trigger_index.get(phrase_lower)
            if form_id:
                return self._forms.get(form_id)
            return None

    async def find_by_trigger(self, text: str) -> FormSchema | None:
        """Find a form whose trigger phrase appears anywhere in text.

        Uses case-insensitive substring matching.

        Args:
            text: Text to search for trigger phrases.

        Returns:
            First matching FormSchema, or None.
        """
        text_lower = text.lower()
        async with self._lock:
            for phrase, form_id in self._trigger_index.items():
                if phrase in text_lower:
                    return self._forms.get(form_id)
            return None

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
            self._trigger_index.clear()

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
            from .extractors.yaml import YamlExtractor
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

    async def load_from_storage(self) -> int:
        """Load all persisted forms from storage into memory.

        Args: None

        Returns:
            Number of forms loaded from storage.
        """
        if self._storage is None:
            self.logger.warning("load_from_storage() called but no storage configured")
            return 0

        try:
            form_list = await self._storage.list_forms()
        except Exception as exc:
            self.logger.error("Failed to list forms from storage: %s", exc)
            return 0

        count = 0
        for item in form_list:
            form_id = item.get("form_id")
            if not form_id:
                continue
            try:
                form = await self._storage.load(form_id)
                if form is not None:
                    await self.register(form, overwrite=True)
                    count += 1
            except Exception as exc:
                self.logger.warning(
                    "Failed to load form %s from storage: %s", form_id, exc
                )

        self.logger.info("Loaded %d forms from storage", count)
        return count

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
