"""fetch_models: rehydrate JSON-flattened DataFrame columns before model validation."""
import json
import logging
from typing import Any, Dict, List, Optional

import pandas as pd
import pytest
from pydantic import BaseModel

from parrot_tools.interfaces.workday import service as service_mod
from parrot_tools.interfaces.workday.service import WorkdayService, _record_to_model_kwargs


class _Row(BaseModel):
    worker_id: str
    note: Optional[str] = None
    organizations: Optional[List[Dict[str, Any]]] = None
    compensation_summary: Optional[Dict[str, Any]] = None
    position_organizations: List[Dict[str, Any]] = []
    hours: Optional[float] = None


def test_json_strings_are_decoded_for_non_str_fields():
    kwargs = _record_to_model_kwargs(
        _Row,
        {
            "worker_id": "T0000005001147",
            "organizations": json.dumps([{"organization_id": "SO100074"}]),
            "compensation_summary": json.dumps({"grade": "E80"}),
        },
    )
    row = _Row(**kwargs)
    assert row.organizations == [{"organization_id": "SO100074"}]
    assert row.compensation_summary == {"grade": "E80"}


def test_empty_strings_fall_back_to_field_defaults():
    row = _Row(**_record_to_model_kwargs(_Row, {"worker_id": "1", "organizations": "", "position_organizations": ""}))
    assert row.organizations is None
    assert row.position_organizations == []


def test_str_fields_are_untouched():
    kwargs = _record_to_model_kwargs(_Row, {"worker_id": "[1]", "note": "{not json"})
    assert kwargs == {"worker_id": "[1]", "note": "{not json"}


def test_nan_becomes_none():
    assert _record_to_model_kwargs(_Row, {"worker_id": "1", "hours": float("nan")})["hours"] is None


def test_invalid_json_is_left_for_validation():
    assert _record_to_model_kwargs(_Row, {"worker_id": "1", "organizations": "[broken"})["organizations"] == "[broken"


@pytest.mark.asyncio
async def test_fetch_models_builds_models_from_flattened_rows(monkeypatch):
    svc = WorkdayService.__new__(WorkdayService)
    svc._logger = logging.getLogger("test.workday.fetch_models")
    df = pd.DataFrame(
        [{"worker_id": "T0000005001147", "organizations": json.dumps([{"organization_id": "SO100074"}]), "hours": None}]
    )

    async def fake_fetch(operation_type, **params):
        return df

    monkeypatch.setattr(svc, "fetch", fake_fetch)
    monkeypatch.setitem(service_mod._OPERATION_MODEL_MAP, "get_rows", _Row)

    models = await svc.fetch_models("get_rows")

    assert len(models) == 1
    assert models[0].organizations == [{"organization_id": "SO100074"}]
