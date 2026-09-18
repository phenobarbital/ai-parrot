"""AbstractPipeline backend resolution and open_image(enhance=) (FEAT-574, spec Module 5)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from parrot_pipelines.abstract import AbstractPipeline


class _Pipe(AbstractPipeline):
    """Minimal concrete pipeline."""

    async def run(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """No-op run."""
        return {}


@pytest.fixture(autouse=True)
def _no_google_client():
    """roi_client is still built in __init__ (kept until TASK-3432): stub the class so no SDK/credentials are needed."""
    with patch("parrot.clients.google.GoogleGenAIClient", MagicMock()):
        yield


def _build(**kwargs: Any):
    """Construct _Pipe with _get_llm patched; returns (pipe, get_llm_mock)."""
    fake = SimpleNamespace(client_name="Fake", model=None)
    with patch.object(_Pipe, "_get_llm", return_value=fake) as get_llm:
        return _Pipe(**kwargs), get_llm


def test_default_backend_is_google():
    """Nothing passed ⇒ Google client from the package default."""
    pipe, get_llm = _build()
    assert get_llm.call_args.args[0] == "google"
    assert pipe.resolved_backend.origin == "package_default"
    assert pipe.roi_client is not None


def test_config_backend_wins_over_omitted_arguments():
    """An omitted llm_provider does not mask the configured backend."""
    pipe, get_llm = _build(config_backend="anthropic:claude-sonnet-5")
    assert get_llm.call_args.args == ("anthropic", "claude-sonnet-5")
    assert pipe.resolved_backend.origin == "config"


def test_explicit_provider_switch_does_not_inherit_model():
    """A provider switch never inherits the other provider's model id."""
    pipe, get_llm = _build(llm_provider="google", config_backend="anthropic:claude-sonnet-5")
    assert get_llm.call_args.args == ("google", None)
    assert pipe.resolved_backend.origin == "constructor"


def test_llm_string_builds_client():
    """A "provider:model" string builds the client instead of crashing on .client_name."""
    pipe, get_llm = _build(llm="anthropic:claude-sonnet-5")
    assert get_llm.call_args.args == ("anthropic", "claude-sonnet-5")
    assert pipe.resolved_backend.origin == "llm_string"
    assert pipe.llm.client_name == "Fake"


def test_llm_instance_is_kept_and_provider_read_from_client_name():
    """An injected instance is kept as is; _get_llm is never called."""
    instance = SimpleNamespace(client_name="Anthropic", model="claude-sonnet-5")
    pipe, get_llm = _build(llm=instance)
    assert pipe.llm is instance
    get_llm.assert_not_called()
    assert pipe.llm_provider == "anthropic"
    assert pipe.resolved_backend.origin == "llm_instance"
    assert pipe.roi_client is not None


def test_config_backend_not_forwarded_but_other_kwargs_are():
    """config_backend is consumed by __init__; other kwargs reach _get_llm."""
    _, get_llm = _build(config_backend="google:x", temperature=0.0)
    assert get_llm.call_args.kwargs == {"temperature": 0.0}


def test_open_image_enhance_flag():
    """enhance default → one _enhance_image call; enhance=False → none; non-RGB input comes back RGB."""
    pipe, _ = _build()
    with patch.object(_Pipe, "_enhance_image", side_effect=lambda i: i) as enhance:
        pipe.open_image(Image.new("RGB", (4, 4)))
        assert enhance.call_count == 1
        out = pipe.open_image(Image.new("L", (4, 4)), enhance=False)
        assert enhance.call_count == 1
        assert out.mode == "RGB"
