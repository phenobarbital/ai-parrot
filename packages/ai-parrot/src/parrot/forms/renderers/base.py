"""Abstract base class for form renderers.

All form renderers implement AbstractFormRenderer to produce RenderedForm
output from FormSchema + StyleSchema input.
"""

from abc import ABC, abstractmethod
from typing import Any

from ..schema import FormSchema, RenderedForm
from ..style import StyleSchema


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
