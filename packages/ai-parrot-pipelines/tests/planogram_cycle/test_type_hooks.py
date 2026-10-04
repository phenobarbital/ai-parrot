"""Strict three-hook AbstractPlanogramType contract (FEAT-612, Module 11)."""

from __future__ import annotations

import inspect
import logging
from unittest.mock import MagicMock

import pytest

from parrot_pipelines.planogram.contracts import ComparisonResult, IdentificationResult, PerceptionResult
from parrot_pipelines.planogram.layout import LayoutProfile
from parrot_pipelines.planogram.perception import PRICE_TAG_PROFILE
from parrot_pipelines.planogram.plan import PlanogramCompliance
from parrot_pipelines.planogram.types import abstract as abstract_module
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType

LEGACY = (
    "compute_roi",
    "detect_objects_roi",
    "detect_objects",
    "check_planogram_compliance",
    "get_grid_strategy",
    "_LEGACY_CONTRACT",
    "_LEGACY_PROMPTS",
)
MEMBERS = ("default_layout_profile", "perceive", "identify", "compare")


def _pipeline():
    pipeline = MagicMock()
    pipeline.logger = logging.getLogger("test.type_hooks")
    return pipeline


def _config(slots_definition=None, name="cfg"):
    config = MagicMock()
    config.config_name = name
    config.planogram_config = {}
    config.slots_definition = slots_definition
    return config


class _Complete(AbstractPlanogramType):
    @classmethod
    def default_layout_profile(cls) -> LayoutProfile:
        return LayoutProfile(shape_profiles=[PRICE_TAG_PROFILE])

    async def perceive(self, image, image_id, ctx):
        return PerceptionResult(image_id=image_id)

    async def identify(self, image, perception, ctx):
        return IdentificationResult(image_id=perception.image_id)

    async def compare(self, perceptions, identifications, ctx):
        return ComparisonResult()


def test_legacy_members_removed():
    for name in LEGACY:
        assert not hasattr(AbstractPlanogramType, name)
    source = inspect.getsource(abstract_module)
    assert "legacy_adapter" not in source and "grid.strategy" not in source


@pytest.mark.parametrize("missing", MEMBERS)
def test_missing_member_is_type_error(missing):
    members = {k: _Complete.__dict__[k] for k in MEMBERS if k != missing}
    half = type("Half", (AbstractPlanogramType,), members)
    with pytest.raises(TypeError):
        half(pipeline=_pipeline(), config=_config({"shelves": []}))


def test_base_is_not_instantiable():
    with pytest.raises(TypeError):
        AbstractPlanogramType(pipeline=_pipeline(), config=_config({"shelves": []}))


def test_implements_is_classmethod_safe():
    handler = _Complete(pipeline=_pipeline(), config=_config({"shelves": []}))
    assert handler._implements("default_layout_profile") and handler._implements("compare")
    assert not handler._implements("get_render_colors")


def test_implements_false_for_missing_classmethod():
    members = {k: _Complete.__dict__[k] for k in MEMBERS if k != "default_layout_profile"}
    half = type("Half", (AbstractPlanogramType,), members)
    half.__abstractmethods__ = frozenset()  # allow __new__ so the MRO check can be probed directly
    assert not object.__new__(half)._implements("default_layout_profile")


def test_missing_definition_names_config_and_runbook():
    with pytest.raises(ValueError, match="planogram-cycle-migration.md") as exc:
        _Complete(pipeline=_pipeline(), config=_config(None, name="store-42"))
    assert "store-42" in str(exc.value)


@pytest.mark.parametrize("ptype", sorted(PlanogramCompliance._PLANOGRAM_TYPES))
def test_every_registered_type_is_complete(ptype):
    cls = PlanogramCompliance._PLANOGRAM_TYPES[ptype]
    handler = cls(pipeline=_pipeline(), config=_config({"shelves": []}))
    assert all(handler._implements(n) for n in AbstractPlanogramType._CYCLE_HOOKS)
    a, b = cls.default_layout_profile(), cls.default_layout_profile()
    assert isinstance(a, LayoutProfile) and a is not b


def test_render_colors_default_kept():
    colors = _Complete(pipeline=_pipeline(), config=_config({"shelves": []})).get_render_colors()
    assert {"compliant", "non_compliant"} <= set(colors)
