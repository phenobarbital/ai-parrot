"""Unit tests for InfographicAuthoringMixin (FEAT-326, Module 3 / TASK-1884)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.bots.data import PandasAgent
from parrot.bots.mixins import InfographicAuthoringMixin, IntentRouterMixin
from parrot.tools.infographic_sections import (
    ProvenanceDescriptor,
    SectionDescriptor,
    SectionSpec,
)
from parrot.tools.infographic_toolkit import (
    InfographicRenderResult,
    InfographicValidationError,
)


class _AuthoringAgent(InfographicAuthoringMixin, PandasAgent):
    """Test composition: mixin before PandasAgent (cooperative MRO)."""


def _fake_store():
    store = MagicMock()
    store.save_artifact = AsyncMock(return_value=None)
    return store


def _fake_render_result(artifact_id="art-1"):
    return InfographicRenderResult(
        artifact_id=artifact_id,
        html_url="https://signed/x",
        html_inline="<html/>",
        template_name="tpl",
    )


class _FakeEntry:
    def __init__(self, df):
        self.df = df
        self.columns = list(df.columns) if df is not None else []


class _FakeDM:
    def __init__(self, datasets):
        self._d = datasets  # alias -> _FakeEntry

    def get_dataset_entry(self, name):
        return self._d.get(name)


@pytest.fixture(scope="module")
def agent():
    """One composed agent for the whole module (instantiation is heavy)."""
    return _AuthoringAgent(name="reporter", artifact_store=_fake_store())


# ---------------------------------------------------------------------------
# Composition / MRO
# ---------------------------------------------------------------------------

class TestMixinComposition:
    def test_mro_cooperative_with_pandas_agent(self, agent):
        mro = [c.__name__ for c in type(agent).__mro__]
        assert mro.index("InfographicAuthoringMixin") < mro.index("PandasAgent")
        # IntentRouterMixin behavior is intact.
        assert isinstance(agent, IntentRouterMixin)
        assert "IntentRouterMixin" in mro

    def test_toolkit_tools_registered_on_agent(self, agent):
        names = agent.get_available_tools()
        assert "infographic_render_data_template" in names
        assert "infographic_render_template" in names

    def test_import_path(self):
        from parrot.bots.mixins import InfographicAuthoringMixin as _M
        assert _M is InfographicAuthoringMixin


# ---------------------------------------------------------------------------
# generate_infographic
# ---------------------------------------------------------------------------

class TestGenerateInfographic:
    async def test_returns_result_and_provenance(self, agent, monkeypatch):
        descriptor = SectionDescriptor(
            template="tpl",
            mode="data-splice",
            sections=[SectionSpec(name="hero", target="/hero", shape="records")],
        )
        # Stub the toolkit render + the build seam.
        agent._infographic_toolkit.render_data_template = AsyncMock(
            return_value=_fake_render_result("art-42")
        )

        async def _fake_build(desc, params):
            return {"hero": [{"x": 1}]}, {"revenue": "2026-07-24T00:00:00+00:00"}

        monkeypatch.setattr(agent, "_build_section_payload", _fake_build)

        result, provenance = await agent.generate_infographic("tpl", descriptor)
        assert isinstance(result, InfographicRenderResult)
        assert result.artifact_id == "art-42"
        assert isinstance(provenance, ProvenanceDescriptor)
        assert provenance.tier == "one-shot"
        assert provenance.artifact_id == "art-42"
        assert provenance.dataset_snapshots == {"revenue": "2026-07-24T00:00:00+00:00"}

    def test_provenance_has_no_code(self):
        assert not any(
            "code" in f or "source" in f
            for f in ProvenanceDescriptor.model_fields
        )

    async def test_validation_gate_blocks_before_render(self, agent, monkeypatch):
        descriptor = SectionDescriptor(
            template="tpl",
            mode="data-splice",
            sections=[
                SectionSpec(
                    name="hero", target="/hero", datasets=["revenue"], shape="records"
                )
            ],
        )
        # DatasetManager lacks 'revenue' → gate must raise before any render.
        monkeypatch.setattr(agent, "_dataset_manager", _FakeDM({}))
        render_spy = AsyncMock(return_value=_fake_render_result())
        agent._infographic_toolkit.render_data_template = render_spy

        with pytest.raises(InfographicValidationError) as exc:
            await agent.generate_infographic("tpl", descriptor)
        assert exc.value.code == "sections_unmet"
        render_spy.assert_not_called()

    async def test_accepts_descriptor_json_string(self, agent, monkeypatch):
        descriptor = SectionDescriptor(
            template="tpl",
            mode="data-splice",
            sections=[SectionSpec(name="hero", target="/hero", shape="records")],
        )
        agent._infographic_toolkit.render_data_template = AsyncMock(
            return_value=_fake_render_result("art-json")
        )

        async def _fake_build(desc, params):
            return {"hero": []}, {}

        monkeypatch.setattr(agent, "_build_section_payload", _fake_build)

        result, _ = await agent.generate_infographic(
            "tpl", descriptor.model_dump_json()
        )
        assert result.artifact_id == "art-json"
