"""Field option definitions for select and multi-select fields.

This module defines the data models for static options and dynamic
options sources that can be loaded from external services.
"""

from pydantic import BaseModel

from .types import LocalizedString


class FieldOption(BaseModel):
    """A single option in a select or multi-select field.

    Attributes:
        value: The machine-readable value submitted with the form.
        label: The human-readable label shown to the user.
        description: Optional extended description of the option.
        disabled: Whether this option is disabled and cannot be selected.
        icon: Optional icon identifier or URL to display alongside the option.
    """

    value: str
    label: LocalizedString
    description: LocalizedString | None = None
    disabled: bool = False
    icon: str | None = None


class OptionsSource(BaseModel):
    """Dynamic options source configuration for fetching options at runtime.

    Attributes:
        source_type: Type of source (e.g., "tool", "endpoint", "query").
        source_ref: Reference to the source (tool name, URL, query name).
        value_field: Field in the source response to use as option value.
        label_field: Field in the source response to use as option label.
        cache_ttl_seconds: How long to cache the fetched options. None means no cache.
    """

    source_type: str
    source_ref: str
    value_field: str = "value"
    label_field: str = "label"
    cache_ttl_seconds: int | None = None
