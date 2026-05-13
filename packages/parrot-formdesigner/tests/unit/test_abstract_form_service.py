"""Unit tests for AbstractFormService ABC contract (TASK-1125)."""

from typing import Any

import pytest

from parrot_formdesigner.tools.services.abstract import AbstractFormService
from parrot_formdesigner.core.schema import FormSchema


class TestAbstractFormService:
    """Tests verifying the ABC contract for AbstractFormService."""

    def test_abc_cannot_be_instantiated(self) -> None:
        """ABC must reject direct instantiation."""
        with pytest.raises(TypeError):
            AbstractFormService()  # type: ignore[abstract]

    def test_subclass_missing_fetch_cannot_instantiate(self) -> None:
        """Subclass that only implements to_form_schema must fail."""

        class Half(AbstractFormService):
            def to_form_schema(self, raw: dict[str, Any]) -> FormSchema:
                return FormSchema(form_id="x", title="x", sections=[])

        with pytest.raises(TypeError):
            Half()  # type: ignore[abstract]

    def test_subclass_missing_to_form_schema_cannot_instantiate(self) -> None:
        """Subclass that only implements fetch must fail."""

        class Half(AbstractFormService):
            async def fetch(self, **params: Any) -> dict[str, Any]:
                return {}

        with pytest.raises(TypeError):
            Half()  # type: ignore[abstract]

    @pytest.mark.asyncio
    async def test_fully_implemented_subclass_works(self) -> None:
        """Concrete subclass instantiates and methods are callable."""

        class Concrete(AbstractFormService):
            async def fetch(self, **params: Any) -> dict[str, Any]:
                return {"params": params}

            def to_form_schema(self, raw: dict[str, Any]) -> FormSchema:
                return FormSchema(form_id="t-1", title="t", sections=[])

        svc = Concrete()
        raw = await svc.fetch(formid=1, orgid=2)
        assert raw == {"params": {"formid": 1, "orgid": 2}}
        form = svc.to_form_schema(raw)
        assert form.form_id == "t-1"
