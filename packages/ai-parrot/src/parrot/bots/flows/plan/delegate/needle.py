"""``NeedleDelegate`` — Needle 3 tool proposals via an executor + instance pool (FEAT-590).

The engine is blocking and non-reentrant. It runs through an executor with an instance pool
keyed by tool subset (``Needle(tools=...)`` binds the toolset at construction).

The executor defaults to ``"thread"`` (per decision.md, ProcessPoolExecutor hangs in this
sandboxed environment). Thread mode bounds concurrent blocking calls to ``pool_size`` OS
threads with an ``asyncio.Semaphore`` (there is no work-item queue to manage: each call is
independent, so a semaphore-gated ``asyncio.to_thread`` is the whole pool). Because the
engine is non-reentrant, a per-cache-key ``threading.Lock`` (module-level, alongside
``_WORKER_CACHE``) additionally serializes ``reset()``/``complete()`` for calls that land on
the *same* cached engine instance, across whichever OS threads happen to run them
concurrently — different toolsets (different cache keys) still run in parallel.

Facts map onto Needle's fixed ``system`` keys (``date``, ``locale``, ``device``,
``battery``, ``network``, ``location``, ``user``, ``assistant``). Other facts are folded
into the instruction text as ``key: value`` lines.

Only ``complete()`` is used, never ``agent.run()``. ``needle`` is imported lazily.
A missing package raises ``ImportError("NeedleDelegate requires the 'ai-parrot[needle]' extra (pip install ai-parrot[needle])")``.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import Executor, ProcessPoolExecutor
from typing import Any, Dict, FrozenSet, List, Literal, Mapping, Optional, Sequence, Tuple, Type, Union

from pydantic import BaseModel

from .protocol import DelegateBackendError, ToolCallProposal, ToolSpec

__all__ = ("NeedleDelegate",)

_SYSTEM_KEYS = frozenset({"date", "locale", "device", "battery", "network", "location", "user", "assistant"})
_EXTRA_HINT = "NeedleDelegate requires the 'ai-parrot[needle]' extra (pip install ai-parrot[needle])"

# Per-process cache: {(weights, frozenset(tool names)): Needle instance}. Lives in the worker process.
_WORKER_CACHE: Dict[Tuple[Optional[str], FrozenSet[str]], Any] = {}
# One threading.Lock per cache key, serializing reset()/complete() on that (non-reentrant)
# engine instance across concurrent worker threads. Guarded by _WORKER_CACHE_LOCK below --
# creating the cache entry and its lock must be atomic, or two threads racing on a brand-new
# cache key could each create and use a *different* lock for the *same* engine instance.
_WORKER_LOCKS: Dict[Tuple[Optional[str], FrozenSet[str]], threading.Lock] = {}
_WORKER_CACHE_LOCK = threading.Lock()


def _import_needle() -> Any:
    """Import ``needle`` lazily with an actionable error."""
    try:
        import needle  # type: ignore  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(_EXTRA_HINT) from exc
    return needle


def _complete_in_worker(
    weights: Optional[str], tools: List[Dict[str, Any]], system: Dict[str, str], text: str
) -> Dict[str, Any]:
    """Top-level (picklable) worker: get/create the cached engine, reset, complete. Returns the raw response dict.

    The worker is picklable because it only uses immutable data structures and the Needle constructor
    accepts a list of dicts (the tool schemas), not bound methods or live objects.
    """
    needle = _import_needle()

    # Build the tool list: each tool is a dict with _needle_tool set to its schema.
    # This matches the verified Needle API from decision.md.
    tool_list: List[Dict[str, Any]] = []
    for tool in tools:
        tool_list.append({"_needle_tool": tool})

    # Create a unique cache key: (weights, frozenset of tool names)
    tool_names = frozenset(t["name"] for t in tools)
    cache_key = (weights, tool_names)

    # Get or create the cached Needle instance and its per-key lock atomically -- two
    # threads racing on the same brand-new cache key must land on the same engine AND
    # the same lock, or the lock below serializes nothing.
    with _WORKER_CACHE_LOCK:
        if cache_key not in _WORKER_CACHE:
            # Needle(tools=tools, system=system, weights=weights)
            # Note: system is a dict of str->str, which is picklable
            _WORKER_CACHE[cache_key] = needle.Needle(tools=tool_list, system=system, weights=weights)
            _WORKER_LOCKS[cache_key] = threading.Lock()
        engine = _WORKER_CACHE[cache_key]
        engine_lock = _WORKER_LOCKS[cache_key]

    # The engine is stateful (reset()) and documented as blocking/non-reentrant, so
    # concurrent calls sharing this cache key (same toolset+weights) must never
    # interleave reset()/complete() on it -- serialize with the per-key lock. Calls
    # against a *different* cache key still run concurrently (different lock).
    with engine_lock:
        engine.reset()
        response = engine.complete(text, max_new_tokens=512)

    return response


class NeedleDelegate:
    """Needle 3 behind an executor; one engine per tool subset."""

    backend_name = "needle"
    max_tools = 5

    def __init__(
        self,
        *,
        weights: Optional[str] = None,
        pool_size: int = 4,
        executor: Literal["process", "thread"] = "thread",
        max_input_chars: int = 1000,
    ) -> None:
        self.weights = weights
        self.pool_size = pool_size
        self.executor_kind = executor
        self.max_input_chars = max_input_chars
        self._executor: Optional[Executor] = None
        self._closed = False
        self.logger = logging.getLogger(f"{__name__}.NeedleDelegate")

    def _split_facts(self, instruction: str, facts: Optional[Mapping[str, str]]) -> Tuple[str, Dict[str, str]]:
        """Map facts onto Needle's fixed system keys; fold the rest into the instruction.

        Needle's system parameter expects a dict of str->str for the fixed keys.
        Any other facts are appended as ``key: value`` lines to the instruction.
        """
        system: Dict[str, str] = {}
        folded_instruction = instruction

        if facts:
            for key, value in facts.items():
                if key in _SYSTEM_KEYS:
                    system[key] = str(value)
                else:
                    folded_instruction += f"\n{key}: {value}"

        return folded_instruction, system

    async def _run(self, tools: Sequence[ToolSpec], system: Dict[str, str], text: str) -> Dict[str, Any]:
        """Run the worker on the configured executor; engine errors → DelegateBackendError."""
        if self._closed:
            raise DelegateBackendError("NeedleDelegate is closed")

        # Lazy executor creation
        if self._executor is None:
            if self.executor_kind == "thread":
                # Thread mode: use asyncio.Queue checkout pool per toolset
                self._executor = _ThreadExecutor(self.pool_size)
            else:
                # Process mode: use ProcessPoolExecutor (not recommended in this sandbox)
                self._executor = ProcessPoolExecutor(max_workers=self.pool_size)

        # Convert tools to the format expected by the worker
        tools_list = [t.model_dump() for t in tools]

        # Run the worker in the executor. _ThreadExecutor.submit() is a coroutine
        # function (it awaits asyncio.to_thread internally), NOT the standard
        # concurrent.futures.Executor.submit() -> Future protocol that
        # loop.run_in_executor() requires -- calling it through run_in_executor
        # hands back a coroutine object where a Future is expected and crashes.
        # ProcessPoolExecutor IS a standard Executor, so it still goes through
        # run_in_executor.
        try:
            if isinstance(self._executor, _ThreadExecutor):
                response = await self._executor.submit(
                    _complete_in_worker,
                    self.weights,
                    tools_list,
                    system,
                    text,
                )
            else:
                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(
                    self._executor,
                    _complete_in_worker,
                    self.weights,
                    tools_list,
                    system,
                    text,
                )
        except Exception as exc:
            # Wrap any engine error in DelegateBackendError
            raise DelegateBackendError(f"Needle backend error: {exc}") from exc

        return response

    async def propose_call(
        self, instruction: str, tools: Sequence[ToolSpec], facts: Optional[Mapping[str, str]] = None
    ) -> ToolCallProposal:
        """Propose one call from the engine's ``function_calls`` (first entry), or decline."""
        if len(tools) > self.max_tools:
            raise DelegateBackendError(f"Too many tools ({len(tools)} > {self.max_tools})")

        # Split facts into system and instruction
        instruction_text, system = self._split_facts(instruction, facts)

        # Run the worker
        response = await self._run(tools, system, instruction_text)

        # Map the response to a ToolCallProposal
        # The response dict has keys: type, success, error, error_code, reason, function_calls, suppressed_calls,
        # reasoning, confidence, prefill_tps, decode_tps, peak_ram_mb, validation
        # We only care about function_calls and confidence
        function_calls = response.get("function_calls", [])
        confidence = response.get("confidence")

        # If function_calls is empty, the model declined
        if not function_calls:
            return ToolCallProposal(
                name=None,
                arguments={},
                confidence=confidence,
                backend=self.backend_name,
                latency_ms=0.0,  # Will be set by the caller
            )

        # Take the first function call
        first_call = function_calls[0]
        name = first_call.get("name")
        arguments = first_call.get("arguments", {})

        return ToolCallProposal(
            name=name,
            arguments=arguments,
            confidence=confidence,
            backend=self.backend_name,
            latency_ms=0.0,  # Will be set by the caller
        )

    async def extract(self, text: str, schema: Union[Type[BaseModel], Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Not implemented for this backend; always declines with ``None``.

        The spec's ``extract`` hook expects a ``needle.extract``-style call, but
        ``sdd/state/FEAT-590/spike/decision.md`` (TASK-3624) verified only
        ``Needle.complete()`` -- the extraction API was never exercised by the spike
        and is not safe to guess at here (this backend's whole design principle is
        "never invent a tool name or argument key"; guessing a schema-extraction
        call shape is the same mistake). Declining is the deliberate, documented
        behavior until a follow-up task verifies the real API against a live
        engine, not a placeholder awaiting implementation.
        """
        return None

    async def aclose(self) -> None:
        """Shut the executor down and drop pools. Idempotent; owned by the toolkit."""
        if self._closed:
            return
        self._closed = True
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None


class _ThreadExecutor:
    """Bounds concurrent blocking Needle calls to ``max_workers`` OS threads.

    There is no work-item queue here by design: each ``submit()`` call is an
    independent unit of work (``asyncio.to_thread`` already hands it its own OS
    thread from the interpreter's default thread pool), so all this needs to do is
    cap how many can run at once. A semaphore is the correct, minimal primitive for
    that -- it does not "dispatch" anything, it just gates entry.

    Cross-thread safety for the *same* cached Needle engine (same toolset+weights)
    is NOT this class's job: the engine is non-reentrant, so serializing access to
    one cache entry is handled by the per-cache-key ``threading.Lock`` in
    ``_complete_in_worker`` itself. This pool only bounds total concurrency.
    """

    def __init__(self, max_workers: int) -> None:
        self._semaphore = asyncio.Semaphore(max_workers)

    async def submit(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Run ``func(*args, **kwargs)`` in a thread, gated by the semaphore."""
        async with self._semaphore:
            return await asyncio.to_thread(func, *args, **kwargs)

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        """No-op: there are no persistent worker tasks or threads to release.

        Each ``submit()`` call's ``asyncio.to_thread`` future is already awaited
        to completion (or cancellation propagates naturally) by the caller in
        ``NeedleDelegate._run``; nothing outlives it for this pool to clean up.
        """
        return
