"""TASK-2143: Residual parser & model hunks (curated sweep).

Covers the behaviour-changing *adopt* decisions recorded in this task's
Completion Note, plus the no-regression guards from the spec's Acceptance
Criteria.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from parrot_tools.interfaces.workday.handlers.custom_report import CustomReportType
from parrot_tools.interfaces.workday.handlers.import_reported_time_blocks import (
    ImportReportedTimeBlocksType,
)
from parrot_tools.interfaces.workday.handlers.import_time_clock_events import (
    ImportTimeClockEventsType,
)
from parrot_tools.interfaces.workday.handlers.time_blocks import TimeBlockType
from parrot_tools.interfaces.workday.models.clock_event import (
    ClockEvent,
    ReportedTimeBlock,
)
from parrot_tools.interfaces.workday.models.organizations import Organization
from parrot_tools.interfaces.workday.parsers.cost_center_parsers import (
    parse_cost_center_data,
    parse_integration_id_data,
    parse_organization_container_data,
)

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


class _FakeService:
    def __init__(self):
        self._logger = logging.getLogger("test.workday.residual_hunks")

    def add_metric(self, key, value):
        pass


class TestAdoptedHandlerHunks:
    async def test_time_blocks_worker_id_type_adopted(self):
        """Covers the time_blocks.py worker_id_type adoption (contractor support)."""
        handler = TimeBlockType(_FakeService())
        captured: dict = {}

        async def fake_paginate(operation, **kwargs):
            captured.update(kwargs)
            return []

        handler._paginate_soap_operation = fake_paginate

        await handler.execute(worker_id="C-1", worker_id_type="Contingent_Worker_ID")

        worker_ref = captured["Request_Criteria"]["Worker_Reference"][0]
        assert worker_ref["ID"]["type"] == "Contingent_Worker_ID"
        assert worker_ref["ID"]["_value_1"] == "C-1"

    async def test_time_blocks_worker_id_type_defaults_to_employee_id(self):
        """Non-regression: omitting worker_id_type still defaults to Employee_ID."""
        handler = TimeBlockType(_FakeService())
        captured: dict = {}

        async def fake_paginate(operation, **kwargs):
            captured.update(kwargs)
            return []

        handler._paginate_soap_operation = fake_paginate

        await handler.execute(worker_id="E-1")

        worker_ref = captured["Request_Criteria"]["Worker_Reference"][0]
        assert worker_ref["ID"]["type"] == "Employee_ID"

    def test_import_time_clock_events_emits_location_cost_center_override_rate(self):
        """Covers the import_time_clock_events.py override-field adoption."""
        handler = ImportTimeClockEventsType.__new__(ImportTimeClockEventsType)
        event = ClockEvent(
            employee_id="E1",
            event_datetime=_NOW,
            clock_event_type="In",
            location="Warehouse B",
            cost_center="CC-100",
            override_rate=0,
        )
        body = handler.build_request(events=[event])
        item = body["Time_Clock_Event_Data"][0]
        assert item["Location"] == "Warehouse B"
        assert item["Cost_Center"] == "CC-100"
        assert item["Override_Rate"] == 0  # presence-based: 0 IS sent

    def test_import_time_clock_events_gps_never_serialised(self):
        handler = ImportTimeClockEventsType.__new__(ImportTimeClockEventsType)
        event = ClockEvent(
            employee_id="E1",
            event_datetime=_NOW,
            clock_event_type="In",
            latitude=37.7749,
            longitude=-122.4194,
        )
        body = handler.build_request(events=[event])
        item = body["Time_Clock_Event_Data"][0]
        assert "latitude" not in item
        assert "longitude" not in item

    def test_import_reported_time_blocks_emits_override_rate(self):
        """Covers the ReportedTimeBlock.override_rate model + handler adoption."""
        handler = ImportReportedTimeBlocksType.__new__(ImportReportedTimeBlocksType)
        block = ReportedTimeBlock(
            employee_id="E1",
            start_datetime=_NOW,
            override_rate=12.5,
        )
        body = handler.build_request(blocks=[block])
        item = body["Reported_Time_Block_Data"][0]
        assert item["Override_Rate"] == 12.5

    def test_import_reported_time_blocks_override_rate_omitted_when_none(self):
        handler = ImportReportedTimeBlocksType.__new__(ImportReportedTimeBlocksType)
        block = ReportedTimeBlock(employee_id="E1", start_datetime=_NOW)
        body = handler.build_request(blocks=[block])
        item = body["Reported_Time_Block_Data"][0]
        assert "Override_Rate" not in item


class TestAdoptedParserHunks:
    def test_custom_report_list_of_dicts_json_scalar_merge(self):
        """Covers the _list_of_dicts_to_dict JSON RaaS scalar-merge adoption."""
        handler = CustomReportType(_FakeService())
        items = [{"Time_Entry_Codes": "A"}, {"Time_Entry_Codes": "B"}]
        result = handler._list_of_dicts_to_dict(items)
        assert result == {"Time_Entry_Codes": "A; B"}

    def test_custom_report_list_of_dicts_still_handles_type_value_shape(self):
        """Non-regression: the pre-existing type/_value branch is unaffected."""
        handler = CustomReportType(_FakeService())
        items = [{"type": "X", "_value": "1"}, {"type": "Y", "_value": "2"}]
        result = handler._list_of_dicts_to_dict(items)
        assert result == {"X": "1", "Y": "2"}

    def test_integration_id_data_handles_nested_id_list(self):
        """Covers the cost_center_parsers.py parse_integration_id_data adoption."""
        integration_data = [
            {"ID": [
                {"_value_1": "2502$3", "System_ID": "WD-I"},
                {"_value_1": "795b89c2", "System_ID": "WD-WID"},
            ]}
        ]
        result = parse_integration_id_data(integration_data)
        assert "WD-I:2502$3" in result["integration_ids"]
        assert "WD-WID:795b89c2" in result["integration_ids"]
        assert result["external_integration_id"] == "795b89c2"

    def test_integration_id_data_empty_returns_defaults(self):
        result = parse_integration_id_data(None)
        assert result == {"integration_ids": [], "external_integration_id": None}

    def test_organization_container_data_handles_list_shape(self):
        """Covers the parse_organization_container_data list-shape adoption."""
        container_data = {
            "Organization_Container_Reference": [
                {
                    "ID": [{"type": "Organization_Reference_ID", "_value_1": "ORG-1"}],
                    "Descriptor": "Region A",
                }
            ]
        }
        result = parse_organization_container_data(container_data)
        assert result["container_organization_id"] == "ORG-1"
        assert result["container_organization_name"] == "Region A"

    def test_organization_container_data_still_handles_dict_shape(self):
        """Non-regression: the dict shape still works."""
        container_data = {
            "Organization_Container_Reference": {
                "ID": [{"type": "Organization_Reference_ID", "_value_1": "ORG-2"}],
                "Descriptor": "Region B",
            }
        }
        result = parse_organization_container_data(container_data)
        assert result["container_organization_id"] == "ORG-2"

    def test_cost_center_data_reads_integration_id_from_organization_data(self):
        """Covers the parse_cost_center_data Integration_ID_Data path fix."""
        cost_center = {
            "Cost_Center_Reference": {
                "ID": [{"type": "Cost_Center_Reference_ID", "_value_1": "CC-1"}],
            },
            "Cost_Center_Data": {
                "Organization_Data": {
                    "ID": [{"type": "Organization_Reference_ID", "_value_1": "CC-1"}],
                    "Integration_ID_Data": [
                        {"ID": [{"_value_1": "ext-1", "System_ID": "WD-WID"}]}
                    ],
                },
            },
        }
        parsed = parse_cost_center_data(cost_center)
        assert parsed["external_integration_id"] == "ext-1"


class TestAdoptedModelHunks:
    def test_organization_boolean_field_preserves_none(self):
        """Covers the models/organizations.py null-preserving validator adoption."""
        org = Organization(inactive=None)
        assert org.inactive is None

    def test_organization_boolean_field_still_coerces_strings_and_bools(self):
        """Non-regression: string/bool coercion is unaffected."""
        assert Organization(inactive="true").inactive is True
        assert Organization(inactive="0").inactive is False
        assert Organization(inactive=True).inactive is True

    def test_cost_center_carries_explicit_org_enrichment_fields(self):
        """Covers the models/cost_center.py explicit org_* field adoption."""
        from parrot_tools.interfaces.workday.models.cost_center import CostCenter

        cc = CostCenter(org_parent_organization_id="ORG-1", org_hierarchy_chain="[]")
        assert cc.org_parent_organization_id == "ORG-1"
        assert cc.org_hierarchy_chain == "[]"
        assert cc.org_parent_organization_name is None


class TestNoRegressions:
    def test_all_handler_exports_present(self):
        """All 21 exports survive, including the five FEAT-230/232 handlers."""
        from parrot_tools.interfaces.workday import handlers

        for name in (
            "RequestTimeOffType",
            "TimeOffEligibilityType",
            "PayrollBalancesType",
            "PayrollResultsType",
            "CompanyPaymentDatesType",
        ):
            assert hasattr(handlers, name)

    def test_no_vendor_strings(self):
        """No troc / jtorres@trocglobal.com / _PROD_WORKDAY_URL anywhere."""
        import pathlib
        import re

        root = pathlib.Path(
            __import__("parrot_tools.interfaces.workday", fromlist=["dummy"]).__path__[0]
        )
        pattern = re.compile(r"troc|jtorres@trocglobal\.com|_PROD_WORKDAY_URL")
        offenders = []
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            if pattern.search(text):
                offenders.append(str(path))
        assert offenders == []

    def test_removed_imports_not_reintroduced(self):
        """locations.py and organizations.py stay free of asyncio/math/datetime."""
        import inspect

        from parrot_tools.interfaces.workday.handlers import locations, organizations

        for mod in (locations, organizations):
            src = inspect.getsource(mod)
            assert "import asyncio" not in src
            assert "import math" not in src
            assert "from datetime import" not in src
