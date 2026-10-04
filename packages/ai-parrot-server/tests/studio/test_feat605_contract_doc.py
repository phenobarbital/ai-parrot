"""FEAT-605 — the API contract doc carries every code, route and mount hook (AC21)."""
from __future__ import annotations

from pathlib import Path

import pytest

DOC = Path(__file__).resolve().parents[4] / "docs" / "agent_studio_api.md"

CODES = ["name_taken", "declarative_only", "studio_disabled", "tenant_mismatch", "authoring_denied",
         "reserved_config_key", "tenant_required", "groups_required", "groups_not_allowed", "not_manageable",
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


def test_registry_only_no_longer_marked_incomplete():
    assert "incomplete lifecycle" not in _text().lower()


ROOT = DOC.parents[1]
SPECS = ["agentstudio-db-storage", "agentstudio-tenant-visibility", "agentstudio-host-toolkits"]
HEADING = "## Cross-spec contract (package)"


def _contract(spec: str) -> str:
    text = (ROOT / "sdd" / "specs" / f"{spec}.spec.md").read_text(encoding="utf-8")
    start = text.index(HEADING)
    end = text.find("\n## ", start + len(HEADING))
    return text[start:end if end != -1 else len(text)]


def test_cross_spec_contract_identical_in_the_three_specs():
    assert _contract(SPECS[0]) == _contract(SPECS[1]) == _contract(SPECS[2])


@pytest.mark.parametrize("spec", SPECS)
def test_x14_lists_the_new_codes(spec):
    contract = _contract(spec)
    assert "`groups_not_allowed` 422" in contract and "`not_manageable` 403" in contract


@pytest.mark.parametrize("spec", SPECS)
def test_required_schema_version_is_eight(spec):
    assert "required versions 1..8 for the `database` backend" in _contract(spec)
    assert "1..5" not in _contract(spec)


def test_storage_spec_states_required_eight():
    text = (ROOT / "sdd" / "specs" / "agentstudio-db-storage.spec.md").read_text(encoding="utf-8")
    assert "STUDIO_SCHEMA_REQUIRED = 8" in text and "STUDIO_SCHEMA_REQUIRED stays 5" not in text


def test_doc_error_table_has_no_open_question_and_documents_behaviour_changes():
    text = _text()
    assert "open question" not in text.lower()
    for needle in ("`not_manageable` | 403", "`groups_not_allowed` | 422", "`name_taken` (409) on agents",
                   "(+ `version` for a Studio agent)", "docs/agentstudio/db-storage.md", "host-toolkits.md"):
        assert needle in text.replace("`name_taken` (409)\non agents", "`name_taken` (409) on agents"), needle


def test_changelog_lists_the_plain_host_behaviour_changes():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = text[text.index("## [Unreleased]"):text.index("\n## [", text.index("## [Unreleased]") + 5)]
    for needle in ("name_taken", "not_manageable", "PATCH /astudio/agents/{name}/visibility", "`version`",
                   "required migration level is 8"):
        assert needle in unreleased, needle
