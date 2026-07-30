"""Unit tests for the compression savings report (TASK-1957)."""
import pytest

from navigator_eventbus.lifecycle.base import TraceContext
from parrot.core.events.lifecycle.events import AfterToolCallEvent
from parrot.tools.compression.report import CompressionReport


def _evt(tool, before, after, ms=0.5, codec="columnar", skipped=None):
    return AfterToolCallEvent(
        trace_context=TraceContext.new_root(),
        tool_name=tool, duration_ms=10.0, result_status="success",
        result_size_bytes=after, result_size_bytes_original=before,
        compression_codec=codec, compression_level="normal",
        compression_duration_ms=ms, compression_teed=False,
    )


class TestCompressionReport:
    def test_aggregates_bytes_tokens_and_ms(self):
        r = CompressionReport()
        r.handle(_evt("db", 1000, 400))
        r.handle(_evt("db", 2000, 800))
        s = r.summary().tools["db"]
        assert s.calls == 2
        assert s.bytes_before == 3000 and s.bytes_after == 1200
        assert s.est_tokens_saved == (600 + 1200) // 4
        assert s.compression_ms_total == pytest.approx(1.0)
        assert s.pct_saved == pytest.approx(60.0)

    def test_no_gain_is_recorded(self):
        r = CompressionReport()
        r.handle(_evt("small", 500, 500))
        s = r.summary().tools["small"]
        assert s.pct_saved == 0.0
        assert s.calls == 1
        assert s.compressed_calls == 1

    def test_skipped_reasons_tracked(self):
        r = CompressionReport()
        evt = _evt("t", 0, 0, codec="")
        r.handle(evt, skipped_reason="min_rows")
        s = r.summary().tools["t"]
        assert s.skipped["min_rows"] == 1
        assert s.calls == 1
        assert s.compressed_calls == 0

    def test_render_includes_caveat(self):
        r = CompressionReport()
        r.handle(_evt("db", 1000, 400))
        out = r.render()
        assert "bytes/4" in out or "approximate" in out
        assert "ms" in out              # cost shown next to saving

    def test_listener_never_raises(self):
        r = CompressionReport()
        r.handle(None)                  # malformed
        assert r.summary() is not None

    def test_listener_ignores_events_without_tool_name(self):
        r = CompressionReport()
        r.handle(object())              # no `tool_name` attribute at all
        assert r.summary().tools == {}

    def test_no_division_by_zero(self):
        r = CompressionReport()
        r.handle(_evt("t", 0, 0, codec=""))
        assert r.summary().tools["t"].pct_saved == 0.0

    def test_session_total_aggregates_across_tools(self):
        r = CompressionReport()
        r.handle(_evt("a", 1000, 500))
        r.handle(_evt("b", 2000, 1000))
        sess = r.summary().session
        assert sess.calls == 2
        assert sess.bytes_before == 3000
        assert sess.bytes_after == 1500
        assert sess.pct_saved == pytest.approx(50.0)

    def test_skipped_and_compressed_calls_both_counted_per_tool(self):
        r = CompressionReport()
        r.handle(_evt("t", 1000, 400))
        r.handle(_evt("t", 0, 0), skipped_reason="budget_passthrough")
        s = r.summary().tools["t"]
        assert s.calls == 2
        assert s.compressed_calls == 1
        assert s.skipped["budget_passthrough"] == 1

    def test_p50_p99_reported(self):
        r = CompressionReport()
        for ms in [1.0, 2.0, 3.0, 4.0, 100.0]:
            r.handle(_evt("t", 100, 90, ms=ms))
        s = r.summary().tools["t"]
        assert s.p50_compression_ms > 0
        assert s.p99_compression_ms >= s.p50_compression_ms

    def test_summary_is_an_independent_snapshot(self):
        r = CompressionReport()
        r.handle(_evt("t", 1000, 400))
        snap = r.summary()
        snap.tools["t"].calls = 999  # mutate the snapshot
        assert r.summary().tools["t"].calls == 1  # internal state untouched

    def test_reports_are_per_instance_isolated(self):
        """CompressionReport holds purely per-instance state — safe for
        eventual per-session ownership (mirrors BudgetRouter/CompressionTee,
        TASK-1952/1953's ToolManager.clone() pattern)."""
        r1 = CompressionReport()
        r2 = CompressionReport()
        r1.handle(_evt("t", 1000, 400))
        assert r1.summary().tools.get("t") is not None
        assert r2.summary().tools == {}
