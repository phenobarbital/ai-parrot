"""Importing ``parrot_tools.workday`` must not emit Pydantic V1-style deprecations.

Downstream projects run their suites with warnings turned into errors; a
``PydanticDeprecatedSince20`` raised at import time (V1 ``@validator`` or a
class-based ``Config``) breaks their test collection.
"""
import subprocess
import sys
import textwrap
from datetime import date, datetime, timezone
from decimal import Decimal


def test_import_emits_no_pydantic_deprecation():
    """A fresh interpreter imports the package with the warning escalated."""
    code = textwrap.dedent(
        """
        import warnings
        from pydantic.warnings import PydanticDeprecatedSince20

        warnings.simplefilter("error", PydanticDeprecatedSince20)
        import parrot_tools.workday  # noqa: F401
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    assert "PydanticDeprecatedSince20" not in result.stderr


def test_before_validators_still_coerce_inputs():
    """The migrated ``mode="before"`` validators keep their V1 ``pre=True`` behavior."""
    from parrot_tools.interfaces.workday.models import CostCenter, TimeOffBalance
    from parrot_tools.interfaces.workday.models.job_posting import JobPosting

    balance = TimeOffBalance(
        worker_id="1",
        time_off_plan_name="Vacation",
        balance=Decimal("1.5"),
    )
    assert balance.balance == 1.5
    assert isinstance(balance.balance, float)

    posting = JobPosting(
        job_posting_id="jp-1",
        is_posted="Yes",
        number_of_openings="3.0",
        integration_ids="only-one",
        posting_date=date(2025, 1, 2),
    )
    assert posting.is_posted is True
    assert posting.number_of_openings == 3
    assert posting.integration_ids == ["only-one"]
    assert posting.posting_date == "2025-01-02"

    center = CostCenter(
        cost_center_id="cc-1",
        cost_center_name="CC",
        inactive="1",
        worktags=None,
        effective_date=datetime(2025, 1, 2, 3, 4, 5),
    )
    assert center.inactive is True
    assert center.worktags == []
    assert center.effective_date == "2025-01-02T03:04:05"
    # extra="allow" survived the ConfigDict migration
    assert CostCenter(cost_center_id="x", cost_center_name="y", foo=1).foo == 1


def test_crew_definition_timestamps_keep_isoformat_json():
    """``CrewDefinition`` timestamps keep ``isoformat()`` output (``+00:00``, not ``Z``)."""
    from parrot.models.crew_definition import CrewDefinition

    when = datetime(2025, 1, 2, 3, 4, 5, 6, tzinfo=timezone.utc)
    crew = CrewDefinition(name="x", agents=[], created_at=when, updated_at=when)
    dumped = crew.model_dump(mode="json")
    assert dumped["created_at"] == "2025-01-02T03:04:05.000006+00:00"
    assert dumped["updated_at"] == "2025-01-02T03:04:05.000006+00:00"
    # Python mode is untouched: the datetime object itself.
    assert crew.model_dump()["created_at"] == when
