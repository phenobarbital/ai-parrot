"""
Dialog Registry.

Manages registration and lookup of available form dialog definitions.
"""
from pathlib import Path
from typing import Dict, Optional, List, Union, Callable, Awaitable
from threading import Lock
import asyncio

from .models import FormDefinition
from .parser import parse_yaml_file, FormParserError


class FormRegistry:
    """
    Registry for managing available form dialog definitions.

    Thread-safe registry that supports:
    - Manual registration via register()
    - Auto-loading from directories
    - Lookup by form_id or trigger phrases
    - Integration with FormDefinitionCache

    Example:
        >>> registry = FormRegistry()
        >>> registry.load_from_directory('/path/to/forms')
        >>> form = registry.get('employee_onboarding')
        >>> form.title
        'New Employee Registration'
    """

    def __init__(self):
        self._forms: Dict[str, FormDefinition] = {}
        self._trigger_index: Dict[str, str] = {}  # phrase -> form_id
        self._lock = Lock()
        self._on_register: List[Callable[[FormDefinition], Awaitable[None]]] = []

    def register(self, form: FormDefinition, overwrite: bool = False) -> bool:
        """
        Register a form definition.

        Args:
            form: FormDefinition to register
            overwrite: If True, overwrite existing registration

        Returns:
            True if registered, False if already exists and not overwriting
        """
        with self._lock:
            if form.form_id in self._forms and not overwrite:
                return False

            self._forms[form.form_id] = form

            # Index trigger phrases
            for phrase in form.trigger_phrases:
                phrase_lower = phrase.lower()
                self._trigger_index[phrase_lower] = form.form_id

            return True

    def unregister(self, form_id: str) -> bool:
        """
        Unregister a form definition.

        Args:
            form_id: ID of the form to unregister

        Returns:
            True if unregistered, False if not found
        """
        with self._lock:
            if form_id not in self._forms:
                return False

            form = self._forms.pop(form_id)

            # Remove trigger phrases from index
            for phrase in form.trigger_phrases:
                phrase_lower = phrase.lower()
                if self._trigger_index.get(phrase_lower) == form_id:
                    del self._trigger_index[phrase_lower]

            return True

    def get(self, form_id: str) -> Optional[FormDefinition]:
        """
        Get a form definition by ID.

        Args:
            form_id: Form identifier

        Returns:
            FormDefinition or None if not found
        """
        with self._lock:
            return self._forms.get(form_id)

    def get_by_trigger(self, phrase: str) -> Optional[FormDefinition]:
        """
        Get a form definition by trigger phrase.

        Args:
            phrase: Trigger phrase to match

        Returns:
            FormDefinition or None if no match
        """
        phrase_lower = phrase.lower()
        with self._lock:
            form_id = self._trigger_index.get(phrase_lower)
            if form_id:
                return self._forms.get(form_id)
            return None

    def find_by_trigger(self, text: str) -> Optional[FormDefinition]:
        """
        Find a form that matches any trigger phrase in the text.

        Args:
            text: Text to search for trigger phrases

        Returns:
            First matching FormDefinition or None
        """
        text_lower = text.lower()
        with self._lock:
            for phrase, form_id in self._trigger_index.items():
                if phrase in text_lower:
                    return self._forms.get(form_id)
            return None

    def list_forms(self) -> List[FormDefinition]:
        """Get all registered forms."""
        with self._lock:
            return list(self._forms.values())

    def list_form_ids(self) -> List[str]:
        """Get all registered form IDs."""
        with self._lock:
            return list(self._forms.keys())

    def contains(self, form_id: str) -> bool:
        """Check if a form ID is registered."""
        with self._lock:
            return form_id in self._forms

    def clear(self):
        """Clear all registered forms."""
        with self._lock:
            self._forms.clear()
            self._trigger_index.clear()

    def load_from_directory(
        self,
        directory: Union[str, Path],
        recursive: bool = True,
        overwrite: bool = False,
    ) -> Dict[str, Union[FormDefinition, Exception]]:
        """
        Load all YAML form definitions from a directory.

        Args:
            directory: Path to forms directory
            recursive: If True, search subdirectories
            overwrite: If True, overwrite existing registrations

        Returns:
            Dict mapping filename to FormDefinition or Exception if failed
        """
        dir_path = Path(directory)
        if not dir_path.exists():
            return {}

        results = {}
        pattern = "**/*.yaml" if recursive else "*.yaml"

        for yaml_file in dir_path.glob(pattern):
            try:
                form = parse_yaml_file(yaml_file)
                if self.register(form, overwrite=overwrite):
                    results[str(yaml_file)] = form
                else:
                    results[str(yaml_file)] = ValueError(
                        f"Form '{form.form_id}' already registered"
                    )
            except Exception as e:
                results[str(yaml_file)] = e

        # Also check .yml extension
        yml_pattern = "**/*.yml" if recursive else "*.yml"
        for yaml_file in dir_path.glob(yml_pattern):
            try:
                form = parse_yaml_file(yaml_file)
                if self.register(form, overwrite=overwrite):
                    results[str(yaml_file)] = form
                else:
                    results[str(yaml_file)] = ValueError(
                        f"Form '{form.form_id}' already registered"
                    )
            except Exception as e:
                results[str(yaml_file)] = e

        return results

    def on_register(self, callback: Callable[[FormDefinition], Awaitable[None]]):
        """Register a callback for form registration events."""
        self._on_register.append(callback)

    async def register_async(
        self,
        form: FormDefinition,
        overwrite: bool = False
    ) -> bool:
        """
        Async version of register() that triggers callbacks.

        Args:
            form: FormDefinition to register
            overwrite: If True, overwrite existing registration

        Returns:
            True if registered, False if already exists and not overwriting
        """
        result = self.register(form, overwrite=overwrite)
        if result:
            for callback in self._on_register:
                try:
                    await callback(form)
                except Exception:
                    pass  # Don't fail on callback errors
        return result

    def __len__(self) -> int:
        """Return number of registered forms."""
        with self._lock:
            return len(self._forms)

    def __contains__(self, form_id: str) -> bool:
        """Check if form_id is registered."""
        return self.contains(form_id)

    def __iter__(self):
        """Iterate over registered forms."""
        return iter(self.list_forms())


# Global registry instance
_global_registry: Optional[FormRegistry] = None


def get_registry() -> FormRegistry:
    """Get the global form registry instance."""
    global _global_registry
    if _global_registry is None:
        _global_registry = FormRegistry()
    return _global_registry


def register_form(form: FormDefinition, overwrite: bool = False) -> bool:
    """Register a form in the global registry."""
    return get_registry().register(form, overwrite=overwrite)


def get_form(form_id: str) -> Optional[FormDefinition]:
    """Get a form from the global registry."""
    return get_registry().get(form_id)


__all__ = [
    'FormRegistry',
    'get_registry',
    'register_form',
    'get_form',
]
