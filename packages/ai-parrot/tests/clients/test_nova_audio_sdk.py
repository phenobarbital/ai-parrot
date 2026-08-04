"""Wrapper-level tests for ``NovaAudio`` against the REAL Pre-Alpha voice SDK.

Why this file exists
--------------------
Every ``stream_voice()`` test in ``test_nova.py`` patches the three thin SDK
wrappers (``_open_stream``/``_send_event``/``_iter_events``) — which is correct
for testing the *protocol* logic, but it means the wrappers themselves were
never executed. That gap let ``_open_stream`` ship importing
``BedrockAgentRuntimeClient`` (a class from the unrelated
*bedrock-agent-runtime* service that exists in no version of
``aws_sdk_bedrock_runtime``) and ``_iter_events`` ship returning
``stream.output_stream``, which is ``None`` until ``await_output()`` is
awaited. Both failed on the first real voice turn.

These tests therefore assert against the SDK's own types
(``Config``, ``InvokeModelWithBidirectionalStream*``) rather than mocks of
them, so a future rename or shape change fails here instead of in production.

Requires the Pre-Alpha SDK (Python >= 3.12); the whole module skips without it.
"""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip(
    "aws_sdk_bedrock_runtime",
    reason=(
        "Pre-Alpha 'aws_sdk_bedrock_runtime' (Python >= 3.12) not installed — "
        "these tests exercise the real SDK surface, not mocks of it."
    ),
)

# Imported after the importorskip above on purpose: these must not be
# collected when the Pre-Alpha SDK is absent.
from aws_sdk_bedrock_runtime import models as sdk_models
from aws_sdk_bedrock_runtime.config import Config
from parrot.clients.nova import NovaClient
from parrot.clients.nova import audio as audio_mod


def _make_client(**kwargs) -> NovaClient:
    kwargs.setdefault("model", "nova-2-sonic")
    kwargs.setdefault("region", "us-east-1")
    return NovaClient(**kwargs)


# ---------------------------------------------------------------------------
# Test doubles for smithy's DuplexEventStream contract
# ---------------------------------------------------------------------------

class _FakeReceiver:
    """Async-iterable stand-in for ``smithy_core`` ``EventReceiver``."""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


class _FakeDuplexStream:
    """Stand-in for ``DuplexEventStream``.

    Mirrors the two properties that matter: ``output_stream`` is ``None``
    until ``await_output()`` is awaited, and ``close()`` tears the stream down.
    """

    def __init__(self, chunks=()):
        self._receiver = _FakeReceiver(chunks)
        self.output_stream = None
        self.closed = False
        self.input_stream = MagicMock()
        self.input_stream.send = AsyncMock()

    async def await_output(self):
        self.output_stream = self._receiver
        return (None, self._receiver)

    async def close(self):
        self.closed = True


def _payload_chunk(frame: dict):
    """Build a real SDK output chunk carrying *frame* as JSON bytes."""
    return sdk_models.InvokeModelWithBidirectionalStreamOutputChunk(
        value=sdk_models.BidirectionalOutputPayloadPart(
            bytes_=json.dumps(frame).encode("utf-8")
        )
    )


# ---------------------------------------------------------------------------
# _resolve_voice_client_class
# ---------------------------------------------------------------------------

class TestResolveVoiceClientClass:
    def test_resolves_a_real_class_from_the_installed_sdk(self):
        cls = audio_mod._resolve_voice_client_class()
        assert cls.__name__ in audio_mod._VOICE_CLIENT_CLASS_NAMES
        # The whole point of the class: opening a bidirectional stream.
        assert hasattr(cls, "invoke_model_with_bidirectional_stream")

    def test_agent_runtime_name_is_not_a_candidate(self):
        """Regression guard: BedrockAgentRuntimeClient belongs to a different
        AWS service and exists in no release of this package."""
        assert "BedrockAgentRuntimeClient" not in audio_mod._VOICE_CLIENT_CLASS_NAMES

    def test_module_neither_imports_nor_calls_agent_runtime_client(self):
        """The name may appear only in the explanatory comment — never as an
        import or a constructor call."""
        source = Path(audio_mod.__file__).read_text(encoding="utf-8")
        assert "import BedrockAgentRuntimeClient" not in source
        assert "BedrockAgentRuntimeClient(" not in source

    def test_unknown_name_raises_listing_what_is_available(self, monkeypatch):
        """The error must be actionable when the Pre-Alpha SDK renames again:
        it names what was tried AND what the package actually exposes."""
        monkeypatch.setattr(
            audio_mod, "_VOICE_CLIENT_CLASS_NAMES", ("TotallyNotAClient",)
        )
        with pytest.raises(ImportError) as excinfo:
            audio_mod._resolve_voice_client_class()
        message = str(excinfo.value)
        assert "TotallyNotAClient" in message
        assert "BedrockRuntimeClient" in message  # the real, available name


# ---------------------------------------------------------------------------
# _open_stream
# ---------------------------------------------------------------------------

class TestOpenStream:
    @pytest.mark.asyncio
    async def test_builds_real_config_and_operation_input(self):
        client = _make_client(
            region="us-west-2", aws_access_key="AKIATEST", aws_secret_key="SECRET"
        )
        captured = {}

        class FakeSDKClient:
            def __init__(self, config=None, plugins=None):
                captured["config"] = config

            async def invoke_model_with_bidirectional_stream(self, inp, plugins=None):
                captured["input"] = inp
                return "THE-STREAM"

        with patch.object(
            audio_mod, "_resolve_voice_client_class", return_value=FakeSDKClient
        ):
            stream = await client._open_stream("amazon.nova-2-sonic-v1:0")

        assert stream == "THE-STREAM"

        # The SDK takes a Config object — NOT a region= kwarg.
        config = captured["config"]
        assert isinstance(config, Config)
        assert config.region == "us-west-2"
        assert config.aws_access_key_id == "AKIATEST"
        assert config.aws_secret_access_key == "SECRET"

        operation_input = captured["input"]
        assert isinstance(
            operation_input,
            sdk_models.InvokeModelWithBidirectionalStreamOperationInput,
        )
        assert operation_input.model_id == "amazon.nova-2-sonic-v1:0"

    @pytest.mark.asyncio
    async def test_installs_a_credentials_identity_resolver(self):
        """Regression test: the SDK leaves aws_credentials_identity_resolver at
        None, and SigV4 signing then fails with SmithyIdentityError even when
        the static key fields ARE set. The wrapper must install the standard
        Static -> Environment -> IMDS chain."""
        client = _make_client(aws_access_key="AKIATEST", aws_secret_key="SECRET")
        captured = {}

        class FakeSDKClient:
            def __init__(self, config=None, plugins=None):
                captured["config"] = config

            async def invoke_model_with_bidirectional_stream(self, inp, plugins=None):
                return MagicMock()

        with patch.object(
            audio_mod, "_resolve_voice_client_class", return_value=FakeSDKClient
        ):
            await client._open_stream("amazon.nova-2-sonic-v1:0")

        resolver = captured["config"].aws_credentials_identity_resolver
        assert resolver is not None
        # And it must actually resolve the static keys the config carries.
        identity = await resolver.get_identity(
            properties={
                "access_key_id": "AKIATEST",
                "secret_access_key": "SECRET",
                "session_token": None,
            }
        )
        assert identity.access_key_id == "AKIATEST"
        assert identity.secret_access_key == "SECRET"

    @pytest.mark.asyncio
    async def test_forwards_session_token_when_present(self):
        client = _make_client(
            aws_access_key="AKIATEST",
            aws_secret_key="SECRET",
            aws_session_token="TOKEN",
        )
        captured = {}

        class FakeSDKClient:
            def __init__(self, config=None, plugins=None):
                captured["config"] = config

            async def invoke_model_with_bidirectional_stream(self, inp, plugins=None):
                return MagicMock()

        with patch.object(
            audio_mod, "_resolve_voice_client_class", return_value=FakeSDKClient
        ):
            await client._open_stream("amazon.nova-2-sonic-v1:0")

        assert captured["config"].aws_session_token == "TOKEN"

    @pytest.mark.asyncio
    async def test_omits_credential_kwargs_when_no_static_keys(self):
        """With no static keys the SDK's own default chain must apply — the
        wrapper must not pass empty strings/None and shadow it."""
        client = _make_client()
        client._aws_access_key = None
        client._aws_secret_key = None
        client._aws_bearer_token = None
        captured = {}

        class FakeSDKClient:
            def __init__(self, config=None, plugins=None):
                captured["config"] = config

            async def invoke_model_with_bidirectional_stream(self, inp, plugins=None):
                return MagicMock()

        with patch.object(
            audio_mod, "_resolve_voice_client_class", return_value=FakeSDKClient
        ):
            await client._open_stream("amazon.nova-2-sonic-v1:0")

        config = captured["config"]
        assert config.aws_access_key_id is None
        assert config.aws_secret_access_key is None

    @pytest.mark.asyncio
    async def test_warns_when_only_a_bearer_token_is_configured(self):
        """The text path accepts a Bedrock API key; this SDK has no bearer-auth
        scheme, so voice must say so loudly rather than fail obscurely."""
        client = _make_client()
        client._aws_access_key = None
        client._aws_secret_key = None
        client._aws_bearer_token = "ABSKtestkey"

        class FakeSDKClient:
            def __init__(self, config=None, plugins=None):
                pass

            async def invoke_model_with_bidirectional_stream(self, inp, plugins=None):
                return MagicMock()

        with patch.object(
            audio_mod, "_resolve_voice_client_class", return_value=FakeSDKClient
        ), patch.object(client, "logger") as mock_logger:
            await client._open_stream("amazon.nova-2-sonic-v1:0")

        mock_logger.warning.assert_called_once()
        assert "bearer" in mock_logger.warning.call_args[0][0].lower()


# ---------------------------------------------------------------------------
# _send_event
# ---------------------------------------------------------------------------

class TestSendEvent:
    @pytest.mark.asyncio
    async def test_wraps_dict_into_real_input_chunk_as_json_bytes(self):
        """The SDK rejects a bare dict — the frame must be serialized and
        wrapped in InputChunk(value=BidirectionalInputPayloadPart(bytes_=...))."""
        client = _make_client()
        stream = _FakeDuplexStream()
        frame = {"event": {"audioInput": {"content": "AAAA", "promptName": "p"}}}

        await client._send_event(stream, frame)

        stream.input_stream.send.assert_awaited_once()
        chunk = stream.input_stream.send.await_args[0][0]
        assert isinstance(
            chunk, sdk_models.InvokeModelWithBidirectionalStreamInputChunk
        )
        assert isinstance(chunk.value, sdk_models.BidirectionalInputPayloadPart)
        assert isinstance(chunk.value.bytes_, bytes)
        assert json.loads(chunk.value.bytes_) == frame


# ---------------------------------------------------------------------------
# _iter_events
# ---------------------------------------------------------------------------

class TestIterEvents:
    @pytest.mark.asyncio
    async def test_awaits_output_decodes_json_and_unwraps_event_envelope(self):
        client = _make_client()
        stream = _FakeDuplexStream([
            _payload_chunk({"event": {"textOutput": {"content": "hello"}}}),
            _payload_chunk({"event": {"audioOutput": {"content": "QUJD"}}}),
            _payload_chunk({"event": {"completionEnd": {}}}),
        ])

        events = [event async for event in client._iter_events(stream)]

        # Unwrapped one level, so stream_voice()'s event.get("textOutput") works.
        assert events == [
            {"textOutput": {"content": "hello"}},
            {"audioOutput": {"content": "QUJD"}},
            {"completionEnd": {}},
        ]
        # Proves await_output() was actually awaited — output_stream is None
        # before that, which is what the original implementation returned.
        assert stream.output_stream is not None

    @pytest.mark.asyncio
    async def test_tolerates_already_unwrapped_frames(self):
        client = _make_client()
        stream = _FakeDuplexStream([_payload_chunk({"textOutput": {"content": "hi"}})])
        events = [event async for event in client._iter_events(stream)]
        assert events == [{"textOutput": {"content": "hi"}}]

    @pytest.mark.asyncio
    async def test_raises_instead_of_hanging_when_output_never_arrives(self):
        """Regression test: the Pre-Alpha SDK runs the request in a background
        task and, if that task raises (bad credentials, no model access), the
        output future is never resolved — await_output() would block forever
        and the turn would hang silently with no error surfaced."""
        client = _make_client()
        client._OUTPUT_READY_TIMEOUT_SECONDS = 0.05

        class _NeverReadyStream:
            async def await_output(self):
                await asyncio.Event().wait()  # never resolves

        with pytest.raises(RuntimeError, match="did not return an initial response"):
            [
                event
                async for event in client._iter_events(_NeverReadyStream())
            ]

    @pytest.mark.asyncio
    async def test_raises_on_non_payload_chunk(self):
        """The output union also carries the service's modelled exceptions
        (validation, throttling, model-timeout, ...). Those have no JSON
        payload and must surface, not be silently skipped."""
        client = _make_client()
        stream = _FakeDuplexStream([object()])

        with pytest.raises(RuntimeError, match="non-payload event"):
            [event async for event in client._iter_events(stream)]


# ---------------------------------------------------------------------------
# _close_stream + stream_voice integration
# ---------------------------------------------------------------------------

class TestCloseStream:
    @pytest.mark.asyncio
    async def test_closes_the_stream(self):
        client = _make_client()
        stream = _FakeDuplexStream()
        await client._close_stream(stream)
        assert stream.closed is True

    @pytest.mark.asyncio
    async def test_swallows_close_errors(self):
        """A turn often ends with the service already half-closing the stream."""
        client = _make_client()
        stream = MagicMock()
        stream.close = AsyncMock(side_effect=RuntimeError("already closed"))
        await client._close_stream(stream)  # must not raise


class TestErrorReporting:
    @pytest.mark.asyncio
    async def test_empty_service_error_still_reports_the_exception_type(self):
        """AWS's modelled errors (AccessDeniedException on a 403, for one) often
        have an empty str(), which produced metadata={"error": ""} — falsy, so
        consumers testing truthiness reported the turn as successfully complete."""

        class AccessDeniedException(Exception):
            def __str__(self):
                return ""

        client = _make_client()

        async def audio_iterator():
            yield b"\x00\x01" * 8
            yield None

        def _boom(_stream):
            raise AccessDeniedException()

        with patch.object(client, "_open_stream", return_value=_FakeDuplexStream()), \
             patch.object(client, "_send_event", new=AsyncMock()), \
             patch.object(client, "_iter_events", new=_boom):
            responses = [r async for r in client.stream_voice(audio_iterator())]

        assert responses[-1].metadata["error"] == "AccessDeniedException"
        assert responses[-1].is_complete is True


class TestStreamVoiceUsesRealWrappers:
    """End-to-end over the real _iter_events/_close_stream (only _open_stream
    and _send_event are stubbed, since those reach the network)."""

    @pytest.mark.asyncio
    async def test_turn_completes_and_stream_is_closed(self):
        client = _make_client()
        stream = _FakeDuplexStream([
            _payload_chunk({"event": {"textOutput": {"content": "hello"}}}),
            _payload_chunk({"event": {"completionEnd": {}}}),
        ])

        async def audio_iterator():
            yield b"\x00\x01" * 8
            yield None

        with patch.object(client, "_open_stream", return_value=stream), \
             patch.object(client, "_send_event", new=AsyncMock()):
            responses = [
                r async for r in client.stream_voice(audio_iterator())
            ]

        assert any(r.text == "hello" for r in responses)
        assert responses[-1].is_complete is True
        # The leak this fix closes: one stream_voice() call == one turn.
        assert stream.closed is True
