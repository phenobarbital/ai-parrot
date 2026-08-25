"""Unit tests for OpenLitUsageRecorder and its factory wiring (FEAT-462).

Spec: sdd/specs/unified-telemetry-bus.spec.md §3 Module 4.
Task: TASK-2473.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from parrot.observability.config import ObservabilityConfig
from parrot.observability.recorders.factory import build_recorders_from_config
from parrot.observability.recorders.models import UsageRecord


@pytest.fixture
def sample_record() -> UsageRecord:
    return UsageRecord(
        provider="openai",
        model="gpt-4o",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.002,
        duration_ms=1200.0,
        finish_reason="stop",
        trace_id="abc123",
        service_name="ai-parrot",
        timestamp=datetime.now(UTC),
    )


@pytest.fixture
def patched_otel():
    """Patch the OTel SDK symbols OpenLitUsageRecorder lazy-imports."""
    with (
        patch("opentelemetry.sdk.trace.TracerProvider") as mock_provider_cls,
        patch("opentelemetry.sdk.trace.export.BatchSpanProcessor") as mock_bsp,
        patch("opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter") as mock_exporter_cls,
        patch("opentelemetry.sdk.resources.Resource") as mock_resource,
    ):
        yield {
            "provider_cls": mock_provider_cls,
            "bsp": mock_bsp,
            "exporter_cls": mock_exporter_cls,
            "resource": mock_resource,
        }


class TestOpenLitUsageRecorder:
    def test_construction(self, patched_otel) -> None:
        from parrot.observability.recorders.openlit_recorder import (
            OpenLitUsageRecorder,
        )

        recorder = OpenLitUsageRecorder(endpoint="http://localhost:4318")
        assert recorder.name == "openlit"

    async def test_record_sets_attributes(self, patched_otel, sample_record) -> None:
        from parrot.observability.recorders.openlit_recorder import (
            OpenLitUsageRecorder,
        )

        recorder = OpenLitUsageRecorder(endpoint="http://localhost:4318")
        mock_span = MagicMock()
        recorder._tracer.start_span = MagicMock(return_value=mock_span)

        await recorder.record(sample_record)

        mock_span.set_attribute.assert_any_call("gen_ai.provider.name", "openai")
        mock_span.set_attribute.assert_any_call("gen_ai.request.model", "gpt-4o")
        mock_span.set_attribute.assert_any_call("gen_ai.operation.name", "chat")
        mock_span.set_attribute.assert_any_call("gen_ai.usage.cost", 0.002)
        mock_span.set_attribute.assert_any_call("parrot.cost.usd", 0.002)
        mock_span.set_attribute.assert_any_call("parrot.trace_id", "abc123")
        mock_span.end.assert_called_once()

    async def test_record_omits_cost_when_none(self, patched_otel) -> None:
        from parrot.observability.recorders.openlit_recorder import (
            OpenLitUsageRecorder,
        )

        recorder = OpenLitUsageRecorder(endpoint="http://localhost:4318")
        mock_span = MagicMock()
        recorder._tracer.start_span = MagicMock(return_value=mock_span)

        record = UsageRecord(provider="anthropic", model="claude-3-5-sonnet")
        await recorder.record(record)

        calls = [c.args for c in mock_span.set_attribute.call_args_list]
        assert not any(c[0] == "gen_ai.usage.cost" for c in calls)
        assert not any(c[0] == "parrot.cost.usd" for c in calls)

    async def test_aclose_flushes(self, patched_otel) -> None:
        from parrot.observability.recorders.openlit_recorder import (
            OpenLitUsageRecorder,
        )

        recorder = OpenLitUsageRecorder(endpoint="http://localhost:4318")
        await recorder.aclose()
        recorder._provider.force_flush.assert_called_once()
        recorder._provider.shutdown.assert_called_once()

    async def test_aclose_resilient_to_errors(self, patched_otel) -> None:
        from parrot.observability.recorders.openlit_recorder import (
            OpenLitUsageRecorder,
        )

        recorder = OpenLitUsageRecorder(endpoint="http://localhost:4318")
        recorder._provider.force_flush.side_effect = RuntimeError("boom")
        await recorder.aclose()  # must not raise


class TestFactoryOpenlitBranch:
    def test_returns_recorder_when_endpoint_set(self, patched_otel) -> None:
        config = ObservabilityConfig(openlit_recorder_endpoint="http://openlit:4318")
        recorders = build_recorders_from_config(config)
        recorder_names = [r.name for r in recorders]
        assert "openlit" in recorder_names

    def test_falls_back_to_otlp_endpoint_when_no_explicit_endpoint(self, patched_otel) -> None:
        config = ObservabilityConfig(
            openlit_recorder_endpoint="http://openlit:4318",
            otlp_endpoint="http://default:4318",
        )
        with patch("parrot.observability.recorders.openlit_recorder.OpenLitUsageRecorder") as mock_recorder_cls:
            build_recorders_from_config(config)
            mock_recorder_cls.assert_called_once_with(
                endpoint="http://openlit:4318",
                headers=config.otlp_headers,
                service_name=config.service_name,
            )

    def test_no_recorder_when_endpoint_unset(self) -> None:
        config = ObservabilityConfig()
        recorders = build_recorders_from_config(config)
        recorder_names = [r.name for r in recorders]
        assert "openlit" not in recorder_names

    def test_additive_alongside_logging_backend(self, patched_otel) -> None:
        """The recorder is additive — not exclusive with other backends."""
        config = ObservabilityConfig(
            usage_backend="logging",
            openlit_recorder_endpoint="http://openlit:4318",
        )
        recorders = build_recorders_from_config(config)
        recorder_names = [r.name for r in recorders]
        assert "logging" in recorder_names
        assert "openlit" in recorder_names
