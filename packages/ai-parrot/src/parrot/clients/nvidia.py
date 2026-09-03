"""Nvidia NIM client for AI-Parrot.

Extends OpenAIBaseClient to route requests through Nvidia's OpenAI-compatible
NIM gateway at https://integrate.api.nvidia.com/v1.

All completion, streaming, tool-calling, retry, and invoke logic is inherited
from OpenAIBaseClient unchanged. Two Nvidia-specific affordances are added:

1. The ``enable_thinking`` keyword on ``ask`` / ``ask_stream`` that injects
   ``chat_template_kwargs`` into ``extra_body`` for reasoning-capable models
   such as ``nvidia/nemotron-3-nano-omni-30b-a3b-reasoning``.
2. A ``free_tier`` flag (default ``True``) that throttles outbound requests to
   Nvidia's free-endpoint quota of 40 requests per minute.  Set
   ``free_tier=False`` — or ``NVIDIA_FREE_TIER=false`` in the environment — for
   paid/self-hosted NIM endpoints that carry no such cap.
"""
import asyncio
import contextvars
from collections import deque
from typing import Any, AsyncIterator, Deque, Dict, Optional

from navconfig import config
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..exceptions import ParrotError
from ..models import AIMessage
from .openai_base import OpenAIBaseClient
from ..models.nvidia import NvidiaModel

#: Requests-per-minute quota enforced on Nvidia's free NIM endpoints.
FREE_TIER_RPM: int = 40

#: Length of the rate-limit window, in seconds.
RATE_LIMIT_WINDOW: float = 60.0

# Context variable that carries enable_thinking / clear_thinking flags from
# ask / ask_stream down to _chat_completion without altering the parent's
# call signatures.  Using a ContextVar is safe for concurrent async calls
# because each asyncio Task inherits an isolated copy of the context.
_thinking_ctx: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar(
    "_nvidia_thinking_ctx", default={}
)

# Sampling parameters that ``OpenAIBaseClient.ask`` cannot accept.  Its signature is
# fixed and carries no ``**kwargs``, so passing ``top_p``/``seed`` to it raises
# TypeError.  They ride the same ContextVar channel as the thinking flags and
# are merged into the request inside ``_chat_completion``.
_sampling_ctx: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar(
    "_nvidia_sampling_ctx", default={}
)

#: Sampling parameters this client can inject that the parent cannot forward.
#: ``top_p`` is deliberately NOT defaulted from ``self.top_p``: ``AbstractClient``
#: assigns it ``0.2`` when the caller says nothing (base.py:319), and silently
#: sending that would change results for every existing Nvidia call.
#:
#: These are all *native* OpenAI parameters, so they are passed straight to
#: ``client.chat.completions.create()`` as keyword arguments.
INJECTABLE_SAMPLING_PARAMS: tuple[str, ...] = ("top_p", "seed")

#: NIM-only request parameters, which must travel inside ``extra_body`` rather
#: than as keyword arguments: the OpenAI SDK's ``create()`` has an explicit
#: signature and raises ``TypeError`` on any keyword it does not define, so
#: passing these directly would break the call before it left the process.
#:
#: ``reasoning_budget`` caps how many tokens a reasoning model may spend on
#: ``reasoning_content`` before it must start answering. It is only sent when
#: explicitly requested — NIM applies its own per-model default otherwise, and
#: inventing a number here would silently cap every reasoning call.
INJECTABLE_EXTRA_BODY_PARAMS: tuple[str, ...] = ("reasoning_budget",)


class NvidiaRateLimitError(ParrotError):
    """Raised when a free-tier slot could not be acquired within ``max_wait``.

    Only raised when :class:`NvidiaClient` was constructed with an explicit
    ``rate_limit_max_wait``.  With the default (``None``) the client waits as
    long as necessary instead of raising.

    Args:
        message: Human-readable error description.
        *args: Forwarded to :class:`~parrot.exceptions.ParrotError`.
        retry_after: Seconds the caller should wait before retrying, when known.
        **kwargs: Forwarded to :class:`~parrot.exceptions.ParrotError`.

    Attributes:
        retry_after: Seconds until a slot is expected to free up, or ``None``.
    """

    def __init__(
        self,
        message: str,
        *args,
        retry_after: Optional[float] = None,
        **kwargs,
    ) -> None:
        super().__init__(message, *args, **kwargs)
        self.retry_after: Optional[float] = retry_after


class SlidingWindowRateLimiter:
    """Async sliding-window rate limiter.

    Admits at most ``limit`` acquisitions in any trailing ``window`` seconds.
    Unlike a fixed-window counter, a sliding window cannot be defeated by
    bursting across a window boundary, which matters because Nvidia measures
    its 40 rpm free-tier quota continuously.

    Timestamps come from the running event loop's monotonic clock
    (``loop.time()``), so the limiter is unaffected by wall-clock adjustments.

    The limiter is *not* shared between instances: each :class:`NvidiaClient`
    owns its own window.  Nvidia enforces the quota per account, so N clients
    sharing one API key can collectively exceed 40 rpm.

    Args:
        limit: Maximum number of acquisitions per window. Must be >= 1.
        window: Window length in seconds. Must be > 0.

    Raises:
        ValueError: If ``limit`` < 1 or ``window`` <= 0.

    Example::

        limiter = SlidingWindowRateLimiter(limit=40, window=60.0)
        waited = await limiter.acquire()
    """

    #: Added to every computed sleep so float imprecision can never cause a
    #: spin where the woken waiter finds the oldest hit still inside the window.
    _EPSILON: float = 0.001

    def __init__(self, limit: int, window: float = RATE_LIMIT_WINDOW) -> None:
        if limit < 1:
            raise ValueError(f"limit must be >= 1, got {limit!r}")
        if window <= 0:
            raise ValueError(f"window must be > 0, got {window!r}")
        self._limit: int = int(limit)
        self._window: float = float(window)
        self._hits: Deque[float] = deque()
        self._lock: asyncio.Lock = asyncio.Lock()

    @property
    def limit(self) -> int:
        """Maximum acquisitions allowed per window."""
        return self._limit

    @property
    def window(self) -> float:
        """Window length in seconds."""
        return self._window

    def _prune(self, now: float) -> None:
        """Drop recorded hits that have aged out of the trailing window.

        Args:
            now: Current monotonic time, from ``loop.time()``.
        """
        cutoff = now - self._window
        while self._hits and self._hits[0] <= cutoff:
            self._hits.popleft()

    def current_usage(self) -> int:
        """Return how many acquisitions currently occupy the window.

        Intended for logging and tests; the value is a snapshot and may be
        stale as soon as it is returned. Must be called from inside a running
        event loop, since the window is measured on that loop's clock.

        Returns:
            Number of hits still inside the trailing window.

        Raises:
            RuntimeError: If called with no running event loop.
        """
        self._prune(asyncio.get_running_loop().time())
        return len(self._hits)

    async def acquire(self, max_wait: Optional[float] = None) -> float:
        """Reserve one slot, sleeping while the window is saturated.

        Args:
            max_wait: Maximum total seconds to wait. ``None`` waits as long as
                necessary. When the projected wait exceeds this budget the
                call raises instead of sleeping, and no slot is consumed.

        Returns:
            Total seconds spent waiting (``0.0`` when a slot was free).

        Raises:
            NvidiaRateLimitError: If a slot could not be reserved within
                ``max_wait`` seconds.
        """
        waited = 0.0
        while True:
            async with self._lock:
                now = asyncio.get_running_loop().time()
                self._prune(now)
                if len(self._hits) < self._limit:
                    self._hits.append(now)
                    return waited
                # Window is full: the oldest hit dictates when a slot frees.
                sleep_for = max(self._hits[0] + self._window - now, 0.0)
            sleep_for += self._EPSILON
            if max_wait is not None and waited + sleep_for > max_wait:
                raise NvidiaRateLimitError(
                    f"Nvidia free-tier rate limit reached "
                    f"({self._limit} requests / {self._window:g}s); a slot would "
                    f"not free up within max_wait={max_wait:g}s",
                    retry_after=sleep_for,
                )
            await asyncio.sleep(sleep_for)
            waited += sleep_for


class NvidiaClient(OpenAIBaseClient):
    """Client for Nvidia NIM's OpenAI-compatible API gateway.

    Routes all requests through ``https://integrate.api.nvidia.com/v1`` and
    resolves the API key from the constructor argument or the ``NVIDIA_API_KEY``
    environment variable (via ``navconfig.config``).

    All inherited OpenAI machinery — ``ask``, ``ask_stream``, ``invoke``,
    ``_chat_completion``, tool calling, structured output, and retry — works
    without modification.

    Two Nvidia-specific affordances are layered on top:

    **Thinking flags.** The ``enable_thinking`` shortcut on ``ask`` /
    ``ask_stream`` injects ``chat_template_kwargs`` into ``extra_body`` for
    reasoning-capable models (e.g. ``nvidia/nemotron-3-nano-omni-30b-a3b-reasoning``).  It is propagated to
    ``_chat_completion`` via an async context variable so that no changes to
    the parent's call signatures are required.

    **Free-tier rate limiting.** Nvidia's free NIM endpoints cap traffic at 40
    requests per minute.  With ``free_tier=True`` (the default) every outbound
    request first reserves a slot in a :class:`SlidingWindowRateLimiter`,
    async-sleeping when the window is saturated so the quota is never
    exceeded.  Set ``free_tier=False`` for paid or self-hosted NIM endpoints to
    remove the cap entirely.  The limiter covers ``ask``, ``invoke``,
    ``ask_stream``, and every other path routed through ``_chat_completion``;
    each retry attempt consumes its own slot, since a retry is a real request.
    Inherited OpenAI-only vision helpers (e.g. ``ask_to_image``) call the SDK
    directly and are therefore not counted.

    Args:
        api_key: Nvidia NIM API key. Falls back to ``NVIDIA_API_KEY`` env var
            (resolved via ``navconfig.config``).
        free_tier: When ``True`` (default), throttle requests to
            ``requests_per_minute``. When ``None``, the value is read from the
            ``NVIDIA_FREE_TIER`` env var, itself defaulting to ``True``.
            :data:`~parrot.models.nvidia.FREE_TIER_MODELS` lists the models
            NVIDIA publishes as free preview endpoints — the ones this
            throttle exists for. Note that a free endpoint answers ``503
            ResourceExhausted`` when it is at capacity; that is saturation,
            not a bad model id, and the right response is to retry rather
            than switch models.
        requests_per_minute: Requests allowed per 60s window while
            ``free_tier`` is active. Defaults to :data:`FREE_TIER_RPM` (40).
        rate_limit_max_wait: Maximum seconds to wait for a free-tier slot.
            ``None`` (default) waits as long as necessary; a number makes the
            client raise :class:`NvidiaRateLimitError` rather than block past
            that budget.
        seed: Default sampling seed for reproducibility, overridable per call.
        reasoning_budget: Default cap on the tokens a reasoning model may
            spend on ``reasoning_content`` before it must answer, overridable
            per call. ``None`` (default) sends nothing and lets NIM apply its
            own per-model default.
        **kwargs: Additional arguments passed to ``OpenAIBaseClient`` /
            ``AbstractClient``. Notably ``timeout`` (defaults to
            :attr:`_default_timeout`, 300s — reasoning calls are slow) and
            ``max_tokens`` (defaults to :attr:`_default_max_tokens`, 65536 —
            reasoning shares the answer's budget).

    Example::

        client = NvidiaClient(model=NvidiaModel.GLM_5_2)
        response = await client.ask(
            "Explain gradient descent.",
            enable_thinking=True,
        )

        # Paid endpoint — no throttling.
        paid = NvidiaClient(free_tier=False)

        # Free endpoint, but fail fast instead of waiting more than 5s.
        strict = NvidiaClient(rate_limit_max_wait=5.0)
    """

    client_type: str = "nvidia"
    client_name: str = "nvidia"
    _default_model: str = NvidiaModel.MINIMAX_M3.value

    # NIM's reasoning models routinely take longer than the 60s
    # OpenAIBaseClient default: a measured single-turn word problem against
    # ``nemotron-3-nano-omni-30b-a3b-reasoning`` took 96.8s end to end, which
    # failed with APITimeoutError against a perfectly healthy endpoint.
    _default_timeout: float = 300.0

    # NIM accepts 65536 on its current chat models (verified against
    # nemotron-3-nano-omni-30b-a3b-reasoning, minimax-m3 and gpt-oss-120b).
    # ``max_tokens`` is a cap, not a reservation — nothing is billed for
    # headroom that goes unused — and reasoning models need the room because
    # ``reasoning_content`` is drawn from the same budget as the answer.
    _default_max_tokens: int = 65536

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        free_tier: Optional[bool] = None,
        requests_per_minute: Optional[int] = None,
        rate_limit_max_wait: Optional[float] = None,
        seed: Optional[int] = None,
        reasoning_budget: Optional[int] = None,
        **kwargs,
    ):
        resolved_key = api_key or config.get("NVIDIA_API_KEY")

        # Capture an explicit top_p BEFORE super().__init__ runs: AbstractClient
        # assigns self.top_p = kwargs.get('top_p', 0.2), after which an explicit
        # 0.2 is indistinguishable from the default.  Only a caller-supplied
        # value becomes the per-instance default, so existing behaviour (no
        # top_p on the wire) is preserved for everyone who never passed one.
        explicit_top_p = kwargs.get("top_p")

        super().__init__(
            api_key=resolved_key,
            base_url="https://integrate.api.nvidia.com/v1",
            **kwargs,
        )
        # Re-set after super().__init__ because AbstractClient may overwrite
        # self.api_key during its own initialisation.  This mirrors the guard
        # used by OpenRouterClient (openrouter.py:75).
        self.api_key = resolved_key

        # Rate-limit state is built after super().__init__ for the same reason:
        # the parent must not be able to clobber it.
        if free_tier is None:
            free_tier = config.getboolean("NVIDIA_FREE_TIER", fallback=True)
        self.free_tier: bool = bool(free_tier)
        self.requests_per_minute: int = int(
            requests_per_minute if requests_per_minute is not None else FREE_TIER_RPM
        )
        self.rate_limit_max_wait: Optional[float] = rate_limit_max_wait
        self._rate_limiter: Optional[SlidingWindowRateLimiter] = (
            SlidingWindowRateLimiter(self.requests_per_minute, RATE_LIMIT_WINDOW)
            if self.free_tier
            else None
        )

        # Per-instance sampling defaults for the parameters the parent drops.
        self.seed: Optional[int] = seed
        self.reasoning_budget: Optional[int] = reasoning_budget
        self._default_top_p: Optional[float] = explicit_top_p

    def _resolve_sampling(
        self,
        top_p: Optional[float],
        seed: Optional[int],
        reasoning_budget: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Merge per-call sampling overrides over the per-instance defaults.

        Args:
            top_p: Per-call nucleus-sampling value, or ``None`` to fall back to
                the value passed to the constructor.
            seed: Per-call seed, or ``None`` to fall back to the constructor's.
            reasoning_budget: Per-call reasoning-token cap, or ``None`` to fall
                back to the constructor's.

        Returns:
            Only the parameters that resolved to a non-``None`` value, so
            nothing extra is ever put on the wire.
        """
        resolved = {
            "top_p": top_p if top_p is not None else self._default_top_p,
            "seed": seed if seed is not None else self.seed,
            "reasoning_budget": (
                reasoning_budget
                if reasoning_budget is not None
                else self.reasoning_budget
            ),
        }
        return {key: value for key, value in resolved.items() if value is not None}

    async def _acquire_rate_limit_slot(self) -> float:
        """Reserve a free-tier slot before issuing a request.

        A no-op returning ``0.0`` when ``free_tier`` is ``False``.  Otherwise
        delegates to the client's :class:`SlidingWindowRateLimiter`, sleeping
        until the 40 rpm window has room.

        Returns:
            Seconds spent waiting for the slot.

        Raises:
            NvidiaRateLimitError: If ``rate_limit_max_wait`` is set and a slot
                could not be reserved within that budget.
        """
        if self._rate_limiter is None:
            return 0.0
        waited = await self._rate_limiter.acquire(
            max_wait=self.rate_limit_max_wait
        )
        if waited > 0:
            self.logger.warning(
                "Nvidia free-tier limit (%s rpm) reached; throttled for %.2fs. "
                "Pass free_tier=False for paid NIM endpoints.",
                self._rate_limiter.limit,
                waited,
            )
        return waited

    @staticmethod
    def _merge_thinking_extra_body(
        extra_body: Optional[Dict[str, Any]],
        enable_thinking: bool,
        clear_thinking: bool,
    ) -> Optional[Dict[str, Any]]:
        """Merge ``chat_template_kwargs`` reasoning flags into ``extra_body``.

        When ``enable_thinking`` is ``False`` the function returns
        ``extra_body`` completely unchanged (including returning ``None`` when
        ``extra_body`` was ``None``).

        When ``enable_thinking`` is ``True`` the function returns a new dict
        that preserves every existing key in ``extra_body`` and every existing
        key inside ``extra_body["chat_template_kwargs"]``, then adds
        ``enable_thinking`` and ``clear_thinking`` flags.

        This is an internal helper; callers should use the ``enable_thinking``
        keyword on ``ask`` / ``ask_stream`` rather than calling this directly.

        Args:
            extra_body: Existing ``extra_body`` dict (may be ``None``).
            enable_thinking: When ``True``, inject the reasoning flags.
            clear_thinking: Value forwarded to ``clear_thinking`` in the
                injected payload.

        Returns:
            Updated ``extra_body`` dict, or ``None`` when nothing was injected.
        """
        if not enable_thinking:
            return extra_body
        merged: Dict[str, Any] = dict(extra_body or {})
        kwargs_block: Dict[str, Any] = dict(merged.get("chat_template_kwargs") or {})
        kwargs_block["enable_thinking"] = True
        kwargs_block["clear_thinking"] = clear_thinking
        merged["chat_template_kwargs"] = kwargs_block
        return merged

    async def _chat_completion(
        self,
        model: str,
        messages: Any,
        use_tools: bool = False,
        **kwargs,
    ) -> Any:
        """Run a chat completion against NVIDIA NIM via ``create()``.

        Three NVIDIA-specific differences from ``OpenAIBaseClient._chat_completion``:

        1. Always uses ``client.chat.completions.create``. NIM rejects the
           OpenAI SDK's ``parse()`` shortcut (returns 5xx / "page not found"),
           so we never route through it — even when ``use_tools`` is ``False``.
        2. Reads the thinking flags from the async context variable set by
           ``ask`` / ``ask_stream`` and merges them into ``extra_body`` for
           reasoning-capable models (e.g. ``nvidia/nemotron-3-nano-omni-30b-a3b-reasoning``).
        3. Reserves a free-tier rate-limit slot before *each* attempt when
           ``free_tier`` is active, so retries are counted against the quota
           too.

        Args:
            model: Model identifier string.
            messages: Chat messages list.
            use_tools: Whether tools are enabled (kept for parity with parent).
            **kwargs: Additional completion arguments forwarded to the OpenAI SDK.

        Returns:
            Raw OpenAI ``ChatCompletion`` response.

        Raises:
            NvidiaRateLimitError: If ``rate_limit_max_wait`` is set and no
                free-tier slot became available within that budget.
        """
        from openai import (
            APIConnectionError,
            APIError,
            APITimeoutError,
            RateLimitError,
        )
        thinking = _thinking_ctx.get()
        if thinking.get("enable_thinking"):
            kwargs["extra_body"] = self._merge_thinking_extra_body(
                kwargs.get("extra_body"),
                True,
                thinking.get("clear_thinking", False),
            )

        # Inject the sampling parameters the parent's fixed signature drops.
        # An explicit value already in kwargs always wins, so this can never
        # override something a caller managed to set by another route.
        # Native OpenAI parameters go on as keyword arguments; NIM-only ones
        # must be nested under extra_body or the SDK rejects the keyword.
        sampling = _sampling_ctx.get()
        for name, value in sampling.items():
            if name in INJECTABLE_SAMPLING_PARAMS and kwargs.get(name) is None:
                kwargs[name] = value

        nim_params = {
            name: value
            for name, value in sampling.items()
            if name in INJECTABLE_EXTRA_BODY_PARAMS
        }
        if nim_params:
            extra_body = dict(kwargs.get("extra_body") or {})
            # An explicit extra_body entry always wins, mirroring the rule
            # applied to the keyword parameters above.
            for name, value in nim_params.items():
                extra_body.setdefault(name, value)
            kwargs["extra_body"] = extra_body
        # APITimeoutError is a *subclass* of APIConnectionError, so it used to
        # be swept into the retry set. That is the worst possible thing to
        # retry here: a reasoning request that outran the timeout is not a
        # transient fault, and each retry pays the full timeout again *and*
        # makes the endpoint regenerate the whole answer from scratch. Three
        # attempts at the 300s default would block for 15 minutes before
        # surfacing the same error. Fail on the first one instead, and tell the
        # caller which knob actually fixes it.
        retry_policy = AsyncRetrying(
            retry=(
                retry_if_exception_type(
                    (APIConnectionError, RateLimitError, APIError)
                )
                & retry_if_not_exception_type(APITimeoutError)
            ),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            stop=stop_after_attempt(3),
            reraise=True,
        )
        async for attempt in retry_policy:
            with attempt:
                await self._acquire_rate_limit_slot()
                return await self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    **kwargs,
                )

    async def ask(
        self,
        prompt: str,
        *,
        enable_thinking: bool = False,
        clear_thinking: bool = False,
        top_p: Optional[float] = None,
        seed: Optional[int] = None,
        reasoning_budget: Optional[int] = None,
        **kwargs,
    ) -> AIMessage:
        """Submit a prompt and return the full response.

        Identical to ``OpenAIBaseClient.ask`` with two additions:

        1. An ``enable_thinking`` shortcut that injects
           ``chat_template_kwargs`` into ``extra_body`` for reasoning-capable
           models (e.g. ``nvidia/nemotron-3-nano-omni-30b-a3b-reasoning``).
        2. ``top_p`` and ``seed`` support. ``OpenAIBaseClient.ask`` has a fixed
           signature with no ``**kwargs``, so passing either to it raises
           ``TypeError``; both are accepted here and merged into the request
           inside ``_chat_completion``.

        All of it travels via async context variables, so the parent's call
        signature is preserved.

        Args:
            prompt: User message text.
            enable_thinking: When ``True``, add
                ``extra_body["chat_template_kwargs"]["enable_thinking"] = True``.
            clear_thinking: Forwarded to ``clear_thinking`` in the payload
                when ``enable_thinking`` is ``True``.
            top_p: Nucleus-sampling value. Defaults to the ``top_p`` passed to
                the constructor; when neither is given, none is sent and the
                endpoint's own default applies.
            seed: Sampling seed for reproducibility. Defaults to the ``seed``
                passed to the constructor.
            reasoning_budget: Maximum tokens a reasoning model may spend on
                ``reasoning_content`` before answering. Defaults to the
                constructor's value; when neither is given, NIM's own
                per-model default applies.
            **kwargs: All other keyword arguments delegated to
                ``OpenAIBaseClient.ask`` (e.g. ``model``, ``temperature``,
                ``system_prompt``, ``session_id``).

        Returns:
            AIMessage with the model response. For reasoning models the
            thinking trace is available on ``AIMessage.reasoning``, kept
            separate from the answer in ``AIMessage.output``.
        """
        kwargs.setdefault("model", self.model or self._default_model)
        thinking_token = _thinking_ctx.set(
            {"enable_thinking": enable_thinking, "clear_thinking": clear_thinking}
        )
        sampling_token = _sampling_ctx.set(
            self._resolve_sampling(top_p, seed, reasoning_budget)
        )
        try:
            return await super().ask(prompt, **kwargs)
        finally:
            _thinking_ctx.reset(thinking_token)
            _sampling_ctx.reset(sampling_token)

    async def ask_stream(
        self,
        prompt: str,
        *,
        enable_thinking: bool = False,
        clear_thinking: bool = False,
        top_p: Optional[float] = None,
        seed: Optional[int] = None,
        reasoning_budget: Optional[int] = None,
        **kwargs,
    ) -> AsyncIterator[str]:
        """Submit a prompt and stream response chunks.

        Identical to ``OpenAIBaseClient.ask_stream`` with the same
        ``enable_thinking`` shortcut as ``ask``.  For reasoning-capable models
        (e.g. ``nvidia/nemotron-3-nano-omni-30b-a3b-reasoning``) each chunk may
        carry a ``delta.reasoning_content`` field in addition to
        ``delta.content``.

        The flags are forwarded to ``_chat_completion`` via an async context
        variable, so the parent's call signature is preserved.

        FEAT-438 (TASK-2298/2300): ``ask_stream`` now routes through
        ``_chat_completion`` (the single completion funnel), so the
        free-tier slot is reserved there — no separate reservation is made
        here, which would otherwise double-count against the 40 rpm quota.

        ``top_p``, ``seed`` and ``reasoning_budget`` ARE supported here.  They
        previously raised ``NotImplementedError`` because ``ask_stream`` did
        not set the ``_sampling_ctx`` context variable that
        ``_chat_completion`` reads.  Once TASK-2298 routed the streaming path
        through ``_chat_completion`` as well, that limitation became stale
        plumbing rather than a real constraint: the injection point is shared,
        so setting the same context variable here is all it took.  This
        matters most for reasoning models, whose natural mode is streaming.

        Args:
            prompt: User message text.
            enable_thinking: When ``True``, inject reasoning flags into
                ``extra_body``.
            clear_thinking: Forwarded to ``clear_thinking`` in the payload
                when ``enable_thinking`` is ``True``.
            top_p: Nucleus-sampling value. Defaults to the constructor's.
            seed: Sampling seed for reproducibility. Defaults to the
                constructor's.
            reasoning_budget: Maximum tokens spent on reasoning before
                answering. Defaults to the constructor's.
            **kwargs: All other keyword arguments delegated to
                ``OpenAIBaseClient.ask_stream`` (e.g. ``model``, ``temperature``,
                ``system_prompt``, ``session_id``).

        Yields:
            Response text chunks (same shape as ``OpenAIBaseClient.ask_stream``).

        Raises:
            NvidiaRateLimitError: If ``rate_limit_max_wait`` is set and no
                free-tier slot became available within that budget.
        """
        kwargs.setdefault("model", self.model or self._default_model)
        # FEAT-438 TASK-2300: no manual _acquire_rate_limit_slot() call here
        # anymore — ask_stream() now routes through _chat_completion (the
        # single completion funnel, TASK-2298), which already reserves a
        # slot per attempt. A second reservation here would double-count
        # every streamed call against the 40 rpm free-tier quota.
        thinking_token = _thinking_ctx.set(
            {"enable_thinking": enable_thinking, "clear_thinking": clear_thinking}
        )
        sampling_token = _sampling_ctx.set(
            self._resolve_sampling(top_p, seed, reasoning_budget)
        )
        try:
            async for chunk in super().ask_stream(prompt, **kwargs):
                yield chunk
        finally:
            _thinking_ctx.reset(thinking_token)
            _sampling_ctx.reset(sampling_token)
