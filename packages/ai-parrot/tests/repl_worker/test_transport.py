"""DataFrame transport tests for FEAT-380 Module 7 (TASK-1945, G9/AC9).

Arrow IPC over shared memory is the primary host -> worker DataFrame
transport; pickle+base64 is the fallback ONLY for dtypes Arrow can't
represent, and that fallback must log a warning. This file covers both the
pure encode/decode round trip (in-process, no worker) and the full
host -> worker delivery via `WorkerHandle.inject_dataframe()`.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pytest

from parrot.tools.repl_worker.handle import WorkerHandle
from parrot.tools.repl_worker.protocol import WorkerConfig
from parrot.tools.repl_worker.transport import (
    decode_dataframe_from_shm,
    decode_pickle_payload,
    encode_dataframe,
    unlink_shm,
)


@pytest.fixture
def sample_df():
    return pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})


@pytest.fixture
def real_worker_config():
    """Generous AS (spec default ~4 GiB) so the real worker can actually boot."""
    return WorkerConfig(deadline_ms=10_000, max_workers=2, idle_ttl_seconds=5, prewarm_pool_size=0)


class TestEncodeDecodeRoundtrip:
    """Pure in-process encode/decode — no worker process involved."""

    def test_arrow_roundtrip_dtype_fidelity(self, sample_df):
        encoded = encode_dataframe(sample_df, "sample")
        try:
            assert encoded.format == "arrow"
            assert encoded.shm_name is not None
            decoded = decode_dataframe_from_shm(encoded.shm_name, encoded.size)
            pd.testing.assert_frame_equal(decoded, sample_df)
        finally:
            unlink_shm(encoded.shm_name)

    def test_arrow_roundtrip_preserves_numeric_dtypes(self):
        df = pd.DataFrame({"i": np.array([1, 2, 3], dtype="int32"), "f": np.array([1.5, 2.5, 3.5], dtype="float64")})
        encoded = encode_dataframe(df, "numeric")
        try:
            decoded = decode_dataframe_from_shm(encoded.shm_name, encoded.size)
            assert str(decoded["i"].dtype) == "int32"
            assert str(decoded["f"].dtype) == "float64"
        finally:
            unlink_shm(encoded.shm_name)

    def test_pickle_fallback_warns_on_unsupported_dtype(self, caplog):
        """A column of unhashable/mixed Python objects Arrow can't infer -> pickle + warning."""
        df = pd.DataFrame({"obj": [{"nested": 1}, [1, 2], object()]})
        with caplog.at_level(logging.WARNING):
            encoded = encode_dataframe(df, "weird_df")

        assert encoded.format == "pickle"
        assert encoded.shm_name is None
        assert encoded.payload is not None
        assert any("weird_df" in record.message and "pickle" in record.message for record in caplog.records)

        decoded = decode_pickle_payload(encoded.payload)
        assert decoded.shape == df.shape

    def test_unlink_shm_is_idempotent(self, sample_df):
        encoded = encode_dataframe(sample_df, "sample")
        unlink_shm(encoded.shm_name)
        unlink_shm(encoded.shm_name)  # second call must not raise


class TestWorkerHandleInjectDataframe:
    """Real host -> worker delivery via WorkerHandle (spawns a real worker)."""

    async def test_df_arrow_roundtrip(self, real_worker_config, sample_df, tmp_path):
        handle = WorkerHandle(real_worker_config, output_dir=str(tmp_path))
        await handle.start()
        try:
            await handle.inject_dataframe("my_df", sample_df)
            value = await handle.get_var("my_df")
            pd.testing.assert_frame_equal(value, sample_df)
            assert "my_df" in handle.known_vars
        finally:
            await handle.kill()

    async def test_df_visible_to_executed_code(self, real_worker_config, sample_df, tmp_path):
        handle = WorkerHandle(real_worker_config, output_dir=str(tmp_path))
        await handle.start()
        try:
            await handle.inject_dataframe("my_df", sample_df)
            result = await handle.execute("result = len(my_df)")
            assert isinstance(result, str)
            assert "3" in result
        finally:
            await handle.kill()

    async def test_no_shm_leaks_after_inject(self, real_worker_config, sample_df, tmp_path):
        """The host unlinks the shm block once the worker has ack'd (no leaks)."""
        import glob

        before = set(glob.glob("/dev/shm/*"))
        handle = WorkerHandle(real_worker_config, output_dir=str(tmp_path))
        await handle.start()
        try:
            await handle.inject_dataframe("my_df", sample_df)
        finally:
            await handle.kill()
        after = set(glob.glob("/dev/shm/*"))
        assert after - before == set(), f"leaked shm segments: {after - before}"
