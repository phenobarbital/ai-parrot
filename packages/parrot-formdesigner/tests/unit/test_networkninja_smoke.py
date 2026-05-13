"""Smoke tests for NetworkninjaFormService — minimal coverage at this checkpoint.

Full mapping test relocation happens in TASK-1130.
"""

import json

import pytest

from parrot_formdesigner.tools.services.networkninja import NetworkninjaFormService
from parrot_formdesigner.core.schema import FormSchema


def test_instantiable() -> None:
    """Service can be instantiated with an explicit DSN."""
    svc = NetworkninjaFormService(dsn="postgres://fake/db")
    assert svc is not None


def test_to_form_schema_returns_form_schema_for_empty_blocks() -> None:
    """to_form_schema produces a FormSchema even with zero question_blocks."""
    svc = NetworkninjaFormService(dsn="postgres://fake/db")
    row = {
        "formid": 1,
        "form_name": "Empty",
        "description": None,
        "client_id": 1,
        "client_name": "C",
        "orgid": 1,
        "question_blocks": json.dumps([]),
        "metadata": [],
    }
    form = svc.to_form_schema(row)
    assert isinstance(form, FormSchema)
    assert form.form_id == "db-form-1-1"
    assert form.sections == []


def test_get_dsn_prefers_constructor_arg(monkeypatch: pytest.MonkeyPatch) -> None:
    """Constructor dsn= takes priority over env var."""
    monkeypatch.delenv("PARROT_NETWORKNINJA_DSN", raising=False)
    svc = NetworkninjaFormService(dsn="postgres://explicit")
    assert svc._get_dsn() == "postgres://explicit"


def test_get_dsn_uses_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """PARROT_NETWORKNINJA_DSN env var is used when no constructor arg is given."""
    monkeypatch.setenv("PARROT_NETWORKNINJA_DSN", "postgres://from-env")
    svc = NetworkninjaFormService()
    assert svc._get_dsn() == "postgres://from-env"
