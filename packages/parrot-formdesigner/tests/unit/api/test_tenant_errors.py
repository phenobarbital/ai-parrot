"""Unit tests for typed tenant error responses (FEAT-421 TASK-2198)."""

import json

import pytest
from aiohttp import web
from parrot_formdesigner.api.errors import (
    TenantConflictError,
    TenantForbiddenError,
    TenantNotDeclaredError,
)


class TestTenantErrors:
    """Status code, content-type, and body-shape assertions."""

    def test_not_declared_is_400(self):
        exc = TenantNotDeclaredError(expected="/api/v1/t/{tenant}/forms")
        assert exc.status == 400
        assert exc.content_type == "application/json"
        body = json.loads(exc.text)
        assert body["error"] == "tenant_not_declared"
        assert body["expected"] == "/api/v1/t/{tenant}/forms"
        assert "message" in body

    def test_not_declared_without_expected(self):
        exc = TenantNotDeclaredError()
        body = json.loads(exc.text)
        assert body["error"] == "tenant_not_declared"
        assert "expected" not in body

    def test_forbidden_is_403(self):
        exc = TenantForbiddenError()
        assert exc.status == 403
        assert exc.content_type == "application/json"
        body = json.loads(exc.text)
        assert body["error"] == "tenant_forbidden"
        assert "message" in body

    def test_conflict_is_400(self):
        exc = TenantConflictError()
        assert exc.status == 400
        assert exc.content_type == "application/json"
        body = json.loads(exc.text)
        assert body["error"] == "tenant_conflict"
        assert "message" in body

    def test_all_are_raisable_http_exceptions(self):
        for cls in (TenantNotDeclaredError, TenantForbiddenError, TenantConflictError):
            assert issubclass(cls, web.HTTPException)
            with pytest.raises(cls):
                raise cls()
