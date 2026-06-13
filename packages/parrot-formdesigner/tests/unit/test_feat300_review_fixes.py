"""Regression tests for the FEAT-300 code-review fixes (C1, C2, H1–H5, M1–M3).

Each test class maps to one finding from the pre-merge review:

- C1 — SQL injection guard on QuestionBankService identifiers.
- C2 — DELETE /forms/{id} blocked (409) when the form has responses.
- H1 — version history survives a process restart (storage reconstruction).
- H3 — storage failures during publish propagate (no silent in-memory fallback).
- H4 — concurrent-publish unique violation surfaces as ValueError.
- H5 — safe_delete uses the public registry API.
- M1 — PUT/PATCH cannot clobber published_version.
- M2 — formula placeholder HTML-escapes field_id and title.
- M5 — backfill propagates storage errors instead of reporting changed=0.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from parrot_formdesigner.core.schema import FormField, FormSchema
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.html5 import HTML5Renderer
from parrot_formdesigner.services.form_version import FormVersionService
from parrot_formdesigner.services.question_bank import QuestionBankService
from parrot_formdesigner.services.registry import FormRegistry, FormStorage

from tests.unit.test_api_feat300 import _make_form, _make_handler, _make_request


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class InMemoryStorage(FormStorage):
    """Dict-backed FormStorage honoring UNIQUE(form_id, version)."""

    def __init__(self) -> None:
        # (tenant, form_id) → {version: FormSchema}; insertion order = save order
        self._rows: dict[tuple[str, str], dict[str, FormSchema]] = {}

    async def save(self, form: FormSchema, style=None, *, tenant=None) -> str:
        versions = self._rows.setdefault((tenant, form.form_id), {})
        if form.version in versions:
            raise RuntimeError(
                'duplicate key value violates unique constraint "form_schemas_form_id_version_key"'
            )
        versions[form.version] = form.model_copy(deep=True)
        return form.form_id

    async def load(self, form_id, version=None, *, tenant=None):
        versions = self._rows.get((tenant, form_id), {})
        if not versions:
            return None
        if version is not None:
            snap = versions.get(version)
            return snap.model_copy(deep=True) if snap else None
        latest = list(versions.values())[-1]
        return latest.model_copy(deep=True)

    async def delete(self, form_id, *, tenant=None) -> bool:
        return self._rows.pop((tenant, form_id), None) is not None

    async def list_forms(self, *, tenant=None) -> list[dict[str, Any]]:
        return [
            {"form_id": fid, "version": list(v.keys())[-1], "tenant": t}
            for (t, fid), v in self._rows.items()
            if t == tenant
        ]


class FailingStorage(InMemoryStorage):
    """Storage whose save/list always fail — simulates an unreachable DB."""

    async def save(self, form, style=None, *, tenant=None) -> str:
        raise ConnectionError("database unreachable")

    async def list_forms(self, *, tenant=None):
        raise ConnectionError("database unreachable")


async def _registry_with_form(form_id: str = "f1", tenant: str = "t1") -> FormRegistry:
    registry = FormRegistry()
    await registry.register(_make_form(form_id, tenant), tenant=tenant)
    return registry


# ---------------------------------------------------------------------------
# C1 — SQL injection guard
# ---------------------------------------------------------------------------


class TestC1IdentifierValidation:
    def test_malicious_tenant_rejected(self):
        with pytest.raises(ValueError, match="Invalid tenant"):
            QuestionBankService(None, tenant='public"; DROP TABLE epson.field_bank; --')

    def test_malicious_table_rejected(self):
        with pytest.raises(ValueError, match="Invalid table"):
            QuestionBankService(None, tenant="t1", table="field_bank; DROP TABLE x")

    def test_valid_identifiers_quoted(self):
        svc = QuestionBankService(None, tenant="t1", table="field_bank")
        assert svc._qualified == '"t1"."field_bank"'


# ---------------------------------------------------------------------------
# C2 — delete_form blocked when responses exist
# ---------------------------------------------------------------------------


class TestC2DeleteGuard:
    async def test_delete_blocked_with_responses(self):
        registry = await _registry_with_form()

        async def has_responses(form_id: str, tenant: str) -> bool:
            return True

        handler = _make_handler(registry)
        handler._version_service = FormVersionService(
            registry, has_responses=has_responses
        )

        resp = await handler.delete_form(_make_request(method="DELETE", form_id="f1"))
        assert resp.status == 409
        assert await registry.get("f1", tenant="t1") is not None  # untouched

    async def test_delete_allowed_without_responses(self):
        registry = await _registry_with_form()

        async def has_responses(form_id: str, tenant: str) -> bool:
            return False

        handler = _make_handler(registry)
        handler._version_service = FormVersionService(
            registry, has_responses=has_responses
        )

        resp = await handler.delete_form(_make_request(method="DELETE", form_id="f1"))
        assert resp.status == 204


# ---------------------------------------------------------------------------
# H1 — version history survives restart
# ---------------------------------------------------------------------------


class TestH1HistorySurvivesRestart:
    async def test_list_versions_reconstructed_from_storage(self):
        storage = InMemoryStorage()
        registry = await _registry_with_form()
        svc = FormVersionService(registry, storage=storage)

        v1 = await svc.publish("f1", tenant="t1")  # 1.1
        v2 = await svc.publish("f1", tenant="t1")  # 1.2

        # Simulate process restart: fresh service, same storage, empty _meta
        registry2 = await _registry_with_form()
        svc2 = FormVersionService(registry2, storage=storage)

        versions = [m.version for m in await svc2.list_versions("f1", tenant="t1")]
        assert versions == [v1, v2]

    async def test_published_at_recovered_from_stamp(self):
        storage = InMemoryStorage()
        registry = await _registry_with_form()
        svc = FormVersionService(registry, storage=storage)
        await svc.publish("f1", tenant="t1")

        svc2 = FormVersionService(FormRegistry(), storage=storage)
        metas = await svc2.list_versions("f1", tenant="t1")
        assert metas and metas[0].published_at is not None


# ---------------------------------------------------------------------------
# H3 / H4 — storage failures during publish
# ---------------------------------------------------------------------------


class TestH3H4PublishStorageFailures:
    async def test_storage_failure_propagates(self):
        """H3: a publish that cannot persist must NOT report success."""
        registry = await _registry_with_form()
        svc = FormVersionService(registry, storage=FailingStorage())

        with pytest.raises(ConnectionError):
            await svc.publish("f1", tenant="t1")

    async def test_unique_violation_surfaces_as_frozen_error(self):
        """H4: the DB unique constraint is the atomic immutability guard."""
        storage = InMemoryStorage()
        registry = await _registry_with_form()
        svc = FormVersionService(registry, storage=storage)
        await svc.publish("f1", tenant="t1")  # creates 1.1

        # Simulate the TOCTOU race: a second writer saved 1.2 between the
        # fast-path check and save() — seed 1.2 directly, then reset the
        # live form version so publish() recomputes 1.2 (stale read).
        live = await registry.get("f1", tenant="t1")
        stale = live.model_copy(deep=True, update={"version": "1.1"})
        racing = stale.model_copy(
            deep=True, update={"version": "1.2", "published_version": "1.2"}
        )
        # bypass published_version check in get_published (no stamp → still frozen row)
        storage._rows[("t1", "f1")]["1.2"] = racing.model_copy(
            deep=True, update={"published_version": None}
        )
        await registry.register(stale, overwrite=True, tenant="t1")

        with pytest.raises(ValueError, match="already exists and is frozen"):
            await svc.publish("f1", tenant="t1")


# ---------------------------------------------------------------------------
# H5 — safe_delete via public registry API
# ---------------------------------------------------------------------------


class TestH5PublicRegistryApi:
    async def test_safe_delete_unregisters_via_public_api(self):
        registry = await _registry_with_form()
        svc = FormVersionService(registry)

        await svc.safe_delete("f1", tenant="t1")
        assert await registry.get("f1", tenant="t1") is None


# ---------------------------------------------------------------------------
# M1 — published_version immutable through PUT/PATCH
# ---------------------------------------------------------------------------


class TestM1PublishedVersionImmutable:
    async def _published_handler(self):
        registry = FormRegistry()
        form = _make_form().model_copy(
            deep=True, update={"published_version": "1.0"}
        )
        await registry.register(form, tenant="t1")
        return _make_handler(registry), registry

    async def test_put_cannot_clear_published_version(self):
        handler, registry = await self._published_handler()
        body = _make_form().model_dump(mode="json")
        body["published_version"] = None  # attempted unfreeze

        resp = await handler.update_form(
            _make_request(method="PUT", form_id="f1", body=body)
        )
        assert resp.status == 200
        assert json.loads(resp.body)["published_version"] == "1.0"

    async def test_patch_cannot_clear_published_version(self):
        handler, registry = await self._published_handler()

        resp = await handler.patch_form(
            _make_request(
                method="PATCH", form_id="f1", body={"published_version": None}
            )
        )
        assert resp.status == 200
        assert json.loads(resp.body)["published_version"] == "1.0"


# ---------------------------------------------------------------------------
# M2 — formula placeholder escapes HTML
# ---------------------------------------------------------------------------


class TestM2FormulaEscaping:
    def test_field_id_and_expression_escaped(self):
        field = FormField(
            field_id='x" onmouseover="alert(1)',
            field_type=FieldType.FORMULA,
            label="XSS",
            meta={"expression": '"><script>alert(1)</script>'},
        )
        html_out = HTML5Renderer()._render_formula_placeholder(field)
        assert "<script>" not in html_out
        assert 'onmouseover="alert' not in html_out
        assert "&quot;" in html_out or "&gt;" in html_out


# ---------------------------------------------------------------------------
# M5 — backfill propagates storage errors
# ---------------------------------------------------------------------------


class TestM5BackfillStorageErrors:
    async def test_backfill_raises_when_storage_unreachable(self):
        registry = FormRegistry()  # nothing in-memory to backfill
        svc = FormVersionService(registry, storage=FailingStorage())

        with pytest.raises(ConnectionError):
            await svc.backfill_published(tenant="t1")
