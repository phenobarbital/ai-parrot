"""TASK-2142: Two latent bug fixes — TimeBlock Pydantic defaults + Organization_Type_ID form."""
from __future__ import annotations

import logging

import pytest
from parrot_tools.interfaces.workday.handlers.organizations import OrganizationType
from parrot_tools.interfaces.workday.models.time_block import TimeBlock
from pydantic import ValidationError


class _FakeService:
    """Minimal stand-in providing the logger the handler base looks up."""

    def __init__(self):
        self._logger = logging.getLogger("test.workday.organizations")


class TestTimeBlockPartialResponse:
    def test_partial_response_parses(self):
        """REGRESSION: a response omitting is_deleted and calculated_* fields
        previously raised (Pydantic v2 treats bare Optional[X] as required).
        It must now parse."""
        tb = TimeBlock(raw_data={"whatever": 1})
        assert tb.is_deleted is None
        assert tb.calculated_date is None
        assert tb.calculated_in_time is None
        assert tb.calculated_out_time is None
        assert tb.calculated_quantity is None
        assert tb.time_block_id is None
        assert tb.time_block_wid is None
        assert tb.worker_id is None
        assert tb.worker_name is None
        assert tb.status is None
        assert tb.calculation_tags is None
        assert tb.last_updated is None
        assert tb.worktags is None
        # Pre-existing correct default is unaffected.
        assert tb.shift_date is None

    def test_full_response_still_parses(self):
        """Non-regression: a fully-populated response still works."""
        tb = TimeBlock(
            time_block_id="TB1",
            time_block_wid="WID1",
            worker_id="W1",
            worker_name="Alice",
            calculated_date="2026-01-01",
            calculated_in_time="2026-01-01T08:00:00",
            calculated_out_time="2026-01-01T17:00:00",
            shift_date="2026-01-01",
            calculated_quantity=9.0,
            status="Approved",
            is_deleted=False,
            calculation_tags=["REG"],
            last_updated="2026-01-01T18:00:00",
            worktags={"k": "v"},
            raw_data={"whatever": 1},
        )
        assert tb.time_block_id == "TB1"
        assert tb.is_deleted is False
        assert tb.calculated_quantity == 9.0

    def test_raw_data_still_required(self):
        with pytest.raises(ValidationError):
            TimeBlock()


class TestOrganizationTypeForm:
    async def test_get_cost_centers_sends_underscore_form(self):
        """REGRESSION: must send 'Cost_Center', not 'Cost Center'."""
        handler = OrganizationType(_FakeService())
        captured: dict = {}

        async def fake_paginate(operation, **kwargs):
            captured["operation"] = operation
            captured.update(kwargs)
            return []

        handler._paginate_soap_operation = fake_paginate

        await handler.get_cost_centers()

        assert captured["operation"] == "Get_Organizations"
        org_type_ref = captured["Request_Criteria"]["Organization_Type_Reference"][0]
        assert org_type_ref["ID"]["_value_1"] == "Cost_Center"
        assert org_type_ref["ID"]["_value_1"] != "Cost Center"

    async def test_execute_with_explicit_organization_type_underscore_form(self):
        """execute(organization_type=...) itself is a pure pass-through — this
        pins the payload shape the fix in get_cost_centers() now relies on."""
        handler = OrganizationType(_FakeService())
        captured: dict = {}

        async def fake_paginate(operation, **kwargs):
            captured.update(kwargs)
            return []

        handler._paginate_soap_operation = fake_paginate

        await handler.execute(organization_type="Cost_Center")

        org_type_ref = captured["Request_Criteria"]["Organization_Type_Reference"][0]
        assert org_type_ref["ID"]["type"] == "Organization_Type_ID"
        assert org_type_ref["ID"]["_value_1"] == "Cost_Center"
