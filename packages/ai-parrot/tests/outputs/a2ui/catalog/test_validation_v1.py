"""Tests for v1.0 catalog validation (FEAT-470 TASK-2535)."""

from __future__ import annotations

import jsonschema
import pytest
from parrot.outputs.a2ui.catalog import (
    DEFAULT_CATALOG_ID,
    ProducerOrigin,
    catalog_instructions,
    register_component,
    resolve_catalog,
    unregister_component,
    validate_envelope,
    validate_message,
)
from parrot.outputs.a2ui.catalog.base import (
    ACTION_NOT_ALLOWED_FOR_LLM,
    CATALOG_UNRESOLVED,
    DANGLING_CHILD,
    DUPLICATE_ID,
    MISSING_ROOT,
    UNALLOWED_CHILD,
    UNALLOWED_PARENT,
    CatalogValidationError,
)
from parrot.outputs.a2ui.catalog.basic import BASIC_CATALOG_ID
from parrot.outputs.a2ui.models import A2UIAgentMessage, Component, CreateSurface


@pytest.fixture
def cleanup_catalog():
    registered: list[str] = []
    yield registered
    for name in registered:
        unregister_component(name)


def _root_surface(*components: Component) -> CreateSurface:
    """Build a CreateSurface whose first component is treated as ``root``."""
    return CreateSurface(
        surfaceId="main", catalogId=DEFAULT_CATALOG_ID, components=list(components)
    )


class TestValidateMessageAgentToRenderer:
    def test_validate_message_agent_to_renderer(self):
        """A well-formed createSurface envelope validates against the real schema."""
        msg = A2UIAgentMessage(
            version="v1.0",
            createSurface={
                "surfaceId": "main",
                "catalogId": BASIC_CATALOG_ID,
                "components": [{"id": "root", "component": "Text", "text": "hi"}],
            },
        )
        validate_message(msg)  # must not raise

    def test_validate_message_reports_path_on_failure(self):
        msg_dict = {
            "version": "v1.0",
            "createSurface": {"surfaceId": "s", "components": []},
        }
        with pytest.raises(jsonschema.exceptions.ValidationError):
            validate_message(A2UIAgentMessage.model_validate(msg_dict))


class TestResolveCatalogPrecedence:
    def test_resolve_catalog_precedence(self):
        assert resolve_catalog("component-cat", "surface-cat") == "component-cat"
        assert resolve_catalog(None, "surface-cat") == "surface-cat"

    def test_resolve_catalog_unresolved(self):
        with pytest.raises(CatalogValidationError) as exc:
            resolve_catalog(None, None)
        assert exc.value.code == CATALOG_UNRESOLVED


class TestValidateRootRequiredAndUniqueIds:
    def test_missing_root_raises(self):
        surface = _root_surface(Component(id="x", component="Text", text="hi"))
        with pytest.raises(CatalogValidationError) as exc:
            validate_envelope(surface)
        assert MISSING_ROOT in {i["code"] for i in exc.value.issues}

    def test_duplicate_id_raises(self):
        surface = _root_surface(
            Component(id="root", component="Text", text="a"),
            Component(id="root", component="Text", text="b"),
        )
        with pytest.raises(CatalogValidationError) as exc:
            validate_envelope(surface)
        assert DUPLICATE_ID in {i["code"] for i in exc.value.issues}

    def test_valid_root_and_unique_ids_pass(self):
        surface = _root_surface(Component(id="root", component="Text", text="hi"))
        validate_envelope(surface)  # must not raise


class TestDanglingChildReported:
    def test_dangling_child_reported(self):
        surface = _root_surface(
            Component(id="root", component="Column", children=["ghost"])
        )
        with pytest.raises(CatalogValidationError) as exc:
            validate_envelope(surface)
        assert DANGLING_CHILD in {i["code"] for i in exc.value.issues}

    def test_dangling_child_template_reported(self):
        surface = _root_surface(
            Component(
                id="root",
                component="List",
                children={"componentId": "ghost-template", "path": "/items"},
            )
        )
        with pytest.raises(CatalogValidationError) as exc:
            validate_envelope(surface)
        assert DANGLING_CHILD in {i["code"] for i in exc.value.issues}


class TestUnallowedParentChildCodes:
    def test_unallowed_parent_child_codes(self, cleanup_catalog):
        @register_component("StrictParent", allowed_children=["Text"])
        class StrictParent:
            def lower(self, component, data_model):
                return None

        @register_component("PickyChild", allowed_parents=["Column"])
        class PickyChild:
            def lower(self, component, data_model):
                return None

        cleanup_catalog += ["StrictParent", "PickyChild"]

        surface = _root_surface(
            Component(id="root", component="StrictParent", children=["kid"]),
            Component(id="kid", component="PickyChild"),
        )
        with pytest.raises(CatalogValidationError) as exc:
            validate_envelope(surface)
        codes = {i["code"] for i in exc.value.issues}
        assert UNALLOWED_CHILD in codes
        assert UNALLOWED_PARENT in codes


class TestLlmOriginRejectsAction:
    def test_llm_origin_rejects_action(self):
        surface = _root_surface(
            Component(
                id="root",
                component="Button",
                child="lbl",
                action={"event": {"name": "submit"}},
            ),
            Component(id="lbl", component="Text", text="Go"),
        )
        with pytest.raises(CatalogValidationError) as exc:
            validate_envelope(surface, origin=ProducerOrigin.LLM)
        assert ACTION_NOT_ALLOWED_FOR_LLM in {i["code"] for i in exc.value.issues}

    def test_tool_origin_allows_action(self):
        surface = _root_surface(
            Component(
                id="root",
                component="Button",
                child="lbl",
                action={"event": {"name": "submit"}},
            ),
            Component(id="lbl", component="Text", text="Go"),
        )
        validate_envelope(surface, origin=ProducerOrigin.TOOL)  # must not raise


class TestAllErrorsReportedAtOnce:
    def test_all_errors_reported_at_once(self):
        """MISSING_ROOT + DANGLING_CHILD + DUPLICATE_ID all surface together."""
        surface = _root_surface(
            Component(id="x", component="Column", children=["ghost"]),
            Component(id="x", component="Text", text="dup"),
        )
        with pytest.raises(CatalogValidationError) as exc:
            validate_envelope(surface)
        codes = {i["code"] for i in exc.value.issues}
        assert MISSING_ROOT in codes
        assert DANGLING_CHILD in codes
        assert DUPLICATE_ID in codes


class TestCatalogInstructionsNoRstripBug:
    def test_catalog_instructions_no_rstrip_bug(self, cleanup_catalog):
        @register_component("TrailingColon")
        class TrailingColon:
            INSTRUCTIONS = "Always end with a colon:"

            def lower(self, component, data_model):
                return None

        cleanup_catalog.append("TrailingColon")
        assert "TrailingColon: Always end with a colon:" in catalog_instructions()
