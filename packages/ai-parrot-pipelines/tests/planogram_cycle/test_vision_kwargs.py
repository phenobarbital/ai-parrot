"""Tests for AbstractPlanogramType._vision_kwargs and the three core call sites (TASK-3429)."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from PIL import Image

import parrot_pipelines
from parrot_pipelines.planogram.backend import ResolvedBackend
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType

_PLANOGRAM = Path(parrot_pipelines.__file__).parent / "planogram"


class _LegacyType(AbstractPlanogramType):
    """Minimal concrete type for helper tests."""

    async def compute_roi(self, img):
        return None, None, None, None, []

    async def detect_objects_roi(self, img, roi):
        return []

    async def detect_objects(self, img, roi, macro_objects):
        return [], []

    def check_planogram_compliance(self, identified_products, planogram_description):
        return []


class _ClientContext:
    """Async context manager yielding ``client`` (the idiom ``async with pipeline.llm as client``)."""

    def __init__(self, client) -> None:
        self.client = client

    async def __aenter__(self):
        return self.client

    async def __aexit__(self, *exc) -> None:
        return None


def _make_type(model):
    pipeline = MagicMock()
    pipeline.logger = logging.getLogger("test.vision_kwargs")
    pipeline.resolved_backend = ResolvedBackend(provider="anthropic", model=model, origin="config")
    client = SimpleNamespace(ask_to_image=AsyncMock(return_value=MagicMock(output="LIGHT_OFF")))
    pipeline.llm = _ClientContext(client)
    pipeline.client = client
    roi_client = SimpleNamespace(ask_to_image=AsyncMock(side_effect=AssertionError("roi_client must not be used")))
    pipeline.roi_client = _ClientContext(roi_client)
    pipeline._downscale_image = MagicMock(side_effect=lambda img, **kw: img)
    return _LegacyType(pipeline=pipeline, config=MagicMock()), pipeline


def test_vision_kwargs_without_model():
    handler, _ = _make_type(model=None)
    assert handler._vision_kwargs() == {"no_memory": True}


def test_vision_kwargs_with_model_and_extra():
    handler, _ = _make_type(model="claude-sonnet-5")
    assert handler._vision_kwargs(max_tokens=16) == {"no_memory": True, "max_tokens": 16, "model": "claude-sonnet-5"}


def test_vision_kwargs_ignores_non_string_or_empty_model():
    handler, pipeline = _make_type(model=None)
    pipeline.resolved_backend = MagicMock()  # .model is a MagicMock
    assert "model" not in handler._vision_kwargs()
    pipeline.resolved_backend = SimpleNamespace(model="")
    assert handler._vision_kwargs() == {"no_memory": True}


def test_vision_kwargs_without_resolved_backend_attribute():
    handler, pipeline = _make_type(model=None)
    del pipeline.resolved_backend
    assert handler._vision_kwargs() == {"no_memory": True}


async def test_check_illumination_uses_pipeline_llm():
    """ask_to_image is awaited on pipeline.llm's client with model from the backend, never on roi_client."""
    handler, pipeline = _make_type(model="claude-sonnet-5")
    img = Image.new("RGB", (64, 64), "white")
    roi = SimpleNamespace(bbox=SimpleNamespace(x1=0.0, y1=0.0, x2=1.0, y2=1.0))
    assert await handler._check_illumination(img, roi=roi) == "illumination_status: OFF"
    kwargs = pipeline.client.ask_to_image.await_args.kwargs
    assert kwargs["no_memory"] is True
    assert kwargs["max_tokens"] == 128
    assert kwargs["model"] == "claude-sonnet-5"

    handler_no_model, pipeline_no_model = _make_type(model=None)
    await handler_no_model._check_illumination(img)
    assert "model" not in pipeline_no_model.client.ask_to_image.await_args.kwargs


def test_core_files_have_no_literals():
    """The three core files no longer reference roi_client or a hard-coded Gemini model."""
    for relative in ("types/abstract.py", "plan.py", "legacy.py"):
        text = (_PLANOGRAM / relative).read_text()
        assert "roi_client" not in text, relative
        assert 'model="gemini' not in text, relative
