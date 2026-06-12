"""Unit tests for FEAT-301 POST /api/v1/forms/{form_id}/evaluate endpoint.

Uses the same mocked-request pattern as tests/unit/test_api_feat300.py.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock


from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.core.constraints import (
    ConditionOperator,
    DependencyRule,
    FieldRefCondition,
    LocationVarCondition,
)
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.registry import FormRegistry


# ---------------------------------------------------------------------------
# Helpers (mirrors test_api_feat300.py pattern)
# ---------------------------------------------------------------------------

def _make_form(form_id: str = "f1", *, with_rule: bool = True) -> FormSchema:
    """Build a minimal FormSchema, optionally with a DependencyRule on q2."""
    rule = DependencyRule(
        conditions=[FieldRefCondition(field_id="q1", operator=ConditionOperator.EQ, value="yes")],
        effect="show",
    ) if with_rule else None

    return FormSchema(
        form_id=form_id,
        title={"en": "Test Form"},
        sections=[
            FormSection(
                section_id="s1",
                title={"en": "Section 1"},
                fields=[
                    FormField(field_id="q1", field_type=FieldType.TEXT, label={"en": "Q1"}),
                    FormField(
                        field_id="q2",
                        field_type=FieldType.TEXT,
                        label={"en": "Q2"},
                        depends_on=rule,
                    ),
                ],
            )
        ],
    )


def _make_request(
    *,
    form_id: str = "f1",
    body: dict | None = None,
    bad_body: bool = False,
    tenant: str = "t1",
) -> MagicMock:
    """Build a mocked aiohttp web.Request for the evaluate endpoint.

    Args:
        form_id: The form_id path parameter.
        body: Optional JSON body dict.
        bad_body: If True, simulate a JSON decode error.
        tenant: Tenant string for session programs.
    """
    from aiohttp import web

    req = MagicMock(spec=web.Request)
    req.method = "POST"
    req.match_info = {"form_id": form_id}
    session_obj = {"session": {"programs": [tenant]}}
    req.session = session_obj
    req.__contains__ = lambda self, key: False

    if bad_body:
        req.json = AsyncMock(side_effect=ValueError("bad json"))
    elif body is not None:
        req.json = AsyncMock(return_value=body)
    else:
        req.json = AsyncMock(return_value={})

    return req


def _make_handler(registry: FormRegistry | None = None, *, tenant: str = "t1") -> FormAPIHandler:
    """Build a FormAPIHandler with a minimal mock registry."""
    if registry is None:
        registry = MagicMock(spec=FormRegistry)
        registry.get = AsyncMock(return_value=None)
        registry.storage = None
        registry.default_tenant = tenant
        registry.register = AsyncMock()
    return FormAPIHandler(registry=registry)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEvaluateFormEndpoint:
    """Tests for FormAPIHandler.evaluate_form() — POST /evaluate."""

    async def test_evaluate_endpoint_200_with_match(self) -> None:
        """Valid body with matching answer → 200 + results map with effect."""
        registry = FormRegistry()
        form = _make_form()
        await registry.register(form, tenant="t1")

        handler = _make_handler(registry)
        req = _make_request(body={"answers": {"q1": "yes"}})

        resp = await handler.evaluate_form(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert "results" in body
        # q2 has depends_on → should be in results
        assert "q2" in body["results"]
        assert body["results"]["q2"]["effect"] == "show"
        assert body["results"]["q2"]["matched"] is True

    async def test_evaluate_endpoint_200_no_match(self) -> None:
        """When answer doesn't match, effect=show, matched=False."""
        registry = FormRegistry()
        form = _make_form()
        await registry.register(form, tenant="t1")

        handler = _make_handler(registry)
        req = _make_request(body={"answers": {"q1": "no"}})

        resp = await handler.evaluate_form(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["results"]["q2"]["effect"] == "show"
        assert body["results"]["q2"]["matched"] is False

    async def test_evaluate_endpoint_empty_body(self) -> None:
        """Empty body {} evaluates with empty context → 200."""
        registry = FormRegistry()
        form = _make_form()
        await registry.register(form, tenant="t1")

        handler = _make_handler(registry)
        req = _make_request(body={})

        resp = await handler.evaluate_form(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert "results" in body

    async def test_evaluate_endpoint_with_location_vars(self) -> None:
        """location_vars in body are passed to evaluator."""
        loc_rule = DependencyRule(
            conditions=[LocationVarCondition(
                source="location_variable",
                key="store_type",
                operator=ConditionOperator.EQ,
                value="flagship",
            )],
            effect="show",
        )
        form = FormSchema(
            form_id="f2",
            title={"en": "T"},
            sections=[FormSection(
                section_id="s1",
                title={"en": "S"},
                fields=[
                    FormField(field_id="q1", field_type=FieldType.TEXT, label={"en": "Q1"}),
                    FormField(
                        field_id="q2", field_type=FieldType.TEXT, label={"en": "Q2"},
                        depends_on=loc_rule,
                    ),
                ],
            )],
        )
        registry = FormRegistry()
        await registry.register(form, tenant="t1")

        handler = _make_handler(registry)
        req = _make_request(
            form_id="f2",
            body={"answers": {}, "location_vars": {"store_type": "flagship"}},
        )

        resp = await handler.evaluate_form(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["results"]["q2"]["matched"] is True

    async def test_evaluate_endpoint_form_no_rules(self) -> None:
        """Form with no DependencyRule fields → empty results dict."""
        registry = FormRegistry()
        form = _make_form(with_rule=False)
        await registry.register(form, tenant="t1")

        handler = _make_handler(registry)
        req = _make_request(body={"answers": {"q1": "yes"}})

        resp = await handler.evaluate_form(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["results"] == {}

    async def test_evaluate_endpoint_404_unknown_form(self) -> None:
        """Non-existent form_id → 404."""
        handler = _make_handler()  # registry returns None for all gets
        req = _make_request(form_id="no-such-form", body={})

        resp = await handler.evaluate_form(req)

        assert resp.status == 404
        body = json.loads(resp.body)
        assert "error" in body

    async def test_evaluate_endpoint_400_bad_json(self) -> None:
        """Malformed JSON body → 400."""
        registry = FormRegistry()
        form = _make_form()
        await registry.register(form, tenant="t1")

        handler = _make_handler(registry)
        req = _make_request(bad_body=True)

        resp = await handler.evaluate_form(req)

        assert resp.status == 400
        body = json.loads(resp.body)
        assert "error" in body

    async def test_evaluate_endpoint_400_non_dict_body(self) -> None:
        """Non-dict JSON body (e.g. a list) → 400."""
        registry = FormRegistry()
        form = _make_form()
        await registry.register(form, tenant="t1")

        handler = _make_handler(registry)
        # Simulate req.json() returning a list instead of a dict
        req = MagicMock()
        req.method = "POST"
        req.match_info = {"form_id": "f1"}
        req.session = {"session": {"programs": ["t1"]}}
        req.__contains__ = lambda self, key: False
        req.json = AsyncMock(return_value=["not", "a", "dict"])

        resp = await handler.evaluate_form(req)

        assert resp.status == 400

    async def test_evaluate_endpoint_400_non_dict_answers(self) -> None:
        """answers value that's not a dict → 400 (review M-1)."""
        registry = FormRegistry()
        form = _make_form()
        await registry.register(form, tenant="t1")

        handler = _make_handler(registry)
        req = _make_request(body={"answers": ["not", "a", "dict"]})

        resp = await handler.evaluate_form(req)

        assert resp.status == 400

    async def test_evaluate_endpoint_result_structure(self) -> None:
        """Result entries contain exactly 'effect' and 'matched' keys."""
        registry = FormRegistry()
        form = _make_form()
        await registry.register(form, tenant="t1")

        handler = _make_handler(registry)
        req = _make_request(body={"answers": {"q1": "yes"}})

        resp = await handler.evaluate_form(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        for field_id, result in body["results"].items():
            assert "effect" in result
            assert "matched" in result
            assert result["effect"] in ("show", "hide", "require", "disable")
            assert isinstance(result["matched"], bool)
