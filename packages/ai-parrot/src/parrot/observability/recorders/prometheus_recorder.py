"""PrometheusUsageRecorder — pull-based metrics backend (described, lazy-loaded).

A lightweight, low-latency backend for usage/token/cost metrics. Uses
``prometheus_client`` directly (not the OTel→Prometheus exporter) so the
logging-first design never drags in the OTel SDK. Metrics are updated in-process
(counter ``.inc`` / histogram ``.observe`` — no network on the hot path) and
exposed on an HTTP endpoint that Prometheus scrapes, so request latency is
unaffected.

Install with: ``pip install 'ai-parrot[observability-prometheus]'``.

Cardinality contract: labels are limited to ``provider`` (bounded ~10 values)
and ``model``. NEVER ``trace_id``/``user_id``/``session_id``/prompt content.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from parrot.observability.recorders.base import AbstractLogger
from parrot.observability.recorders.models import UsageRecord

logger = logging.getLogger(__name__)

# Latency buckets (seconds) — mirrors MetricsSubscriber._DEFAULT_BUCKETS.
_LATENCY_BUCKETS = (0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0, 60.0)
# Token-space buckets — mirrors MetricsSubscriber._TOKEN_BUCKETS.
_TOKEN_BUCKETS = (10, 50, 100, 500, 1000, 2000, 5000, 10000, 50000, 100000)

# Module-level guards so re-construction (multi-bot, tests) neither re-registers
# instruments with the default Prometheus registry nor re-binds the HTTP server.
_INSTRUMENTS: Any = None
_SERVER_STARTED = False
_LOCK = threading.Lock()


def _build_instruments() -> Any:
    """Create (once) and return the Prometheus instruments namespace."""
    global _INSTRUMENTS  # noqa: PLW0603
    if _INSTRUMENTS is not None:
        return _INSTRUMENTS
    from prometheus_client import Counter, Histogram  # noqa: PLC0415

    labelnames = ("provider", "model")
    _INSTRUMENTS = {
        "requests": Counter(
            "parrot_llm_requests_total",
            "Number of LLM API calls.",
            labelnames,
        ),
        "input_tokens": Counter(
            "parrot_llm_input_tokens_total",
            "Total input tokens billed.",
            labelnames,
        ),
        "output_tokens": Counter(
            "parrot_llm_output_tokens_total",
            "Total output tokens billed.",
            labelnames,
        ),
        "cost": Counter(
            "parrot_llm_cost_usd_total",
            "Total estimated cost of LLM API calls in USD.",
            labelnames,
        ),
        "duration": Histogram(
            "parrot_llm_request_duration_seconds",
            "Duration of LLM API calls in seconds.",
            labelnames,
            buckets=_LATENCY_BUCKETS,
        ),
        "tokens": Histogram(
            "parrot_llm_tokens",
            "Token usage per LLM API call (input + output).",
            ("provider", "model", "type"),
            buckets=_TOKEN_BUCKETS,
        ),
    }
    return _INSTRUMENTS


class PrometheusUsageRecorder(AbstractLogger):
    """Record usage as Prometheus counters/histograms exposed over HTTP.

    Args:
        port: Exposition HTTP server port (default ``9464``).
        addr: Bind address (default ``"0.0.0.0"``).
        start_server: When ``True`` (default), start the exposition server.
            Pass ``False`` in tests that scrape the default registry directly.
    """

    name = "prometheus"

    def __init__(
        self,
        *,
        port: int = 9464,
        addr: str = "0.0.0.0",
        start_server: bool = True,
    ) -> None:
        try:
            import prometheus_client  # noqa: F401, PLC0415
        except ImportError as exc:  # pragma: no cover - exercised via extras
            raise ImportError(
                "PrometheusUsageRecorder requires the 'observability-prometheus' "
                "extra. Install with: pip install 'ai-parrot[observability-prometheus]'"
            ) from exc

        self._m = _build_instruments()
        if start_server:
            self._maybe_start_server(port, addr)

    @staticmethod
    def _maybe_start_server(port: int, addr: str) -> None:
        """Start the exposition HTTP server once per process."""
        global _SERVER_STARTED  # noqa: PLW0603
        with _LOCK:
            if _SERVER_STARTED:
                return
            from prometheus_client import start_http_server  # noqa: PLC0415

            start_http_server(port, addr=addr)
            _SERVER_STARTED = True
            logger.info(
                "PrometheusUsageRecorder: exposition server on http://%s:%d/metrics",
                addr,
                port,
            )

    async def record(self, record: UsageRecord) -> None:
        """Update Prometheus instruments from *record* (no network in hot path)."""
        labels = {"provider": record.provider, "model": record.model}
        self._m["requests"].labels(**labels).inc()
        if record.input_tokens:
            self._m["input_tokens"].labels(**labels).inc(record.input_tokens)
            self._m["tokens"].labels(type="input", **labels).observe(record.input_tokens)
        if record.output_tokens:
            self._m["output_tokens"].labels(**labels).inc(record.output_tokens)
            self._m["tokens"].labels(type="output", **labels).observe(record.output_tokens)
        if record.cost_usd is not None:
            self._m["cost"].labels(**labels).inc(record.cost_usd)
        self._m["duration"].labels(**labels).observe(record.duration_ms / 1000.0)
