"""Lazy-SDK-guard smoke tests for NovaAudio (FEAT-315, TASK-1807).

Verifies that importing the mixin, and constructing a host class around
it, never requires the Pre-Alpha ``aws_sdk_bedrock_runtime`` package —
only calling ``stream_voice()`` does, and it raises an actionable
``ImportError`` when the package is missing.
"""
import sys

import pytest

from parrot.clients.nova.audio import NovaAudio


def test_module_imports_without_sdk():
    """Importing the mixin never requires the Pre-Alpha SDK."""
    assert NovaAudio is not None


class _Host(NovaAudio):
    """Minimal host exposing the attributes NovaAudio reads from a
    composed client (self.voice_id, self._region_prefix, self.model,
    self.default_model, self.logger)."""

    voice_id = "matthew"
    _region_prefix = "us"
    _region = "us-east-1"
    model = None
    default_model = "nova-2-sonic"

    def __init__(self):
        import logging
        self.logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_stream_voice_raises_actionable_import_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "aws_sdk_bedrock_runtime", None)

    async def gen():
        yield b"\x00\x00"

    with pytest.raises(ImportError, match="aws_sdk_bedrock_runtime"):
        async for _ in _Host().stream_voice(gen()):
            pass


def test_no_init_defined():
    assert "__init__" not in NovaAudio.__dict__
