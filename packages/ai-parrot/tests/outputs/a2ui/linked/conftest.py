"""Shared fixtures for linked-surface tests (FEAT-598)."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from parrot.outputs.a2ui.linked import LinkedDataSource, ParamSpec, SourceRequest


@pytest.fixture
def activity_frame() -> pd.DataFrame:
    """Return twelve rows of date, visit, and program activity."""
    days = [dt.date(2026, 9, 1) + dt.timedelta(days=index) for index in range(12)]
    return pd.DataFrame(
        {
            "day": days,
            "visits": [10 * (index + 1) for index in range(12)],
            "program": ["epson" if index % 2 == 0 else "pokemon" for index in range(12)],
        }
    )


@pytest.fixture
def linked_source() -> LinkedDataSource:
    """Return the standard epson field-activity source descriptor."""
    return LinkedDataSource(
        slug="epson_field_activity",
        tenant=None,
        conditions={"firstdate": "YESTERDAY", "lastdate": "TODAY"},
        request=SourceRequest(placeholders={"firstdate": "YESTERDAY", "lastdate": "TODAY"}),
        params={
            "firstdate": ParamSpec(type="date", accepts_keywords=True),
            "lastdate": ParamSpec(type="date", accepts_keywords=True),
        },
        target="/activity/rows",
    )
