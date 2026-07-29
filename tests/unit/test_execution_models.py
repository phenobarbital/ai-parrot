"""Unit tests for the saved-execution Pydantic models (FEAT-307)."""
from datetime import datetime


class TestExecutionModels:
    def test_execution_filter_defaults(self):
        from parrot.handlers.crew.models import ExecutionFilter

        f = ExecutionFilter()
        assert f.crew_name is None
        assert f.method is None

    def test_execution_summary_required_fields(self):
        from parrot.handlers.crew.models import ExecutionSummary

        s = ExecutionSummary(
            id="abc", crew_name="test", method="run_sequential", timestamp=datetime.now()
        )
        assert s.tenant == "global"
        assert s.status == "success"

    def test_execution_detail_inherits_summary(self):
        from parrot.handlers.crew.models import ExecutionDetail

        d = ExecutionDetail(
            id="abc", crew_name="test", method="run", timestamp=datetime.now()
        )
        assert d.payload == {}

    def test_schedule_request_required_fields(self):
        from parrot.handlers.crew.models import ScheduleRequest

        s = ScheduleRequest(schedule_type="DAILY", schedule_config={"hour": 9})
        assert s.schedule_type == "DAILY"

    def test_paginated_response(self):
        from parrot.handlers.crew.models import PaginatedResponse

        p = PaginatedResponse(items=[], total=0, limit=20, offset=0)
        assert p.total == 0
