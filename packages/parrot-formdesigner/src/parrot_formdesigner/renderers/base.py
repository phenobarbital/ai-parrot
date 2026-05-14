"""Abstract base class for form renderers.

All form renderers implement AbstractFormRenderer to produce RenderedForm
output from FormSchema + StyleSchema input.
"""

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from ..core.schema import FormField, FormSchema, RenderedForm
from ..core.style import StyleSchema


@runtime_checkable
class FieldRenderer(Protocol):
    """Per-target field renderer. One concrete impl per (FieldType, output target).

    The render() signature uses keyword-only args so callers can pass optional
    context without breaking positional compatibility. Return type is Any
    because each output target uses a different representation (str for HTML5,
    dict for Adaptive Card/JSON Schema, bytes for PDF, etc.).
    """

    async def render(
        self,
        field: FormField,
        *,
        locale: str = "en",
        prefilled: Any = None,
        error: str | None = None,
    ) -> Any: ...


class FallbackRenderer:
    """Concrete fallback emitter — degraded representation.

    Each renderer subclasses or instantiates this to define what 'degraded'
    means for its target. The base implementation returns None — subclasses
    must override render() to emit target-appropriate content.

    Warning appending is the renderer's responsibility (it has access to
    RenderedForm.warnings once Module 8 is merged).
    """

    async def render(
        self,
        field: FormField,
        *,
        locale: str = "en",
        prefilled: Any = None,
        error: str | None = None,
    ) -> Any:
        """Return None as placeholder. Override in renderer-specific subclasses."""
        return None


class AbstractFormRenderer(ABC):
    """Abstract base for form renderers.

    Subclasses implement render() to convert a FormSchema into a
    platform-specific representation (Adaptive Card, HTML5, JSON Schema, etc.).

    The render() method is async to support renderers that may need
    to fetch dynamic options or perform I/O.
    """

    @abstractmethod
    async def render(
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm:
        """Render a FormSchema into the target format.

        Args:
            form: The form schema to render.
            style: Optional style configuration. Defaults to StyleSchema().
            locale: BCP 47 locale tag for i18n label resolution.
            prefilled: Pre-filled field values (field_id -> value).
            errors: Validation errors to display (field_id -> message).

        Returns:
            RenderedForm with the rendered content and metadata.
        """
        ...
