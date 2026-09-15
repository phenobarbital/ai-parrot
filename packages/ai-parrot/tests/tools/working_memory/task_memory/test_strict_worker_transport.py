"""Strict REPL worker transport for task-memory evidence (FEAT-538 / TASK-2992).

Three required cases from the task's Test Specification:

- ``test_no_pickle`` — force an Arrow conversion failure and spy on
  ``pickle.dumps``: a strict call never reaches it, while the legacy
  fallback still works untouched.
- ``test_roundtrip`` — supported Arrow/JSON values and generation
  envelopes round-trip safely, in a **real subprocess** and in in-process
  mode.
- ``test_cleanup`` — cancellation, a corrupt envelope and byte overflow
  leave no leaked shared-memory segments.

The spy on ``pickle.dumps`` is the important one. Asserting only that a
strict call "raises" would still pass if the implementation built the
pickle payload first and then declined to send it — by which point the
arbitrary objects have already been serialized in-process, which is
exactly what strict mode exists to prevent.
"""

from __future__ import annotations

import asyncio
import gc
import os
from multiprocessing import shared_memory
from typing import Any, List

import pandas as pd
import pytest
from parrot.tools.repl_worker import transport as transport_module
from parrot.tools.repl_worker.protocol import InjectDfRequest, TransportEnvelope, decode_value, encode_value
from parrot.tools.repl_worker.transport import (
    DEFAULT_STRICT_MAX_BYTES,
    StrictTransportError,
    decode_dataframe_from_shm,
    encode_dataframe,
    ensure_strict_json,
    unlink_shm,
    validate_strict_dataframe,
)

# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────


def supported_frame(rows: int = 50) -> pd.DataFrame:
    """Return a frame Arrow can represent losslessly.

    Args:
        rows: Number of rows.

    Returns:
        A numeric/string DataFrame.
    """
    return pd.DataFrame(
        {
            "n": range(rows),
            "f": [float(i) / 3 for i in range(rows)],
            "s": [f"row-{i}" for i in range(rows)],
        }
    )


class Opaque:
    """A value Arrow cannot represent but pickle can.

    Deliberately module-level, not nested in a helper: a locally-defined
    class is unpicklable, which would make the *legacy* fallback path
    fail for the wrong reason and hide whether it still works.
    """

    def __init__(self, n: int) -> None:
        """Store an arbitrary payload.

        Args:
            n: Any integer.
        """
        self.n = n

    def __eq__(self, other: object) -> bool:
        """Compare by payload."""
        return isinstance(other, Opaque) and other.n == self.n


def unsupported_frame() -> pd.DataFrame:
    """Return a frame Arrow cannot convert.

    Verified by :func:`test_no_pickle_fixture_really_defeats_arrow` — a
    fixture Arrow silently *accepts* would make every assertion in this
    module vacuous.

    Returns:
        A DataFrame with an unconvertible object column.
    """
    return pd.DataFrame({"obj": pd.Series([Opaque(1), Opaque(2)], dtype="object")})


class _PickleSpy:
    """Records every ``pickle.dumps`` call made through ``transport``."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Install the spy.

        Args:
            monkeypatch: pytest's patcher.
        """
        self.calls: List[Any] = []
        real = transport_module.pickle.dumps

        def _spy(obj: Any, *args: Any, **kwargs: Any) -> bytes:
            self.calls.append(obj)
            return real(obj, *args, **kwargs)

        monkeypatch.setattr(transport_module.pickle, "dumps", _spy)

    @property
    def called(self) -> bool:
        """Whether ``pickle.dumps`` was reached at all."""
        return bool(self.calls)


def _live_segments() -> set:
    """Return the names of shared-memory segments currently on this host.

    Returns:
        A set of segment names found under ``/dev/shm``, or an empty set
        on a platform without it.
    """
    shm_dir = "/dev/shm"
    if not os.path.isdir(shm_dir):
        return set()
    return {n for n in os.listdir(shm_dir) if n.startswith("psm_")}


# ─────────────────────────────────────────────────────────────
# test_no_pickle
# ─────────────────────────────────────────────────────────────


def test_no_pickle_fixture_really_defeats_arrow() -> None:
    """The 'unsupported' fixture must actually defeat Arrow.

    Asserted first and separately: if Arrow happened to accept this frame,
    every strict-refusal assertion below would pass vacuously.
    """
    import pyarrow as pa

    with pytest.raises(transport_module._ARROW_CONVERSION_ERRORS):
        pa.Table.from_pandas(unsupported_frame(), preserve_index=True)


def test_no_pickle_strict_never_reaches_pickle(monkeypatch: pytest.MonkeyPatch) -> None:
    """A strict encode refuses BEFORE any pickle payload is constructed."""
    spy = _PickleSpy(monkeypatch)

    with pytest.raises(StrictTransportError, match="never falls back to pickle"):
        encode_dataframe(unsupported_frame(), "evidence", strict=True)

    assert not spy.called, "strict mode serialized a pickle payload before refusing"


def test_no_pickle_legacy_fallback_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """The legacy default is untouched: it still falls back to pickle (AC13)."""
    spy = _PickleSpy(monkeypatch)

    encoded = encode_dataframe(unsupported_frame(), "legacy")

    assert encoded.format == "pickle"
    assert encoded.payload is not None
    assert encoded.shm_name is None
    assert spy.called, "the legacy fallback must keep working exactly as before"


def test_no_pickle_default_argument_is_non_strict() -> None:
    """``strict`` defaults to False, so no existing caller changes behaviour."""
    import inspect

    signature = inspect.signature(encode_dataframe)
    assert signature.parameters["strict"].default is False
    assert signature.parameters["max_bytes"].default is None


def test_no_pickle_in_process_validation_is_equally_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    """The in-process path refuses the same frame, without serializing it."""
    spy = _PickleSpy(monkeypatch)

    with pytest.raises(StrictTransportError, match="never falls back to pickle"):
        validate_strict_dataframe(unsupported_frame(), "evidence")

    assert not spy.called
    # A supported frame passes.
    validate_strict_dataframe(supported_frame(), "evidence")


def test_no_pickle_strict_json_refuses_unsupported_values() -> None:
    """Strict JSON evidence permits only exactly round-trippable values."""
    ensure_strict_json({"a": 1, "b": [1, 2.5, "x", None, True]}, name="v")

    for bad in (
        supported_frame(),
        {1, 2},
        b"bytes",
        object(),
        (1, 2),  # round-trips as a list — the value that arrives differs
    ):
        with pytest.raises(StrictTransportError):
            ensure_strict_json(bad, name="v")

    # Non-string mapping keys cannot round-trip exactly.
    with pytest.raises(StrictTransportError, match="non-string mapping key"):
        ensure_strict_json({1: "a"}, name="v")

    # Nested unsupported values are caught too.
    with pytest.raises(StrictTransportError):
        ensure_strict_json({"outer": [{"inner": {1, 2}}]}, name="v")

    # Depth guard.
    deep: Any = "leaf"
    for _ in range(40):
        deep = [deep]
    with pytest.raises(StrictTransportError, match="nests deeper"):
        ensure_strict_json(deep, name="v")


def test_no_pickle_worker_refuses_a_strict_non_arrow_frame() -> None:
    """The worker refuses independently of the host.

    A host-side bug — or a forged frame — must not be able to smuggle a
    pickle payload across under a task-memory evidence label. Unpickling
    is what strict mode exists to prevent, so the check has to live on the
    side that would perform it.
    """
    from parrot.tools.repl_worker.protocol import ErrorResponse
    from parrot.tools.repl_worker.worker import _dispatch

    class _Namespace:
        def __init__(self) -> None:
            self.vars: dict = {}

        def set_var(self, name: str, value: Any) -> None:
            self.vars[name] = value

    namespace = _Namespace()
    legacy_pickle = encode_dataframe(unsupported_frame(), "legacy")
    forged = InjectDfRequest(
        name="evidence",
        format="pickle",
        payload=legacy_pickle.payload,
        strict=True,
    )
    response = _dispatch(namespace, forged)  # type: ignore[arg-type]

    assert isinstance(response, ErrorResponse)
    assert "strict transport refused" in response.message
    assert namespace.vars == {}, "the worker must not bind anything it refused"


def test_no_pickle() -> None:
    """Required aggregate case: strict never pickles; legacy fallback still does."""
    test_no_pickle_fixture_really_defeats_arrow()
    test_no_pickle_default_argument_is_non_strict()
    test_no_pickle_strict_json_refuses_unsupported_values()
    test_no_pickle_worker_refuses_a_strict_non_arrow_frame()


# ─────────────────────────────────────────────────────────────
# test_roundtrip
# ─────────────────────────────────────────────────────────────


def test_roundtrip_arrow_shm_preserves_the_frame() -> None:
    """A supported frame survives the Arrow/shm hop unchanged."""
    df = supported_frame(200)
    encoded = encode_dataframe(df, "evidence", strict=True)
    assert encoded.format == "arrow"
    assert encoded.shm_name is not None
    try:
        decoded = decode_dataframe_from_shm(encoded.shm_name, encoded.size)
        pd.testing.assert_frame_equal(df, decoded)
    finally:
        unlink_shm(encoded.shm_name)


def test_roundtrip_envelope_is_bounded_and_typed() -> None:
    """The transport envelope carries only bounded, validated context."""
    envelope = TransportEnvelope(
        scope_key="bot-a:user-1:sess-1",
        task_id="t-1",
        artifact_id="art-1",
        version=3,
        worker_generation="gen-abc",
        fencing_token=7,
    )
    restored = TransportEnvelope.model_validate_json(envelope.model_dump_json())
    assert restored == envelope

    # A binding is to a VERSION, never to a mutable alias.
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TransportEnvelope(scope_key="s", version=0)
    with pytest.raises(ValidationError):
        TransportEnvelope(scope_key="x" * 513)
    with pytest.raises(ValidationError):
        TransportEnvelope(scope_key="s", fencing_token=-1)


def test_roundtrip_inject_request_defaults_are_legacy() -> None:
    """An InjectDfRequest built the old way is unchanged on the wire."""
    legacy = InjectDfRequest(name="df", format="arrow", shm_name="psm_x", size=10)
    assert legacy.strict is False
    assert legacy.envelope is None

    # And the new fields survive a round trip when used.
    strict = InjectDfRequest(
        name="df",
        format="arrow",
        shm_name="psm_x",
        size=10,
        strict=True,
        envelope=TransportEnvelope(scope_key="s", worker_generation="gen-1"),
    )
    restored = InjectDfRequest.model_validate_json(strict.model_dump_json())
    assert restored.strict is True
    assert restored.envelope is not None
    assert restored.envelope.worker_generation == "gen-1"


def test_roundtrip_json_values_survive_the_value_codec() -> None:
    """Strict-safe JSON values round-trip through the existing value codec."""
    for value in ({"a": 1, "b": ["x", None, True, 2.5]}, [1, 2, 3], "text", 42, None):
        ensure_strict_json(value, name="v")
        assert decode_value(encode_value(value)) == value


@pytest.mark.asyncio
async def test_roundtrip_in_process_handle_binds_and_reports_generation() -> None:
    """In-process mode binds a supported frame and exposes a generation."""
    from parrot.tools.repl_worker.inprocess import InProcessHandle

    handle, tool = _make_inprocess_handle()
    try:
        assert isinstance(handle.generation, str) and len(handle.generation) == 32

        df = supported_frame()
        await handle.inject_dataframe("evidence", df, strict=True)
        assert "evidence" in handle.known_vars
        pd.testing.assert_frame_equal(tool.locals["evidence"], df)

        # And it refuses the unsupported one, exactly like the worker.
        with pytest.raises(StrictTransportError):
            await handle.inject_dataframe("bad", unsupported_frame(), strict=True)
        assert "bad" not in handle.known_vars
    finally:
        await handle.kill()


@pytest.mark.asyncio
async def test_roundtrip_in_process_legacy_injection_is_unchanged() -> None:
    """Without ``strict``, in-process injection accepts anything (AC13)."""
    from parrot.tools.repl_worker.inprocess import InProcessHandle  # noqa: F401

    handle, tool = _make_inprocess_handle()
    try:
        await handle.inject_dataframe("legacy", unsupported_frame())
        assert "legacy" in handle.known_vars
    finally:
        await handle.kill()


def _make_inprocess_handle():
    """Build an :class:`InProcessHandle` over a minimal fake tool.

    A real ``PythonREPLTool`` pulls in the whole REPL stack; this handle
    only needs ``locals``/``globals`` for the namespace API under test.

    Returns:
        A ``(handle, tool)`` pair.
    """
    import concurrent.futures

    from parrot.tools.repl_worker.inprocess import InProcessHandle

    class _FakeTool:
        def __init__(self) -> None:
            self.locals: dict = {}
            self.globals: dict = {}

        def reset_environment(self) -> None:
            self.locals.clear()
            self.globals.clear()

    tool = _FakeTool()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    return InProcessHandle(tool, executor, deadline_ms=5_000), tool  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_roundtrip_real_subprocess_worker() -> None:
    """A real worker subprocess accepts a strict Arrow frame and refuses pickle.

    This is the only case that exercises the actual process boundary. It
    is skipped — explicitly, and reported as a skip rather than a pass —
    when a worker cannot be spawned in this environment.
    """
    from parrot.tools.repl_worker.handle import WorkerHandle

    handle = WorkerHandle()
    try:
        try:
            await asyncio.wait_for(handle.start(), timeout=60)
            await asyncio.wait_for(handle.wait_ready(), timeout=60)
        except Exception as exc:  # noqa: BLE001 — environmental, reported as a skip
            pytest.skip(f"REPL worker subprocess unavailable in this environment: {exc!r}")

        assert isinstance(handle.generation, str) and len(handle.generation) == 32

        df = supported_frame()
        before = _live_segments()
        await handle.inject_dataframe(
            "evidence",
            df,
            strict=True,
            envelope=TransportEnvelope(scope_key="bot:user:sess", task_id="t-1", worker_generation=handle.generation),
        )
        assert "evidence" in handle.known_vars

        got = await handle.get_var("evidence")
        (
            pd.testing.assert_frame_equal(pd.DataFrame(got), df)
            if not isinstance(got, pd.DataFrame)
            else (pd.testing.assert_frame_equal(got, df))
        )

        # The host unlinked the block after the ACK.
        assert _live_segments() - before == set(), "a completed strict inject leaked a shm segment"

        # An unsupported frame is refused host-side, before anything is sent.
        with pytest.raises(StrictTransportError):
            await handle.inject_dataframe("bad", unsupported_frame(), strict=True)
        assert "bad" not in handle.known_vars
    finally:
        await handle.kill()


def test_roundtrip() -> None:
    """Required aggregate case: supported values and envelopes round-trip safely."""
    test_roundtrip_arrow_shm_preserves_the_frame()
    test_roundtrip_envelope_is_bounded_and_typed()
    test_roundtrip_inject_request_defaults_are_legacy()
    test_roundtrip_json_values_survive_the_value_codec()


# ─────────────────────────────────────────────────────────────
# test_cleanup
# ─────────────────────────────────────────────────────────────


def test_cleanup_strict_refusal_creates_no_segment() -> None:
    """A refused strict encode leaves no shared-memory block behind."""
    before = _live_segments()
    with pytest.raises(StrictTransportError):
        encode_dataframe(unsupported_frame(), "evidence", strict=True)
    gc.collect()
    assert _live_segments() - before == set()


def test_cleanup_byte_overflow_creates_no_segment() -> None:
    """An over-ceiling strict encode refuses before allocating the block."""
    before = _live_segments()
    with pytest.raises(StrictTransportError, match="above the strict ceiling"):
        encode_dataframe(supported_frame(5_000), "evidence", strict=True, max_bytes=64)
    gc.collect()
    assert _live_segments() - before == set(), "the ceiling check must precede shm allocation"


def test_cleanup_json_byte_overflow_is_refused() -> None:
    """Strict JSON enforces its byte ceiling on the canonical encoding."""
    with pytest.raises(StrictTransportError, match="above the strict ceiling"):
        ensure_strict_json({"blob": "x" * 5_000}, name="v", max_bytes=100)
    # And the default ceiling is the documented one.
    assert DEFAULT_STRICT_MAX_BYTES == 2_000_000


def test_cleanup_unlink_is_idempotent() -> None:
    """Unlinking twice (a retried cleanup) is not an error."""
    block = shared_memory.SharedMemory(create=True, size=16)
    name = block.name
    block.close()
    unlink_shm(name)
    unlink_shm(name)  # must not raise
    assert name not in _live_segments()


@pytest.mark.asyncio
async def test_cleanup_cancelled_inject_frees_the_segment() -> None:
    """A cancelled strict inject still unlinks its shared-memory block.

    The block is created before the frame is sent, so a cancellation
    landing on the send is exactly the window in which a segment would
    leak. The ``finally`` in ``inject_dataframe`` is shielded so the
    unlink completes even as the cancellation propagates.
    """
    from parrot.tools.repl_worker.handle import WorkerHandle

    handle = WorkerHandle()
    captured: dict = {}

    async def _hang(request: Any, timeout_s: float) -> Any:
        captured["shm_name"] = request.shm_name
        await asyncio.sleep(3600)

    handle._send = _hang  # type: ignore[assignment]

    before = _live_segments()
    task = asyncio.create_task(handle.inject_dataframe("evidence", supported_frame(), strict=True))
    for _ in range(200):
        await asyncio.sleep(0.01)
        if "shm_name" in captured:
            break
    assert "shm_name" in captured, "the send was never reached"
    assert captured["shm_name"] in _live_segments() or not _live_segments()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Give the shielded unlink a moment to complete.
    for _ in range(200):
        if captured["shm_name"] not in _live_segments():
            break
        await asyncio.sleep(0.01)

    assert captured["shm_name"] not in _live_segments(), "a cancelled inject leaked a shm segment"
    assert _live_segments() - before == set()
    await handle.kill()


@pytest.mark.asyncio
async def test_cleanup_send_failure_frees_the_segment() -> None:
    """A failed send (corrupt frame, dead worker) still unlinks the block."""
    from parrot.tools.repl_worker.handle import WorkerHandle

    handle = WorkerHandle()
    captured: dict = {}

    async def _boom(request: Any, timeout_s: float) -> Any:
        captured["shm_name"] = request.shm_name
        raise RuntimeError("corrupt envelope")

    handle._send = _boom  # type: ignore[assignment]

    before = _live_segments()
    with pytest.raises(RuntimeError, match="corrupt envelope"):
        await handle.inject_dataframe("evidence", supported_frame(), strict=True)

    assert captured["shm_name"] not in _live_segments()
    assert _live_segments() - before == set()
    await handle.kill()


def test_cleanup() -> None:
    """Required aggregate case: refusals and failures leak no shm segments."""
    test_cleanup_strict_refusal_creates_no_segment()
    test_cleanup_byte_overflow_creates_no_segment()
    test_cleanup_json_byte_overflow_is_refused()
    test_cleanup_unlink_is_idempotent()
