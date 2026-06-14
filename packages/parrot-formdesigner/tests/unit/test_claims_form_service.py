"""Unit tests for ClaimsFormService builders (TASK-020)."""

import pytest

from parrot_formdesigner.core.schema import FormType
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services import ClaimsFormService, ClaimScope
from parrot_formdesigner.services.registry import FormRegistry


@pytest.fixture
def registry() -> FormRegistry:
    return FormRegistry(default_tenant="navigator", require_tenant=False)


@pytest.fixture
def service(registry: FormRegistry) -> ClaimsFormService:
    return ClaimsFormService(registry, tenant="navigator")


async def test_build_claim_type_form_returns_schema(service: ClaimsFormService) -> None:
    form = await service.build_claim_type_form(ClaimScope.PROGRAM)
    assert form.form_type is FormType.CLAIMS_CONFIG
    assert len(form.sections) >= 1
    field_ids = {f.field_id for f in form.iter_all_fields()}
    assert {"category", "scope", "event_config"} <= field_ids


async def test_build_pay_period_form_has_date_fields(service: ClaimsFormService) -> None:
    form = await service.build_pay_period_form()
    date_fields = {
        f.field_id for f in form.iter_all_fields() if f.field_type is FieldType.DATE
    }
    assert {"start", "end", "paydate", "lockdate"} <= date_fields


async def test_build_exception_config_form_has_number_fields(
    service: ClaimsFormService,
) -> None:
    form = await service.build_exception_config_form()
    number_fields = {
        f.field_id for f in form.iter_all_fields() if f.field_type is FieldType.NUMBER
    }
    assert "threshold_value" in number_fields


async def test_claims_form_service_registers_form(
    service: ClaimsFormService, registry: FormRegistry
) -> None:
    form = await service.build_claim_type_form(ClaimScope.CLIENT)
    fetched = await registry.get(form.form_id, tenant="navigator")
    assert fetched is not None
    assert fetched.form_id == form.form_id


async def test_cascade_scope_forms_distinct_ids(service: ClaimsFormService) -> None:
    g = await service.build_claim_type_form(ClaimScope.GLOBAL)
    c = await service.build_claim_type_form(ClaimScope.CLIENT)
    p = await service.build_claim_type_form(ClaimScope.PROGRAM)
    assert len({g.form_id, c.form_id, p.form_id}) == 3
