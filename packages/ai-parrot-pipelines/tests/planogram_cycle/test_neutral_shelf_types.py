"""Provider-neutral call sites of the shelf-style planogram types (TASK-3430)."""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from parrot_pipelines.planogram.types import (
    EndcapNoShelvesPromotional,
    ProductCounter,
    ProductOnShelves,
)

_TYPES_DIR = Path(__file__).resolve().parents[2] / "src" / "parrot_pipelines" / "planogram" / "types"
_FILES = ("product_on_shelves.py", "product_counter.py", "endcap_no_shelves_promotional.py")


def _pipeline(model):
    """Mock pipeline whose llm is an async context manager yielding a recording client."""
    client = MagicMock()
    client.ask_to_image = AsyncMock(return_value=MagicMock(output="", structured_output=None))
    llm = MagicMock()
    llm.__aenter__ = AsyncMock(return_value=client)
    llm.__aexit__ = AsyncMock(return_value=False)
    pipeline = MagicMock()
    pipeline.logger = logging.getLogger("test.neutral_shelf_types")
    pipeline.llm = llm
    pipeline.roi_client = MagicMock(name="roi_client_must_not_be_used")
    pipeline.resolved_backend = MagicMock(provider="anthropic", model=model)
    pipeline._downscale_image = MagicMock(return_value=Image.new("RGB", (64, 64)))
    return pipeline, client


def _config():
    """Minimal type config: description with a brand, no custom prompts."""
    config = MagicMock()
    config.get_planogram_description.return_value = SimpleNamespace(
        brand="TestBrand", tags=[], advertisement_endcap=None
    )
    # Legacy types require both prompts at construction (TASK-3442 validate_contract).
    config.roi_detection_prompt = "Find the display area"
    config.object_identification_prompt = "Identify the products"
    config.planogram_config = {"brand": "TestBrand", "shelves": []}
    return config


async def _call_ignoring_parse_errors(coro):
    """The call site is what is under test; downstream parsing of the empty answer may fail."""
    with contextlib.suppress(Exception):
        await coro


@pytest.mark.parametrize("name", _FILES)
def test_no_literals_left(name):
    text = (_TYPES_DIR / name).read_text(encoding="utf-8")
    assert "roi_client" not in text
    assert 'model="gemini' not in text
    assert "no_memory=True" not in text  # now supplied by _vision_kwargs()


async def test_product_counter_compute_roi_uses_pipeline_llm():
    pipeline, client = _pipeline(model="claude-sonnet-5")
    handler = ProductCounter(pipeline=pipeline, config=_config())
    await _call_ignoring_parse_errors(handler.compute_roi(Image.new("RGB", (256, 256))))
    kwargs = client.ask_to_image.await_args.kwargs
    assert kwargs["no_memory"] is True and kwargs["model"] == "claude-sonnet-5"
    assert kwargs["max_tokens"] == 8192
    pipeline.roi_client.__aenter__.assert_not_called()


async def test_product_counter_detect_objects_roi_uses_pipeline_llm():
    pipeline, client = _pipeline(model="claude-sonnet-5")
    handler = ProductCounter(pipeline=pipeline, config=_config())
    roi = SimpleNamespace(bbox=SimpleNamespace(x1=0.0, y1=0.0, x2=1.0, y2=1.0), label="counter")
    await _call_ignoring_parse_errors(handler.detect_objects_roi(Image.new("RGB", (256, 256)), roi))
    kwargs = client.ask_to_image.await_args.kwargs
    assert kwargs["no_memory"] is True and kwargs["model"] == "claude-sonnet-5"
    pipeline.roi_client.__aenter__.assert_not_called()


async def test_endcap_no_shelves_compute_roi_uses_pipeline_llm():
    pipeline, client = _pipeline(model="claude-sonnet-5")
    handler = EndcapNoShelvesPromotional(pipeline=pipeline, config=_config())
    await _call_ignoring_parse_errors(handler.compute_roi(Image.new("RGB", (256, 256))))
    kwargs = client.ask_to_image.await_args.kwargs
    assert kwargs["no_memory"] is True and kwargs["model"] == "claude-sonnet-5"
    pipeline.roi_client.__aenter__.assert_not_called()


async def test_endcap_no_shelves_detect_objects_roi_uses_pipeline_llm():
    pipeline, client = _pipeline(model="claude-sonnet-5")
    handler = EndcapNoShelvesPromotional(pipeline=pipeline, config=_config())
    roi = SimpleNamespace(bbox=SimpleNamespace(x1=0.0, y1=0.0, x2=1.0, y2=1.0), label="endcap")
    await _call_ignoring_parse_errors(handler.detect_objects_roi(Image.new("RGB", (256, 256)), roi))
    kwargs = client.ask_to_image.await_args.kwargs
    assert kwargs["no_memory"] is True and kwargs["model"] == "claude-sonnet-5"
    pipeline.roi_client.__aenter__.assert_not_called()


async def test_pos_find_poster_uses_pipeline_llm():
    pipeline, client = _pipeline(model="claude-sonnet-5")
    config = _config()
    handler = ProductOnShelves(pipeline=pipeline, config=config)
    planogram = SimpleNamespace(brand="TestBrand", tags=[], advertisement_endcap=None)
    await _call_ignoring_parse_errors(
        handler._find_poster(Image.new("RGB", (256, 256)), planogram, "Find the {brand} poster {tag_hint}")
    )
    kwargs = client.ask_to_image.await_args.kwargs
    assert kwargs["no_memory"] is True and kwargs["model"] == "claude-sonnet-5"
    pipeline.roi_client.__aenter__.assert_not_called()


async def test_model_omitted_when_backend_has_none():
    pipeline, client = _pipeline(model=None)
    handler = ProductCounter(pipeline=pipeline, config=_config())
    await _call_ignoring_parse_errors(handler.compute_roi(Image.new("RGB", (256, 256))))
    kwargs = client.ask_to_image.await_args.kwargs
    assert kwargs["no_memory"] is True
    assert "model" not in kwargs


def test_pos_detect_objects_call_untouched():
    """product_on_shelves.py still contains 'await self.pipeline.llm.detect_objects(' exactly once."""
    text = (_TYPES_DIR / "product_on_shelves.py").read_text(encoding="utf-8")
    assert text.count("await self.pipeline.llm.detect_objects(") == 1
