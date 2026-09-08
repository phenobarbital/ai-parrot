"""Protocol roundtrip tests for FEAT-380 Module 2 (`repl_worker.protocol`)."""

from __future__ import annotations

import base64
import io
import pickle

import pandas as pd
import pytest
from pydantic import ValidationError

from parrot.tools.repl_worker.protocol import (
    _MESSAGE_TYPES,
    ErrorResponse,
    ExecRequest,
    ExecResult,
    GetVarRequest,
    InjectDfRequest,
    ListNsRequest,
    ListNsResponse,
    MemoryVerdict,
    NamespaceLossError,
    OkResponse,
    PingRequest,
    PongResponse,
    ProcessSample,
    ReadyResponse,
    ResetRequest,
    SetVarRequest,
    SnapshotRequest,
    SnapshotResponse,
    ValueResponse,
    WorkerConfig,
    decode_value,
    encode_value,
    read_frame,
    write_frame,
)

ALL_MESSAGES = [
    ExecRequest(code="x = 1", deadline_ms=1000),
    InjectDfRequest(name="df"),
    GetVarRequest(name="x"),
    SetVarRequest(name="x", value=1),
    ListNsRequest(),
    SnapshotRequest(),
    ResetRequest(),
    PingRequest(),
    ExecResult(output="hello", new_vars=["x"]),
    ExecResult(status="error", result="boom", error="boom"),
    ValueResponse(name="x", value=1),
    OkResponse(),
    ListNsResponse(names=["pd", "np"]),
    SnapshotResponse(data={"x": 1}),
    PongResponse(),
    ErrorResponse(message="not_implemented"),
    ReadyResponse(pid=1, bootstrap_ms=10),
]


@pytest.mark.parametrize("message", ALL_MESSAGES, ids=[m.op for m in ALL_MESSAGES])
def test_protocol_roundtrip(message):
    """Every protocol message model survives frame -> unframe -> parse."""
    stream = io.BytesIO()
    write_frame(stream, message)
    stream.seek(0)
    parsed = read_frame(stream)
    assert type(parsed) is type(message)
    assert parsed.model_dump() == message.model_dump()


def test_ready_response_roundtrip():
    """The FEAT-500 readiness frame survives write_frame -> read_frame."""
    buf = io.BytesIO()
    write_frame(buf, ReadyResponse(pid=4242, bootstrap_ms=1234))
    buf.seek(0)
    msg = read_frame(buf)
    assert isinstance(msg, ReadyResponse)
    assert (msg.pid, msg.bootstrap_ms) == (4242, 1234)


def test_worker_config_new_fields_defaults_and_validation():
    """Both FEAT-500 timeout budgets default to 30 s and reject <= 0."""
    cfg = WorkerConfig()
    assert cfg.bootstrap_timeout_ms == 30_000
    assert cfg.namespace_timeout_ms == 30_000
    with pytest.raises(ValidationError):
        WorkerConfig(bootstrap_timeout_ms=0)
    with pytest.raises(ValidationError):
        WorkerConfig(namespace_timeout_ms=-1)


class TestFeat521ConfigFields:
    """Spec §2 Data Models — observation/interrupt/memory `WorkerConfig` fields
    added by FEAT-521 (TASK-2774), plus the cross-field validators and the
    host-local `ProcessSample`/`MemoryVerdict` models (TASK-2780).
    """

    def test_defaults_match_spec(self):
        cfg = WorkerConfig()
        assert cfg.observer_poll_ms == 500
        assert cfg.stall_window_ms == 5_000
        assert cfg.bootstrap_stall_ms == 0
        assert cfg.interrupt_before_kill is True
        assert cfg.interrupt_grace_ms == 2_000
        assert cfg.memory_soft_limit_bytes == 4 * 1024**3
        assert cfg.memory_hard_limit_bytes == 8 * 1024**3
        assert cfg.host_memory_reserve_bytes == 2 * 1024**3

    def test_zero_disables_soft_limit(self):
        cfg = WorkerConfig(memory_soft_limit_bytes=0)
        assert cfg.memory_soft_limit_bytes == 0
        assert cfg.memory_hard_limit_bytes == 8 * 1024**3  # untouched, still enabled

    def test_zero_disables_hard_limit(self):
        cfg = WorkerConfig(memory_hard_limit_bytes=0)
        assert cfg.memory_hard_limit_bytes == 0
        assert cfg.memory_soft_limit_bytes == 4 * 1024**3  # untouched, still enabled

    def test_zero_disables_both_memory_limits(self):
        cfg = WorkerConfig(memory_soft_limit_bytes=0, memory_hard_limit_bytes=0)
        assert cfg.memory_soft_limit_bytes == 0
        assert cfg.memory_hard_limit_bytes == 0

    def test_hard_below_soft_raises(self):
        with pytest.raises(ValidationError):
            WorkerConfig(memory_soft_limit_bytes=8 * 1024**3, memory_hard_limit_bytes=4 * 1024**3)

    def test_hard_equal_to_soft_is_allowed(self):
        cfg = WorkerConfig(memory_soft_limit_bytes=4 * 1024**3, memory_hard_limit_bytes=4 * 1024**3)
        assert cfg.memory_hard_limit_bytes == cfg.memory_soft_limit_bytes

    def test_hard_above_rlimit_as_raises(self):
        with pytest.raises(ValidationError):
            WorkerConfig(
                rlimit_as_bytes=1 * 1024**3,
                memory_soft_limit_bytes=0,
                memory_hard_limit_bytes=2 * 1024**3,
            )

    def test_hard_at_rlimit_as_is_allowed(self):
        cfg = WorkerConfig(
            rlimit_as_bytes=2 * 1024**3,
            memory_soft_limit_bytes=0,
            memory_hard_limit_bytes=2 * 1024**3,
        )
        assert cfg.memory_hard_limit_bytes == cfg.rlimit_as_bytes

    def test_interrupt_grace_equal_to_deadline_raises(self):
        with pytest.raises(ValidationError):
            WorkerConfig(deadline_ms=1_000, interrupt_grace_ms=1_000)

    def test_interrupt_grace_above_deadline_raises(self):
        with pytest.raises(ValidationError):
            WorkerConfig(deadline_ms=1_000, interrupt_grace_ms=2_000)

    def test_interrupt_grace_below_deadline_is_allowed(self):
        cfg = WorkerConfig(deadline_ms=1_000, interrupt_grace_ms=999)
        assert cfg.interrupt_grace_ms == 999

    def test_host_local_models_are_not_wire_messages(self):
        """`ProcessSample`/`MemoryVerdict` never cross the control pipe (TASK-2774)."""
        assert ProcessSample not in _MESSAGE_TYPES.values()
        assert MemoryVerdict not in _MESSAGE_TYPES.values()

    def test_process_sample_defaults(self):
        sample = ProcessSample(t=1.0, cpu_s=0.5, rss=100, state="running")
        assert sample.wchan == ""
        assert sample.threads == 0

    def test_memory_verdict_cause_is_fixed(self):
        verdict = MemoryVerdict(rss=100, limit=50)
        assert verdict.cause == "memory"


def test_read_frame_raises_eoferror_on_empty_stream():
    """An empty stream (worker process gone) raises EOFError, not a crash."""
    stream = io.BytesIO(b"")
    with pytest.raises(EOFError):
        read_frame(stream)


def test_write_frame_uses_length_prefixed_framing_not_newlines():
    """Frames are length-prefixed, not newline-delimited (REPL output has newlines)."""
    message = ExecResult(output="line one\nline two\nline three")
    stream = io.BytesIO()
    write_frame(stream, message)
    stream.seek(0)
    parsed = read_frame(stream)
    assert parsed.output == "line one\nline two\nline three"


def test_multiple_frames_on_one_stream():
    """Several messages back-to-back on the same stream each parse cleanly."""
    stream = io.BytesIO()
    write_frame(stream, PingRequest())
    write_frame(stream, ExecRequest(code="1+1", deadline_ms=500))
    stream.seek(0)
    first = read_frame(stream)
    second = read_frame(stream)
    assert isinstance(first, PingRequest)
    assert isinstance(second, ExecRequest)
    assert second.code == "1+1"


class TestValueCodec:
    def test_json_native_values_pass_through(self):
        for value in (None, True, 1, 1.5, "text", [1, 2], {"a": 1}):
            assert encode_value(value) == value
            assert decode_value(encode_value(value)) == value

    def test_dataframe_round_trips_via_pickle_fallback(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        encoded = encode_value(df)
        assert isinstance(encoded, dict)
        decoded = decode_value(encoded)
        pd.testing.assert_frame_equal(decoded, df)

    def test_worker_config_defaults_match_spec(self):
        """Spec §2 Data Models — defaults must match exactly.

        `rlimit_as_bytes` was empirically calibrated by TASK-1946 (was the
        spec's illustrative 4 GiB placeholder) — see
        artifacts/logs/feat-380-rlimit-as-calibration.md before changing.
        """
        config = WorkerConfig()
        assert config.rlimit_as_bytes == 12 * 1024**3
        assert config.rlimit_cpu_seconds == 300
        assert config.rlimit_nofile == 256
        assert config.deadline_ms == 60_000
        assert config.max_workers == 0
        assert config.idle_ttl_seconds == 1800
        assert config.prewarm_pool_size == 2

    def test_namespace_loss_error_shape(self):
        err = NamespaceLossError(cause="timeout", lost_variables=["df", "x"], message="recreate your state")
        assert err.cause == "timeout"
        assert err.lost_variables == ["df", "x"]


class TestInsecureDeserializationGuard:
    """Code-review finding (post-TASK-1945): `decode_value()` runs on the
    HOST for values shaped by the worker's (attacker-influenceable)
    namespace — a plain dict literal matching the pickle-marker shape is
    indistinguishable from a genuinely-pickled value, so unrestricted
    `pickle.loads()` there is host-process RCE. No sandbox import is needed
    to construct the payload — it's a plain string literal.
    """

    def test_os_system_reduce_gadget_blocked(self):
        import os

        class Evil:
            def __reduce__(self):
                return (os.system, ("true",))

        payload = base64.b64encode(pickle.dumps(Evil())).decode("ascii")
        with pytest.raises(pickle.UnpicklingError):
            decode_value({"__repl_worker_pickle_b64__": payload})

    def test_subprocess_popen_reduce_gadget_blocked(self):
        import subprocess

        class Evil:
            def __reduce__(self):
                return (subprocess.Popen, (["true"],))

        payload = base64.b64encode(pickle.dumps(Evil())).decode("ascii")
        with pytest.raises(pickle.UnpicklingError):
            decode_value({"__repl_worker_pickle_b64__": payload})

    def test_builtins_eval_reduce_gadget_blocked(self):
        class Evil:
            def __reduce__(self):
                return (eval, ("1+1",))

        payload = base64.b64encode(pickle.dumps(Evil())).decode("ascii")
        with pytest.raises(pickle.UnpicklingError):
            decode_value({"__repl_worker_pickle_b64__": payload})

    def test_functools_partial_gadget_blocked(self):
        import functools

        class Evil:
            def __reduce__(self):
                return (functools.partial, (eval, "1+1"))

        payload = base64.b64encode(pickle.dumps(Evil())).decode("ascii")
        with pytest.raises(pickle.UnpicklingError):
            decode_value({"__repl_worker_pickle_b64__": payload})

    def test_plain_dict_literal_shaped_like_marker_is_rejected(self):
        """The actual attack shape: a JSON-native dict an LLM could type
        directly (no pickle/base64 import needed) that happens to match the
        wrapper's key — must not silently unpickle whatever string is there.
        Well-formed base64 that isn't a real pickle stream must fail safely
        (some pickle/decode error), never succeed or execute anything.
        """
        garbage_b64 = base64.b64encode(b"not a real pickle stream").decode("ascii")
        with pytest.raises((pickle.UnpicklingError, EOFError, ValueError)):
            decode_value({"__repl_worker_pickle_b64__": garbage_b64})

    def test_legitimate_dataframe_still_round_trips(self):
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        decoded = decode_value(encode_value(df))
        pd.testing.assert_frame_equal(decoded, df)

    def test_legitimate_numpy_array_still_round_trips(self):
        import numpy as np

        arr = np.array([1, 2, 3])
        decoded = decode_value(encode_value(arr))
        assert (decoded == arr).all()
