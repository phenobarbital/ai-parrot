"""Tests for JSON-2 transport create-fallback detection and get_views mapping."""
from __future__ import annotations

from parrot.interfaces.odoointerface import OdooRPCError
from parrot_tools.odoo.transport.json2 import Json2Transport


def test_widened_vals_list_pattern_matches() -> None:
    exc = OdooRPCError("got an unexpected keyword argument 'vals_list'")
    assert Json2Transport._is_create_signature_error(exc) is True


def test_original_patterns_still_match() -> None:
    assert Json2Transport._is_create_signature_error(
        OdooRPCError("x.create: missing a required argument: 'vals'")
    )
    assert Json2Transport._is_create_signature_error(
        OdooRPCError("x.create: got an unexpected keyword argument 'foo'")
    )


def test_unrelated_errors_rejected() -> None:
    assert not Json2Transport._is_create_signature_error(OdooRPCError("Access denied"))
    assert not Json2Transport._is_create_signature_error(OdooRPCError("unexpected keyword argument 'foo'"))


def test_get_views_mapping() -> None:
    views = [[False, "form"], [False, "list"]]
    body = Json2Transport._build_body("get_views", [views, {"load_filters": True}], None)
    assert body == {"views": views, "options": {"load_filters": True}}
    assert Json2Transport._build_body("get_views", [views], None) == {"views": views}
