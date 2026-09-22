"""Unit tests for the Amazon Polly TTS backend."""
from types import SimpleNamespace

import pytest

from parrot.voice.tts.models import SynthesisResult, TTSConfig
from parrot.voice.tts.polly_backend import AmazonPollyTTSBackend, split_text_for_polly


class _AudioStream:
    """Minimal asynchronous Polly audio stream."""

    def __init__(self, audio: bytes) -> None:
        self._audio = audio

    async def read(self) -> bytes:
        """Return the configured audio bytes."""
        return self._audio


class _PollyClient:
    """Async Polly client recording its synthesis requests."""

    def __init__(self) -> None:
        self.requests: list[dict[str, str]] = []

    async def __aenter__(self) -> "_PollyClient":
        """Enter the async client context."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit the async client context."""

    async def synthesize_speech(self, **kwargs: str) -> dict[str, _AudioStream]:
        """Record the request and return deterministic chunk audio."""
        self.requests.append(kwargs)
        return {"AudioStream": _AudioStream(kwargs["Text"].encode())}


class _PollySession:
    """aioboto3 session substitute exposing one Polly client."""

    def __init__(self, client: _PollyClient) -> None:
        self._client = client
        self.region_name: str | None = None

    def client(self, service_name: str, *, region_name: str) -> _PollyClient:
        """Return the fake Polly client for the requested region."""
        assert service_name == "polly"
        self.region_name = region_name
        return self._client


def _install_aioboto3_stub(monkeypatch: pytest.MonkeyPatch) -> tuple[_PollyClient, _PollySession]:
    """Install a small aioboto3 substitute and return its observable state."""
    client = _PollyClient()
    session = _PollySession(client)
    monkeypatch.setitem(__import__("sys").modules, "aioboto3", SimpleNamespace(Session=lambda **kwargs: session))
    return client, session


def test_polly_split_text_sentence_boundaries() -> None:
    """Sentence splitting retains order and hard-splits oversized sentences."""
    text = "First sentence. Second sentence. " + "x" * 12
    chunks = split_text_for_polly(text, max_chars=16)
    assert all(len(chunk) <= 16 for chunk in chunks)
    assert chunks[0] == "First sentence."
    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")


def test_ttsconfig_accepts_polly_defaults() -> None:
    """Polly configuration defaults to its long-form engine."""
    config = TTSConfig(backend="polly")
    assert config.polly_engine == "long-form"
    assert config.polly_region is None


@pytest.mark.asyncio
async def test_polly_synthesize_concatenates_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Polly requests each chunk in order and concatenates their audio."""
    client, session = _install_aioboto3_stub(monkeypatch)
    backend = AmazonPollyTTSBackend()
    text = "First. Second."

    result = await backend.synthesize(text)

    assert isinstance(result, SynthesisResult)
    assert result.audio == b"First. Second."
    assert result.mime_format == "audio/mpeg"
    assert [request["Text"] for request in client.requests] == [text]
    assert client.requests[0]["Engine"] == "long-form"
    assert client.requests[0]["VoiceId"] == "Danielle"
    assert session.region_name == "us-east-1"


@pytest.mark.asyncio
async def test_polly_honours_region_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """AWS_POLLY_REGION is used when no explicit backend region is given."""
    _, session = _install_aioboto3_stub(monkeypatch)
    monkeypatch.setenv("AWS_POLLY_REGION", "eu-west-1")

    await AmazonPollyTTSBackend().synthesize("Hello")

    assert session.region_name == "eu-west-1"


@pytest.mark.asyncio
async def test_polly_unsupported_mime_raises() -> None:
    """Formats not supported by Polly fail before creating a session."""
    with pytest.raises(ValueError, match="Unsupported"):
        await AmazonPollyTTSBackend().synthesize("Hello", mime_format="audio/wav")


@pytest.mark.asyncio
async def test_polly_missing_aioboto3_names_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing optional dependency identifies the extra to install."""
    monkeypatch.delitem(__import__("sys").modules, "aioboto3", raising=False)
    backend = AmazonPollyTTSBackend()
    original_import = __import__("builtins").__import__

    def missing_aioboto3(name: str, *args: object, **kwargs: object) -> object:
        """Raise ImportError only for the optional dependency."""
        if name == "aioboto3":
            raise ImportError("missing aioboto3")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", missing_aioboto3)
    with pytest.raises(ImportError, match="voice-polly"):
        await backend.synthesize("Hello")


@pytest.mark.asyncio
async def test_polly_error_retains_aws_error_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """AWS error codes remain visible when Polly requests fail."""
    client, _ = _install_aioboto3_stub(monkeypatch)

    async def fail(**kwargs: str) -> dict[str, _AudioStream]:
        """Raise an AWS-shaped error response."""
        error = RuntimeError("denied")
        error.response = {"Error": {"Code": "AccessDeniedException"}}
        raise error

    client.synthesize_speech = fail  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="AccessDeniedException"):
        await AmazonPollyTTSBackend().synthesize("Hello")
