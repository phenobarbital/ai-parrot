"""Protocol roundtrip tests for FEAT-380 Module 2 (`repl_worker.protocol`)."""

from __future__ import annotations

import base64
import io
import pickle

import pandas as pd
import pytest

from parrot.tools.repl_worker.protocol import (
    ErrorResponse,
    ExecRequest,
    ExecResult,
    GetVarRequest,
    InjectDfRequest,
    ListNsRequest,
    ListNsResponse,
    NamespaceLossError,
    OkResponse,
    PingRequest,
    PongResponse,
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
        err = NamespaceLossError(
            cause="timeout", lost_variables=["df", "x"], message="recreate your state"
        )
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
