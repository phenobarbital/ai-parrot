"""FEAT-605 — the API contract doc carries every code, route and mount hook (AC21)."""
from __future__ import annotations

from pathlib import Path

import pytest

DOC = Path(__file__).resolve().parents[4] / "docs" / "agent_studio_api.md"

CODES = ["name_taken", "declarative_only", "studio_disabled", "tenant_mismatch", "authoring_denied",
         "reserved_config_key", "tenant_required", "groups_required", "groups_not_allowed",
         "tooling_not_permitted", "confirmation_required", "server_managed", "tool_scope_unavailable"]

ROUTES = ["GET /me", "/agents/{name}/visibility", "/drafts/{name}/visibility", "/skills/{id}/visibility",
          "POST /skills/resync", "POST /tools/{slug}/execute", "POST /drafts/{name}/activate",
          "PATCH /agents/{name}", "/agents/{name}/reload", "/agents/{name}/files/{kind}"]


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


@pytest.mark.parametrize("code", CODES)
def test_every_error_code_documented(code):
    assert f"`{code}`" in _text()


@pytest.mark.parametrize("route", ROUTES)
def test_route_rows_documented(route):
    assert route in _text()


def test_mount_hooks_and_me_documented():
    text = _text()
    for needle in ("setup_studio_routes", "view_wrapper", "studio_routes", "setup_registry_only",
                   "GET {prefix}/me", "may_administer", "studio_scope", "VisibilityUpdateRequest"):
        assert needle in text, needle


def test_registry_only_marked_incomplete():
    assert "incomplete lifecycle" in _text().lower()
