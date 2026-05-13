"""AbstractFormService — strategy interface for form-source services."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ...core.schema import FormSchema


class AbstractFormService(ABC):
    """Strategy interface for sourcing a FormSchema from any origin.

    Subclasses implement two methods:
    - ``fetch(**params)``        — retrieve raw data (DB row, REST payload, …).
    - ``to_form_schema(raw)``    — translate raw data into a FormSchema.

    Splitting fetch from mapping keeps the schema-mapping logic testable
    without I/O. The FormRegistry coupling stays in DatabaseFormTool — the
    service must not call registry.register() itself.
    """

    @abstractmethod
    async def fetch(self, **params: Any) -> dict[str, Any]:
        """Fetch raw form data from the underlying source."""

    @abstractmethod
    def to_form_schema(self, raw: dict[str, Any]) -> FormSchema:
        """Translate the raw payload into a canonical FormSchema."""
