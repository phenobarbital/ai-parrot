# parrot/telemetry/__init__.py
from typing import Optional, Dict, Any
from contextlib import contextmanager
import time
import openlit
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.metrics import MeterProvider


class TelemetryMixin:
    """Mixin to add observability to LLM clients"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._telemetry_enabled = kwargs.get('enable_telemetry', True)

        if self._telemetry_enabled:
            # Get tracer and meter for this client
            self.tracer = trace.get_tracer(f"parrot.client.{self.client_name}")
            self.meter = metrics.get_meter(f"parrot.client.{self.client_name}")

            # Create metrics
            self.request_counter = self.meter.create_counter(
                name="llm.requests",
                description="Total LLM requests",
                unit="1"
            )
            self.token_counter = self.meter.create_counter(
                name="llm.tokens",
                description="Total tokens used",
                unit="1"
            )
            self.latency_histogram = self.meter.create_histogram(
                name="llm.request.duration",
                description="LLM request duration",
                unit="ms"
            )
            self.error_counter = self.meter.create_counter(
                name="llm.errors",
                description="LLM errors",
                unit="1"
            )

    @contextmanager
    def track_request(self, operation: str, **attributes):
        """Context manager for tracking LLM requests"""
        if not self._telemetry_enabled:
            yield {}
            return

        start_time = time.time()
        span_attributes = {
            "llm.provider": self.client_name,
            "llm.operation": operation,
            **attributes
        }

        with self.tracer.start_as_current_span(
            f"{self.client_name}.{operation}",
            attributes=span_attributes
        ) as span:
            metrics = {
                "start_time": start_time,
                "span": span
            }

            try:
                yield metrics
                # Success tracking
                self.request_counter.add(1, {
                    "provider": self.client_name,
                    "operation": operation,
                    "status": "success"
                })
            except Exception as e:
                # Error tracking
                self.error_counter.add(1, {
                    "provider": self.client_name,
                    "operation": operation,
                    "error_type": type(e).__name__
                })
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise
            finally:
                # Always track latency
                duration_ms = (time.time() - start_time) * 1000
                self.latency_histogram.record(duration_ms, {
                    "provider": self.client_name,
                    "operation": operation
                })

    def track_tokens(self, usage: Dict[str, int], model: str):
        """Track token usage"""
        if not self._telemetry_enabled:
            return

        if "input_tokens" in usage:
            self.token_counter.add(usage["input_tokens"], {
                "provider": self.client_name,
                "model": model,
                "token_type": "input"
            })

        if "output_tokens" in usage:
            self.token_counter.add(usage["output_tokens"], {
                "provider": self.client_name,
                "model": model,
                "token_type": "output"
            })
