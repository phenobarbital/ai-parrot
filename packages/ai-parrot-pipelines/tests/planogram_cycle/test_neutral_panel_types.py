"""Provider-neutral call sites of the panel-style planogram types (TASK-3431)."""

from __future__ import annotations

import contextlib
import logging
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from parrot_pipelines.planogram.types import EndcapBacklitMultitier, GraphicPanelDisplay

_TYPES_DIR = Path(__file__).resolve().parents[2] / "src" / "parrot_pipelines" / "planogram" / "types"
_EXPECTED_SITES = {"endcap_backlit_multitier.py": 6, "graphic_panel_display.py": 4}


def _pipeline(model):
    """Mock pipeline whose llm is an async context manager yielding a recording client."""
    client = MagicMock()
    client.ask_to_image = AsyncMock(return_value=MagicMock(output="LIGHT_ON", structured_output=None))
    llm = MagicMock()
    llm.__aenter__ = AsyncMock(return_value=client)
    llm.__aexit__ = AsyncMock(return_value=False)
    pipeline = MagicMock()
    pipeline.logger = logging.getLogger("test.neutral_panel_types")
    pipeline.llm = llm
    pipeline.roi_client = MagicMock(name="roi_client_must_not_be_used")
    pipeline.resolved_backend = MagicMock(provider="anthropic", model=model)
    pipeline._downscale_image = MagicMock(return_value=Image.new("RGB", (64, 64)))
    return pipeline, client


def _config():
    """Minimal type config: description with a brand, no custom prompts."""
    config = MagicMock()
    config.get_planogram_description.return_value = SimpleNamespace(
        brand="TestBrand", tags=[], advertisement_endcap=None, shelves=[]
    )
    # Legacy types require both prompts at construction (TASK-3442 validate_contract).
    config.roi_detection_prompt = "Find the display area"
    config.object_identification_prompt = "Identify the products"
    config.planogram_config = {"brand": "TestBrand", "shelves": []}
    return config


@pytest.mark.parametrize("name,sites", sorted(_EXPECTED_SITES.items()))
def test_no_literals_and_site_count(name, sites):
    text = (_TYPES_DIR / name).read_text(encoding="utf-8")
    assert "roi_client" not in text
    assert 'model="gemini' not in text
    assert "no_memory=True" not in text
    assert len(re.findall(r"async with self\.pipeline\.llm as client:", text)) == sites


async def test_graphic_panel_illumination_uses_pipeline_llm():
    pipeline, client = _pipeline(model="claude-sonnet-5")
    handler = GraphicPanelDisplay(pipeline=pipeline, config=_config())
    roi = SimpleNamespace(bbox=SimpleNamespace(x1=0.0, y1=0.0, x2=1.0, y2=1.0))
    await handler._check_illumination_from_roi(Image.new("RGB", (128, 128)), roi, SimpleNamespace(brand="TestBrand"))
    kwargs = client.ask_to_image.await_args.kwargs
    assert kwargs["no_memory"] is True and kwargs["model"] == "claude-sonnet-5" and kwargs["max_tokens"] == 16
    pipeline.roi_client.__aenter__.assert_not_called()


async def test_backlit_compute_roi_uses_pipeline_llm():
    pipeline, client = _pipeline(model="claude-sonnet-5")
    handler = EndcapBacklitMultitier(pipeline=pipeline, config=_config())
    with contextlib.suppress(Exception):  # parsing of the canned empty answer is not under test
        await handler.compute_roi(Image.new("RGB", (256, 256)))
    kwargs = client.ask_to_image.await_args.kwargs
    assert kwargs["no_memory"] is True and kwargs["model"] == "claude-sonnet-5"
    assert kwargs["max_tokens"] == 8192
    assert kwargs["structured_output"].__name__ == "_RawDetections"
    pipeline.roi_client.__aenter__.assert_not_called()


async def test_model_omitted_when_backend_has_none():
    pipeline, client = _pipeline(model=None)
    handler = GraphicPanelDisplay(pipeline=pipeline, config=_config())
    await handler._check_illumination_from_roi(Image.new("RGB", (128, 128)), None, SimpleNamespace(brand=""))
    kwargs = client.ask_to_image.await_args.kwargs
    assert kwargs["no_memory"] is True
    assert "model" not in kwargs
