"""Adapter-mediated illumination and backend/model forwarding through PlanogramCompliance.run() (FEAT-612)."""

from __future__ import annotations

from pathlib import Path

import pytest

import parrot_pipelines
from parrot.models.detections import DetectionBox
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram import plan as plan_module
from parrot_pipelines.planogram.backend import ResolvedBackend
from parrot_pipelines.planogram.contracts import FixtureMembership, PerceptionResult, Shape, ShapeKind
from parrot_pipelines.planogram.plan import PlanogramCompliance

_PLANOGRAM = Path(parrot_pipelines.__file__).parent / "planogram"
_CORE_FILES = ("types/abstract.py", "plan.py", "identification/evidence.py", "stages/identify.py")


class _InlineExecutor:
    """CpuExecutor substitute for deterministic offline cycle tests."""

    def __init__(self, max_workers: int = 2) -> None:
        self.max_workers = max_workers

    async def run(self, fn, *args):
        """Run a CPU helper in-process."""
        return fn(*args)

    async def aclose(self) -> None:
        """Provide the run-template cleanup interface."""
        return None


def _definition() -> dict:
    """Return a synthetic zone-only panel definition."""
    return {
        "shelves": [{"shelf_id": "header", "shelf_number": 0, "facings": []}],
        "zones": [{"zone_id": "Zone-A", "kind": "backlit", "shelf_id": "header", "required": True}],
    }


@pytest.mark.parametrize("model", ["claude-sonnet-5", None])
async def test_illumination_evidence_uses_pipeline_backend(
    model, monkeypatch, fake_vision_client, synthetic_shelf_image
):
    """Illumination uses the run-local adapter, forwarding a pinned model only when configured."""
    config = PlanogramConfig(
        planogram_type="graphic_panel_display",
        planogram_config={
            "rule_bindings": [
                {
                    "rule_id": "illumination",
                    "kind": "illumination",
                    "target_id": "Zone-A",
                    "params": {"required": "on"},
                },
                {"rule_id": "zone_present", "kind": "zone_present", "target_id": "Zone-A"},
            ]
        },
        slots_definition=_definition(),
    )
    fake_vision_client.client_name = "claude"
    pipe = PlanogramCompliance(planogram_config=config, llm=fake_vision_client, enabled_ocr=False)
    pipe.resolved_backend = ResolvedBackend(provider="anthropic", model=model, origin="config")
    monkeypatch.setattr(plan_module, "CpuExecutor", _InlineExecutor)
    zone = Shape(
        shape_id="img0:zone0",
        image_id="img0",
        kind=ShapeKind.ZONE,
        box=DetectionBox(x1=0, y1=0, x2=800, y2=200, confidence=1.0),
        membership=FixtureMembership.ON_FIXTURE,
    )

    async def perceive(image, image_id, ctx):
        return PerceptionResult(image_id=image_id, image_size=image.size, zones=[zone])

    monkeypatch.setattr(pipe._type_handler, "perceive", perceive)
    fake_vision_client.queue(
        "ask_to_image",
        {"existing_identifications": [{"shape_id": "img0:zone0", "occupancy": "occupied"}]},
        {"illumination": "on"},
    )
    result = await pipe.run(synthetic_shelf_image)
    calls = fake_vision_client.calls_to("ask_to_image")
    assert calls
    for call in calls:
        kwargs = call["kwargs"]
        assert kwargs["no_memory"] is True and kwargs.get("structured_output") is not None
        assert (kwargs.get("model") == model) if model else ("model" not in kwargs)
    assert any(
        outcome.rule_id == "illumination" and outcome.assessed for outcome in result["shelf_scores"][0].rule_results
    )


def test_core_files_have_no_literals():
    """Surviving core files never reference roi_client or a hard-coded Gemini model."""
    for relative in _CORE_FILES:
        text = (_PLANOGRAM / relative).read_text(encoding="utf-8")
        assert "roi_client" not in text, relative
        assert 'model="gemini' not in text, relative
