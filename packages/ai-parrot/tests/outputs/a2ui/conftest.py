"""Shared fixtures for the ``tests/outputs/a2ui`` suite (FEAT-469 TASK-2576).

Consolidates ``v1_schemas`` so both the unit suites (``runtime/``,
``catalog/``) and this task's new conformance sweep share one definition,
per the task's own scope: "Shared fixtures (v1_schemas, memory_store,
a2ui_call_ctx) consolidated so unit and integration suites share one
definition."
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def v1_schemas() -> dict:
    """The four vendored A2UI v1.0 JSON Schemas, keyed by their ``load_spec`` name."""
    from parrot.outputs.a2ui.catalog.basic import load_spec

    return {
        name: load_spec(name)
        for name in ("agent_to_renderer", "renderer_to_agent", "agent_capabilities", "catalog_definition")
    }
