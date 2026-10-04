"""Registry, strict cycle contract, and compatibility tests for planogram types."""

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from parrot.pipelines.planogram.plan import PlanogramCompliance
from parrot.pipelines.planogram.types.abstract import AbstractPlanogramType
from parrot.pipelines.planogram.types.product_on_shelves import ProductOnShelves
from parrot.pipelines.models import EndcapGeometry, PlanogramConfig
from parrot_pipelines.planogram.contracts import ComparisonResult, IdentificationResult, PerceptionResult

_MIN_SLOTS_DEFINITION = {
    "shelves": [
        {
            "shelf_id": "shelf_1",
            "shelf_number": 1,
            "facings": [
                {
                    "facing_id": "f1",
                    "shelf_id": "shelf_1",
                    "slot": 1,
                    "product": "P-100",
                    "descriptors": {"display_name": "P-100"},
                }
            ],
        }
    ]
}


@pytest.fixture
def planogram_config_obj() -> PlanogramConfig:
    """Build a minimal valid migrated configuration."""
    return PlanogramConfig(
        config_name="test_planogram",
        planogram_type="product_on_shelves",
        planogram_config={},
        slots_definition=_MIN_SLOTS_DEFINITION,
    )


@pytest.fixture
def mock_pipeline(planogram_config_obj: PlanogramConfig) -> MagicMock:
    """Build the parent reference used by composable type tests."""
    pipeline = MagicMock(spec=PlanogramCompliance)
    pipeline.logger = logging.getLogger("test.planogram")
    pipeline.planogram_config = planogram_config_obj
    pipeline.reference_images = {}
    return pipeline


class TestAbstractPlanogramType:
    """The strict four-member migrated type contract."""

    def test_cannot_instantiate_directly(self, mock_pipeline: MagicMock, planogram_config_obj: PlanogramConfig) -> None:
        """AbstractPlanogramType cannot be instantiated."""
        with pytest.raises(TypeError):
            AbstractPlanogramType(pipeline=mock_pipeline, config=planogram_config_obj)

    def test_missing_cycle_hooks_rejected(
        self, mock_pipeline: MagicMock, planogram_config_obj: PlanogramConfig
    ) -> None:
        """A subclass implementing only perceive() is rejected by the strict contract."""

        class IncompleteType(AbstractPlanogramType):
            @classmethod
            def default_layout_profile(cls) -> Any:
                return ProductOnShelves.default_layout_profile()

            async def perceive(self, image: Any, image_id: str, ctx: Any) -> PerceptionResult:
                return PerceptionResult(image_id=image_id, image_size=image.size)

        with pytest.raises(TypeError):
            IncompleteType(pipeline=mock_pipeline, config=planogram_config_obj)

    def test_default_render_colors(self, mock_pipeline: MagicMock, planogram_config_obj: PlanogramConfig) -> None:
        """get_render_colors returns RGB tuples for the five keys."""

        class CompleteType(AbstractPlanogramType):
            @classmethod
            def default_layout_profile(cls) -> Any:
                return ProductOnShelves.default_layout_profile()

            async def perceive(self, image: Any, image_id: str, ctx: Any) -> PerceptionResult:
                return PerceptionResult(image_id=image_id, image_size=image.size)

            async def identify(self, image: Any, perception: PerceptionResult, ctx: Any) -> IdentificationResult:
                return IdentificationResult(image_id=perception.image_id)

            async def compare(self, perceptions: Any, identifications: Any, ctx: Any) -> ComparisonResult:
                return ComparisonResult()

        colors = CompleteType(pipeline=mock_pipeline, config=planogram_config_obj).get_render_colors()
        assert set(colors) == {"roi", "detection", "product", "compliant", "non_compliant"}
        assert all(isinstance(value, tuple) and len(value) == 3 for value in colors.values())


class TestPlanogramComplianceRegistry:
    """Registry dispatch remains backwards-compatible while containing only migrated types."""

    def test_registry_contains_product_on_shelves(self) -> None:
        """The default type resolves to ProductOnShelves."""
        assert PlanogramCompliance._PLANOGRAM_TYPES["product_on_shelves"] is ProductOnShelves

    def test_registry_is_exactly_the_six_types(self) -> None:
        """No legacy or unregistered types remain in the public registry."""
        assert set(PlanogramCompliance._PLANOGRAM_TYPES) == {
            "product_on_shelves",
            "graphic_panel_display",
            "product_counter",
            "endcap_no_shelves_promotional",
            "endcap_backlit_multitier",
            "ink_wall",
        }

    @patch("parrot.pipelines.planogram.plan.AbstractPipeline.__init__", return_value=None)
    def test_resolves_product_on_shelves(self, mock_init: MagicMock, planogram_config_obj: PlanogramConfig) -> None:
        """The registry class instantiates from the configured type key."""
        pipeline = PlanogramCompliance.__new__(PlanogramCompliance)
        pipeline.logger = logging.getLogger("test")
        pipeline.planogram_config = planogram_config_obj
        pipeline.reference_images = {}
        pipeline._type_handler = PlanogramCompliance._PLANOGRAM_TYPES[planogram_config_obj.planogram_type](
            pipeline=pipeline, config=planogram_config_obj
        )
        assert isinstance(pipeline._type_handler, ProductOnShelves)

    def test_unknown_type_raises_valueerror(self) -> None:
        """Unknown types fail with the configured key in their message."""
        config = PlanogramConfig(
            planogram_type="nonexistent_type", planogram_config={}, slots_definition=_MIN_SLOTS_DEFINITION
        )
        with pytest.raises(ValueError, match="Unknown planogram_type 'nonexistent_type'"):
            PlanogramCompliance(planogram_config=config)

    def test_default_type_is_product_on_shelves(self) -> None:
        """Omitting the type preserves the established default."""
        assert (
            PlanogramConfig(planogram_config={}, slots_definition=_MIN_SLOTS_DEFINITION).planogram_type
            == "product_on_shelves"
        )


class TestPlanogramConfigType:
    """PlanogramConfig serialises the public type setting."""

    def test_planogram_type_field_exists(self) -> None:
        """PlanogramConfig exposes the type field."""
        assert hasattr(PlanogramConfig(planogram_config={}, slots_definition=_MIN_SLOTS_DEFINITION), "planogram_type")

    def test_planogram_type_default(self) -> None:
        """The default stays product_on_shelves."""
        assert (
            PlanogramConfig(planogram_config={}, slots_definition=_MIN_SLOTS_DEFINITION).planogram_type
            == "product_on_shelves"
        )

    def test_planogram_type_explicit(self) -> None:
        """An explicit type is retained."""
        assert (
            PlanogramConfig(
                planogram_type="tv_wall", planogram_config={}, slots_definition=_MIN_SLOTS_DEFINITION
            ).planogram_type
            == "tv_wall"
        )

    def test_planogram_type_serialization(self) -> None:
        """The type survives Pydantic serialisation."""
        config = PlanogramConfig(planogram_type="ink_wall", planogram_config={}, slots_definition=_MIN_SLOTS_DEFINITION)
        assert config.model_dump()["planogram_type"] == "ink_wall"


class TestProductOnShelves:
    """Construction retains the handler and parent/config references."""

    def test_implements_contract(self, mock_pipeline: MagicMock, planogram_config_obj: PlanogramConfig) -> None:
        """ProductOnShelves fulfils the abstract contract."""
        assert isinstance(ProductOnShelves(mock_pipeline, planogram_config_obj), AbstractPlanogramType)

    def test_pipeline_reference(self, mock_pipeline: MagicMock, planogram_config_obj: PlanogramConfig) -> None:
        """The handler preserves its pipeline reference."""
        assert ProductOnShelves(mock_pipeline, planogram_config_obj).pipeline is mock_pipeline

    def test_config_reference(self, mock_pipeline: MagicMock, planogram_config_obj: PlanogramConfig) -> None:
        """The handler preserves its configuration reference."""
        assert ProductOnShelves(mock_pipeline, planogram_config_obj).config is planogram_config_obj


class TestRenderColors:
    """The surviving rendering helper remains covered."""

    def test_product_on_shelves_default_colors(
        self, mock_pipeline: MagicMock, planogram_config_obj: PlanogramConfig
    ) -> None:
        """ProductOnShelves returns the default colour scheme."""
        assert ProductOnShelves(mock_pipeline, planogram_config_obj).get_render_colors()["roi"] == (0, 255, 0)


class TestHandlerHydration:
    """Database configuration hydration keeps the type default and explicit values."""

    def _row(self) -> dict[str, Any]:
        return {
            "planogram_id": 1,
            "config_name": "test",
            "planogram_type": "product_on_shelves",
            "planogram_config": {},
            "reference_images": {},
            "slots_definition": _MIN_SLOTS_DEFINITION,
        }

    def test_build_planogram_config_includes_type(self) -> None:
        """A persisted type is transferred to PlanogramConfig."""
        from parrot.handlers.planogram_compliance import PlanogramComplianceHandler

        handler = MagicMock(spec=PlanogramComplianceHandler)
        handler._build_planogram_config = PlanogramComplianceHandler._build_planogram_config.__get__(handler)
        handler._decode_json_column.side_effect = lambda value: value
        handler.logger = logging.getLogger("test")
        config = handler._build_planogram_config(self._row())
        assert config.planogram_type == "product_on_shelves"
        assert isinstance(config.endcap_geometry, EndcapGeometry)

    def test_build_planogram_config_default_type(self) -> None:
        """A missing persisted type receives the public default."""
        from parrot.handlers.planogram_compliance import PlanogramComplianceHandler

        handler = MagicMock(spec=PlanogramComplianceHandler)
        handler._build_planogram_config = PlanogramComplianceHandler._build_planogram_config.__get__(handler)
        handler._decode_json_column.side_effect = lambda value: value
        handler.logger = logging.getLogger("test")
        row = self._row()
        row.pop("planogram_type")
        assert handler._build_planogram_config(row).planogram_type == "product_on_shelves"


class TestBackwardsCompatibility:
    """The public default remains stable for existing configurations."""

    def test_config_without_type_uses_default(self) -> None:
        """Legacy configs without planogram_type retain the default handler."""
        assert (
            PlanogramConfig(
                planogram_config={"brand": "Test", "shelves": []}, slots_definition=_MIN_SLOTS_DEFINITION
            ).planogram_type
            == "product_on_shelves"
        )
