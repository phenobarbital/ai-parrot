"""Shared fixtures for Thales integration tests (FEAT-425 TASK-2233).

Everything here is a canned, offline stand-in for a real LLM/tool call —
no network, no API keys. Shapes mirror what `parrot.flows.thales.factories`
normalizers expect (`AIMessage`-duck-typed objects, `ArxivTool._execute()`
result dicts).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from parrot.flows.thales.models import ResearchAngle, SlideSpec
from parrot.flows.thales.nodes.planner import _AnglesEnvelope


def make_web_message(angle_id: str) -> SimpleNamespace:
    """Canned `WebSearchAgent.ask()` response for one angle."""
    return SimpleNamespace(
        response=f"Web finding for {angle_id}: remote work reshapes regional labor markets.",
        output=f"Web finding for {angle_id}",
        metadata={},
        tool_calls=[],
    )


def make_deep_research_message(angle_id: str) -> SimpleNamespace:
    """Canned deep-research `ask(deep_research=True)` response for one angle."""
    return SimpleNamespace(
        response=f"Deep research synthesis for {angle_id}: cross-regional inequality trends.",
        output=f"Deep research synthesis for {angle_id}",
        metadata={},
        tool_calls=[],
    )


def make_arxiv_message(angle_id: str, *, dateless: bool = False) -> SimpleNamespace:
    """Canned arxiv-agent `ask()` response — a ToolCall carrying the raw
    `ArxivTool._execute()` result. Every angle shares the SAME pdf_url so
    the bibliography formatter's dedupe-by-URL path is exercised; one
    angle (``dateless=True``) omits ``published`` to exercise the
    "n.d." — never-invented-date path.
    """
    paper = {
        "title": "Open Source Flight Stacks: A Cross-Regional Review",
        "authors": ["Doe, J."],
        "published": None if dateless else "2024-01-02",
        "updated": None,
        "pdf_url": "https://arxiv.org/pdf/shared-paper",
        "journal_ref": None,
        "summary": f"Findings relevant to {angle_id}.",
        "arxiv_id": "shared-paper",
        "categories": [],
        "primary_category": "cs.AI",
        "comment": None,
    }
    execute_result = {"query": angle_id, "count": 1, "papers": [paper]}
    tool_call = SimpleNamespace(
        id="t1", name="arxiv_search", arguments={}, result=execute_result, error=None,
    )
    return SimpleNamespace(response="", output="", metadata={}, tool_calls=[tool_call])


class FakeAgent:
    """Minimal stand-in for `WebSearchAgent`/arxiv `Agent` — only `.ask()` is used."""

    def __init__(self, message_factory, angle_id: str, *, fail: bool = False) -> None:
        self._message_factory = message_factory
        self._angle_id = angle_id
        self._fail = fail

    async def ask(self, question: str, **kwargs: Any) -> SimpleNamespace:
        if self._fail:
            raise RuntimeError(f"simulated failure for {self._angle_id}")
        return self._message_factory(self._angle_id)


class FakeClient:
    """Stand-in for the shared LLM client — dispatches by call shape.

    Handles all three `client.ask(...)` call shapes `ThalesRunner`'s graph
    produces: `structured_output=_AnglesEnvelope` (planner),
    `structured_output=SlideSpec` (slide_spec), `deep_research=True`
    (deep-research research node), and the plain `question=...` shape
    `synthesize_results` uses (exec summary).
    """

    def __init__(self, num_angles: int = 10) -> None:
        self.num_angles = num_angles

    async def ask(self, *args: Any, **kwargs: Any) -> SimpleNamespace:
        structured_output = kwargs.get("structured_output")
        if structured_output is _AnglesEnvelope:
            angles = [
                ResearchAngle(angle_id=f"a{i}", title=f"Angle {i}", question=f"question {i}", rationale="r")
                for i in range(self.num_angles)
            ]
            return SimpleNamespace(structured_output=_AnglesEnvelope(angles=angles), data=None)

        if structured_output is SlideSpec:
            spec = SlideSpec(deck_ref="x", layout="default", headline="Headline", bullets=["finding"])
            return SimpleNamespace(structured_output=spec, data=None)

        if kwargs.get("deep_research"):
            angle_id = "deep"
            return make_deep_research_message(angle_id)

        # synthesize_results shape: client.ask(question=..., ...)
        return SimpleNamespace(content="An executive summary synthesizing all research angles.")


@pytest.fixture
def mock_research_outputs():
    """Canned WebSearch/DeepResearch/Arxiv responses with known citation
    metadata, incl. one duplicate URL (dedupe) and one date-less source
    ("n.d.").
    """
    return {
        "web": make_web_message,
        "deep_research": make_deep_research_message,
        "arxiv": make_arxiv_message,
    }


class RecordingCheckpointStore:
    """In-memory `CheckpointStore` — no Redis required.

    `assemble_thales_flow` always passes ``checkpoint=True`` (FEAT-399);
    without this stand-in, every integration test would try to reach a
    real Redis instance via `get_checkpoint_store()`'s default backend.
    Mirrors the `FakeCheckpointStore` precedent in
    `tests/flows/checkpoint/test_suspend_resume.py`.
    """

    def __init__(self) -> None:
        self.puts: list[str] = []
        self._by_flow: dict[str, list] = {}
        self._leases: dict[str, str] = {}

    async def put(self, checkpoint) -> None:
        self.puts.append(checkpoint.flow_id)
        self._by_flow.setdefault(checkpoint.flow_id, []).append(checkpoint)

    async def latest(self, flow_id: str):
        history = self._by_flow.get(flow_id, [])
        return history[-1] if history else None

    async def get(self, flow_id: str, checkpoint_id: int):
        for cp in self._by_flow.get(flow_id, []):
            if cp.checkpoint_id == checkpoint_id:
                return cp
        return None

    async def history(self, flow_id: str, limit: int = 10):
        return list(reversed(self._by_flow.get(flow_id, [])))[:limit]

    async def list_flows(self, status: "str | None" = None):
        return []

    async def delete_flow(self, flow_id: str) -> None:
        self._by_flow.pop(flow_id, None)

    async def acquire_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        if flow_id in self._leases:
            return False
        self._leases[flow_id] = holder
        return True

    async def renew_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        return self._leases.get(flow_id) == holder

    async def release_lease(self, flow_id: str, holder: str) -> None:
        if self._leases.get(flow_id) == holder:
            del self._leases[flow_id]

    async def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def patched_checkpoint_store(monkeypatch):
    """Replace `AgentsFlow`'s checkpoint-store resolution with an in-memory
    stand-in for every test in this package — `checkpoint=True` is always
    on for a Thales flow (FEAT-399), so every test that calls
    `ThalesRunner.run()`/`assemble_thales_flow()` needs this, not just the
    checkpoint-specific test.
    """
    import parrot.bots.flows.flow.flow as flow_module

    store = RecordingCheckpointStore()
    monkeypatch.setattr(flow_module, "get_checkpoint_store", lambda *a, **kw: store)
    return store
