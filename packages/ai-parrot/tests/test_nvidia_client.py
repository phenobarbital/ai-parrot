"""Unit tests for NvidiaClient, NvidiaModel, and factory registration.

Tests cover initialization, env-var fallback for NVIDIA_API_KEY, the
``enable_thinking`` / ``_merge_thinking_extra_body`` helper, the full
``ask`` / ``ask_stream`` call path with ``enable_thinking=True``, the
free-tier rate limiter (``free_tier`` flag + ``SlidingWindowRateLimiter``),
model enum values, and LLMFactory registration.

No live Nvidia calls are made.
"""
import asyncio
import contextlib

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from navconfig import config as _navconfig

from parrot.clients.nvidia import (
    FREE_TIER_RPM,
    NvidiaClient,
    NvidiaRateLimitError,
    SlidingWindowRateLimiter,
)
from parrot.models.nvidia import NvidiaModel
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """NvidiaClient with an explicit API key — no env-var lookup needed."""
    return NvidiaClient(api_key="test-key-123")


def make_mock_completion():
    """Build a MagicMock shaped like an OpenAI ``ChatCompletion`` response.

    Returns:
        MagicMock with the ``choices`` / ``usage`` attributes that
        ``OpenAIClient`` reads while post-processing a completion.
    """
    mock_choice = MagicMock()
    mock_choice.message.content = "ok"
    mock_choice.message.tool_calls = None
    mock_choice.message.role = "assistant"
    mock_choice.finish_reason = "stop"
    mock_choice.stop_reason = "stop"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = MagicMock(
        prompt_tokens=1, completion_tokens=1, total_tokens=2
    )
    mock_response.dict = MagicMock(return_value={})
    # AIMessageFactory.from_openai checks hasattr(response, "model_dump")
    # first (responses.py:492) — a bare MagicMock auto-vivifies that
    # attribute too, returning another MagicMock instead of a dict, which
    # fails AIMessage's raw_response validation. Pin it explicitly so this
    # mock exercises the same code path AIMessageFactory.from_openai
    # actually takes (pre-existing gap, predates FEAT-438 — confirmed via
    # the same failure on dev's gpt.py with this exact fixture).
    mock_response.model_dump = MagicMock(return_value={})
    return mock_response


def _fake_stream_create(pieces):
    """Build a ``chat.completions.create`` stand-in that returns a fake
    streaming async-iterable when called with ``stream=True`` (mirroring
    the OpenAI SDK's ``ChatCompletionChunk`` shape — a final usage-only
    chunk with no choices), else a plain completion.

    FEAT-438 TASK-2300: since ``ask_stream()`` now routes through
    ``_chat_completion`` (the completion funnel, TASK-2298) instead of
    calling the SDK directly, streaming tests must stub the SDK itself
    (via ``get_client``) rather than patching the parent class's
    ``ask_stream`` — patching ``OpenAIClient.ask_stream`` has no effect
    once ``NvidiaClient`` no longer has ``OpenAIClient`` in its MRO.
    """

    async def _gen():
        for piece in pieces:
            chunk = MagicMock()
            chunk.choices = [MagicMock(delta=MagicMock(content=piece))]
            chunk.usage = None
            yield chunk
        final = MagicMock()
        final.choices = []
        final.usage = MagicMock(prompt_tokens=1, completion_tokens=1, total_tokens=2)
        yield final

    async def _fake_create(**kwargs):
        if kwargs.get("stream"):
            return _gen()
        return make_mock_completion()

    return AsyncMock(side_effect=_fake_create)


@contextlib.asynccontextmanager
async def mocked_sdk(target_client, recorder=None, side_effect=None):
    """Enter ``target_client`` with a stubbed OpenAI SDK handle.

    Two mechanics make this the right seam:

    - ``AbstractClient.client`` is a loop-local *property* that rejects direct
      assignment ("override get_client() instead"), so ``get_client`` is where
      a fake SDK has to be injected.
    - ``ask()`` does not call ``_ensure_client()`` itself — only
      ``__aenter__`` does — so the client must be entered for ``self.client``
      to be populated at all.

    Stubbing at the SDK level (rather than at ``OpenAIClient._chat_completion``)
    is required because ``NvidiaClient._chat_completion`` calls
    ``chat.completions.create`` directly and never delegates to its parent.

    Args:
        target_client: The NvidiaClient to enter with a stubbed SDK.
        recorder: Optional dict updated with the kwargs of each call.
        side_effect: Optional async callable replacing the default stub, e.g.
            to raise on the first attempt and succeed on a retry.

    Yields:
        The ``AsyncMock`` standing in for ``chat.completions.create``, so
        callers can assert on ``await_count`` / ``await_args``.
    """

    async def _fake_create(**kwargs):
        if recorder is not None:
            recorder.update(kwargs)
        return make_mock_completion()

    mock_create = AsyncMock(side_effect=side_effect or _fake_create)
    fake_sdk = MagicMock()
    fake_sdk.chat.completions.create = mock_create

    with patch.object(
        NvidiaClient, "get_client", new=AsyncMock(return_value=fake_sdk)
    ):
        await target_client.__aenter__()
        try:
            yield mock_create
        finally:
            await target_client.__aexit__(None, None, None)


@pytest.fixture
def env_key(monkeypatch):
    """Patch navconfig.config.get and clear os.environ so NvidiaClient()
    (no api_key) picks up the fake key through config, not the shell env.
    """
    from parrot.clients import nvidia as nvidia_mod

    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setattr(
        nvidia_mod.config,
        "get",
        lambda key, default=None: "env-nvidia-key" if key == "NVIDIA_API_KEY" else default,
    )
    return "env-nvidia-key"


# ---------------------------------------------------------------------------
# TestNvidiaClientInit
# ---------------------------------------------------------------------------


class TestNvidiaClientInit:
    """Tests for NvidiaClient constructor and attribute defaults."""

    def test_client_init_explicit_key(self, client):
        """api_key passed explicitly is stored on the client."""
        assert client.api_key == "test-key-123"

    def test_client_init_env_fallback(self, env_key):
        """With api_key=None the client falls back to NVIDIA_API_KEY via config.get."""
        c = NvidiaClient(api_key=None)
        assert c.api_key == "env-nvidia-key"

    def test_client_base_url(self, client):
        """base_url points to the Nvidia NIM gateway."""
        assert client.base_url == "https://integrate.api.nvidia.com/v1"

    def test_client_type_and_name(self, client):
        """client_type and client_name are both 'nvidia'."""
        assert client.client_type == "nvidia"
        assert client.client_name == "nvidia"

    def test_default_model(self, client):
        """_default_model is MINIMAX_M3 (the previous Kimi default was withdrawn)."""
        assert NvidiaClient._default_model == NvidiaModel.MINIMAX_M3.value


# ---------------------------------------------------------------------------
# TestNvidiaThinkingHelper
# ---------------------------------------------------------------------------


class TestNvidiaThinkingHelper:
    """Tests for the _merge_thinking_extra_body static helper and the full
    ask / ask_stream call path when enable_thinking is active.
    """

    def test_enable_thinking_injects_extra_body(self):
        """Calling with enable_thinking=True on None body returns the right dict."""
        result = NvidiaClient._merge_thinking_extra_body(None, True, False)

        assert result is not None
        assert "chat_template_kwargs" in result
        assert result["chat_template_kwargs"]["enable_thinking"] is True
        assert result["chat_template_kwargs"]["clear_thinking"] is False

    def test_enable_thinking_preserves_existing_extra_body(self):
        """Existing keys in extra_body and chat_template_kwargs are kept."""
        existing = {"k": 1, "chat_template_kwargs": {"other": 1}}
        result = NvidiaClient._merge_thinking_extra_body(existing, True, True)

        assert result is not None
        # top-level key preserved
        assert result["k"] == 1
        ctk = result["chat_template_kwargs"]
        # nested pre-existing key preserved
        assert ctk["other"] == 1
        # new flags injected
        assert ctk["enable_thinking"] is True
        assert ctk["clear_thinking"] is True

    def test_enable_thinking_default_off(self):
        """When enable_thinking=False the helper is a no-op."""
        # None extra_body → still None
        assert NvidiaClient._merge_thinking_extra_body(None, False, False) is None

        # Existing dict → returned as same object (identity, not a copy)
        existing = {"k": 1}
        result = NvidiaClient._merge_thinking_extra_body(existing, False, True)
        assert result is existing

    @pytest.mark.asyncio
    async def test_ask_forwards_thinking_to_chat_completion(self, client):
        """ask(enable_thinking=True) sends extra_body with chat_template_kwargs.

        The seam is the SDK's ``chat.completions.create``, because
        ``NvidiaClient._chat_completion`` calls it directly rather than
        delegating to ``OpenAIClient._chat_completion``.
        """
        captured: dict = {}

        async with mocked_sdk(client, captured):
            await client.ask("hello", enable_thinking=True, clear_thinking=False)

        assert "extra_body" in captured
        ctk = captured["extra_body"]["chat_template_kwargs"]
        assert ctk["enable_thinking"] is True
        assert ctk["clear_thinking"] is False

    @pytest.mark.asyncio
    async def test_ask_no_extra_body_when_thinking_off(self, client):
        """ask(enable_thinking=False) does not inject extra_body into the request."""
        captured: dict = {}

        async with mocked_sdk(client, captured):
            await client.ask("hello")  # enable_thinking defaults to False

        assert "extra_body" not in captured or captured.get("extra_body") is None


# ---------------------------------------------------------------------------
# TestNvidiaSamplingParams
# ---------------------------------------------------------------------------


class TestNvidiaSamplingParams:
    """Tests for top_p / seed, which OpenAIClient.ask cannot forward.

    ``OpenAIClient.ask`` has a fixed signature with no ``**kwargs``, so these
    ride a ContextVar down to ``_chat_completion``.
    """

    @pytest.mark.asyncio
    async def test_top_p_and_seed_reach_the_request(self, client):
        """Per-call top_p / seed are merged into the SDK call."""
        captured: dict = {}

        async with mocked_sdk(client, captured):
            await client.ask("hello", top_p=0.95, seed=42)

        assert captured["top_p"] == 0.95
        assert captured["seed"] == 42

    @pytest.mark.asyncio
    async def test_nothing_sent_when_not_requested(self, client):
        """Neither key is put on the wire when the caller says nothing.

        Guards the regression risk in defaulting from ``self.top_p``, which
        AbstractClient sets to 0.2 whether or not the caller asked for it.
        """
        captured: dict = {}

        async with mocked_sdk(client, captured):
            await client.ask("hello")

        assert "top_p" not in captured
        assert "seed" not in captured

    def test_abstract_client_top_p_default_is_not_adopted(self, client):
        """self.top_p exists but must not become the injected default."""
        # AbstractClient assigns 0.2 when the caller passes nothing...
        assert client.top_p == 0.2
        # ...but the client must not treat that as an explicit request.
        assert client._default_top_p is None

    @pytest.mark.asyncio
    async def test_constructor_values_used_as_defaults(self):
        """top_p / seed given to the constructor apply to every call."""
        c = NvidiaClient(api_key="k", top_p=0.9, seed=7)
        assert c._default_top_p == 0.9
        assert c.seed == 7

        captured: dict = {}
        async with mocked_sdk(c, captured):
            await c.ask("hello")

        assert captured["top_p"] == 0.9
        assert captured["seed"] == 7

    @pytest.mark.asyncio
    async def test_per_call_overrides_constructor(self):
        """A per-call value wins over the per-instance default."""
        c = NvidiaClient(api_key="k", top_p=0.9, seed=7)

        captured: dict = {}
        async with mocked_sdk(c, captured):
            await c.ask("hello", top_p=0.1, seed=99)

        assert captured["top_p"] == 0.1
        assert captured["seed"] == 99

    @pytest.mark.asyncio
    async def test_sampling_coexists_with_thinking(self, client):
        """Sampling injection does not disturb the enable_thinking payload."""
        captured: dict = {}

        async with mocked_sdk(client, captured):
            await client.ask("hello", enable_thinking=True, top_p=0.5, seed=1)

        assert captured["top_p"] == 0.5
        assert captured["seed"] == 1
        ctk = captured["extra_body"]["chat_template_kwargs"]
        assert ctk["enable_thinking"] is True

    @pytest.mark.asyncio
    async def test_context_is_reset_between_calls(self):
        """A call with sampling params must not leak into the next call."""
        c = NvidiaClient(api_key="k")

        first: dict = {}
        async with mocked_sdk(c, first):
            await c.ask("one", top_p=0.3, seed=5)
        assert first["top_p"] == 0.3

        second: dict = {}
        async with mocked_sdk(c, second):
            await c.ask("two")
        assert "top_p" not in second, "sampling params leaked across calls"
        assert "seed" not in second

    @pytest.mark.asyncio
    async def test_stream_applies_sampling_params(self, client):
        """Streaming now injects top_p / seed instead of raising.

        This test previously asserted a ``NotImplementedError``. That guard
        existed because ``ask_stream`` did not set ``_sampling_ctx``, so the
        parameters would have been silently dropped — but once TASK-2298
        routed streaming through ``_chat_completion`` (the same injection
        point ``ask`` uses), the limitation was stale plumbing rather than a
        real constraint. Reasoning models make this matter: streaming is
        their natural mode, and it was the one mode that could not be tuned.
        """
        captured: dict = {}
        mock_create = _fake_stream_create(["a"])

        async def _capture(**kwargs):
            captured.update(kwargs)
            return await mock_create(**kwargs)

        fake_sdk = MagicMock()
        fake_sdk.chat.completions.create = _capture

        with patch.object(
            NvidiaClient, "get_client", new=AsyncMock(return_value=fake_sdk)
        ):
            async with client:
                async for _ in client.ask_stream("hello", top_p=0.95, seed=42):
                    pass

        assert captured["top_p"] == 0.95
        assert captured["seed"] == 42

    @pytest.mark.asyncio
    async def test_stream_applies_reasoning_budget_via_extra_body(self, client):
        """``reasoning_budget`` is a NIM extension, so it must ride extra_body.

        Passing it as a keyword argument would raise ``TypeError`` from the
        OpenAI SDK, whose ``create()`` signature does not define it.
        """
        captured: dict = {}
        mock_create = _fake_stream_create(["a"])

        async def _capture(**kwargs):
            captured.update(kwargs)
            return await mock_create(**kwargs)

        fake_sdk = MagicMock()
        fake_sdk.chat.completions.create = _capture

        with patch.object(
            NvidiaClient, "get_client", new=AsyncMock(return_value=fake_sdk)
        ):
            async with client:
                async for _ in client.ask_stream("hello", reasoning_budget=512):
                    pass

        assert "reasoning_budget" not in captured, "must not be a top-level kwarg"
        assert captured["extra_body"]["reasoning_budget"] == 512

    @pytest.mark.asyncio
    async def test_stream_still_works_without_sampling_params(self, client):
        """The guard does not disturb ordinary streaming.

        FEAT-438 TASK-2300: mocks the SDK level (via get_client), not
        OpenAIClient.ask_stream — NvidiaClient no longer has OpenAIClient
        in its MRO, so patching the old parent has no effect."""
        mock_create = _fake_stream_create(["a"])
        fake_sdk = MagicMock()
        fake_sdk.chat.completions.create = mock_create

        with patch.object(
            NvidiaClient, "get_client", new=AsyncMock(return_value=fake_sdk)
        ):
            async with client:
                chunks = [
                    chunk async for chunk in client.ask_stream("hello") if isinstance(chunk, str)
                ]

        assert chunks == ["a"]


# ---------------------------------------------------------------------------
# TestSlidingWindowRateLimiter
# ---------------------------------------------------------------------------


class TestSlidingWindowRateLimiter:
    """Tests for the standalone sliding-window limiter."""

    def test_rejects_invalid_limit(self):
        """limit < 1 is a construction error."""
        with pytest.raises(ValueError, match="limit must be >= 1"):
            SlidingWindowRateLimiter(limit=0)

    def test_rejects_invalid_window(self):
        """window <= 0 is a construction error."""
        with pytest.raises(ValueError, match="window must be > 0"):
            SlidingWindowRateLimiter(limit=5, window=0)

    def test_exposes_limit_and_window(self):
        """limit / window are readable properties."""
        limiter = SlidingWindowRateLimiter(limit=7, window=30.0)
        assert limiter.limit == 7
        assert limiter.window == 30.0

    @pytest.mark.asyncio
    async def test_admits_up_to_limit_without_waiting(self):
        """The first `limit` acquisitions return immediately."""
        limiter = SlidingWindowRateLimiter(limit=3, window=60.0)

        waits = [await limiter.acquire() for _ in range(3)]

        assert waits == [0.0, 0.0, 0.0]
        assert limiter.current_usage() == 3

    @pytest.mark.asyncio
    async def test_throttles_beyond_limit(self):
        """The (limit + 1)-th acquisition sleeps until the window has room."""
        limiter = SlidingWindowRateLimiter(limit=2, window=0.25)

        await limiter.acquire()
        await limiter.acquire()

        loop = asyncio.get_running_loop()
        start = loop.time()
        waited = await limiter.acquire()
        elapsed = loop.time() - start

        # It had to wait for the oldest of the two hits to age out.
        assert waited > 0
        assert elapsed >= 0.2, f"expected to be throttled, only slept {elapsed:.3f}s"
        # Never over-admits: the pruned window still holds at most `limit`.
        assert limiter.current_usage() <= 2

    @pytest.mark.asyncio
    async def test_window_slides_so_old_hits_stop_counting(self):
        """Once hits age out, acquisitions are free again."""
        limiter = SlidingWindowRateLimiter(limit=1, window=0.1)

        await limiter.acquire()
        await asyncio.sleep(0.15)  # let the single hit age out

        assert limiter.current_usage() == 0
        assert await limiter.acquire() == 0.0

    @pytest.mark.asyncio
    async def test_max_wait_raises_instead_of_blocking(self):
        """With max_wait set, a saturated window raises rather than sleeping."""
        limiter = SlidingWindowRateLimiter(limit=1, window=30.0)
        await limiter.acquire()

        with pytest.raises(NvidiaRateLimitError) as excinfo:
            await limiter.acquire(max_wait=0.05)

        assert excinfo.value.retry_after is not None
        assert excinfo.value.retry_after > 0
        # The failed attempt must not have consumed a slot.
        assert limiter.current_usage() == 1

    @pytest.mark.asyncio
    async def test_concurrent_acquire_never_over_admits(self):
        """Concurrent waiters are serialised: the window is never exceeded."""
        limiter = SlidingWindowRateLimiter(limit=4, window=60.0)

        waits = await asyncio.gather(*(limiter.acquire() for _ in range(4)))

        assert all(w == 0.0 for w in waits)
        assert limiter.current_usage() == 4


# ---------------------------------------------------------------------------
# TestNvidiaFreeTierFlag
# ---------------------------------------------------------------------------


class TestNvidiaFreeTierFlag:
    """Tests for the free_tier flag and its rate-limiter wiring."""

    def test_free_tier_on_by_default(self, client):
        """free_tier defaults to True with a 40 rpm limiter attached."""
        assert client.free_tier is True
        assert client.requests_per_minute == FREE_TIER_RPM == 40
        assert isinstance(client._rate_limiter, SlidingWindowRateLimiter)
        assert client._rate_limiter.limit == 40
        assert client._rate_limiter.window == 60.0

    def test_free_tier_disabled_removes_limiter(self):
        """free_tier=False attaches no limiter at all."""
        c = NvidiaClient(api_key="k", free_tier=False)
        assert c.free_tier is False
        assert c._rate_limiter is None

    def test_free_tier_env_override(self, monkeypatch):
        """free_tier=None reads NVIDIA_FREE_TIER via config.getboolean."""
        from parrot.clients import nvidia as nvidia_mod

        monkeypatch.setattr(
            nvidia_mod.config,
            "getboolean",
            lambda key, fallback=None: (
                False if key == "NVIDIA_FREE_TIER" else fallback
            ),
        )
        c = NvidiaClient(api_key="k")  # free_tier not passed → env consulted
        assert c.free_tier is False
        assert c._rate_limiter is None

    def test_explicit_flag_beats_env(self, monkeypatch):
        """An explicit free_tier argument is not overridden by the env var."""
        from parrot.clients import nvidia as nvidia_mod

        monkeypatch.setattr(
            nvidia_mod.config,
            "getboolean",
            lambda key, fallback=None: False,
        )
        c = NvidiaClient(api_key="k", free_tier=True)
        assert c.free_tier is True
        assert c._rate_limiter is not None

    def test_custom_requests_per_minute(self):
        """requests_per_minute overrides the 40 rpm default."""
        c = NvidiaClient(api_key="k", requests_per_minute=5)
        assert c.requests_per_minute == 5
        assert c._rate_limiter.limit == 5

    def test_rate_limit_max_wait_stored(self):
        """rate_limit_max_wait is retained for later acquire() calls."""
        c = NvidiaClient(api_key="k", rate_limit_max_wait=2.5)
        assert c.rate_limit_max_wait == 2.5

    def test_limiter_is_per_instance(self):
        """Two clients on the same key own independent windows (documented limit)."""
        a = NvidiaClient(api_key="same-key")
        b = NvidiaClient(api_key="same-key")
        assert a._rate_limiter is not b._rate_limiter

    def test_factory_forwards_free_tier(self):
        """LLMFactory.create passes free_tier through to the client."""
        c = LLMFactory.create("nvidia", api_key="k", free_tier=False)
        assert isinstance(c, NvidiaClient)
        assert c.free_tier is False


# ---------------------------------------------------------------------------
# TestNvidiaRateLimitIntegration
# ---------------------------------------------------------------------------


class TestNvidiaRateLimitIntegration:
    """Tests that the limiter is actually consulted on real call paths."""

    @pytest.mark.asyncio
    async def test_ask_consumes_a_slot(self, client):
        """A completed ask() occupies exactly one slot in the window."""
        async with mocked_sdk(client):
            await client.ask("hello")

        assert client._rate_limiter.current_usage() == 1

    @pytest.mark.asyncio
    async def test_ask_throttles_when_window_full(self):
        """ask() blocks while the window is saturated, then proceeds."""
        c = NvidiaClient(api_key="k", requests_per_minute=1)
        # Shrink the window so the test stays fast.
        c._rate_limiter = SlidingWindowRateLimiter(limit=1, window=0.25)

        async with mocked_sdk(c):
            await c.ask("first")  # fills the window

            loop = asyncio.get_running_loop()
            start = loop.time()
            await c.ask("second")  # must wait for the first to age out
            elapsed = loop.time() - start

        assert elapsed >= 0.2, f"ask() was not throttled (took {elapsed:.3f}s)"

    @pytest.mark.asyncio
    async def test_ask_raises_when_max_wait_exceeded(self):
        """With rate_limit_max_wait, a saturated window surfaces the error."""
        c = NvidiaClient(
            api_key="k", requests_per_minute=1, rate_limit_max_wait=0.05
        )

        async with mocked_sdk(c):
            await c.ask("first")

            with pytest.raises(NvidiaRateLimitError):
                await c.ask("second")

    @pytest.mark.asyncio
    async def test_no_throttling_when_free_tier_off(self):
        """free_tier=False issues back-to-back calls with no delay."""
        c = NvidiaClient(api_key="k", free_tier=False)

        async with mocked_sdk(c) as mock_create:
            loop = asyncio.get_running_loop()
            start = loop.time()
            for _ in range(5):
                await c.ask("hi")
            elapsed = loop.time() - start

        assert mock_create.await_count == 5
        assert elapsed < 0.2, f"unexpected throttling with free_tier=False ({elapsed:.3f}s)"

    @pytest.mark.asyncio
    async def test_each_retry_consumes_a_slot(self, client):
        """Retried attempts count against the quota — a retry is a real request."""
        from openai import APIConnectionError

        calls = {"n": 0}

        async def _flaky_create(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise APIConnectionError(request=MagicMock())
            return make_mock_completion()

        async with mocked_sdk(client, side_effect=_flaky_create):
            await client.ask("hello")

        assert calls["n"] == 2
        assert client._rate_limiter.current_usage() == 2

    @pytest.mark.asyncio
    async def test_invoke_consumes_a_slot(self, client):
        """FEAT-438 TASK-2300: invoke() has no override on NvidiaClient — it
        is inherited from OpenAIBaseClient, which now routes through
        _chat_completion (the completion funnel, TASK-2298). The free-tier
        rate limiter — previously only reachable via ask()/ask_stream() —
        now covers invoke() too, with no extra code on NvidiaClient's part.

        Passes model= explicitly: NvidiaClient never sets self.model, and
        _resolve_invoke_model() falls back to self.model (not
        _default_model) when no model is given — a pre-existing,
        unrelated gap, not something this task's rebase changes."""
        async with mocked_sdk(client):
            await client.invoke("hello", model="minimaxai/minimax-m3")

        assert client._rate_limiter.current_usage() == 1

    @pytest.mark.asyncio
    async def test_ask_stream_consumes_a_slot(self, client):
        """FEAT-438 TASK-2300: ask_stream() no longer reserves a slot itself
        — it now routes through _chat_completion (the completion funnel,
        TASK-2298), which reserves the slot. End-to-end: a stream still
        consumes exactly one slot, with no double-count."""
        mock_create = _fake_stream_create(["chunk-a", "chunk-b"])
        fake_sdk = MagicMock()
        fake_sdk.chat.completions.create = mock_create

        with patch.object(
            NvidiaClient, "get_client", new=AsyncMock(return_value=fake_sdk)
        ):
            async with client:
                chunks = [
                    c async for c in client.ask_stream("hello") if isinstance(c, str)
                ]

        assert chunks == ["chunk-a", "chunk-b"]
        assert client._rate_limiter.current_usage() == 1

    @pytest.mark.asyncio
    async def test_ask_stream_not_throttled_when_free_tier_off(self):
        """free_tier=False leaves ask_stream unthrottled and limiter-free."""
        c = NvidiaClient(api_key="k", free_tier=False)
        mock_create = _fake_stream_create(["x"])
        fake_sdk = MagicMock()
        fake_sdk.chat.completions.create = mock_create

        with patch.object(
            NvidiaClient, "get_client", new=AsyncMock(return_value=fake_sdk)
        ):
            async with c:
                chunks = [
                    chunk async for chunk in c.ask_stream("hello") if isinstance(chunk, str)
                ]

        assert chunks == ["x"]
        assert c._rate_limiter is None


# ---------------------------------------------------------------------------
# TestNvidiaModelEnum
# ---------------------------------------------------------------------------


class TestNvidiaModelEnum:
    """Tests that NvidiaModel enum members have the correct values."""

    EXPECTED = {
        "KIMI_K2_6": "moonshotai/kimi-k2.6",
        "MINIMAX_M3": "minimaxai/minimax-m3",
        "DEEPSEEK_V4_PRO": "deepseek-ai/deepseek-v4-pro",
        "DEEPSEEK_V4_FLASH": "deepseek-ai/deepseek-v4-flash",
        "MISTRAL_NEMOTRON": "mistralai/mistral-nemotron",
        "LAGUNA_XS_2_1": "poolside/laguna-xs-2.1",
        "LLAMA_3_3_70B_INSTRUCT": "meta/llama-3.3-70b-instruct",
        "GPT_OSS_120B": "openai/gpt-oss-120b",
        "NEMOTRON_3_NANO_30B": "nvidia/nemotron-3-nano-30b-a3b",
        "NEMOTRON_3_NANO_OMNI_30B_REASONING": (
            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
        ),
        "GLM_5_2": "z-ai/glm-5.2",
        "STEPFUN_STEP_3_7_FLASH": "stepfun-ai/step-3.7-flash",
    }

    #: Slugs withdrawn from the NIM catalog (410 Gone / 404). Guarded against
    #: so a stale slug can never silently reappear in the enum.
    WITHDRAWN = {
        "moonshotai/kimi-k2-thinking",
        "moonshotai/kimi-k2-instruct-0905",
        "moonshotai/kimi-k2.5",
        "minimaxai/minimax-m2.5",
        "minimaxai/minimax-m2.7",
        "mistralai/mamba-codestral-7b-v0.1",
        "deepseek-ai/deepseek-v3.1-terminus",
        "qwen/qwen3.5-397b-a17b",
        "z-ai/glm-5.1",
    }

    def test_nvidia_model_enum_values(self):
        """All model slugs are present and match the live-verified strings."""
        for member_name, expected_value in self.EXPECTED.items():
            member = NvidiaModel[member_name]
            assert member.value == expected_value, (
                f"NvidiaModel.{member_name}.value expected {expected_value!r}, "
                f"got {member.value!r}"
            )

    def test_nvidia_model_importable_from_parrot_models(self):
        """NvidiaModel is re-exported from parrot.models (not just parrot.models.nvidia)."""
        from parrot.models import NvidiaModel as NM
        assert NM is NvidiaModel

    def test_enum_has_no_withdrawn_slugs(self):
        """No end-of-life slug may reappear in the enum."""
        live = {m.value for m in NvidiaModel}
        assert not (live & self.WITHDRAWN), (
            f"withdrawn slug(s) back in NvidiaModel: {sorted(live & self.WITHDRAWN)}"
        )

    def test_enum_membership_is_exactly_expected(self):
        """The enum contains exactly the expected members — no extras, no aliases."""
        assert {m.name: m.value for m in NvidiaModel} == self.EXPECTED

    def test_no_alias_members(self):
        """Every member has a distinct value.

        A str-Enum silently turns a duplicated value into an alias of the first
        member, so ``KIMI_K2_THINKING`` and ``KIMI_K2_5`` sharing one slug would
        make the former resolve to a non-thinking model. ``__members__`` counts
        aliases while iteration does not, so comparing the two detects it.
        """
        assert len(NvidiaModel.__members__) == len(list(NvidiaModel))

    def test_slugs_are_vendor_prefixed(self):
        """Every slug uses NIM's ``vendor/model`` form (vendor may contain a dash)."""
        for member in NvidiaModel:
            assert "/" in member.value, f"{member.name} is not vendor-prefixed"
            vendor, _, model = member.value.partition("/")
            assert vendor and model, f"{member.name} has an empty segment"


# ---------------------------------------------------------------------------
# TestNvidiaFactory
# ---------------------------------------------------------------------------


class TestNvidiaFactory:
    """Tests for LLMFactory registration of NvidiaClient."""

    def test_factory_registration(self):
        """'nvidia' key is present in SUPPORTED_CLIENTS and maps to NvidiaClient."""
        assert "nvidia" in SUPPORTED_CLIENTS
        assert SUPPORTED_CLIENTS["nvidia"] is NvidiaClient

        # Factory creates the right client type with the right model
        c = LLMFactory.create(
            "nvidia:moonshotai/kimi-k2-thinking",
            api_key="test-key",
        )
        assert isinstance(c, NvidiaClient)
        assert c.model == "moonshotai/kimi-k2-thinking"

    def test_factory_default_model(self):
        """LLMFactory.create('nvidia') returns an NvidiaClient using _default_model."""
        c = LLMFactory.create("nvidia", api_key="test-key")
        assert isinstance(c, NvidiaClient)
        assert c._default_model == NvidiaModel.MINIMAX_M3.value


# ---------------------------------------------------------------------------
# Live integration tests (skipped unless NVIDIA_API_KEY is set)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _navconfig.get("NVIDIA_API_KEY"),
    reason="NVIDIA_API_KEY not set — skipping live integration test",
)
class TestNvidiaIntegration:
    """End-to-end tests that require a real NVIDIA_API_KEY."""

    @pytest.mark.asyncio
    async def test_completion_e2e_kimi(self):
        """Live completion against minimaxai/minimax-m3.

        The ``async with`` is required: ``ask()`` does not call
        ``_ensure_client()``, so without entering the context ``self.client``
        stays ``None``.
        """
        async with NvidiaClient(model=NvidiaModel.MINIMAX_M3.value) as c:
            response = await c.ask("Say hello in one word.")
        assert response is not None

    @pytest.mark.asyncio
    async def test_streaming_e2e_reasoning(self):
        """Live streaming + enable_thinking against a reasoning model.

        Repointed from ``z-ai/glm-5.2``, which reached end of life on
        2026-08-21 and now answers every request with ``410 Gone`` — the test
        was failing against the live API regardless of client behavior.
        """
        chunks = []
        model = NvidiaModel.NEMOTRON_3_NANO_OMNI_30B_REASONING.value
        async with NvidiaClient(model=model) as c:
            async for chunk in c.ask_stream("Count to three.", enable_thinking=True):
                chunks.append(chunk)
        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_reasoning_surfaced_on_aimessage(self):
        """A reasoning model's thinking lands on ``AIMessage.reasoning``.

        It arrives in ``choices[].message.reasoning_content`` and used to be
        reachable only by digging through ``raw_response``.
        """
        model = NvidiaModel.NEMOTRON_3_NANO_OMNI_30B_REASONING.value
        async with NvidiaClient(model=model) as c:
            response = await c.ask("What is 17*23? Think it through.")

        assert response.reasoning, "reasoning_content was not surfaced"
        assert response.reasoning != response.output, "reasoning leaked into the answer"
