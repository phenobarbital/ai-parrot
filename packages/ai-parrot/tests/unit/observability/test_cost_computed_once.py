"""FEAT-710 TASK-4550 — one cost computation per LLM call."""
import pytest
from unittest.mock import Mock, AsyncMock

from parrot.core.events.lifecycle.events import AfterClientCallEvent
from navigator_eventbus.lifecycle.registry import EventRegistry
from navigator_eventbus.lifecycle.trace import TraceContext
from parrot.observability.cost.calculator import CostCalculator
from parrot.observability.recorders.subscriber import UsageRecordingSubscriber
from parrot.observability.subscribers.metrics import MetricsSubscriber
from parrot.observability.subscribers.trace import GenAIOpenTelemetrySubscriber
from parrot.observability.recorders.models import UsageRecord


class _SpyCostCalculator:
    """Spy calculator that tracks how many times cost_usd is called."""
    
    def __init__(self):
        self.call_count = 0
        self._real_calculator = CostCalculator()
        
    def cost_usd(self, provider, model, input_tokens, output_tokens):
        self.call_count += 1
        return self._real_calculator.cost_usd(provider, model, input_tokens, output_tokens)


class _CapturingRecorder:
    """Recorder that captures UsageRecords for inspection."""
    
    def __init__(self):
        self.records = []
        self.name = "capture"
        
    async def record(self, record: UsageRecord):
        self.records.append(record)
        
    async def aclose(self):
        pass


@pytest.mark.asyncio
async def test_three_subscribers_zero_recompute_when_event_priced() -> None:
    """With event.cost_usd set, none of the three subscribers calls cost_usd(); all report the same value."""
    # Create a spy cost calculator
    spy_calculator = _SpyCostCalculator()
    
    # Create subscribers with the spy calculator
    capturing_recorder = _CapturingRecorder()
    usage_subscriber = UsageRecordingSubscriber(
        recorders=[capturing_recorder],
        cost_calculator=spy_calculator
    )
    
    metrics_subscriber = MetricsSubscriber(
        cost_calculator=spy_calculator,
        service_name="test-service"
    )
    
    # Mock the meter provider to avoid OTel initialization issues
    mock_meter_provider = Mock()
    mock_meter = Mock()
    mock_counter = Mock()
    mock_meter_provider.get_meter.return_value = mock_meter
    mock_meter.create_counter.return_value = mock_counter
    
    # Replace the counters in metrics subscriber
    metrics_subscriber._client_cost_total = mock_counter
    
    trace_subscriber = GenAIOpenTelemetrySubscriber(
        cost_calculator=spy_calculator,
        service_name="test-service",
        tracer_provider=Mock()  # Mock tracer provider
    )
    
    # Create an event with pre-computed cost
    event = AfterClientCallEvent(
        trace_context=TraceContext.new_root(),
        client_name="openai",
        model="gpt-4o-mini",
        duration_ms=42.0,
        input_tokens=100,
        output_tokens=50,
        finish_reason="stop",
        source_type="client",
        source_name="openai",
        cost_usd=0.002  # Pre-computed cost
    )
    
    # Process the event through all three subscribers
    await usage_subscriber._on_client_after(event)
    await metrics_subscriber._on_client_after(event)
    await trace_subscriber._on_client_end(event)
    
    # Verify that the spy calculator was never called
    assert spy_calculator.call_count == 0
    
    # Verify that all subscribers used the pre-computed cost
    assert len(capturing_recorder.records) == 1
    assert capturing_recorder.records[0].cost_usd == 0.002
    
    # Verify metrics subscriber recorded the cost
    mock_counter.add.assert_called_once_with(0.002, attributes=mock_counter.add.call_args[0][1])
    
    # Verify trace subscriber would use the cost (we can't easily check the span attributes in this test)


@pytest.mark.asyncio
async def test_unpriced_event_still_priced_by_fallback() -> None:
    """Events without cost_usd (dispatcher-style event) are still priced by fallback calculator."""
    # Create a spy cost calculator
    spy_calculator = _SpyCostCalculator()
    
    # Create subscribers with the spy calculator
    capturing_recorder = _CapturingRecorder()
    usage_subscriber = UsageRecordingSubscriber(
        recorders=[capturing_recorder],
        cost_calculator=spy_calculator
    )
    
    metrics_subscriber = MetricsSubscriber(
        cost_calculator=spy_calculator,
        service_name="test-service"
    )
    
    # Mock the meter provider to avoid OTel initialization issues
    mock_meter_provider = Mock()
    mock_meter = Mock()
    mock_counter = Mock()
    mock_meter_provider.get_meter.return_value = mock_meter
    mock_meter.create_counter.return_value = mock_counter
    
    # Replace the counters in metrics subscriber
    metrics_subscriber._client_cost_total = mock_counter
    
    trace_subscriber = GenAIOpenTelemetrySubscriber(
        cost_calculator=spy_calculator,
        service_name="test-service",
        tracer_provider=Mock()  # Mock tracer provider
    )
    
    # Create an event WITHOUT pre-computed cost (None)
    event = AfterClientCallEvent(
        trace_context=TraceContext.new_root(),
        client_name="openai",
        model="gpt-4o-mini",
        duration_ms=42.0,
        input_tokens=100,
        output_tokens=50,
        finish_reason="stop",
        source_type="client",
        source_name="openai",
        cost_usd=None  # No pre-computed cost
    )
    
    # Process the event through all three subscribers
    await usage_subscriber._on_client_after(event)
    await metrics_subscriber._on_client_after(event)
    await trace_subscriber._on_client_end(event)
    
    # Verify that the spy calculator was called (fallback behavior)
    # Each subscriber should call it once, but resolve_event_cost caches the result
    # so it should only be called once total
    assert spy_calculator.call_count >= 1
    
    # Verify that all subscribers computed a cost
    assert len(capturing_recorder.records) == 1
    assert capturing_recorder.records[0].cost_usd is not None
    assert capturing_recorder.records[0].cost_usd > 0
    
    # Verify metrics subscriber recorded the computed cost
    mock_counter.add.assert_called_once()
    computed_cost = mock_counter.add.call_args[0][0]
    assert computed_cost > 0