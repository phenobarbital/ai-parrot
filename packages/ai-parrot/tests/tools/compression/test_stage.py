"""Unit tests for `CompressionStage` (TASK-1951)."""
import pytest

import parrot.tools.compression.codecs  # noqa: F401 — registers json_compact
from parrot.tools.compression import CompressorRegistry, FilterLevel, get_codec
from parrot.tools.compression.budget import BudgetRouter, Route
from parrot.tools.compression.protocol import CompressionOutcome, register_codec
from parrot.tools.compression.stage import CompressionStage


@pytest.fixture
def stage(tmp_path):
    return CompressionStage(
        registry=CompressorRegistry.load(project_root=tmp_path),
        router=BudgetRouter(),
    )


class TestGates:
    @pytest.mark.parametrize("kwargs,env", [
        ({}, {"PARROT_COMPRESSION_DISABLED": "1"}),
        ({"return_direct": True}, {}),
    ])
    async def test_stage_gates(self, stage, monkeypatch, kwargs, env):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        data = {"a": None}
        out, meta = await stage.run(
            "t", data, status="success", metadata={},
            return_direct=kwargs.get("return_direct", False),
        )
        assert out is data
        assert "compression_skipped" in meta

    async def test_idempotency_marker(self, stage):
        data = {"a": None}
        out, meta = await stage.run(
            "t", data, status="success", metadata={"_compressed": True},
            return_direct=False,
        )
        assert out is data
        assert meta["compression_skipped"] == "already_compressed"

    async def test_gates_never_invoke_tee(self, tmp_path):
        calls = []

        def tee(tool_name, payload, codec_name):
            calls.append((tool_name, payload, codec_name))
            return "tee-key"

        stage = CompressionStage(
            registry=CompressorRegistry.load(project_root=tmp_path),
            router=BudgetRouter(),
            tee=tee,
        )
        data = {"a": None}
        await stage.run(
            "t", data, status="success", metadata={"_compressed": True},
            return_direct=False,
        )
        await stage.run("t", data, status="success", metadata={}, return_direct=True)
        assert calls == []


class TestLevelPrecedence:
    async def test_error_status_forces_none(self, stage):
        data = {"a": None}
        out, meta = await stage.run(
            "t", data, status="error", metadata={}, return_direct=False,
        )
        assert out is data
        assert meta["compression_skipped"] == "level_none"

    async def test_per_call_override_wins(self, stage):
        data = {"a": None, "b": 1}
        out, meta = await stage.run(
            "t", data, status="success", metadata={}, return_direct=False,
            level_override=FilterLevel.NONE,
        )
        assert out is data
        assert meta["compression_skipped"] == "level_none"

    async def test_override_wins_even_on_error_status(self, tmp_path):
        """Rule 1 (per-call override) outranks rule 2 (status forces NONE)."""
        stage = CompressionStage(
            registry=CompressorRegistry.load(project_root=tmp_path),
            router=BudgetRouter(),
        )
        data = {"a": 1}
        out, meta = await stage.run(
            "t", data, status="error", metadata={}, return_direct=False,
            level_override=FilterLevel.MINIMAL,
        )
        assert meta["compression_level"] == FilterLevel.MINIMAL.value

    async def test_tool_name_entry_beats_global_default(self, tmp_path):
        d = tmp_path / ".parrot"
        d.mkdir()
        (d / "compressors.toml").write_text(
            '[compressor."special_tool"]\ncodec = "json_compact"\nlevel = "normal"\n'
            '[compressor."*"]\ncodec = "json_compact"\nlevel = "minimal"\n'
        )
        # A dummy (always-"available") tee so NORMAL isn't capped to MINIMAL
        # by the TASK-1953 G3 guard — this test probes precedence, not tee
        # capping (covered separately in test_tee.py).
        stage = CompressionStage(
            registry=CompressorRegistry.load(project_root=tmp_path),
            router=BudgetRouter(),
            tee=lambda tool_name, payload, codec_name: None,
        )
        data = {"a": 1}
        _, meta = await stage.run(
            "special_tool", data, status="success", metadata={}, return_direct=False,
        )
        assert meta["compression_level"] == FilterLevel.NORMAL.value

    async def test_no_config_falls_back_to_minimal(self, stage):
        data = {"a": 1}
        _, meta = await stage.run(
            "unconfigured_tool", data, status="success", metadata={}, return_direct=False,
        )
        assert meta["compression_level"] == FilterLevel.MINIMAL.value


class TestSafety:
    async def test_compressor_exception_returns_original(self, stage, monkeypatch, caplog):
        codec_cls = get_codec("json_compact")
        monkeypatch.setattr(
            codec_cls, "compress",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        data = {"a": 1}
        with caplog.at_level("WARNING"):
            out, meta = await stage.run(
                "t", data, status="success", metadata={}, return_direct=False,
            )
        assert out is data
        assert meta["compression_skipped"] == "codec_error"
        assert any("boom" in r.message or "json_compact" in r.message
                   for r in caplog.records)

    async def test_record_called_even_when_codec_raises(self, tmp_path, monkeypatch):
        router = BudgetRouter()
        calls = []
        monkeypatch.setattr(
            router, "record",
            lambda codec_name, duration_ms, route, level=None: calls.append(
                (codec_name, route),
            ),
        )
        stage = CompressionStage(
            registry=CompressorRegistry.load(project_root=tmp_path),
            router=router,
        )
        codec_cls = get_codec("json_compact")
        monkeypatch.setattr(
            codec_cls, "compress",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        await stage.run("t", {"a": 1}, status="success", metadata={}, return_direct=False)
        assert len(calls) == 1
        assert calls[0][0] == "json_compact"

    async def test_unknown_codec_passthrough(self):
        # CompressorRegistry.load() validates codec names, so build one
        # directly (bypassing load-time validation) to exercise the
        # defensive unknown-codec branch in the stage itself.
        from parrot.tools.compression.config import CompressorEntry
        registry = CompressorRegistry(
            {"*": CompressorEntry(codec="ghost_codec_xyz", level=FilterLevel.NORMAL)}
        )
        stage = CompressionStage(registry=registry, router=BudgetRouter())
        data = {"a": 1}
        out, meta = await stage.run(
            "t", data, status="success", metadata={}, return_direct=False,
        )
        assert out is data
        assert meta["compression_skipped"] == "unknown_codec"


class TestMetrics:
    async def test_happy_path_metadata_keys(self, stage):
        data = {"rows": [{"a": 1, "b": None} for _ in range(30)]}
        _, meta = await stage.run(
            "t", data, status="success", metadata={}, return_direct=False,
        )
        for key in ("_compressed", "compression_codec", "compression_level",
                    "result_size_bytes_original", "result_size_bytes",
                    "compression_duration_ms", "compression_teed"):
            assert key in meta
        assert meta["_compressed"] is True
        assert meta["compression_codec"] == "json_compact"
        assert meta["compression_teed"] is False

    async def test_metadata_not_mutated_in_place(self, stage):
        data = {"a": 1}
        original_metadata = {"foo": "bar"}
        _, meta = await stage.run(
            "t", data, status="success", metadata=original_metadata, return_direct=False,
        )
        assert original_metadata == {"foo": "bar"}
        assert meta is not original_metadata


class TestTee:
    async def test_lossy_outcome_invokes_tee(self, tmp_path):
        @register_codec
        class _AlwaysLossy:
            codec_name = "always_lossy_test"

            def compress(self, result, *, level, params):
                return CompressionOutcome(
                    payload={"summary": "x"}, lossy=True, bytes_before=100,
                    bytes_after=10, est_tokens_saved=20, codec_name="always_lossy_test",
                )

        try:
            d = tmp_path / ".parrot"
            d.mkdir()
            (d / "compressors.toml").write_text(
                '[compressor."*"]\ncodec = "always_lossy_test"\nlevel = "normal"\n'
            )
            calls = []

            def tee(tool_name, payload, codec_name):
                calls.append((tool_name, payload, codec_name))
                return "tee-key-1"

            stage = CompressionStage(
                registry=CompressorRegistry.load(project_root=tmp_path),
                router=BudgetRouter(),
                tee=tee,
            )
            data = {"a": 1}
            out, meta = await stage.run(
                "t", data, status="success", metadata={}, return_direct=False,
            )
            # TASK-1953: the stage now appends the `_tee` recovery pointer
            # to the returned payload itself (not just metadata) so the
            # LLM can see it and call wm_get_result without extra prompting.
            assert out == {
                "summary": "x",
                "_tee": {
                    "key": "tee-key-1", "reason": "lossy",
                    "hint": "use wm_get_result for the full payload",
                },
            }
            assert meta["compression_teed"] is True
            assert meta["compression_tee_key"] == "tee-key-1"
            assert calls == [("t", data, "always_lossy_test")]
        finally:
            from parrot.tools.compression.protocol import _CODEC_REGISTRY
            _CODEC_REGISTRY.pop("always_lossy_test", None)

    async def test_lossy_outcome_without_tee_falls_back_to_original(self, tmp_path):
        # G3 (code-review fix): a lossy outcome with no way to recover the
        # original must NEVER be returned. With `tee=None`, `_invoke_tee`
        # always returns `None` — the stage must fall back to the
        # UNCOMPRESSED original rather than returning `outcome.payload`
        # (which was the previous, buggy behavior: the compressed payload
        # was still returned even though it could never be recovered).
        @register_codec
        class _AlwaysLossy2:
            codec_name = "always_lossy_test_2"

            def compress(self, result, *, level, params):
                return CompressionOutcome(
                    payload={"summary": "x"}, lossy=True, bytes_before=100,
                    bytes_after=10, est_tokens_saved=20, codec_name="always_lossy_test_2",
                )

        try:
            d = tmp_path / ".parrot"
            d.mkdir()
            (d / "compressors.toml").write_text(
                '[compressor."*"]\ncodec = "always_lossy_test_2"\nlevel = "normal"\n'
            )
            stage = CompressionStage(
                registry=CompressorRegistry.load(project_root=tmp_path),
                router=BudgetRouter(),
                tee=None,
            )
            data = {"a": 1}
            out, meta = await stage.run(
                "t", data, status="success", metadata={}, return_direct=False,
            )
            assert out is data
            assert meta["compression_skipped"] == "tee_failed"
        finally:
            from parrot.tools.compression.protocol import _CODEC_REGISTRY
            _CODEC_REGISTRY.pop("always_lossy_test_2", None)

    async def test_lossy_outcome_tee_returns_none_falls_back_to_original(self, tmp_path):
        # Same G3 guarantee, but for the "tee IS configured yet the actual
        # store() call still fails/returns None at runtime" case — this is
        # the gap the static `_tee_available()` check (used for the G3
        # level-capping decision) cannot predict, since it only knows a
        # `WorkingMemoryToolkit` is registered, not that a specific store()
        # call will succeed (`CompressionTee.store()` never raises, it
        # returns `None` by contract; see tee.py).
        @register_codec
        class _AlwaysLossy3:
            codec_name = "always_lossy_test_3"

            def compress(self, result, *, level, params):
                return CompressionOutcome(
                    payload={"summary": "x"}, lossy=True, bytes_before=100,
                    bytes_after=10, est_tokens_saved=20, codec_name="always_lossy_test_3",
                )

        try:
            d = tmp_path / ".parrot"
            d.mkdir()
            (d / "compressors.toml").write_text(
                '[compressor."*"]\ncodec = "always_lossy_test_3"\nlevel = "normal"\n'
            )
            stage = CompressionStage(
                registry=CompressorRegistry.load(project_root=tmp_path),
                router=BudgetRouter(),
                # Reports "available" (bare callable can't be introspected)
                # but the actual call always fails at runtime.
                tee=lambda tool_name, payload, codec_name: None,
            )
            data = {"a": 1}
            out, meta = await stage.run(
                "t", data, status="success", metadata={}, return_direct=False,
            )
            assert out is data
            assert meta["compression_skipped"] == "tee_failed"
        finally:
            from parrot.tools.compression.protocol import _CODEC_REGISTRY
            _CODEC_REGISTRY.pop("always_lossy_test_3", None)


class TestBudgetIntegration:
    async def test_budget_passthrough_returns_original(self, tmp_path):
        d = tmp_path / ".parrot"
        d.mkdir()
        (d / "compressors.toml").write_text(
            '[compressor."*"]\ncodec = "json_compact"\nlevel = "normal"\n'
        )
        router = BudgetRouter(size_threshold_bytes=1, row_threshold=1)
        # A dummy (always-"available") tee so NORMAL isn't capped to MINIMAL
        # (TASK-1953 G3 guard) — MINIMAL always routes INLINE regardless of
        # size, which would short-circuit the budget/route decision this
        # test exercises.
        stage = CompressionStage(
            registry=CompressorRegistry.load(project_root=tmp_path),
            router=router,
            tee=lambda tool_name, payload, codec_name: None,
            # TASK-1955 built the optional Rust extension in this dev
            # environment; force the "absent" state explicitly rather
            # than relying on ambient environment reality, since this
            # test specifically exercises the no-Rust PASSTHROUGH route.
            rust_available=False,
        )
        data = [{"a": "x" * 1000} for _ in range(50)]
        out, meta = await stage.run(
            "t", data, status="success", metadata={}, return_direct=False,
        )
        assert out is data
        assert meta["compression_skipped"] == "budget_passthrough"

    async def test_executor_route_runs_off_loop(self, tmp_path):
        d = tmp_path / ".parrot"
        d.mkdir()
        (d / "compressors.toml").write_text(
            '[compressor."*"]\ncodec = "json_compact"\nlevel = "normal"\n'
        )
        router = BudgetRouter(size_threshold_bytes=1, row_threshold=1)
        # A dummy (always-"available") tee so NORMAL isn't capped to MINIMAL
        # (TASK-1953 G3 guard) — MINIMAL always routes INLINE, which would
        # prevent this test from actually exercising the EXECUTOR route.
        stage = CompressionStage(
            registry=CompressorRegistry.load(project_root=tmp_path),
            router=router,
            rust_available=True,
            tee=lambda tool_name, payload, codec_name: None,
        )
        data = [{"a": "x" * 1000} for _ in range(50)]
        out, meta = await stage.run(
            "t", data, status="success", metadata={}, return_direct=False,
        )
        assert "compression_skipped" not in meta
        assert meta["_compressed"] is True
        assert meta["compression_level"] == FilterLevel.NORMAL.value
