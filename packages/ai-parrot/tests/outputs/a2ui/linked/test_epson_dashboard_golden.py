"""FEAT-611 M8 — Epson dashboard TOOL: golden equality, TOOL validation, unauthorized blocked before rows."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

import parrot.outputs.a2ui.linked as linked_pkg
import parrot.tools.dataset_manager.sources.query_slug as query_slug
from parrot.auth.exceptions import AuthorizationRequired
from parrot.auth.permission import build_principal_context
from parrot.outputs.a2ui.catalog import ProducerOrigin, validate_envelope
from parrot.outputs.a2ui.linked.dsl import frame_from_records
from parrot.outputs.a2ui.models import CreateSurface

pytestmark = pytest.mark.asyncio
REPO = Path(__file__).resolve().parents[6]
TOOL_PATH = REPO / "examples/agents/a2ui/linked_e2e/dashboard_tool.py"
FIXTURES = Path(linked_pkg.__file__).parent / "contract" / "fixtures"
GOLDEN = FIXTURES / "envelopes" / "linked_epson_dashboard.json"
PARITY = json.loads((FIXTURES / "parity" / "epson_dashboard_params.json").read_text())
FIXED_SNAPSHOT_AT = "2026-09-25T00:00:00Z"


def _load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_epson_dashboard_tool", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _FakeGuard:
    """Records authorize_source calls; denies the (source_type, source_id) pairs in `deny` (test_service.py pattern)."""

    def __init__(self, deny: set[str] | None = None) -> None:
        self.deny = deny or set()
        self.calls: list[tuple[Any, Any]] = []

    async def authorize_source(self, ctx: Any, resources: Any) -> None:
        self.calls.append((ctx, resources))
        key = f"{resources.source_type}:{resources.source_id}"
        if key in self.deny:
            raise AuthorizationRequired(tool_name="dataplane_authz", message="denied")


@pytest.fixture
def fake_qs(monkeypatch):
    """Slug-keyed FakeQS (test_linked_surfaces_e2e.py:202-233 pattern) over the parity input frames."""
    state = SimpleNamespace(executions=0, kwargs=[])

    class FakeQS:
        def __init__(self, **kwargs):
            state.kwargs.append(kwargs)
            self._slug = kwargs["slug"]

        async def query(self, output_format=None):
            state.executions += 1
            return frame_from_records(PARITY["input_frames"][self._slug]), None

        async def close(self):
            return None

    monkeypatch.setattr(query_slug, "_get_qs", lambda: FakeQS)
    return state


def _normalized(result: dict) -> dict:
    envelope = json.loads(json.dumps(result["a2ui_envelope"]))
    for source in envelope["metadata"]["extensions"]["parrot_data_sources"].values():
        source["snapshot_at"] = FIXED_SNAPSHOT_AT
    return envelope


def _dump(envelope: dict) -> str:
    return json.dumps(envelope, sort_keys=True, indent=2) + "\n"  # same format as test_contract_envelopes._dump


async def test_epson_dashboard_golden(fake_qs):
    tool = _load_tool()
    result = await tool.build_epson_activity_dashboard("2026-09-01", "2026-09-07")
    actual = _dump(_normalized(result))
    if os.environ.get("PARROT_REGEN_GOLDEN") == "1":
        GOLDEN.write_text(actual)
    assert GOLDEN.read_text() == actual
    validate_envelope(CreateSurface.model_validate(result["a2ui_envelope"]), origin=ProducerOrigin.TOOL)
    assert result["artifacts"][0]["type"] == "a2ui_linked_surface"
    assert fake_qs.executions == 4
    assert all(kwargs["conditions"]["querylimit"] == 5000 for kwargs in fake_qs.kwargs)


async def test_dashboard_tool_unauthorized_blocked(fake_qs):
    """Guard denies epson_field_activity → AuthorizationRequired, and QS is never executed (§9 S4)."""
    tool = _load_tool()
    guard = _FakeGuard(deny={"query_slug:public:epson_field_activity"})
    pctx = build_principal_context("owner-1", channel="ui_surfaces")
    with pytest.raises(AuthorizationRequired):
        await tool.build_epson_activity_dashboard(pctx=pctx, guard=guard)
    assert fake_qs.executions == 0
    assert fake_qs.kwargs == []
    assert [r.source_id for _, r in guard.calls] == ["public:epson_program_targets", "public:epson_field_activity"]


async def test_dashboard_tool_guard_without_pctx_fails_closed(fake_qs):
    """A guard with pctx=None would fail OPEN in AuthorizingDataSource — the TOOL refuses before any fetch."""
    tool = _load_tool()
    guard = _FakeGuard()
    with pytest.raises(AuthorizationRequired):
        await tool.build_epson_activity_dashboard(guard=guard)
    assert fake_qs.executions == 0
    assert guard.calls == []
