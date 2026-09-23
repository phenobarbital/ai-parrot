"""Tests for process-wide ``VoiceSynthesizer`` reuse."""

import asyncio
import logging

import pytest

from parrot.voice.tts.models import TTSConfig
from parrot.voice.tts import synthesizer as synthesizer_module
from parrot.voice.tts.synthesizer import (
    close_shared_synthesizers,
    get_shared_synthesizer,
)


@pytest.fixture(autouse=True)
async def clear_shared_synthesizers():
    """Ensure each test starts and finishes with an empty shared cache."""
    await close_shared_synthesizers()
    yield
    await close_shared_synthesizers()


async def test_shared_synthesizer_same_config_same_instance():
    """Equal configurations reuse one synthesizer while distinct ones do not."""
    config = TTSConfig(backend="google", voice="Charon")

    first = await get_shared_synthesizer(config)
    second = await get_shared_synthesizer(TTSConfig(backend="google", voice="Charon"))
    different = await get_shared_synthesizer(TTSConfig(backend="google", voice="Kore"))

    assert first is second
    assert first is not different


async def test_shared_synthesizer_concurrent_first_call(monkeypatch):
    """Concurrent first callers construct exactly one shared synthesizer."""
    constructed = 0

    class CountingSynthesizer:
        """Minimal construction counter used to observe cache population."""

        def __init__(self, config: TTSConfig) -> None:
            nonlocal constructed
            constructed += 1
            self.config = config

        async def close(self) -> None:
            """Provide the lifecycle contract required by cache teardown."""

    monkeypatch.setattr(synthesizer_module, "VoiceSynthesizer", CountingSynthesizer)
    config = TTSConfig(backend="google")

    synthesizers = await asyncio.gather(*[get_shared_synthesizer(config) for _ in range(10)])

    assert constructed == 1
    assert all(synthesizer is synthesizers[0] for synthesizer in synthesizers)


async def test_close_shared_synthesizers_best_effort(monkeypatch, caplog):
    """A failed close is logged and still removes every cache entry."""

    class FailingSynthesizer:
        """Shared synthesizer whose close operation raises."""

        def __init__(self, config: TTSConfig) -> None:
            self.config = config

        async def close(self) -> None:
            """Fail to exercise best-effort cleanup."""
            raise RuntimeError("close failure")

    monkeypatch.setattr(synthesizer_module, "VoiceSynthesizer", FailingSynthesizer)
    await get_shared_synthesizer(TTSConfig(backend="google"))

    with caplog.at_level(logging.ERROR, logger="parrot.voice.tts.synthesizer"):
        await close_shared_synthesizers()

    assert synthesizer_module._SHARED == {}
    assert "Failed to close shared voice synthesizer" in caplog.text
