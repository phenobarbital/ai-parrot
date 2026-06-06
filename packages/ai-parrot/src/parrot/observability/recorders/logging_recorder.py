"""LoggingUsageRecorder — zero-infra usage backend that logs one line per call.

The default, lowest-overhead backend: no network, no extra dependencies (stdlib
``logging`` only). Emits a single structured line per LLM call to a dedicated
logger (``parrot.usage`` by default) carrying provider, model, token counts,
estimated cost, duration, and the process-cumulative cost.
"""

from __future__ import annotations

import logging

from parrot.observability.recorders.base import AbstractLogger
from parrot.observability.recorders.models import UsageRecord


class LoggingUsageRecorder(AbstractLogger):
    """Record usage by emitting one structured log line per LLM call.

    Args:
        level: Logging level for the per-call line (default ``logging.INFO``).
        logger_name: Logger to write to (default ``"parrot.usage"``).
    """

    name = "logging"

    def __init__(
        self,
        *,
        level: int = logging.INFO,
        logger_name: str = "parrot.usage",
    ) -> None:
        self._level = level
        self._logger = logging.getLogger(logger_name)

    async def record(self, record: UsageRecord) -> None:
        """Emit a single line summarising *record*.

        Args:
            record: The per-call usage record to log.
        """
        cost = "n/a" if record.cost_usd is None else f"{record.cost_usd:.6f}"
        cumulative = (
            "n/a"
            if record.cumulative_cost_usd is None
            else f"{record.cumulative_cost_usd:.6f}"
        )
        # Lazy %-formatting: skipped entirely when the level is filtered out.
        self._logger.log(
            self._level,
            "llm-usage provider=%s model=%s input_tokens=%d output_tokens=%d "
            "total_tokens=%d cost_usd=%s cumulative_cost_usd=%s duration_ms=%.1f "
            "finish_reason=%s trace=%s",
            record.provider,
            record.model,
            record.input_tokens,
            record.output_tokens,
            record.total_tokens,
            cost,
            cumulative,
            record.duration_ms,
            record.finish_reason or "-",
            record.trace_id or "-",
        )
