"""Provider-neutral cycle: shelf types reach providers only through VisionAdapter (FEAT-612)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from PIL import Image

from parrot.models.detections import DetectionBox
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.backend import ResolvedBackend
from parrot_pipelines.planogram.comparison.definition import RuleBinding, load_slots_definition
from parrot_pipelines.planogram.contracts import CycleContext, FixtureMembership, PerceptionResult, Shape, ShapeKind
from parrot_pipelines.planogram.identification.vision import VisionAdapter
from parrot_pipelines.planogram.types import EndcapNoShelvesPromotional, ProductCounter, ProductOnShelves

_TYPES_DIR = Path(__file__).resolve().parents[2] / "src" / "parrot_pipelines" / "planogram" / "types"
_TYPES = {
    "endcap_no_shelves_promotional.py": EndcapNoShelvesPromotional,
    "product_counter.py": ProductCounter,
    "product_on_shelves.py": ProductOnShelves,
}
_BANNED = ("roi_client", 'model="gemini', "no_memory=True", "ask_to_image", "self.pipeline.llm")


class _InlineExecutor:
    """Run deterministic image helpers inline."""

    async def run(self, fn: Any, *args: Any) -> Any:
        """Call a CPU helper without a process pool."""
        return fn(*args)


class _NoOcr:
    """Offline OCR capability marker."""

    available = False


class _RaisingVision:
    """Fail if the pure comparison stage attempts model I/O."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"compare() must not touch vision ({name})")


def _definition() -> dict[str, Any]:
    """Return generic synthetic product and zone expectations."""
    return {
        "shelves": [
            {"shelf_id": "header", "shelf_number": 0, "facings": []},
            {
                "shelf_id": "s1",
                "shelf_number": 1,
                "facings": [
                    {
                        "facing_id": "s1_f1",
                        "shelf_id": "s1",
                        "slot": 1,
                        "product": "P-100",
                        "descriptors": {"display_name": "P-100"},
                    }
                ],
            },
        ],
        "zones": [{"zone_id": "Zone-A", "kind": "backlit", "shelf_id": "header", "required": True}],
    }


def _handler(type_class: type[Any]) -> Any:
    """Create a type with a generic, fully valid configuration."""
    pipeline = MagicMock()
    pipeline.logger = logging.getLogger("test.neutral_shelf_types")
    config = PlanogramConfig(planogram_type=type_class.__name__, planogram_config={}, slots_definition=_definition())
    return type_class(pipeline=pipeline, config=config)


def _adapter(fake: Any, model: str | None) -> VisionAdapter:
    """Bind the fake to the configured backend under the Claude kwargs policy."""
    fake.client_name = "claude"
    return VisionAdapter(
        fake,
        ResolvedBackend(provider="anthropic", model=model, origin="config"),
        semaphore=asyncio.Semaphore(2),
        repair_retries=0,
    )


def _context(fake: Any, model: str | None, type_class: type[Any]) -> CycleContext:
    """Build the run-local service context used by an identify hook."""
    return CycleContext(
        vision=_adapter(fake, model),
        executor=_InlineExecutor(),
        ocr=_NoOcr(),
        definition=load_slots_definition(_definition()),
        bindings=[RuleBinding(rule_id="illumination", kind="illumination", target_id="Zone-A")],
        layout=type_class.default_layout_profile(),
    )


def _perception() -> PerceptionResult:
    """Return one observed synthetic zone, driving identification and illumination evidence."""
    zone = Shape(
        shape_id="img0:zone0",
        image_id="img0",
        kind=ShapeKind.ZONE,
        box=DetectionBox(x1=20, y1=20, x2=380, y2=120, confidence=1.0),
        membership=FixtureMembership.ON_FIXTURE,
    )
    return PerceptionResult(image_id="img0", image_size=(400, 400), zones=[zone])


@pytest.mark.parametrize("name", sorted(_TYPES))
def test_type_source_has_no_direct_provider_calls(name: str) -> None:
    """Migrated types leave all provider access to the shared adapter."""
    assert [token for token in _BANNED if token in (_TYPES_DIR / name).read_text(encoding="utf-8")] == []


@pytest.mark.parametrize("name", sorted(_TYPES))
@pytest.mark.parametrize("model", ["claude-sonnet-5", None])
async def test_identify_calls_forward_backend_model(name: str, model: str | None, fake_vision_client: Any) -> None:
    """Every provider call uses adapter-normalised backend kwargs without definition labels."""
    type_class = _TYPES[name]
    fake_vision_client.queue(
        "ask_to_image",
        {"existing_identifications": [{"shape_id": "img0:zone0", "occupancy": "occupied"}]},
        {"illumination": "on"},
    )
    await _handler(type_class).identify(
        Image.new("RGB", (400, 400), "white"), _perception(), _context(fake_vision_client, model, type_class)
    )
    calls = fake_vision_client.calls_to("ask_to_image")
    assert calls
    for call in calls:
        kwargs = call["kwargs"]
        assert kwargs["no_memory"] is True and kwargs.get("structured_output") is not None
        assert (kwargs.get("model") == model) if model else ("model" not in kwargs)
        assert "P-100" not in call["prompt"]


@pytest.mark.parametrize("name", sorted(_TYPES))
async def test_compare_never_calls_vision(name: str) -> None:
    """Empty evidence is non-compliant and comparison remains provider-free."""
    type_class = _TYPES[name]
    context = CycleContext(
        vision=_RaisingVision(),
        definition=load_slots_definition(_definition()),
        bindings=[RuleBinding(rule_id="illumination", kind="illumination", target_id="Zone-A")],
        layout=type_class.default_layout_profile(),
    )
    assert (await _handler(type_class).compare([], [], context)).overall_compliant is False


def test_pos_has_no_direct_detector_call() -> None:
    """The fallback detector is owned by the orchestrator, never ProductOnShelves."""
    assert (_TYPES_DIR / "product_on_shelves.py").read_text(encoding="utf-8").count(
        "self.pipeline.llm.detect_objects("
    ) == 0
