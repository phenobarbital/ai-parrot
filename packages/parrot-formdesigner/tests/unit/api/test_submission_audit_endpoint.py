"""Tests for the authenticated submission audit endpoint (FEAT-732)."""

from __future__ import annotations

import json
import uuid
from fnmatch import fnmatch
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot_formdesigner.api import setup_form_api
from parrot_formdesigner.api.handlers import READ_FORM_AUDIT, FormAPIHandler
from parrot_formdesigner.services.public_forms import public_form_paths
from parrot_formdesigner.services.rbac import PermissionRecord, RBACContext, RBACScope
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.submissions import FormSubmission, FormSubmissionStorage

_UID = uuid.UUID("33333333-3333-3333-3333-333333333333")
_OTHER_UID = uuid.UUID("44444444-4444-4444-4444-444444444444")
_TENANT = "t1"


def _request(*, form_uid: uuid.UUID = _UID, submission_id: str = "sub-1") -> MagicMock:
    """Build an authenticated request carrying a validated tenant."""
    request = MagicMock(spec=web.Request)
    request.match_info = {"form_uid": str(form_uid), "submission_id": submission_id}
    request.get = MagicMock(side_effect=lambda key, default=None: _TENANT if key == "tenant" else default)
    user = MagicMock()
    user.id = "auditor"
    user.organizations = []
    request.user = user
    request.session = {"session": {"programs": [_TENANT]}}
    return request


def _grant(scope: RBACScope) -> RBACContext:
    """Return an RBAC context holding ``read_form_audit`` at ``scope``."""
    permission = PermissionRecord(
        user_id="auditor",
        codename=READ_FORM_AUDIT,
        scope=scope,
        program_id=0,
        policy_name=f"user__auditor__{READ_FORM_AUDIT}__{scope.value}__prog0",
        tenant=_TENANT,
    )
    return RBACContext(user_id="auditor", program_id=0, permissions=[permission])


def _rbac(context: RBACContext | None = None, *, error: Exception | None = None) -> MagicMock:
    """Build an RBAC service mock that resolves or raises."""
    service = MagicMock()
    if error is not None:
        service.resolve = AsyncMock(side_effect=error)
    else:
        service.resolve = AsyncMock(
            return_value=context or RBACContext(user_id="auditor", program_id=0)
        )
    return service


def _stored(
    *,
    form_uid: uuid.UUID = _UID,
    context: dict[str, object] | None = None,
    data: dict[str, object] | None = None,
) -> FormSubmission:
    """Build a stored submission row for endpoint tests."""
    return FormSubmission(
        submission_id="sub-1",
        form_uid=form_uid,
        form_id="audit-form",
        form_version="2.0",
        data=data or {"secret": "answer"},
        is_valid=True,
        tenant=_TENANT,
        context=context,
    )


def _handler(
    *,
    rbac_service: object | None = None,
    stored: FormSubmission | None = None,
    form: object | None = None,
) -> FormAPIHandler:
    """Build a handler with mocked registry and submission storage."""
    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=form)
    storage = MagicMock(spec=FormSubmissionStorage)
    storage.get_submission = AsyncMock(return_value=stored)
    return FormAPIHandler(
        registry=registry,
        submission_storage=storage,
        rbac_service=rbac_service,
    )


class TestGate:
    """Fail-closed RBAC gate behavior."""

    @pytest.mark.asyncio
    async def test_no_permission_403(self) -> None:
        handler = _handler(rbac_service=_rbac())

        with pytest.raises(web.HTTPForbidden):
            await handler.get_submission_audit(_request())

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scope", [RBACScope.OWN, RBACScope.TEAM])
    async def test_narrow_scope_403(self, scope: RBACScope) -> None:
        handler = _handler(rbac_service=_rbac(_grant(scope)))

        with pytest.raises(web.HTTPForbidden):
            await handler.get_submission_audit(_request())

    @pytest.mark.asyncio
    async def test_no_rbac_service_403(self) -> None:
        handler = _handler()

        with pytest.raises(web.HTTPForbidden):
            await handler.get_submission_audit(_request())

    @pytest.mark.asyncio
    async def test_resolution_raises_403(self) -> None:
        handler = _handler(rbac_service=_rbac(error=RuntimeError("unavailable")))

        with pytest.raises(web.HTTPForbidden):
            await handler.get_submission_audit(_request())

    @pytest.mark.asyncio
    async def test_shadow_mode_does_not_open_it(self) -> None:
        handler = _handler(rbac_service=_rbac())
        handler.rbac_enforcing = False

        with pytest.raises(web.HTTPForbidden):
            await handler.get_submission_audit(_request())

    @pytest.mark.asyncio
    @pytest.mark.parametrize("submission_id", ["sub-1", "missing"])
    async def test_gate_precedes_lookup(self, submission_id: str) -> None:
        handler = _handler(rbac_service=_rbac(), stored=_stored())

        with pytest.raises(web.HTTPForbidden):
            await handler.get_submission_audit(_request(submission_id=submission_id))

        handler._submission_storage.get_submission.assert_not_awaited()


class TestProjection:
    """Audit projection and miss behavior."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scope", [RBACScope.CLIENT, RBACScope.GLOBAL])
    async def test_wide_scope_returns_exact_projection(self, scope: RBACScope) -> None:
        context = {
            "validation": {"trace_schema": 1},
            "llm_validation": {"status": "ok"},
            "private": "omit",
        }
        handler = _handler(rbac_service=_rbac(_grant(scope)), stored=_stored(context=context))

        response = await handler.get_submission_audit(_request())
        body = json.loads(response.body)

        assert response.status == 200
        assert body == {
            "submission_id": "sub-1",
            "form_uid": str(_UID),
            "form_version": "2.0",
            "is_valid": True,
            "validation": {"trace_schema": 1},
            "llm_validation": {"status": "ok"},
        }
        assert set(body) == {
            "submission_id",
            "form_uid",
            "form_version",
            "is_valid",
            "validation",
            "llm_validation",
        }

    @pytest.mark.asyncio
    async def test_never_returns_answers(self) -> None:
        handler = _handler(
            rbac_service=_rbac(_grant(RBACScope.CLIENT)),
            stored=_stored(data={"secret": "never return this"}),
        )

        body = json.loads((await handler.get_submission_audit(_request())).body)

        assert "data" not in body
        assert "secret" not in json.dumps(body)

    @pytest.mark.asyncio
    async def test_legacy_row_has_null_trace(self) -> None:
        handler = _handler(
            rbac_service=_rbac(_grant(RBACScope.CLIENT)),
            stored=_stored(context=None),
        )

        body = json.loads((await handler.get_submission_audit(_request())).body)

        assert body["validation"] is None
        assert body["llm_validation"] is None

    @pytest.mark.asyncio
    async def test_form_uid_mismatch_404_without_form_lookup(self) -> None:
        handler = _handler(
            rbac_service=_rbac(_grant(RBACScope.CLIENT)),
            stored=_stored(form_uid=_OTHER_UID),
        )

        response = await handler.get_submission_audit(_request())

        assert response.status == 404
        assert json.loads(response.body) == {"error": "Submission not found"}
        handler.registry.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_submission_404(self) -> None:
        plain_form = MagicMock()
        plain_form.persistence = None
        handler = _handler(
            rbac_service=_rbac(_grant(RBACScope.CLIENT)),
            form=plain_form,
        )

        response = await handler.get_submission_audit(_request(submission_id="missing"))

        assert response.status == 404
        assert json.loads(response.body) == {"error": "Submission not found"}
        handler.registry.get.assert_awaited_once_with(_UID, tenant=_TENANT)

    @pytest.mark.asyncio
    async def test_sink_persisted_form_501(self) -> None:
        sink_form = MagicMock()
        sink_form.persistence = object()
        handler = _handler(
            rbac_service=_rbac(_grant(RBACScope.CLIENT)),
            form=sink_form,
        )

        response = await handler.get_submission_audit(_request(submission_id="sink-sub"))

        assert response.status == 501
        assert json.loads(response.body) == {
            "error": (
                "Submission was written to its own persistence sink; "
                "read the audit trail from that sink's context column"
            )
        }

    @pytest.mark.asyncio
    async def test_storage_missing_503(self) -> None:
        registry = MagicMock(spec=FormRegistry)
        handler = FormAPIHandler(
            registry=registry,
            submission_storage=None,
            rbac_service=_rbac(_grant(RBACScope.CLIENT)),
        )

        response = await handler.get_submission_audit(_request())

        assert response.status == 503
        assert json.loads(response.body) == {"error": "Submission storage not configured"}
        registry.get.assert_not_called()


def test_audit_url_is_not_a_public_form_glob() -> None:
    """The nested audit URL must not inherit the public submit exemption."""
    url = f"/api/v1/{_TENANT}/forms/{_UID}/data/sub-1/audit"

    assert not any(fnmatch(url, pattern) for pattern in public_form_paths(str(_UID), _TENANT))


def test_audit_get_route_is_registered() -> None:
    """The canonical tenant-qualified audit route is registered for GET."""
    app = web.Application()
    setup_form_api(app, FormRegistry())

    routes = {(route.method, route.resource.canonical) for route in app.router.routes()}

    assert (
        "GET",
        "/api/v1/{tenant}/forms/{form_uid}/data/{submission_id}/audit",
    ) in routes
