"""DatabaseFormTool — thin dispatcher over an AbstractFormService.

Resolves the requested service by name, runs fetch + to_form_schema, then
registers the resulting FormSchema in the FormRegistry.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

try:
    from parrot.tools.abstract import AbstractTool, ToolResult
except ImportError as exc:
    raise ImportError(
        "parrot-formdesigner tools require the 'ai-parrot' package. "
        "Install it with: uv add ai-parrot"
    ) from exc

from ..services.registry import FormRegistry
from .services import get_form_service


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class DatabaseFormInput(BaseModel):
    """Input schema for DatabaseFormTool — service-aware.

    Attributes:
        service: Form source service name. Must be registered via
            register_form_service(...). Defaults to 'networkninja'.
        formid: Numeric form identifier in the database.
        orgid: Organization ID that owns the form.
        params: Optional service-specific extras forwarded to
            AbstractFormService.fetch(**params).
        persist: Whether to save the resulting FormSchema to the registry storage.
    """

    service: str = Field(
        default="networkninja",
        description=(
            "Form source service name. Must be registered via "
            "register_form_service(...). Defaults to 'networkninja'."
        ),
    )
    formid: int = Field(..., ge=1, description="Numeric form identifier")
    orgid: int = Field(..., ge=1, description="Organization ID that owns the form")
    params: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional service-specific extras forwarded to "
            "AbstractFormService.fetch(**params)."
        ),
    )
    service_kwargs: dict[str, Any] | None = Field(
        default=None,
        description="Extra kwargs forwarded to the service constructor.",
    )
    persist: bool = Field(
        default=False,
        description="Save the generated FormSchema to the registry storage",
    )


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------


class DatabaseFormTool(AbstractTool):
    """Load a form definition from a configured form-source service into a FormSchema.

    Resolves the requested service by name via the form-service registry,
    runs ``fetch()`` to retrieve raw data, maps it via ``to_form_schema()``,
    registers the result in the ``FormRegistry``, and returns it in
    ``ToolResult.metadata["form"]``.

    Example:
        tool = DatabaseFormTool(registry=registry)
        result = await tool.execute(formid=42, orgid=7)
        form_schema = FormSchema(**result.metadata["form"])
    """

    name: str = "database_form"
    description: str = (
        "Load a form definition from a configured form-source service into a "
        "FormSchema. Requires formid and orgid; service defaults to 'networkninja'."
    )
    args_schema = DatabaseFormInput

    def __init__(self, registry: FormRegistry, **kwargs: Any) -> None:
        """Initialize DatabaseFormTool.

        Args:
            registry: FormRegistry where the generated FormSchema will be registered.
            **kwargs: Additional keyword arguments forwarded to AbstractTool.

        Raises:
            TypeError: If legacy ``dsn=`` or ``db=`` kwargs are passed (removed
                in v0.3.0 — each service now owns its own DSN).
        """
        if "dsn" in kwargs:
            raise TypeError(
                "DatabaseFormTool.__init__() got an unexpected keyword argument 'dsn'. "
                "DSN is now owned by the form service. "
                "Pass dsn= to NetworkninjaFormService instead."
            )
        if "db" in kwargs:
            raise TypeError(
                "DatabaseFormTool.__init__() got an unexpected keyword argument 'db'. "
                "DB connection is now owned by the form service. "
                "Pass db= to NetworkninjaFormService instead."
            )
        super().__init__(**kwargs)
        self._registry = registry
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # AbstractTool interface
    # ------------------------------------------------------------------

    async def _execute(  # type: ignore[override]
        self,
        service: str = "networkninja",
        formid: int = 0,
        orgid: int = 0,
        params: dict[str, Any] | None = None,
        service_kwargs: dict[str, Any] | None = None,
        persist: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        """Execute the dispatcher pipeline.

        Args:
            service: Name of the registered form-source service.
            formid: Numeric form identifier.
            orgid: Organization ID.
            params: Optional service-specific extras forwarded to fetch().
                Reserved keys ``formid`` and ``orgid`` are filtered out to
                avoid ``TypeError: got multiple values for keyword argument``.
            service_kwargs: Optional kwargs forwarded to the service constructor.
            persist: If True, persist the form via the registry storage backend.
            **kwargs: Ignored extra arguments.

        Returns:
            ToolResult with ``success=True`` and the FormSchema in
            ``metadata["form"]``, or ``success=False`` with error details.
        """
        # 1. Resolve service
        try:
            cls = get_form_service(service)
        except KeyError as exc:
            msg = str(exc)
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=msg,
                metadata={"error": msg},
            )

        # 2-4. Instantiate + fetch + map
        _RESERVED = {"formid", "orgid"}
        extra = {k: v for k, v in (params or {}).items() if k not in _RESERVED}
        try:
            svc = cls(**(service_kwargs or {}))
            raw = await svc.fetch(formid=formid, orgid=orgid, **extra)
            form = svc.to_form_schema(raw)
        except json.JSONDecodeError as exc:
            self.logger.error("Malformed JSON for formid=%s: %s", formid, exc)
            msg = str(exc)
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=msg,
                metadata={"error": msg},
            )
        except RuntimeError as exc:
            # service raised — e.g., form not found, DB error
            msg = str(exc)
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=msg,
                metadata={"error": msg},
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "DatabaseFormTool error for service=%s formid=%s: %s",
                service,
                formid,
                exc,
                exc_info=True,
            )
            msg = str(exc)
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=msg,
                metadata={"error": msg},
            )

        # 5. Register
        await self._registry.register(form, persist=persist)

        self.logger.info(
            "Loaded form %s via service=%s (formid=%s, orgid=%s) — %d sections",
            form.form_id,
            service,
            formid,
            orgid,
            len(form.sections),
        )

        # 6. Return
        return ToolResult(
            success=True,
            status="success",
            result={"form_id": form.form_id, "title": str(form.title)},
            metadata={"form": form.model_dump()},
        )
