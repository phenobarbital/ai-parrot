"""Unit tests for typed A2UI v1.0 envelope builders (FEAT-470 TASK-2540, Module 5, D1a)."""

import pytest
from parrot.outputs.a2ui import builders
from parrot.outputs.a2ui.catalog import (
    CatalogValidationError,
    ProducerOrigin,
    validate_envelope,
)
from parrot.outputs.a2ui.models import CreateSurface
from parrot.outputs.a2ui.serialization import serialize


class TestEnvelopeBuilders:
    def test_builder_output_is_catalog_valid(self):
        for env in (
            builders.build_chart(chart_type="bar", x="m", y=["v"], data_binding="/rows"),
            builders.build_kpicard(label="Rev", value=100, trend="up"),
            builders.build_card(title="Hi", body="B"),
            builders.build_datatable(columns=[{"name": "a"}], data_binding="/r"),
            builders.build_infographic(
                title="T",
                sections=[
                    {"heading": "H", "components": [{"component": "KPICard", "properties": {"label": "x", "value": 1}}]}
                ],
            ),
        ):
            assert isinstance(env, CreateSurface)
            # Passes display-only (LLM-origin) validation.
            validate_envelope(env, origin=ProducerOrigin.LLM)

    def test_builders_emit_root(self):
        for env in (
            builders.build_chart(chart_type="bar", x="m", y=["v"]),
            builders.build_kpicard(label="Rev", value=100),
            builders.build_card(title="Hi"),
            builders.build_datatable(columns=[{"name": "a"}]),
            builders.build_infographic(title="T", sections=[{"heading": "H"}]),
        ):
            assert env.components[0].id == "root"

    def test_build_card_emits_infocard(self):
        env = builders.build_card(title="Hi")
        assert env.components[0].component == "InfoCard"

    def test_builder_deterministic(self):
        def make():
            return serialize(builders.build_chart(chart_type="line", x="d", y=["a", "b"], title="X"))

        assert make() == make()

    def test_builder_rejects_unknown_component(self):
        with pytest.raises(CatalogValidationError):
            builders.build_surface("NotAComponent", {}, surface_id="bad")

    def test_builders_make_no_llm_calls(self):
        # The builder module imports no client/LLM/agent surfaces (G8 one-way rule).
        import inspect

        import_lines = [
            line.strip()
            for line in inspect.getsource(builders).splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        blob = "\n".join(import_lines)
        for forbidden in ("parrot.clients", "parrot.bots", "DatasetManager", "AbstractClient"):
            assert forbidden not in blob

    def test_chart_binding_passthrough(self):
        env = builders.build_chart(chart_type="bar", x="m", y=["v"], data_binding="/charts/0")
        assert env.components[0].model_extra["data"] == {"path": "/charts/0"}
