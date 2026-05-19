"""Basic telemetry demo for AI-Parrot.

FEAT-177 TASK-1237.

Demonstrates end-to-end observability with OpenTelemetry + OpenLIT.

Prerequisites:
  1. Start the stack: docker compose -f docker-compose.observability.yml up -d
  2. Wait ~15 s for OpenLIT to initialize.
  3. Set OPENAI_API_KEY (or use an OpenAI-compatible local server).

Usage:
  python basic_telemetry.py

Then open http://localhost:3000 to see traces and metrics in OpenLIT UI.
"""

from __future__ import annotations

import asyncio
import logging
import os

from parrot.observability import (
    ObservabilityConfig,
    setup_telemetry,
    shutdown_telemetry,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("parrot.examples.basic_telemetry")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OTLP_ENDPOINT = os.getenv("OTLP_ENDPOINT", "http://localhost:4318")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sk-demo-key")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

DEMO_QUESTIONS = [
    "Hello! What can you do?",
    "In one sentence, what is OpenTelemetry?",
    "Tell me a short joke about observability.",
]


async def main() -> None:
    """Run 3 demo ask() calls and send traces/metrics to OpenLIT."""

    # 1. Boot the observability stack
    logger.info("Initialising observability → %s", OTLP_ENDPOINT)
    setup_telemetry(
        ObservabilityConfig(
            enabled=True,
            service_name="parrot-demo",
            service_version="0.1.0",
            otlp_endpoint=OTLP_ENDPOINT,
            otlp_protocol="http/protobuf",
            enable_traces=True,
            enable_metrics=True,
            enable_cost_tracking=True,
            enable_openlit=True,        # auto-instrument via OpenLIT
            capture_completions=False,  # PII guard
            sampling_ratio=1.0,
        )
    )

    # 2. Build a minimal demo client
    #    We use a simple inline OpenAI-compatible call so the example works
    #    even when a full Chatbot setup is unavailable.
    try:
        import openai  # type: ignore[import]

        client = openai.AsyncOpenAI(
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_BASE_URL,
        )
        model = os.getenv("DEMO_MODEL", "gpt-4o-mini")
        logger.info("Using OpenAI-compatible endpoint: %s (model=%s)", OPENAI_BASE_URL, model)

        for i, question in enumerate(DEMO_QUESTIONS, 1):
            logger.info("Call %d/%d: %s", i, len(DEMO_QUESTIONS), question)
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": question}],
                max_tokens=100,
            )
            answer = response.choices[0].message.content or ""
            logger.info("Answer: %s", answer[:120])

    except ImportError:
        logger.warning(
            "openai package not installed — running in no-op demo mode. "
            "Install with: pip install openai"
        )
        # Emit synthetic events so the observability stack still sees something
        from opentelemetry import trace  # noqa: PLC0415

        tracer = trace.get_tracer("parrot.examples.basic_telemetry")
        for i, question in enumerate(DEMO_QUESTIONS, 1):
            with tracer.start_as_current_span(f"demo.ask.{i}") as span:
                span.set_attribute("demo.question", question)
                span.set_attribute("demo.synthetic", True)
                logger.info("Synthetic span %d emitted for: %s", i, question)
                await asyncio.sleep(0.05)

    finally:
        logger.info("Flushing telemetry…")
        shutdown_telemetry()
        logger.info("Done. Visit http://localhost:3000 to see traces.")


if __name__ == "__main__":
    asyncio.run(main())
