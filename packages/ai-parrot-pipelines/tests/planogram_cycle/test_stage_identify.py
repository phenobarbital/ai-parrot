"""Tests for shared stage-2 orchestration."""

import numpy as np
import pytest
from PIL import Image

from parrot_pipelines.planogram.contracts import (
    CycleContext,
    IdentificationResult,
    IdentifyStrategy,
    ObservationSource,
    OcrReading,
    PerceptionResult,
    RuleObservation,
)
from parrot_pipelines.planogram.layout import LayoutProfile
from parrot_pipelines.planogram.perception.profiles import PRICE_TAG_PROFILE
from parrot_pipelines.planogram.stages import identify as stage


class InlineExecutor:
    """Run CPU helpers inline for stage composition tests."""

    async def run(self, fn, *args):
        """Invoke the supplied helper directly."""
        return fn(*args)


class AvailableOcr:
    """Minimal OCR service exposing the availability contract."""

    available = True


def _layout(strategy):
    """Return a profile with the requested strategy and descriptor vocabulary."""
    return LayoutProfile(
        shape_profiles=[PRICE_TAG_PROFILE],
        identify_strategy=strategy,
        descriptor_fields=["family", "colors"],
        substrip_max_slots=3,
    )


def _ctx(layout=None):
    """Create the context required by shared stage composition."""
    return CycleContext(executor=InlineExecutor(), layout=layout, ocr=AvailableOcr())


def _image():
    """Return an untouched RGB fixture image."""
    return Image.fromarray(np.zeros((20, 30, 3), dtype=np.uint8))


@pytest.mark.asyncio
async def test_requires_layout():
    """A stage without a resolved profile fails explicitly."""
    with pytest.raises(ValueError, match="layout"):
        await stage.identify_image(_image(), PerceptionResult(image_id="img0"), _ctx())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("strategy", "expected"),
    [("full_image", "identify_full_image"), ("strips", "identify_strips"), ("slots", "identify_slots")],
)
async def test_dispatches_configured_strategy(monkeypatch, strategy, expected):
    """The profile chooses exactly one identifying helper."""
    calls = []

    def recorder(name):
        async def _record(*args, **kwargs):
            calls.append((name, kwargs))
            return IdentificationResult(image_id="img0")

        return _record

    for name in ("identify_full_image", "identify_strips", "identify_slots"):
        monkeypatch.setattr(stage, name, recorder(name))

    async def readings(*args):
        return {}

    async def evidence(*args):
        return []

    monkeypatch.setattr(stage, "read_target_text", readings)
    monkeypatch.setattr(stage, "collect_rule_evidence", evidence)
    await stage.identify_image(_image(), PerceptionResult(image_id="img0"), _ctx(_layout(strategy)))
    assert [name for name, _kwargs in calls] == [expected]
    assert calls[0][1]["vocabulary"] == ["family", "colors"]
    if strategy == "strips":
        assert calls[0][1]["substrip_max_slots"] == 3


@pytest.mark.asyncio
async def test_ocr_readings_are_attached_before_dispatch(monkeypatch):
    """Identification sees own-box OCR readings already attached to its perception."""
    seen = []

    async def readings(*args):
        return {"img0:r0:s1": OcrReading(text="62XL", confidence=0.9)}

    async def full_image(_image, perception, _ctx, **_kwargs):
        seen.append(perception.ocr_readings)
        return IdentificationResult(image_id="img0")

    async def evidence(*args):
        return []

    monkeypatch.setattr(stage, "read_target_text", readings)
    monkeypatch.setattr(stage, "identify_full_image", full_image)
    monkeypatch.setattr(stage, "collect_rule_evidence", evidence)
    perception = PerceptionResult(image_id="img0")
    await stage.identify_image(_image(), perception, _ctx(_layout(IdentifyStrategy.FULL_IMAGE)))
    assert seen == [{"img0:r0:s1": OcrReading(text="62XL", confidence=0.9)}]
    assert perception.ocr_available is True


@pytest.mark.asyncio
async def test_rule_observations_are_attached(monkeypatch):
    """Evidence collection augments, rather than replaces, the strategy result."""
    observation = RuleObservation(
        image_id="img0",
        target_id="img0:zone0",
        kind="illumination",
        source=ObservationSource.LLM,
    )

    async def readings(*args):
        return {}

    async def full_image(*args, **kwargs):
        return IdentificationResult(image_id="img0")

    async def evidence(*args):
        return [observation]

    monkeypatch.setattr(stage, "read_target_text", readings)
    monkeypatch.setattr(stage, "identify_full_image", full_image)
    monkeypatch.setattr(stage, "collect_rule_evidence", evidence)
    result = await stage.identify_image(_image(), PerceptionResult(image_id="img0"), _ctx(_layout("full_image")))
    assert result.rule_observations == [observation]
