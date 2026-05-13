"""AbstractFormService — strategy interface for form-source services."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ...core.schema import FormSchema


class AbstractFormService(ABC):
    """Strategy interface for sourcing a FormSchema from any origin.

    Subclasses implement two methods:

    - ``fetch(*, formid, orgid, **kwargs)`` — retrieve raw data (DB row, REST
      payload, …). All parameters are keyword-only.
    - ``to_form_schema(raw)``               — translate raw data into a FormSchema.

    Splitting fetch from mapping keeps the schema-mapping logic testable
    without I/O. The FormRegistry coupling stays in DatabaseFormTool — the
    service must not call registry.register() itself.
    """

    @abstractmethod
    async def fetch(self, **params: Any) -> dict[str, Any]:
        """Fetch raw form data from the underlying source.

        Implementations should declare keyword-only parameters explicitly
        (e.g. ``*, formid: int, orgid: int, **kwargs: Any``) and accept
        additional kwargs gracefully so that callers can forward extra
        service-specific parameters without breaking the interface.
        """

    @abstractmethod
    def to_form_schema(self, raw: dict[str, Any]) -> FormSchema:
        """Translate the raw payload into a canonical FormSchema."""
